"""Zjednodušený senzor pro predikci nabití baterie v průběhu dne."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, ClassVar, Dict, List, Optional, Union

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .. import storage as plan_storage_module
from .. import task_utils as task_utils_module
from ..balancing import helpers as balancing_helpers_module
from ..data import battery_state as battery_state_module
from ..data import load_profiles as load_profiles_module
from ..data import pricing as pricing_module
from ..data import solar_forecast as solar_forecast_module
from ..planning import charging_helpers as charging_helpers_module
from ..planning import forecast_update as forecast_update_module
from ..planning import interval_grouping as interval_grouping_module
from ..planning import mode_recommendations as mode_recommendations_module
from ..planning import scenario_analysis as scenario_analysis_module
from ..presentation import detail_tabs as detail_tabs_module
from ..presentation import plan_tabs as plan_tabs_module
from ..presentation import precompute as precompute_module
from ..presentation import state_attributes as state_attributes_module
from ..presentation import unified_cost_tile as unified_cost_tile_module
from ..timeline import extended as timeline_extended_module
from ..types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
)
from . import sensor_lifecycle as sensor_lifecycle_module
from . import sensor_runtime as sensor_runtime_module
from . import sensor_setup as sensor_setup_module

_LOGGER = logging.getLogger(__name__)

AUTO_SWITCH_STARTUP_DELAY = timedelta(seconds=0)

# CBB 3F Home Plus Premium - Mode Constants (Phase 2)
# NOTE: Mode constants moved to battery_forecast.types.

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
ISO_TZ_OFFSET = "+00:00"

# Stabilizační guard po změně režimu (v minutách)
MODE_GUARD_MINUTES = 60

# NOTE: AC charging limit and efficiency are now read from:
# - Config: home_charge_rate (kW) - user configured max charging power
# - Sensor: sensor.oig_{box_id}_battery_efficiency (%) - real-time measured efficiency
#
# Example: home_charge_rate = 2.8 kW → 0.7 kWh per 15min interval
# Fallback efficiency if sensor unavailable: 88.2%

# Debug options - Phase 1.5: API Optimization
# Set to False for LEAN attributes (96% memory reduction)
DEBUG_EXPOSE_BASELINE_TIMELINE = False  # Expose baseline timeline in sensor attributes


class OigCloudBatteryForecastSensor(RestoreEntity, CoordinatorEntity, SensorEntity):
    """Zjednodušený senzor pro predikci nabití baterie."""

    # Shared log throttling across instances (dashboard/API can trigger multiple computations).
    _GLOBAL_LOG_LAST_TS: ClassVar[Dict[str, float]] = {}

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
        *,
        side_effects_enabled: bool = True,
    ) -> None:
        """Initialize the battery forecast sensor."""
        super().__init__(coordinator)

        sensor_setup_module.initialize_sensor(
            self,
            coordinator,
            sensor_type,
            config_entry,
            device_info,
            hass,
            side_effects_enabled=side_effects_enabled,
            auto_switch_startup_delay=AUTO_SWITCH_STARTUP_DELAY,
        )

    # Legacy attributes kept for backward compatibility (single planner only).
    # NOTE: Single planner only.

    def _log_rate_limited(
        self,
        key: str,
        level: str,
        message: str,
        *args: Any,
        cooldown_s: float = 300.0,
    ) -> None:
        """Proxy to runtime helpers."""
        sensor_runtime_module.log_rate_limited(
            self, _LOGGER, key, level, message, *args, cooldown_s=cooldown_s
        )

    async def async_added_to_hass(self) -> None:  # noqa: C901
        """Proxy to lifecycle helpers."""
        await super().async_added_to_hass()
        self._hass = self.hass
        await sensor_lifecycle_module.async_added_to_hass(self)

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        sensor_runtime_module.handle_will_remove(self)
        await super().async_will_remove_from_hass()

    def _get_config(self) -> Dict[str, Any]:
        """Proxy to runtime helpers."""
        return sensor_runtime_module.get_config(self)

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update.

        NEDĚLÁ ŽÁDNÉ VÝPOČTY - forecast se přepočítá:
        - Každých 15 min (time scheduler)
        - Při startu (delayed 3s initial refresh)
        - Manuálně přes service call
        """
        # Jen zavolat parent pro refresh HA state (rychlé)
        sensor_runtime_module.handle_coordinator_update(self)

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info - Analytics Module."""
        return self._device_info

    @property
    def state(self) -> Optional[Union[float, str]]:
        """
        State = current battery capacity in kWh.

        Dashboard graph needs numeric value to display battery timeline.

        Returns:
            Current battery capacity (kWh) or 0 if no data
        """
        return sensor_runtime_module.get_state(self)

    @property
    def available(self) -> bool:
        """Return if sensor is available.

        CRITICAL FIX: Override CoordinatorEntity.available to prevent 'unavailable' state.
        Sensor should always be available if it has run at least once (has timeline data).
        """
        # If we have timeline data from successful calculation, sensor is available
        return sensor_runtime_module.is_available(self)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Proxy to state attribute helpers."""
        return state_attributes_module.build_extra_state_attributes(
            self, debug_expose_baseline_timeline=DEBUG_EXPOSE_BASELINE_TIMELINE
        )

    def _calculate_data_hash(self, timeline_data: List[Dict[str, Any]]) -> str:
        """Proxy to state attribute helpers."""
        return state_attributes_module.calculate_data_hash(timeline_data)

    async def async_update(self) -> None:  # noqa: C901
        """Proxy to forecast update helpers."""
        await super().async_update()
        await forecast_update_module.async_update(self)

    def _simulate_interval(
        self,
        mode: int,
        solar_kwh: float,
        load_kwh: float,
        battery_soc_kwh: float,
        capacity_kwh: float,
        hw_min_capacity_kwh: float,
        spot_price_czk: float,
        export_price_czk: float,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
        home_charge_rate_kwh_15min: float = 0.7,
        planning_min_capacity_kwh: float = None,
    ) -> dict:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.simulate_interval(
            mode=mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_soc_kwh,
            capacity_kwh=capacity_kwh,
            hw_min_capacity_kwh=hw_min_capacity_kwh,
            spot_price_czk=spot_price_czk,
            export_price_czk=export_price_czk,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            home_charge_rate_kwh_15min=home_charge_rate_kwh_15min,
            planning_min_capacity_kwh=planning_min_capacity_kwh,
        )

    def _calculate_interval_cost(
        self,
        simulation_result: Dict[str, Any],
        spot_price: float,
        export_price: float,
        time_of_day: str,
    ) -> Dict[str, Any]:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.calculate_interval_cost(
            simulation_result,
            spot_price,
            export_price,
            time_of_day,
        )

    def _calculate_fixed_mode_cost(
        self,
        fixed_mode: int,
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        physical_min_capacity: float | None = None,
    ) -> float:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.calculate_fixed_mode_cost(
            self,
            fixed_mode=fixed_mode,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
            physical_min_capacity=physical_min_capacity,
        )

    def _calculate_mode_baselines(
        self,
        current_capacity: float,
        max_capacity: float,
        physical_min_capacity: float,
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
    ) -> Dict[str, Dict[str, Any]]:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.calculate_mode_baselines(
            self,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            physical_min_capacity=physical_min_capacity,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
        )

    def _calculate_do_nothing_cost(
        self,
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
    ) -> float:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.calculate_do_nothing_cost(
            self,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
        )

    def _calculate_full_ups_cost(
        self,
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
    ) -> float:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.calculate_full_ups_cost(
            self,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
        )

    def _create_mode_recommendations(
        self, optimal_timeline: List[Dict[str, Any]], hours_ahead: int = 48
    ) -> List[Dict[str, Any]]:
        """Vytvořit user-friendly doporučení režimů pro DNES a ZÍTRA."""
        return mode_recommendations_module.create_mode_recommendations(
            optimal_timeline,
            hours_ahead=hours_ahead,
            mode_home_i=CBB_MODE_HOME_I,
            mode_home_ii=CBB_MODE_HOME_II,
            mode_home_iii=CBB_MODE_HOME_III,
            mode_home_ups=CBB_MODE_HOME_UPS,
        )

    def _generate_alternatives(  # noqa: C901
        self,
        spot_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        optimal_cost_48h: float,
        current_capacity: float,
        max_capacity: float,
        efficiency: float,
    ) -> Dict[str, Dict[str, Any]]:
        """Proxy to scenario analysis helpers."""
        return scenario_analysis_module.generate_alternatives(
            self,
            spot_prices=spot_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
            optimal_cost_48h=optimal_cost_48h,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            efficiency=efficiency,
        )

    def _update_balancing_plan_snapshot(self, plan: Optional[Dict[str, Any]]) -> None:
        """Proxy to balancing helpers."""
        balancing_helpers_module.update_balancing_plan_snapshot(self, plan)

    def _get_total_battery_capacity(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_total_battery_capacity(self)

    def _get_current_battery_soc_percent(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_current_battery_soc_percent(self)

    def _get_current_battery_capacity(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_current_battery_capacity(self)

    def _get_max_battery_capacity(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_max_battery_capacity(self)

    def _get_min_battery_capacity(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_min_battery_capacity(self)

    def _get_target_battery_capacity(self) -> Optional[float]:
        """Proxy to battery state helpers."""
        return battery_state_module.get_target_battery_capacity(self)

    async def _maybe_fix_daily_plan(self) -> None:  # noqa: C901
        """Proxy to plan storage helpers."""
        await plan_storage_module.maybe_fix_daily_plan(self)

    async def _load_plan_from_storage(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.load_plan_from_storage(self, date_str)

    async def _save_plan_to_storage(
        self,
        date_str: str,
        intervals: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.save_plan_to_storage(
            self, date_str, intervals, metadata
        )

    async def _plan_exists_in_storage(self, date_str: str) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.plan_exists_in_storage(self, date_str)

    def _is_baseline_plan_invalid(self, plan: Optional[Dict[str, Any]]) -> bool:
        """Proxy to plan storage helpers."""
        return plan_storage_module.is_baseline_plan_invalid(plan)

    async def _create_baseline_plan(self, date_str: str) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.create_baseline_plan(self, date_str)

    async def ensure_plan_exists(self, date_str: str) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.ensure_plan_exists(self, date_str)

    async def _aggregate_daily(self, date_str: str) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.aggregate_daily(self, date_str)

    async def _aggregate_weekly(
        self, week_str: str, start_date: str, end_date: str
    ) -> bool:
        """Proxy to plan storage helpers."""
        return await plan_storage_module.aggregate_weekly(
            self, week_str, start_date, end_date
        )

    async def _precompute_ui_data(self) -> None:
        """
        Precompute UI data (detail_tabs + unified_cost_tile) and save to storage.

        PHASE 3.5: Performance Optimization
        - Called every 15 min after forecast update
        - Saves precomputed data to ~/.storage/oig_cloud_precomputed_data_{box_id}.json
        - API endpoints read from storage → instant response (< 100ms)
        - Eliminates 4s wait time for build_detail_tabs() + build_unified_cost_tile()
        """
        await precompute_module.precompute_ui_data(self)

    def _schedule_precompute(self, force: bool = False) -> None:
        """Schedule precompute job with throttling."""
        precompute_module.schedule_precompute(self, force=force)

    async def build_timeline_extended(self) -> Dict[str, Any]:
        """
        Postavit rozšířenou timeline strukturu pro API.

        Phase 2.9: Timeline Extended Builder
        - Kombinuje historická data (včera) + mixed (dnes) + plánovaná (zítra)
        - Používá daily_plan_state pro historical tracking
        - Používá plánovač pro planned data
        - PHASE 3.0: Načítá Storage Helper data pro včerejší baseline plan

        Returns:
            Dict s yesterday/today/tomorrow sekcemi + today_tile_summary
        """
        return await timeline_extended_module.build_timeline_extended(
            self, mode_names=CBB_MODE_NAMES
        )

    async def _build_day_timeline(
        self, day: date, storage_plans: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return await timeline_extended_module.build_day_timeline(
            self, day, storage_plans, mode_names=CBB_MODE_NAMES
        )

    async def build_detail_tabs(
        self, tab: Optional[str] = None, plan: str = "hybrid"
    ) -> Dict[str, Any]:
        """
        Build Detail Tabs data (aggregated mode blocks).
        """
        return await detail_tabs_module.build_detail_tabs(
            self, tab=tab, plan=plan, mode_names=CBB_MODE_NAMES
        )

    def _decorate_plan_tabs(
        self,
        primary_tabs: Dict[str, Any],
        secondary_tabs: Dict[str, Any],
        primary_plan: str,
        secondary_plan: str,
    ) -> Dict[str, Any]:
        """Proxy to plan tab helpers."""
        return plan_tabs_module.decorate_plan_tabs(
            primary_tabs, secondary_tabs, primary_plan, secondary_plan
        )

    def _schedule_forecast_retry(self, delay_seconds: float) -> None:
        """Proxy to task helpers."""
        task_utils_module.schedule_forecast_retry(self, delay_seconds)

    def _create_task_threadsafe(self, coro_func, *args) -> None:
        """Proxy to task helpers."""
        task_utils_module.create_task_threadsafe(self, coro_func, *args)

    async def build_unified_cost_tile(self) -> Dict[str, Any]:
        """
        Build Unified Cost Tile data.

        Phase V2: PLAN_VS_ACTUAL_UX_REDESIGN_V2.md - Fáze 1 (UCT-BE-001 až UCT-BE-004)
        Consolidates 2 cost tiles into one with today/yesterday/tomorrow context.

        Cache: 60s TTL - prevents repeated slow API calls on page refresh.

        Returns:
            Dict with today/yesterday/tomorrow cost data:
            {
                "today": {
                    "plan_total_cost": 45.50,
                    "actual_total_cost": 42.30,
                    "delta": -3.20,
                    "performance": "better",  # better/worse/on_plan
                    "completed_intervals": 32,
                    "total_intervals": 96,
                    "progress_pct": 33,
                    "eod_prediction": {
                        "predicted_total": 128.50,
                        "vs_plan": -4.50,
                        "confidence": "medium"
                    }
                },
                "yesterday": {
                    "plan_total_cost": 125.00,
                    "actual_total_cost": 118.50,
                    "delta": -6.50,
                    "performance": "better"
                },
                "tomorrow": {
                    "plan_total_cost": 135.00
                }
            }
        """
        return await unified_cost_tile_module.build_unified_cost_tile(
            self, mode_names=CBB_MODE_NAMES
        )

    def _group_intervals_by_mode(
        self, intervals: List[Dict[str, Any]], data_type: str = "both"
    ) -> List[Dict[str, Any]]:
        """Proxy to interval grouping helpers."""
        return interval_grouping_module.group_intervals_by_mode(
            intervals, data_type=data_type, mode_names=CBB_MODE_NAMES
        )

    async def _backfill_daily_archive_from_storage(self) -> None:
        """Proxy to plan storage helpers."""
        await plan_storage_module.backfill_daily_archive_from_storage(self)

    def _get_battery_efficiency(self) -> float:
        """Proxy to battery state helpers."""
        return battery_state_module.get_battery_efficiency(self)

    def _get_ac_charging_limit_kwh_15min(self) -> float:
        """Proxy to battery state helpers."""
        return battery_state_module.get_ac_charging_limit_kwh_15min(self)

    def _get_current_mode(self) -> int:
        """Proxy to battery state helpers."""
        return battery_state_module.get_current_mode(self)

    def _get_boiler_available_capacity(self) -> float:
        """Proxy to battery state helpers."""
        return battery_state_module.get_boiler_available_capacity(self)

    def _calculate_final_spot_price(
        self, raw_spot_price: float, target_datetime: datetime
    ) -> float:
        """Proxy to pricing helpers."""
        return pricing_module.calculate_final_spot_price(
            self, raw_spot_price, target_datetime
        )

    async def _get_spot_price_timeline(self) -> List[Dict[str, Any]]:
        """Proxy to pricing helpers."""
        return await pricing_module.get_spot_price_timeline(self)

    async def _get_export_price_timeline(self) -> List[Dict[str, Any]]:
        """Proxy to pricing helpers."""
        return await pricing_module.get_export_price_timeline(self)

    def _get_spot_data_from_price_sensor(
        self, *, price_type: str
    ) -> Optional[Dict[str, Any]]:
        """Proxy to pricing helpers."""
        return pricing_module.get_spot_data_from_price_sensor(
            self, price_type=price_type
        )

    async def _get_spot_data_from_ote_cache(self) -> Optional[Dict[str, Any]]:
        """Proxy to pricing helpers."""
        return await pricing_module.get_spot_data_from_ote_cache(self)

    def _get_solar_forecast(self) -> Dict[str, Any]:
        """Proxy to solar forecast helpers."""
        return solar_forecast_module.get_solar_forecast(self)

    def _get_solar_forecast_strings(self) -> Dict[str, Any]:
        """Proxy to solar forecast helpers."""
        return solar_forecast_module.get_solar_forecast_strings(self)

    def _get_balancing_plan(self) -> Optional[Dict[str, Any]]:
        """Proxy to balancing helpers."""
        return balancing_helpers_module.get_balancing_plan(self)

    def _build_strategy_balancing_plan(
        self,
        spot_prices: List[Dict[str, Any]],
        plan: Optional[Any],
    ) -> Optional[Any]:
        """Build strategy-layer balancing plan from BalancingManager output."""
        if not plan:
            return None

        try:
            from datetime import datetime

            from homeassistant.util import dt as dt_util

            from ..strategy.balancing import StrategyBalancingPlan

            def _get_plan_value(obj: Any, key: str, default: Any = None) -> Any:
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            def _parse_ts(value: Any) -> Optional[datetime]:
                if not value:
                    return None
                try:
                    ts = datetime.fromisoformat(str(value))
                except Exception:
                    return None
                return dt_util.as_local(ts)

            spot_times: List[Optional[datetime]] = []
            index_by_minute: Dict[int, int] = {}
            for idx, sp in enumerate(spot_prices):
                ts = _parse_ts(sp.get("time"))
                spot_times.append(ts)
                if ts:
                    index_by_minute[int(ts.timestamp() // 60)] = idx

            def _find_index(ts: datetime) -> Optional[int]:
                return index_by_minute.get(int(ts.timestamp() // 60))

            is_active = bool(_get_plan_value(plan, "active", True))
            if not is_active:
                return None

            charging_intervals: set[int] = set()
            holding_intervals: set[int] = set()
            mode_overrides: Dict[int, int] = {}

            intervals = _get_plan_value(plan, "intervals", None)
            if not intervals:
                legacy = _get_plan_value(plan, "charging_intervals", []) or []
                intervals = [{"ts": ts, "mode": CBB_MODE_HOME_UPS} for ts in legacy]

            for interval in intervals:
                ts_raw = (
                    interval.get("ts")
                    if isinstance(interval, dict)
                    else getattr(interval, "ts", None)
                )
                mode_raw = (
                    interval.get("mode")
                    if isinstance(interval, dict)
                    else getattr(interval, "mode", None)
                )
                ts = _parse_ts(ts_raw)
                if ts is None or mode_raw is None:
                    continue
                idx = _find_index(ts)
                if idx is None:
                    continue
                mode = int(mode_raw)
                mode_overrides[idx] = mode
                if mode == CBB_MODE_HOME_UPS:
                    charging_intervals.add(idx)

            holding_start = _parse_ts(_get_plan_value(plan, "holding_start"))
            holding_end = _parse_ts(_get_plan_value(plan, "holding_end"))
            if holding_start and holding_end:
                for idx, ts in enumerate(spot_times):
                    if ts and holding_start <= ts < holding_end:
                        holding_intervals.add(idx)

            return StrategyBalancingPlan(
                charging_intervals=charging_intervals,
                holding_intervals=holding_intervals,
                mode_overrides=mode_overrides,
                is_active=is_active,
            )
        except Exception as err:
            _LOGGER.debug("Failed to build strategy balancing plan: %s", err)
            return None

    async def plan_balancing(
        self,
        requested_start: datetime,
        requested_end: datetime,
        target_soc: float,
        mode: str,
    ) -> Dict[str, Any]:
        """Proxy to balancing helpers."""
        return await balancing_helpers_module.plan_balancing(
            self, requested_start, requested_end, target_soc, mode
        )

    def _get_load_avg_sensors(self) -> Dict[str, Any]:
        """Proxy to load profile helpers."""
        return load_profiles_module.get_load_avg_sensors(self)

    def _economic_charging_plan(
        self,
        timeline_data: List[Dict[str, Any]],
        min_capacity_kwh: float,
        effective_minimum_kwh: float,
        target_capacity_kwh: float,
        max_charging_price: float,
        min_savings_margin: float,
        charging_power_kw: float,
        max_capacity: float,
        enable_blackout_protection: bool,
        blackout_protection_hours: int,
        blackout_target_soc_percent: float,
        enable_weather_risk: bool,
        weather_risk_level: str,
        weather_target_soc_percent: float,
        target_reason: str = "default",
    ) -> List[Dict[str, Any]]:
        """Proxy to charging helpers."""
        return charging_helpers_module.economic_charging_plan(
            self,
            timeline_data=timeline_data,
            min_capacity_kwh=min_capacity_kwh,
            effective_minimum_kwh=effective_minimum_kwh,
            target_capacity_kwh=target_capacity_kwh,
            max_charging_price=max_charging_price,
            min_savings_margin=min_savings_margin,
            charging_power_kw=charging_power_kw,
            max_capacity=max_capacity,
            enable_blackout_protection=enable_blackout_protection,
            blackout_protection_hours=blackout_protection_hours,
            blackout_target_soc_percent=blackout_target_soc_percent,
            enable_weather_risk=enable_weather_risk,
            weather_risk_level=weather_risk_level,
            weather_target_soc_percent=weather_target_soc_percent,
            iso_tz_offset=ISO_TZ_OFFSET,
            target_reason=target_reason,
        )

    def _smart_charging_plan(
        self,
        timeline: List[Dict[str, Any]],
        min_capacity: float,
        target_capacity: float,
        max_price: float,
        price_threshold: float,
        charging_power_kw: float,
        max_capacity: float,
    ) -> List[Dict[str, Any]]:
        """Proxy to charging helpers."""
        return charging_helpers_module.smart_charging_plan(
            self,
            timeline=timeline,
            min_capacity=min_capacity,
            target_capacity=target_capacity,
            max_price=max_price,
            price_threshold=price_threshold,
            charging_power_kw=charging_power_kw,
            max_capacity=max_capacity,
        )
