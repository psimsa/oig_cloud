"""Forecast update routine extracted from ha_sensor."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List

from homeassistant.util import dt as dt_util

from ...const import DOMAIN
from ..config import HybridConfig, SimulatorConfig
from ..data.adaptive_consumption import AdaptiveConsumptionHelper
from ..data.input import get_load_avg_for_timestamp, get_solar_for_timestamp
from ..strategy import HybridStrategy
from ..timeline.planner import (
    add_decision_reasons_to_timeline,
    attach_planner_reasons,
    build_planner_timeline,
)
from ..types import CBB_MODE_NAMES
from . import auto_switch as auto_switch_module
from . import mode_guard as mode_guard_module

_LOGGER = logging.getLogger(__name__)
ISO_TZ_OFFSET = "+00:00"
MODE_GUARD_MINUTES = 60


async def async_update(sensor: Any) -> None:  # noqa: C901
    """Update sensor data."""

    try:
        mark_bucket_done = False
        now_aware = dt_util.now()
        bucket_minute = (now_aware.minute // 15) * 15
        bucket_start = now_aware.replace(minute=bucket_minute, second=0, microsecond=0)

        # Enforce single in-flight computation.
        if sensor._forecast_in_progress:
            sensor._log_rate_limited(
                "forecast_in_progress",
                "debug",
                "Forecast computation already in progress - skipping",
                cooldown_s=60.0,
            )
            return

        # Enforce cadence: at most once per 15-minute bucket.
        if sensor._last_forecast_bucket == bucket_start:
            return

        sensor._forecast_in_progress = True

        # Ziskat vsechna potrebna data
        sensor._log_rate_limited(
            "forecast_update_tick",
            "debug",
            "Battery forecast async_update() tick",
            cooldown_s=300.0,
        )
        current_capacity = sensor._get_current_battery_capacity()
        max_capacity = sensor._get_max_battery_capacity()
        min_capacity = sensor._get_min_battery_capacity()

        if current_capacity is None or max_capacity is None or min_capacity is None:
            # During startup, sensors may not be ready yet. Retry shortly without spamming logs.
            sensor._log_rate_limited(
                "forecast_missing_capacity",
                "debug",
                "Forecast prerequisites not ready (current=%s max=%s min=%s); retrying shortly",
                current_capacity,
                max_capacity,
                min_capacity,
                cooldown_s=120.0,
            )
            sensor._schedule_forecast_retry(10.0)
            return
        mark_bucket_done = True

        _LOGGER.debug(
            "Battery capacities: current=%.2f kWh, max=%.2f kWh, min=%.2f kWh",
            current_capacity,
            max_capacity,
            min_capacity,
        )

        sensor._log_rate_limited(
            "forecast_spot_fetch",
            "debug",
            "Calling _get_spot_price_timeline()",
            cooldown_s=600.0,
        )
        spot_prices = await sensor._get_spot_price_timeline()  # ASYNC!
        sensor._log_rate_limited(
            "forecast_spot_fetch_done",
            "debug",
            "_get_spot_price_timeline() returned %s prices",
            len(spot_prices),
            cooldown_s=600.0,
        )

        # CRITICAL FIX: Filter spot prices to start from current 15-minute interval
        # Round NOW down to nearest 15-minute interval (00, 15, 30, 45)
        current_interval_start = bucket_start
        # Convert to naive datetime for comparison (spot prices are timezone-naive strings)
        current_interval_naive = current_interval_start.replace(tzinfo=None)

        sensor._log_rate_limited(
            "forecast_spot_filter",
            "debug",
            "Filtering timeline from current interval: %s",
            current_interval_naive.isoformat(),
            cooldown_s=600.0,
        )

        spot_prices_filtered = [
            sp
            for sp in spot_prices
            if datetime.fromisoformat(sp["time"]) >= current_interval_naive
        ]
        if len(spot_prices_filtered) < len(spot_prices):
            sensor._log_rate_limited(
                "forecast_spot_filtered",
                "debug",
                "Filtered spot prices: %s -> %s (removed %s past intervals)",
                len(spot_prices),
                len(spot_prices_filtered),
                len(spot_prices) - len(spot_prices_filtered),
                cooldown_s=600.0,
            )
        spot_prices = spot_prices_filtered

        # Phase 1.5: Load export prices for timeline integration
        sensor._log_rate_limited(
            "forecast_export_fetch",
            "debug",
            "Calling _get_export_price_timeline()",
            cooldown_s=600.0,
        )
        export_prices = await sensor._get_export_price_timeline()  # ASYNC!
        sensor._log_rate_limited(
            "forecast_export_fetch_done",
            "debug",
            "_get_export_price_timeline() returned %s prices",
            len(export_prices),
            cooldown_s=600.0,
        )

        # Filter export prices too
        export_prices = [
            ep
            for ep in export_prices
            if datetime.fromisoformat(ep["time"]) >= current_interval_naive
        ]

        solar_forecast = sensor._get_solar_forecast()
        load_avg_sensors = sensor._get_load_avg_sensors()

        # NOVE: Zkusit ziskat adaptivni profily
        adaptive_helper = AdaptiveConsumptionHelper(
            sensor.hass or sensor._hass,
            sensor._box_id,
            ISO_TZ_OFFSET,
        )
        adaptive_profiles = await adaptive_helper.get_adaptive_load_prediction()

        # NOVE: Ziskat balancing plan
        balancing_plan = sensor._get_balancing_plan()

        if not spot_prices:
            _LOGGER.warning(
                "No spot prices available - forecast will use fallback prices"
            )
            # Continue anyway - forecast can run with fallback prices

        # ONE PLANNER: single planning pipeline.

        # PHASE 2.8 + REFACTORING: Get target from new getter
        target_capacity = sensor._get_target_battery_capacity()
        current_soc_percent = sensor._get_current_battery_soc_percent()

        if target_capacity is None:
            target_capacity = max_capacity
        if current_soc_percent is None and max_capacity > 0:
            current_soc_percent = (current_capacity / max_capacity) * 100.0

        sensor._log_rate_limited(
            "battery_state_summary",
            "debug",
            "Battery state: current=%.2f kWh (%.1f%%), total=%.2f kWh, min=%.2f kWh, target=%.2f kWh",
            current_capacity,
            float(current_soc_percent or 0.0),
            max_capacity,
            min_capacity,
            target_capacity,
            cooldown_s=600.0,
        )

        # Build load forecast list (kWh/15min for each interval)
        load_forecast = []
        today = dt_util.now().date()
        for sp in spot_prices:
            try:
                timestamp = datetime.fromisoformat(sp["time"])
                # Normalize timezone
                if timestamp.tzinfo is None:
                    timestamp = dt_util.as_local(timestamp)

                if adaptive_profiles:
                    # Use adaptive profiles (hourly  15min)
                    if timestamp.date() == today:
                        profile = adaptive_profiles["today_profile"]
                    else:
                        profile = adaptive_profiles.get(
                            "tomorrow_profile", adaptive_profiles["today_profile"]
                        )

                    hour = timestamp.hour
                    start_hour = profile.get("start_hour", 0)  # Default 0 for tomorrow

                    # Mapovani absolutni hodiny na index v poli
                    # today_profile: start_hour=14  hour=14  index=0, hour=15  index=1
                    # tomorrow_profile: start_hour=0  hour=0  index=0, hour=1  index=1
                    index = hour - start_hour

                    if 0 <= index < len(profile["hourly_consumption"]):
                        hourly_kwh = profile["hourly_consumption"][index]
                    else:
                        # Mimo rozsah - pouzij prumer nebo fallback
                        sensor._log_rate_limited(
                            "adaptive_profile_oob",
                            "debug",
                            "Adaptive profile hour out of range: hour=%s start=%s len=%s (using avg)",
                            hour,
                            start_hour,
                            len(profile.get("hourly_consumption", []) or []),
                            cooldown_s=900.0,
                        )
                        hourly_kwh = profile.get("avg_kwh_h", 0.5)

                    load_kwh = hourly_kwh / 4.0
                else:
                    # Fallback: load_avg sensors
                    load_kwh = get_load_avg_for_timestamp(
                        timestamp,
                        load_avg_sensors,
                        state=sensor,
                    )

                load_forecast.append(load_kwh)
            except Exception as e:
                _LOGGER.warning(f"Failed to get load for {sp.get('time')}: {e}")
                load_forecast.append(0.125)  # 500W fallback

        if adaptive_profiles:
            recent_ratio = await adaptive_helper.calculate_recent_consumption_ratio(
                adaptive_profiles
            )
            if recent_ratio and recent_ratio > 1.1:
                adaptive_helper.apply_consumption_boost_to_forecast(
                    load_forecast, recent_ratio
                )

        # PLANNER: build plan timeline with HybridStrategy.
        try:
            active_balancing_plan = None
            try:
                entry_id = (
                    sensor._config_entry.entry_id if sensor._config_entry else None
                )
                if (
                    entry_id
                    and DOMAIN in sensor._hass.data
                    and entry_id in sensor._hass.data[DOMAIN]
                ):
                    balancing_manager = sensor._hass.data[DOMAIN][entry_id].get(
                        "balancing_manager"
                    )
                    if balancing_manager:
                        active_balancing_plan = balancing_manager.get_active_plan()
            except Exception as err:
                _LOGGER.debug("Could not load BalancingManager plan: %s", err)

            # Build solar list (kWh/15min) aligned to spot_prices
            solar_kwh_list: List[float] = []
            for sp in spot_prices:
                try:
                    ts = datetime.fromisoformat(sp.get("time", ""))
                    if ts.tzinfo is None:
                        ts = dt_util.as_local(ts)
                    solar_kwh_list.append(
                        get_solar_for_timestamp(
                            ts,
                            solar_forecast,
                            log_rate_limited=sensor._log_rate_limited,
                        )
                    )
                except Exception:
                    solar_kwh_list.append(0.0)

            # Hard-limit horizon to 36h (14415min).
            max_intervals = 36 * 4
            if len(spot_prices) > max_intervals:
                spot_prices = spot_prices[:max_intervals]
                export_prices = export_prices[:max_intervals]
                load_forecast = load_forecast[:max_intervals]
                solar_kwh_list = solar_kwh_list[:max_intervals]

            balancing_plan = sensor._build_strategy_balancing_plan(
                spot_prices, active_balancing_plan
            )

            opts = sensor._config_entry.options if sensor._config_entry else {}
            max_ups_price_czk = float(opts.get("max_ups_price_czk", 10.0))
            efficiency = float(sensor._get_battery_efficiency())
            home_charge_rate_kw = float(opts.get("home_charge_rate", 2.8))

            sim_config = SimulatorConfig(
                max_capacity_kwh=max_capacity,
                min_capacity_kwh=max_capacity * 0.20,
                charge_rate_kw=home_charge_rate_kw,
                dc_dc_efficiency=efficiency,
                dc_ac_efficiency=efficiency,
                ac_dc_efficiency=efficiency,
            )
            hybrid_config = HybridConfig(
                planning_min_percent=float(opts.get("min_capacity_percent", 33.0)),
                target_percent=float(opts.get("target_capacity_percent", 80.0)),
                max_ups_price_czk=max_ups_price_czk,
            )

            export_price_values: List[float] = []
            for i in range(len(spot_prices)):
                if i < len(export_prices):
                    export_price_values.append(
                        float(export_prices[i].get("price", 0.0) or 0.0)
                    )
                else:
                    export_price_values.append(0.0)

            strategy = HybridStrategy(hybrid_config, sim_config)
            result = strategy.optimize(
                initial_battery_kwh=current_capacity,
                spot_prices=spot_prices,
                solar_forecast=solar_kwh_list,
                consumption_forecast=load_forecast,
                balancing_plan=balancing_plan,
                export_prices=export_price_values,
            )

            hw_min_kwh = max_capacity * 0.20
            planning_min_kwh = hybrid_config.planning_min_kwh(max_capacity)
            lock_until, lock_modes = mode_guard_module.build_plan_lock(
                now=dt_util.now(),
                spot_prices=spot_prices,
                modes=result.modes,
                mode_guard_minutes=MODE_GUARD_MINUTES,
                plan_lock_until=sensor._plan_lock_until,
                plan_lock_modes=sensor._plan_lock_modes,
            )
            sensor._plan_lock_until = lock_until
            sensor._plan_lock_modes = lock_modes
            guarded_modes, guard_overrides, guard_until = (
                mode_guard_module.apply_mode_guard(
                    modes=result.modes,
                    spot_prices=spot_prices,
                    solar_kwh_list=solar_kwh_list,
                    load_forecast=load_forecast,
                    current_capacity=current_capacity,
                    max_capacity=max_capacity,
                    hw_min_capacity=hw_min_kwh,
                    efficiency=efficiency,
                    home_charge_rate_kw=home_charge_rate_kw,
                    planning_min_kwh=planning_min_kwh,
                    lock_modes=lock_modes,
                    guard_until=lock_until,
                    log_rate_limited=sensor._log_rate_limited,
                )
            )
            sensor._timeline_data = build_planner_timeline(
                modes=guarded_modes,
                spot_prices=spot_prices,
                export_prices=export_prices,
                solar_forecast=solar_forecast,
                load_forecast=load_forecast,
                current_capacity=current_capacity,
                max_capacity=max_capacity,
                hw_min_capacity=hw_min_kwh,
                efficiency=efficiency,
                home_charge_rate_kw=home_charge_rate_kw,
                log_rate_limited=sensor._log_rate_limited,
            )
            attach_planner_reasons(sensor._timeline_data, result.decisions)

            add_decision_reasons_to_timeline(
                sensor._timeline_data,
                current_capacity=current_capacity,
                max_capacity=max_capacity,
                min_capacity=planning_min_kwh,
                efficiency=float(efficiency),
            )
            mode_guard_module.apply_guard_reasons_to_timeline(
                sensor._timeline_data,
                guard_overrides,
                guard_until,
                None,
                mode_names=CBB_MODE_NAMES,
            )
            sensor._hybrid_timeline = sensor._timeline_data
            sensor._mode_optimization_result = {
                "optimal_timeline": sensor._timeline_data,
                "optimal_modes": guarded_modes,
                "planner": "planner",
                "planning_min_kwh": planning_min_kwh,
                "target_kwh": hybrid_config.target_kwh(max_capacity),
                "infeasible": result.infeasible,
                "infeasible_reason": result.infeasible_reason,
            }
            sensor._mode_recommendations = sensor._create_mode_recommendations(
                sensor._timeline_data, hours_ahead=48
            )

        except Exception as e:
            _LOGGER.error("Planner failed: %s", e, exc_info=True)
            sensor._timeline_data = []
            sensor._hybrid_timeline = []
            sensor._mode_optimization_result = None
            sensor._mode_recommendations = []

        # PHASE 2.9: Fix daily plan at midnight for tracking (AFTER _timeline_data is set)
        await sensor._maybe_fix_daily_plan()

        # Baseline timeline (legacy) is no longer computed.
        # Keeping attribute for backwards compatibility only.
        sensor._baseline_timeline = []

        # Phase 1.5: Calculate hash for change detection
        new_hash = sensor._calculate_data_hash(sensor._timeline_data)
        if new_hash != sensor._data_hash:
            _LOGGER.debug(
                f"Timeline data changed: {sensor._data_hash[:8] if sensor._data_hash else 'none'} -> {new_hash[:8]}"
            )
            sensor._data_hash = new_hash
        else:
            _LOGGER.debug("Timeline data unchanged (same hash)")

        sensor._last_update = datetime.now()
        _LOGGER.debug(
            f"Battery forecast updated: {len(sensor._timeline_data)} timeline points"
        )

        # Vypocitat consumption summary pro dashboard
        if adaptive_profiles and isinstance(adaptive_profiles, dict):
            sensor._consumption_summary = adaptive_helper.calculate_consumption_summary(
                adaptive_profiles
            )
        else:
            sensor._consumption_summary = {}

        # Oznacit ze prvni update probehl
        if sensor._first_update:
            sensor._first_update = False

        # KRITICKE: Ulozit timeline zpet do coordinator.data aby grid_charging_planned sensor videl aktualni data
        if hasattr(sensor.coordinator, "battery_forecast_data"):
            sensor.coordinator.battery_forecast_data = {
                "timeline_data": sensor._timeline_data,
                "calculation_time": sensor._last_update.isoformat(),
                "data_source": "simplified_calculation",
                "current_battery_kwh": (
                    sensor._timeline_data[0].get("battery_capacity_kwh", 0)
                    if sensor._timeline_data
                    else 0
                ),
                # Correct key and default: API expects `mode_recommendations` (list)
                "mode_recommendations": sensor._mode_recommendations or [],
            }
            _LOGGER.info(
                " Battery forecast data saved to coordinator - grid_charging_planned will update"
            )

            # Data jsou uz v coordinator.battery_forecast_data
            # Grid charging sensor je zavisly na coordinator update cycle
            # NEMENIME coordinator.data - jen pridavame battery_forecast_data

        # Keep auto mode switching schedule in sync with the latest timeline.
        # This also cancels any previously scheduled events when switching is disabled.
        if sensor._side_effects_enabled:
            sensor._create_task_threadsafe(
                auto_switch_module.update_auto_switch_schedule, sensor
            )

        # SIMPLE STORAGE: Update actual values kazdych 15 minut
        now = dt_util.now()
        current_minute = now.minute

        # Spustit update kazdych 15 minut (v 0, 15, 30, 45)
        should_update = current_minute in [0, 15, 30, 45]

        if should_update:
            # PHASE 3.0: DISABLED - Historical data loading moved to on-demand (API only)
            # Nacitani z Recorderu kazdych 15 min je POMALE!
            # Nove: build_timeline_extended() nacita on-demand pri API volani.
            # NOTE: Historically skipped until initial history update; kept for future re-enable.
            pass

        # CRITICAL FIX: Write state after every update to publish consumption_summary
        # Check if sensor is already added to HA (sensor.hass is set by framework)
        if not sensor.hass:
            _LOGGER.debug("Sensor not yet added to HA, skipping state write")
            return

        sensor._log_rate_limited(
            "write_state_consumption_summary",
            "debug",
            " Writing HA state with consumption_summary: %s",
            sensor._consumption_summary,
            cooldown_s=900.0,
        )
        sensor.async_write_ha_state()

        # NOTE: Single planner only.

        # PHASE 3.5: Precompute UI data for instant API responses
        # Build timeline_extended + unified_cost_tile and save to storage
        # This runs every 15 min after forecast update
        hash_changed = sensor._data_hash != sensor._last_precompute_hash
        sensor._schedule_precompute(
            force=sensor._last_precompute_at is None or hash_changed
        )

        # Notify dependent sensors (BatteryBalancing) that forecast is ready
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        signal_name = f"oig_cloud_{sensor._box_id}_forecast_updated"
        _LOGGER.debug(f" Sending signal: {signal_name}")
        async_dispatcher_send(sensor.hass, signal_name)

    except Exception as e:
        _LOGGER.error(f"Error updating battery forecast: {e}", exc_info=True)
    finally:
        # Mark bucket complete only if prerequisites were ready.
        try:
            if mark_bucket_done:
                now_done = dt_util.now()
                done_bucket_minute = (now_done.minute // 15) * 15
                sensor._last_forecast_bucket = now_done.replace(
                    minute=done_bucket_minute, second=0, microsecond=0
                )
                # We intentionally keep profiles dirty until a successful compute; if async_update
                # failed, the next tick will retry.
                if sensor._timeline_data:
                    sensor._profiles_dirty = False
        except Exception:  # nosec B110
            pass
        sensor._forecast_in_progress = False
