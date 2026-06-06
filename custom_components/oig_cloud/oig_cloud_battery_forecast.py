"""Zjednodušený senzor pro predikci nabití baterie v průběhu dne."""

import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Union

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.event import (
        async_track_time_interval as _async_track_time_interval,  # type: ignore
    )
except Exception:  # pragma: no cover
    _async_track_time_interval = None

from .api.ote_api import OteApi
from .battery_forecast.config import HybridConfig, SimulatorConfig
from .battery_forecast.strategy import BalancingPlan as StrategyBalancingPlan
from .battery_forecast.strategy import HybridStrategy
from .const import (  # PHASE 3: Import DOMAIN for BalancingManager access
    CONF_AUTO_MODE_SWITCH,
    DOMAIN,
    OTE_SPOT_PRICE_CACHE_FILE,
)
from .physics import simulate_interval

_LOGGER = logging.getLogger(__name__)

AUTO_SWITCH_STARTUP_DELAY = timedelta(seconds=0)


# PHASE 3.0 FIX: Safe nested get helper to prevent AttributeError on None values
def safe_nested_get(obj: Optional[Dict[str, Any]], *keys: str, default: Any = 0) -> Any:
    """
    Safely get nested dict values, handling None at any level.

    Args:
        obj: Dict or None
        keys: Sequence of keys to traverse (e.g., "planned", "net_cost")
        default: Default value if any key is missing or value is None

    Returns:
        Value if found, default otherwise

    Example:
        safe_nested_get(interval, "planned", "net_cost", default=0)
        # Same as: interval.get("planned", {}).get("net_cost", 0)
        # But handles: interval.get("planned") = None ✓
    """
    current = obj
    for key in keys:
        if current is None or not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


# CBB 3F Home Plus Premium - Mode Constants (Phase 2)
# Mode definitions from sensor.oig_{box_id}_box_prms_mode
CBB_MODE_HOME_I = 0  # Grid priority (cheap mode)
CBB_MODE_HOME_II = 1  # Battery priority
CBB_MODE_HOME_III = 2  # Solar priority (default)
CBB_MODE_HOME_UPS = 3  # UPS mode (AC charging enabled)
#
# Note: The box also supports "Home 5" and "Home 6". We do not simulate these
# modes; when they appear in history/current state, we map them to HOME I.

# Mode names for display
CBB_MODE_NAMES = {
    CBB_MODE_HOME_I: "HOME I",
    CBB_MODE_HOME_II: "HOME II",
    CBB_MODE_HOME_III: "HOME III",
    CBB_MODE_HOME_UPS: "HOME UPS",
}

# Mode transition costs (energy loss + time delay)
MODE_LABEL_HOME_I = "Home I"
MODE_LABEL_HOME_II = "Home II"
MODE_LABEL_HOME_III = "Home III"
MODE_LABEL_HOME_UPS = "Home UPS"

SERVICE_MODE_HOME_1 = "Home 1"
SERVICE_MODE_HOME_2 = "Home 2"
SERVICE_MODE_HOME_3 = "Home 3"
SERVICE_MODE_HOME_UPS = "Home UPS"
SERVICE_MODE_HOME_5 = "Home 5"
SERVICE_MODE_HOME_6 = "Home 6"

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
ISO_TZ_OFFSET = "+00:00"

TRANSITION_COSTS = {
    (MODE_LABEL_HOME_I, MODE_LABEL_HOME_UPS): {
        "energy_loss_kwh": 0.05,  # Energy loss when switching to UPS
        "time_delay_intervals": 1,  # Delay in 15-min intervals
    },
    (MODE_LABEL_HOME_UPS, MODE_LABEL_HOME_I): {
        "energy_loss_kwh": 0.02,  # Energy loss when switching from UPS
        "time_delay_intervals": 0,
    },
    (MODE_LABEL_HOME_I, MODE_LABEL_HOME_II): {
        "energy_loss_kwh": 0.0,  # No loss between Home modes
        "time_delay_intervals": 0,
    },
    (MODE_LABEL_HOME_II, MODE_LABEL_HOME_I): {
        "energy_loss_kwh": 0.0,
        "time_delay_intervals": 0,
    },
}

# Minimum mode duration (in 15-min intervals)
MIN_MODE_DURATION = {
    MODE_LABEL_HOME_UPS: 2,  # UPS must run at least 30 minutes (2×15min)
    MODE_LABEL_HOME_I: 1,
    MODE_LABEL_HOME_II: 1,
}

# Stabilizační guard po změně režimu (v minutách)
MODE_GUARD_MINUTES = 60

CBB_MODE_SERVICE_MAP = {
    CBB_MODE_HOME_I: SERVICE_MODE_HOME_1,
    CBB_MODE_HOME_II: SERVICE_MODE_HOME_2,
    CBB_MODE_HOME_III: SERVICE_MODE_HOME_3,
    CBB_MODE_HOME_UPS: SERVICE_MODE_HOME_UPS,
}

# AC Charging - modes where charging is DISABLED (only solar DC/DC allowed)
AC_CHARGING_DISABLED_MODES = [CBB_MODE_HOME_I, CBB_MODE_HOME_II, CBB_MODE_HOME_III]

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

        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._device_info = device_info

        # Nastavit hass - priorita: parametr > coordinator.hass
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)
        # Guard side effects (service calls, timers) for temp instances created by coordinator.
        self._side_effects_enabled: bool = bool(side_effects_enabled)

        # Stabilní box_id resolution (config entry → proxy → coordinator numeric keys)
        try:
            from .oig_cloud_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        if self._box_id == "unknown":
            _LOGGER.warning(
                "Battery forecast sensor: unable to resolve box_id, using 'unknown' (sensor will be unstable)"
            )

        # Nastavit atributy senzoru - STEJNĚ jako OigCloudStatisticsSensor
        # Unique ID má formát oig_cloud_{boxId}_{sensor} pro konzistenci
        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        self._attr_icon = "mdi:battery-charging-60"
        self._attr_native_unit_of_measurement = "kWh"
        self._attr_device_class = SensorDeviceClass.ENERGY_STORAGE
        # Represents current/forecasted battery capacity; not strictly increasing.
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = None

        # Načíst název ze sensor types
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")
        self._attr_name = name_cs or name_en or sensor_type

        # Timeline data cache
        # Throttling: forecast should be computed at most once per 15-minute interval.
        self._last_forecast_bucket: Optional[datetime] = None
        self._forecast_in_progress: bool = False
        self._profiles_dirty: bool = False
        self._plan_lock_until: Optional[datetime] = None
        self._plan_lock_modes: Dict[str, int] = {}
        self._timeline_data: List[Dict[str, Any]] = (
            []
        )  # ACTIVE timeline (with applied plan)
        self._baseline_timeline: List[Dict[str, Any]] = []  # CLEAN baseline (no plan)
        self._last_update: Optional[datetime] = None
        self._charging_metrics: Dict[str, Any] = {}
        self._adaptive_consumption_data: Dict[str, Any] = {}  # DEPRECATED
        self._consumption_summary: Dict[str, Any] = (
            {}
        )  # NOVÉ: pro dashboard (4 hodnoty)
        self._first_update: bool = True  # Flag pro první update (setup)
        self._auto_switch_handles: List[Any] = []
        self._last_auto_switch_request: Optional[Tuple[str, datetime]] = None
        self._auto_switch_ready_at: Optional[datetime] = (
            dt_util.now() + AUTO_SWITCH_STARTUP_DELAY
        )
        self._auto_switch_retry_unsub: Optional[Callable[[], None]] = None
        self._auto_switch_watchdog_unsub: Optional[Callable[[], None]] = None
        self._auto_switch_watchdog_interval: timedelta = timedelta(seconds=30)
        self._forecast_retry_unsub: Optional[Callable[[], None]] = None

        # Log throttling to prevent HA "logging too frequently" warnings
        self._log_last_ts = self._GLOBAL_LOG_LAST_TS

        # Planner result snapshot (legacy attribute schema name: mode_optimization)
        self._mode_optimization_result: Optional[Dict[str, Any]] = None

        # Phase 2.8: Mode recommendations (DNES + ZÍTRA) for API
        self._mode_recommendations: List[Dict[str, Any]] = []

        # Phase 2.9: Daily plans archive (včera, předevčírem, ...)
        self._daily_plans_archive: Dict[str, Dict[str, Any]] = {}  # {date: plan_state}

        # Phase 2.9: Current daily plan state (will be restored from HA storage)
        self._daily_plan_state: Optional[Dict[str, Any]] = None
        self._baseline_repair_attempts: set[str] = set()

        # Phase 1.5: Hash-based change detection
        self._data_hash: Optional[str] = (
            None  # MD5 hash of timeline_data for efficient change detection
        )

        # Unified charging planner - aktivní plán
        self._active_charging_plan: Optional[Dict[str, Any]] = None
        self._plan_status: str = "none"  # none | pending | active | completed
        self._balancing_plan_snapshot: Optional[Dict[str, Any]] = None

        # Phase 2.9: Hourly history update tracking
        self._last_history_update_hour: Optional[int] = None
        self._initial_history_update_done: bool = False

        # Phase 3.0: Storage Helper for persistent battery plans
        # Storage path: /var/lib/homeassistant/homeassistant/config/.storage/
        # File: oig_cloud.battery_plans_{box_id}
        # Version: 1 (structure compatible with future migrations)
        self._plans_store: Optional[Store] = None
        if self._hass:
            self._plans_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.battery_plans_{self._box_id}",
            )
            _LOGGER.debug(
                f"✅ Initialized Storage Helper: oig_cloud.battery_plans_{self._box_id}"
            )
        else:
            _LOGGER.warning(
                "⚠️ Cannot initialize Storage Helper - hass not available yet. "
                "Will retry in async_added_to_hass()"
            )

        # Phase 3.5: Storage Helper for precomputed UI data (timeline_extended + unified_cost_tile)
        # File: oig_cloud.precomputed_data_{box_id}
        # Updated every 15 min by coordinator → instant API responses
        self._precomputed_store: Optional[Store] = None
        self._precompute_interval = timedelta(minutes=15)
        self._last_precompute_at: Optional[datetime] = None
        self._last_precompute_hash: Optional[str] = None
        self._precompute_task: Optional[asyncio.Task] = None
        if self._hass:
            self._precomputed_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )
            _LOGGER.debug(
                f"✅ Initialized Precomputed Data Storage: oig_cloud.precomputed_data_{self._box_id}"
            )
        else:
            _LOGGER.debug(
                "⚠️ Precomputed storage will be initialized in async_added_to_hass()"
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
        """Log at most once per cooldown_s for a given key."""
        now_ts = time.time()
        last = self._log_last_ts.get(key, 0.0)
        if now_ts - last < cooldown_s:
            return
        self._log_last_ts[key] = now_ts
        logger = getattr(_LOGGER, level, None)
        if callable(logger):
            logger(message, *args)

    async def async_added_to_hass(self) -> None:  # noqa: C901
        """Při přidání do HA - restore persistent data."""
        await super().async_added_to_hass()
        self._hass = self.hass

        # Phase 3.0: Retry Storage Helper initialization if failed in __init__
        if not self._plans_store and self._hass:
            self._plans_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.battery_plans_{self._box_id}",
            )
            _LOGGER.info(
                f"✅ Retry: Initialized Storage Helper: oig_cloud.battery_plans_{self._box_id}"
            )

        # Phase 3.5: Retry Precomputed Data Storage initialization if failed in __init__
        if not self._precomputed_store and self._hass:
            self._precomputed_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )
            _LOGGER.info(
                f"✅ Retry: Initialized Precomputed Data Storage: oig_cloud.precomputed_data_{self._box_id}"
            )

        if self._auto_mode_switch_enabled():
            self._start_auto_switch_watchdog()
            # Keep scheduled set_box_mode calls aligned with the currently loaded timeline.
            if self._side_effects_enabled:
                self._create_task_threadsafe(self._update_auto_switch_schedule)

        # Restore last successful forecast output (so dashboard doesn't show 0 after restart)
        # Source of truth is the precomputed storage which also includes timeline snapshot.
        if self._precomputed_store:
            try:
                precomputed = await self._precomputed_store.async_load() or {}
                timeline = precomputed.get("timeline_hybrid")
                last_update = precomputed.get("last_update")
                if isinstance(timeline, list) and timeline:
                    self._timeline_data = timeline
                    # Keep a copy as hybrid timeline if other code references it.
                    setattr(self, "_hybrid_timeline", copy.deepcopy(timeline))
                    if isinstance(last_update, str) and last_update:
                        try:
                            self._last_update = dt_util.parse_datetime(
                                last_update
                            ) or dt_util.dt.datetime.fromisoformat(last_update)
                        except Exception:
                            self._last_update = dt_util.now()
                    self._data_hash = self._calculate_data_hash(self._timeline_data)
                    self.async_write_ha_state()
                    _LOGGER.debug(
                        "[BatteryForecast] Restored timeline from storage (%d points)",
                        len(self._timeline_data),
                    )
            except Exception as err:
                _LOGGER.debug(
                    "[BatteryForecast] Failed to restore precomputed data: %s", err
                )

        # Restore data z předchozí instance
        if last_state := await self.async_get_last_state():
            if last_state.attributes:
                # Restore active plan z attributes (pokud existoval)
                if "active_plan_data" in last_state.attributes:
                    try:
                        plan_json = last_state.attributes.get("active_plan_data")
                        if plan_json:
                            self._active_charging_plan = json.loads(plan_json)
                            self._plan_status = last_state.attributes.get(
                                "plan_status", "pending"
                            )
                            if self._active_charging_plan:
                                _LOGGER.info(
                                    f"✅ Restored charging plan: "
                                    f"requester={self._active_charging_plan.get('requester', 'unknown')}, "
                                    f"status={self._plan_status}"
                                )
                    except (json.decoder.JSONDecodeError, TypeError) as e:
                        _LOGGER.warning(f"Failed to restore charging plan: {e}")

        # PHASE 3.0: Storage Helper Integration
        # Storage plán se načítá on-demand v build_timeline_extended() (když API endpoint volá)
        # NEPOTŘEBUJEME načítat při startu - to jen zpomaluje startup
        _LOGGER.debug("Sensor initialized - storage plans will load on-demand via API")

        # PHASE 3.1: Load daily plans archive from storage (včera data pro Unified Cost Tile)
        if self._plans_store:
            try:
                storage_data = await self._plans_store.async_load() or {}
                if "daily_archive" in storage_data:
                    self._daily_plans_archive = storage_data["daily_archive"]
                    _LOGGER.info(
                        f"✅ Restored daily plans archive from storage: {len(self._daily_plans_archive)} days"
                    )
                else:
                    _LOGGER.info(
                        "No daily archive in storage - will backfill from history"
                    )
            except Exception as e:
                _LOGGER.warning(f"Failed to load daily plans archive from storage: {e}")

        # PHASE 3.1: Backfill missing days from storage detailed plans
        if self._plans_store and len(self._daily_plans_archive) < 3:
            try:
                _LOGGER.info("🔄 Backfilling daily plans archive from storage...")
                await self._backfill_daily_archive_from_storage()
            except Exception as e:
                _LOGGER.warning(f"Failed to backfill daily archive: {e}")

        # FALLBACK: Restore z attributes (starý způsob - bude deprecated)
        if last_state and last_state.attributes:
            # Restore daily plan state with actual intervals (Phase 2.9)
            if "daily_plan_state" in last_state.attributes:
                try:
                    daily_plan_json = last_state.attributes.get("daily_plan_state")
                    if daily_plan_json:
                        self._daily_plan_state = json.loads(daily_plan_json)
                        actual_count = len(self._daily_plan_state.get("actual", []))
                        _LOGGER.info(
                            f"✅ Restored daily plan state: "
                            f"date={self._daily_plan_state.get('date')}, "
                            f"actual={actual_count}"
                        )
                except (json.decoder.JSONDecodeError, TypeError) as e:
                    _LOGGER.warning(f"Failed to restore daily plan state: {e}")

        # PHASE 3.0: DISABLED - Historical data loading moved to on-demand (API only)
        # Old Phase 2.9 loaded history every 15 min - POMALÉ a ZBYTEČNÉ!
        # Nově: build_timeline_extended() načítá z Recorderu on-demand při API volání
        _LOGGER.debug("Historical data will load on-demand via API (not at startup)")

        # Import helper pro time tracking
        from homeassistant.helpers.event import async_track_time_change

        # ========================================================================
        # SCHEDULER: Forecast refresh každých 15 minut (asynchronní, neblokuje)
        # ========================================================================
        async def _forecast_refresh_job(now):
            """Run forecast refresh every 15 minutes (aligned with spot price intervals)."""
            _LOGGER.info(f"⏰ Forecast refresh triggered at {now.strftime('%H:%M')}")
            try:
                await self.async_update()
            except Exception as e:
                _LOGGER.error(f"Forecast refresh failed: {e}", exc_info=True)

        # Schedule every 15 minutes (at :00, :15, :30, :45)
        for minute in [0, 15, 30, 45]:
            async_track_time_change(
                self.hass,
                _forecast_refresh_job,
                minute=minute,
                second=30,  # 30s offset to ensure spot prices are updated
            )
        _LOGGER.info("✅ Scheduled forecast refresh every 15 minutes")

        # ========================================================================
        # LISTEN for AdaptiveLoadProfiles updates (dispatcher pattern)
        # ========================================================================
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        async def _on_profiles_updated():
            """Called when AdaptiveLoadProfiles completes update."""
            # Do not recompute immediately; keep forecast cadence at 1× / 15 minutes.
            # Mark inputs dirty and let the next scheduled 15-min tick pick it up.
            self._profiles_dirty = True
            self._log_rate_limited(
                "profiles_updated_deferred",
                "info",
                "📡 profiles_updated received - deferring forecast refresh to next 15-min tick",
                cooldown_s=300.0,
            )

        # Subscribe to profiles updates
        signal_name = f"oig_cloud_{self._box_id}_profiles_updated"
        _LOGGER.debug(f"📡 Subscribing to signal: {signal_name}")
        async_dispatcher_connect(self.hass, signal_name, _on_profiles_updated)

        # ========================================================================
        # INITIAL REFRESH: Wait for profiles, then calculate (non-blocking)
        # ========================================================================
        async def _delayed_initial_refresh():
            """Initial forecast calculation - wait for profiles (non-blocking)."""
            # Wait max 60s for first profiles update
            _LOGGER.info("⏳ Waiting for AdaptiveLoadProfiles to complete (max 60s)...")

            profiles_ready = False

            async def _mark_ready():
                nonlocal profiles_ready
                profiles_ready = True

            # Temporary listener for initial profiles
            temp_unsub = async_dispatcher_connect(
                self.hass, f"oig_cloud_{self._box_id}_profiles_updated", _mark_ready
            )

            try:
                # Wait max 60s for profiles
                for _ in range(60):
                    if profiles_ready:
                        _LOGGER.info("✅ Profiles ready - starting initial forecast")
                        break
                    await asyncio.sleep(1)
                else:
                    _LOGGER.info(
                        "Profiles not ready after 60s - starting forecast anyway"
                    )

                # Now run forecast
                await self.async_update()
                _LOGGER.info("✅ Initial forecast completed")

            except Exception as e:
                _LOGGER.error(f"Initial forecast failed: {e}", exc_info=True)
            finally:
                # Cleanup temporary listener
                temp_unsub()

        # Spustit jako background task (neblokuje async_added_to_hass)
        self.hass.async_create_task(_delayed_initial_refresh())

        # ========================================================================
        # SCHEDULER: Daily and weekly aggregations
        # ========================================================================
        # Daily aggregation at 00:05 (aggregate yesterday's data)
        async def _daily_aggregation_job(now):
            """Run daily aggregation at 00:05."""
            yesterday = (now.date() - timedelta(days=1)).strftime(DATE_FMT)
            _LOGGER.info(f"⏰ Daily aggregation job triggered for {yesterday}")
            await self._aggregate_daily(yesterday)

        async_track_time_change(
            self.hass,
            _daily_aggregation_job,
            hour=0,
            minute=5,
            second=0,
        )
        _LOGGER.debug("✅ Scheduled daily aggregation at 00:05")

        # Weekly aggregation every Sunday at 23:55
        async def _weekly_aggregation_job(now):
            """Run weekly aggregation on Sunday at 23:55."""
            # Only run on Sunday (weekday() == 6)
            if now.weekday() != 6:
                return

            # Calculate week info
            year, week_num, _ = now.isocalendar()
            week_str = f"{year}-W{week_num:02d}"

            # Week end is today (Sunday)
            end_date = now.date().strftime(DATE_FMT)
            # Week start is 6 days ago (Monday)
            start_date = (now.date() - timedelta(days=6)).strftime(DATE_FMT)

            _LOGGER.info(f"⏰ Weekly aggregation job triggered for {week_str}")
            await self._aggregate_weekly(week_str, start_date, end_date)

        async_track_time_change(
            self.hass,
            _weekly_aggregation_job,
            hour=23,
            minute=55,
            second=0,
        )
        _LOGGER.debug("✅ Scheduled weekly aggregation at Sunday 23:55")

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        self._cancel_auto_switch_schedule()
        self._stop_auto_switch_watchdog()
        await super().async_will_remove_from_hass()

    def _get_config(self) -> Dict[str, Any]:
        """Return config dict from config entry (options preferred, then data)."""
        if not self._config_entry:
            return {}
        options = getattr(self._config_entry, "options", None)
        if options:
            return options
        return self._config_entry.data or {}

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update.

        NEDĚLÁ ŽÁDNÉ VÝPOČTY - forecast se přepočítá:
        - Každých 15 min (time scheduler)
        - Při startu (delayed 3s initial refresh)
        - Manuálně přes service call
        """
        # Jen zavolat parent pro refresh HA state (rychlé)
        super()._handle_coordinator_update()

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
        if self._timeline_data and len(self._timeline_data) > 0:
            # Try new format first (battery_soc from HYBRID)
            capacity = self._timeline_data[0].get("battery_soc")
            if capacity is None:
                # Fallback: old format (battery_capacity_kwh)
                capacity = self._timeline_data[0].get("battery_capacity_kwh", 0)
            return round(capacity, 2)
        return 0

    @property
    def available(self) -> bool:
        """Return if sensor is available.

        CRITICAL FIX: Override CoordinatorEntity.available to prevent 'unavailable' state.
        Sensor should always be available if it has run at least once (has timeline data).
        """
        # If we have timeline data from successful calculation, sensor is available
        if hasattr(self, "_timeline_data") and self._timeline_data:
            return True

        # Otherwise use coordinator availability
        return super().available

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """
        Dodatečné atributy - LEAN VERSION (Phase 1.5 API Optimization).

        PŘED: 280 KB (celá timeline v attributes)
        PO: ~2 KB (pouze summary, timeline přes API)

        Full data dostupná přes API:
        GET /api/oig_cloud/battery_forecast/{box_id}/timeline
        """
        # LEAN ATTRIBUTES: Pouze summary data pro dashboard
        attrs = {
            # Basic info
            "last_update": (
                self._last_update.isoformat() if self._last_update else None
            ),
            "data_source": "simplified_calculation",
            # Current state
            "current_battery_kwh": (
                round(
                    self._timeline_data[0].get(
                        "battery_soc",
                        self._timeline_data[0].get("battery_capacity_kwh", 0),
                    ),
                    2,
                )
                if self._timeline_data and len(self._timeline_data) > 0
                else 0
            ),
            "current_timestamp": (
                self._timeline_data[0].get(
                    "time", self._timeline_data[0].get("timestamp")
                )
                if self._timeline_data and len(self._timeline_data) > 0
                else None
            ),
            # Capacity limits
            "max_capacity_kwh": self._get_max_battery_capacity(),
            "min_capacity_kwh": self._get_min_battery_capacity(),
            # Timeline metadata
            "timeline_points_count": (
                len(self._timeline_data) if self._timeline_data else 0
            ),
            "timeline_horizon_hours": (
                round((len(self._timeline_data) * 15 / 60), 1)
                if self._timeline_data
                else 0
            ),
            # Phase 1.5: Hash-based change detection
            "data_hash": self._data_hash if self._data_hash else "unknown",
            # API endpoint hint
            "api_endpoint": f"/api/oig_cloud/battery_forecast/{self._box_id}/timeline",
            "api_query_params": "?type=active (default) | baseline | both",
            "api_note": "Full timeline data available via REST API (reduces memory by 96%)",
        }

        # Metriky nabíjení (malé, keep)
        if hasattr(self, "_charging_metrics") and self._charging_metrics:
            attrs.update(self._charging_metrics)

        # Consumption summary (4 hodnoty, keep)
        if hasattr(self, "_consumption_summary") and self._consumption_summary:
            attrs.update(self._consumption_summary)

        # Balancing cost (1 hodnota, keep)
        if hasattr(self, "_balancing_cost") and self._balancing_cost:
            attrs["balancing_cost"] = self._balancing_cost

        # PERSISTENCE: Active plan (kompaktní JSON, keep)
        plan_snapshot: Optional[Dict[str, Any]] = None
        if getattr(self, "_balancing_plan_snapshot", None):
            plan_snapshot = self._balancing_plan_snapshot
        elif hasattr(self, "_active_charging_plan") and self._active_charging_plan:
            plan_snapshot = self._active_charging_plan

        if plan_snapshot:
            attrs["active_plan_data"] = json.dumps(plan_snapshot)

        attrs["plan_status"] = getattr(self, "_plan_status", "none")

        # Phase 2.9: REMOVED daily_plan_state from attributes
        # Důvod: Ukládá se do JSON storage místo HA database (optimalizace)
        # Data dostupná přes timeline_extended API endpoint

        # Planner summary (legacy attribute schema: mode_optimization)
        if (
            hasattr(self, "_mode_optimization_result")
            and self._mode_optimization_result
        ):
            mo = self._mode_optimization_result
            attrs["mode_optimization"] = {
                # Phase 2.8: Use 48h cost for frontend tile (DNES+ZÍTRA only)
                "total_cost_czk": round(mo.get("total_cost_48h", 0), 2),
                "total_savings_vs_home_i_czk": round(mo.get("total_savings_48h", 0), 2),
                "total_cost_72h_czk": round(
                    mo.get("total_cost", 0), 2
                ),  # For reference
                "modes_distribution": {
                    "HOME_I": mo["optimal_modes"].count(0),
                    "HOME_II": mo["optimal_modes"].count(1),
                    "HOME_III": mo["optimal_modes"].count(2),
                    "HOME_UPS": mo["optimal_modes"].count(3),
                },
                # Backwards compatibility: lowercase keys for old dashboard
                "home_i_intervals": mo["optimal_modes"].count(0),
                "home_ii_intervals": mo["optimal_modes"].count(1),
                "home_iii_intervals": mo["optimal_modes"].count(2),
                "home_ups_intervals": mo["optimal_modes"].count(3),
                "timeline_length": len(mo.get("optimal_timeline", [])),
            }

            # Phase 2.10: 4-Baseline Comparison
            if mo.get("baselines"):
                attrs["mode_optimization"]["baselines"] = mo["baselines"]
                attrs["mode_optimization"]["best_baseline"] = mo.get("best_baseline")
                attrs["mode_optimization"]["hybrid_cost"] = round(
                    mo.get("hybrid_cost", 0), 2
                )
                attrs["mode_optimization"]["best_baseline_cost"] = round(
                    mo.get("best_baseline_cost", 0), 2
                )
                attrs["mode_optimization"]["savings_vs_best"] = round(
                    mo.get("savings_vs_best", 0), 2
                )
                attrs["mode_optimization"]["savings_percentage"] = round(
                    mo.get("savings_percentage", 0), 1
                )

            # Phase 2.6: What-if Analysis - Alternatives
            if mo.get("alternatives"):
                attrs["mode_optimization"]["alternatives"] = mo["alternatives"]

            # Phase 2.8: mode_recommendations moved to API endpoint
            # (no longer in attributes to reduce memory usage)

            # Phase 2.5: Boiler summary (if boiler was used in optimization)
            boiler_total = sum(
                interval.get("boiler_charge", 0)
                for interval in mo.get("optimal_timeline", [])
            )
            curtailed_total = sum(
                interval.get("curtailed_loss", 0)
                for interval in mo.get("optimal_timeline", [])
            )

            if boiler_total > 0.001 or curtailed_total > 0.001:
                attrs["boiler_summary"] = {
                    "total_energy_kwh": round(boiler_total, 2),
                    "intervals_used": sum(
                        1
                        for i in mo.get("optimal_timeline", [])
                        if i.get("boiler_charge", 0) > 0.001
                    ),
                    "avoided_export_loss_czk": round(curtailed_total, 2),
                }

        # Phase V2: Unified Cost Tile - MOVED TO API ENDPOINT
        # unified_cost_tile now built on-demand in REST API (async context)
        # Not in attributes to avoid blocking extra_state_attributes()

        # DEBUG MODE: Expose full timeline pouze pro development/testing
        # V produkci: False (timeline přes API)
        if DEBUG_EXPOSE_BASELINE_TIMELINE:
            _LOGGER.warning(
                "⚠️ DEBUG MODE: Full timeline in attributes (280 KB)! "
                "Set DEBUG_EXPOSE_BASELINE_TIMELINE=False for production."
            )
            attrs["timeline_data"] = self._timeline_data
            if hasattr(self, "_baseline_timeline"):
                attrs["baseline_timeline_data"] = self._baseline_timeline

        return attrs

    def _calculate_data_hash(self, timeline_data: List[Dict[str, Any]]) -> str:
        """
        Calculate MD5 hash of timeline data for efficient change detection.

        Phase 1.5: Hash-based change detection
        - Frontend watches sensor state (hash)
        - State change triggers WebSocket event
        - Frontend fetches new data from API
        - Avoids polling, reduces bandwidth

        Args:
            timeline_data: List of timeline points (active or baseline)

        Returns:
            MD5 hash string (32 chars hex)
        """
        if not timeline_data:
            return "empty"

        # Convert to deterministic JSON string
        data_str = json.dumps(timeline_data, sort_keys=True)

        # Calculate SHA-256 hash (secure for integrity checking)
        return hashlib.sha256(data_str.encode()).hexdigest()

    async def async_update(self) -> None:  # noqa: C901
        """Update sensor data."""
        await super().async_update()

        try:
            mark_bucket_done = False
            now_aware = dt_util.now()
            bucket_minute = (now_aware.minute // 15) * 15
            bucket_start = now_aware.replace(
                minute=bucket_minute, second=0, microsecond=0
            )

            previous_timeline = (
                copy.deepcopy(self._timeline_data)
                if getattr(self, "_timeline_data", None)
                else None
            )

            # Enforce single in-flight computation.
            if self._forecast_in_progress:
                self._log_rate_limited(
                    "forecast_in_progress",
                    "debug",
                    "Forecast computation already in progress - skipping",
                    cooldown_s=60.0,
                )
                return

            # Enforce cadence: at most once per 15-minute bucket.
            if self._last_forecast_bucket == bucket_start:
                return

            self._forecast_in_progress = True

            # Získat všechna potřebná data
            self._log_rate_limited(
                "forecast_update_tick",
                "debug",
                "Battery forecast async_update() tick",
                cooldown_s=300.0,
            )
            current_capacity = self._get_current_battery_capacity()
            max_capacity = self._get_max_battery_capacity()
            min_capacity = self._get_min_battery_capacity()

            if current_capacity is None or max_capacity is None or min_capacity is None:
                # During startup, sensors may not be ready yet. Retry shortly without spamming logs.
                self._log_rate_limited(
                    "forecast_missing_capacity",
                    "debug",
                    "Forecast prerequisites not ready (current=%s max=%s min=%s); retrying shortly",
                    current_capacity,
                    max_capacity,
                    min_capacity,
                    cooldown_s=120.0,
                )
                self._schedule_forecast_retry(10.0)
                return
            mark_bucket_done = True

            _LOGGER.debug(
                "Battery capacities: current=%.2f kWh, max=%.2f kWh, min=%.2f kWh",
                current_capacity,
                max_capacity,
                min_capacity,
            )

            self._log_rate_limited(
                "forecast_spot_fetch",
                "debug",
                "Calling _get_spot_price_timeline()",
                cooldown_s=600.0,
            )
            spot_prices = await self._get_spot_price_timeline()  # ASYNC!
            self._log_rate_limited(
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

            self._log_rate_limited(
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
                self._log_rate_limited(
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
            self._log_rate_limited(
                "forecast_export_fetch",
                "debug",
                "Calling _get_export_price_timeline()",
                cooldown_s=600.0,
            )
            export_prices = await self._get_export_price_timeline()  # ASYNC!
            self._log_rate_limited(
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

            solar_forecast = self._get_solar_forecast()
            load_avg_sensors = self._get_load_avg_sensors()

            # NOVÉ: Zkusit získat adaptivní profily
            adaptive_profiles = await self._get_adaptive_load_prediction()

            # NOVÉ: Získat balancing plán
            balancing_plan = self._get_balancing_plan()

            if not spot_prices:
                _LOGGER.warning(
                    "No spot prices available - forecast will use fallback prices"
                )
                # Continue anyway - forecast can run with fallback prices

            # ONE PLANNER: single planning pipeline.

            # PHASE 2.8 + REFACTORING: Get target from new getter
            target_capacity = self._get_target_battery_capacity()
            current_soc_percent = self._get_current_battery_soc_percent()

            if target_capacity is None:
                target_capacity = max_capacity
            if current_soc_percent is None and max_capacity > 0:
                current_soc_percent = (current_capacity / max_capacity) * 100.0

            self._log_rate_limited(
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
                        # Use adaptive profiles (hourly → 15min)
                        if timestamp.date() == today:
                            profile = adaptive_profiles["today_profile"]
                        else:
                            profile = adaptive_profiles.get(
                                "tomorrow_profile", adaptive_profiles["today_profile"]
                            )

                        hour = timestamp.hour
                        start_hour = profile.get(
                            "start_hour", 0
                        )  # Default 0 for tomorrow

                        # Mapování absolutní hodiny na index v poli
                        # today_profile: start_hour=14 → hour=14 → index=0, hour=15 → index=1
                        # tomorrow_profile: start_hour=0 → hour=0 → index=0, hour=1 → index=1
                        index = hour - start_hour

                        if 0 <= index < len(profile["hourly_consumption"]):
                            hourly_kwh = profile["hourly_consumption"][index]
                        else:
                            # Mimo rozsah - použij průměr nebo fallback
                            self._log_rate_limited(
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
                        load_kwh = self._get_load_avg_for_timestamp(
                            timestamp, load_avg_sensors
                        )

                    load_forecast.append(load_kwh)
                except Exception as e:
                    _LOGGER.warning(f"Failed to get load for {sp.get('time')}: {e}")
                    load_forecast.append(0.125)  # 500W fallback

            if adaptive_profiles:
                recent_ratio = await self._calculate_recent_consumption_ratio(
                    adaptive_profiles
                )
                if recent_ratio and recent_ratio > 1.1:
                    self._apply_consumption_boost_to_forecast(
                        load_forecast, recent_ratio
                    )

            # PLANNER: build plan timeline with HybridStrategy.
            try:
                active_balancing_plan = None
                try:
                    entry_id = (
                        self._config_entry.entry_id if self._config_entry else None
                    )
                    if (
                        entry_id
                        and DOMAIN in self._hass.data
                        and entry_id in self._hass.data[DOMAIN]
                    ):
                        balancing_manager = self._hass.data[DOMAIN][entry_id].get(
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
                            self._get_solar_for_timestamp(ts, solar_forecast)
                        )
                    except Exception:
                        solar_kwh_list.append(0.0)

                # Hard-limit horizon to 36h (144×15min).
                max_intervals = 36 * 4
                if len(spot_prices) > max_intervals:
                    spot_prices = spot_prices[:max_intervals]
                    export_prices = export_prices[:max_intervals]
                    load_forecast = load_forecast[:max_intervals]
                    solar_kwh_list = solar_kwh_list[:max_intervals]

                balancing_plan = self._build_strategy_balancing_plan(
                    spot_prices, active_balancing_plan
                )

                opts = self._config_entry.options if self._config_entry else {}
                max_ups_price_czk = float(opts.get("max_ups_price_czk", 10.0))
                efficiency = float(self._get_battery_efficiency())
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
                (
                    guarded_modes,
                    guard_overrides,
                    guard_until,
                    guard_current_mode,
                ) = self._apply_mode_guard(
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
                    previous_timeline=previous_timeline,
                )
                self._timeline_data = self._build_planner_timeline(
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
                )
                self._attach_planner_reasons(self._timeline_data, result.decisions)

                self._add_decision_reasons_to_timeline(
                    self._timeline_data,
                    current_capacity=current_capacity,
                    max_capacity=max_capacity,
                    min_capacity=planning_min_kwh,
                    efficiency=float(efficiency),
                )
                self._apply_guard_reasons_to_timeline(
                    self._timeline_data,
                    guard_overrides,
                    guard_until,
                    guard_current_mode,
                )
                self._hybrid_timeline = self._timeline_data
                self._mode_optimization_result = {
                    "optimal_timeline": self._timeline_data,
                    "optimal_modes": guarded_modes,
                    "planner": "planner",
                    "planning_min_kwh": planning_min_kwh,
                    "target_kwh": hybrid_config.target_kwh(max_capacity),
                    "infeasible": result.infeasible,
                    "infeasible_reason": result.infeasible_reason,
                }
                self._mode_recommendations = self._create_mode_recommendations(
                    self._timeline_data, hours_ahead=48
                )

            except Exception as e:
                _LOGGER.error("Planner failed: %s", e, exc_info=True)
                self._timeline_data = []
                self._hybrid_timeline = []
                self._mode_optimization_result = None
                self._mode_recommendations = []

            # PHASE 2.9: Fix daily plan at midnight for tracking (AFTER _timeline_data is set)
            await self._maybe_fix_daily_plan()

            # Baseline timeline (legacy) is no longer computed.
            # Keeping attribute for backwards compatibility only.
            self._baseline_timeline = []

            # Phase 1.5: Calculate hash for change detection
            new_hash = self._calculate_data_hash(self._timeline_data)
            if new_hash != self._data_hash:
                _LOGGER.debug(
                    f"Timeline data changed: {self._data_hash[:8] if self._data_hash else 'none'} -> {new_hash[:8]}"
                )
                self._data_hash = new_hash
            else:
                _LOGGER.debug("Timeline data unchanged (same hash)")

            self._last_update = datetime.now()
            _LOGGER.debug(
                f"Battery forecast updated: {len(self._timeline_data)} timeline points"
            )

            # Vypočítat consumption summary pro dashboard
            if adaptive_profiles and isinstance(adaptive_profiles, dict):
                self._calculate_consumption_summary(adaptive_profiles)
            else:
                self._consumption_summary = {}

            # Označit že první update proběhl
            if self._first_update:
                self._first_update = False

            # KRITICKÉ: Uložit timeline zpět do coordinator.data aby grid_charging_planned sensor viděl aktuální data
            if hasattr(self.coordinator, "battery_forecast_data"):
                self.coordinator.battery_forecast_data = {
                    "timeline_data": self._timeline_data,
                    "calculation_time": self._last_update.isoformat(),
                    "data_source": "simplified_calculation",
                    "current_battery_kwh": (
                        self._timeline_data[0].get("battery_capacity_kwh", 0)
                        if self._timeline_data
                        else 0
                    ),
                    # Correct key and default: API expects `mode_recommendations` (list)
                    "mode_recommendations": self._mode_recommendations or [],
                }
                _LOGGER.info(
                    "✅ Battery forecast data saved to coordinator - grid_charging_planned will update"
                )

                # Data jsou už v coordinator.battery_forecast_data
                # Grid charging sensor je závislý na coordinator update cycle
                # NEMĚNÍME coordinator.data - jen přidáváme battery_forecast_data

            # Keep auto mode switching schedule in sync with the latest timeline.
            # This also cancels any previously scheduled events when switching is disabled.
            if self._side_effects_enabled:
                self._create_task_threadsafe(self._update_auto_switch_schedule)

            # SIMPLE STORAGE: Update actual values každých 15 minut
            now = dt_util.now()
            current_minute = now.minute

            # Spustit update každých 15 minut (v 0, 15, 30, 45)
            should_update = current_minute in [0, 15, 30, 45]

            if should_update:
                # PHASE 3.0: DISABLED - Historical data loading moved to on-demand (API only)
                # Načítání z Recorderu každých 15 min je POMALÉ!
                # Nově: build_timeline_extended() načítá on-demand při API volání.
                # NOTE: Historically skipped until initial history update; kept for future re-enable.
                pass

            # CRITICAL FIX: Write state after every update to publish consumption_summary
            # Check if sensor is already added to HA (self.hass is set by framework)
            if not self.hass:
                _LOGGER.debug("Sensor not yet added to HA, skipping state write")
                return

            self._log_rate_limited(
                "write_state_consumption_summary",
                "debug",
                "🔄 Writing HA state with consumption_summary: %s",
                self._consumption_summary,
                cooldown_s=900.0,
            )
            self.async_write_ha_state()

            # NOTE: Single planner only.

            # PHASE 3.5: Precompute UI data for instant API responses
            # Build timeline_extended + unified_cost_tile and save to storage
            # This runs every 15 min after forecast update
            hash_changed = self._data_hash != self._last_precompute_hash
            self._schedule_precompute(
                force=self._last_precompute_at is None or hash_changed
            )

            # Notify dependent sensors (BatteryBalancing) that forecast is ready
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            signal_name = f"oig_cloud_{self._box_id}_forecast_updated"
            _LOGGER.debug(f"📡 Sending signal: {signal_name}")
            async_dispatcher_send(self.hass, signal_name)

        except Exception as e:
            _LOGGER.error(f"Error updating battery forecast: {e}", exc_info=True)
        finally:
            # Mark bucket complete only if prerequisites were ready.
            try:
                if mark_bucket_done:
                    now_done = dt_util.now()
                    done_bucket_minute = (now_done.minute // 15) * 15
                    self._last_forecast_bucket = now_done.replace(
                        minute=done_bucket_minute, second=0, microsecond=0
                    )
                    # We intentionally keep profiles dirty until a successful compute; if async_update
                    # failed, the next tick will retry.
                    if self._timeline_data:
                        self._profiles_dirty = False
            except Exception:
                pass
            self._forecast_in_progress = False

    def _simulate_interval(
        self,
        mode: int,  # 0=HOME I, 1=HOME II, 2=HOME III, 3=HOME UPS
        solar_kwh: float,  # FVE produkce (kWh/15min)
        load_kwh: float,  # Spotřeba (kWh/15min)
        battery_soc_kwh: float,  # Aktuální SoC (kWh)
        capacity_kwh: float,  # Max kapacita (kWh)
        hw_min_capacity_kwh: float,  # Fyzické minimum 20% (kWh) - INVERTOR LIMIT
        spot_price_czk: float,  # Nákupní cena (Kč/kWh)
        export_price_czk: float,  # Prodejní cena (Kč/kWh)
        charge_efficiency: float = 0.95,  # AC→DC + DC→battery efficiency
        discharge_efficiency: float = 0.95,  # battery→DC + DC→AC efficiency
        home_charge_rate_kwh_15min: float = 0.7,  # HOME UPS: 2.8kW = 0.7kWh/15min
        planning_min_capacity_kwh: float = None,  # Planning minimum (může být vyšší než hw_min)
    ) -> dict:
        """
        Simulovat jeden 15min interval s konkrétním CBB režimem.

        ZDROJ PRAVDY: CBB_MODES_DEFINITIVE.md

        DŮLEŽITÉ - Oddělení odpovědností:
        - Tato funkce implementuje POUZE fyziku režimů měniče
        - Zná pouze hw_min_capacity (invertor hardware limit = 20%)
        - NEVÍ o planning_min_capacity (to řeší HYBRID plánovač)
        - NEVÍ o target SoC (to řeší HYBRID plánovač)
        - NEVÍ o cheap/expensive prices (to řeší HYBRID plánovač)

        Režimy podle CBB_MODES_DEFINITIVE.md:

        HOME I (0) - DEN: FVE → spotřeba → baterie, deficit vybíjí
        HOME I (0) - NOC: Baterie → spotřeba (do hw_min), pak síť

        HOME II (1) - DEN: FVE → spotřeba, přebytek → baterie, deficit → SÍŤ (NETOUCHED!)
        HOME II (1) - NOC: Stejné jako HOME I (vybíjí do hw_min)

        HOME III (2) - DEN: FVE → baterie, spotřeba → VŽDY SÍŤ
        HOME III (2) - NOC: Stejné jako HOME I (vybíjí do hw_min)

        HOME UPS (3): Nabíjení na 100% (FVE + síť), spotřeba → síť

        Args:
            mode: CBB režim (0-3)
            solar_kwh: FVE produkce za 15min (kWh)
            load_kwh: Spotřeba za 15min (kWh)
            battery_soc_kwh: Aktuální stav baterie (kWh, NE %)
            capacity_kwh: Max kapacita (kWh)
            hw_min_capacity_kwh: HW minimum invertoru (kWh, typicky 20% = 3.07 kWh)
            spot_price_czk: Nákupní cena (Kč/kWh)
            export_price_czk: Prodejní cena (Kč/kWh)
            charge_efficiency: Nabíjecí účinnost (default 0.95)
            discharge_efficiency: Vybíjecí účinnost (default 0.95)
            home_charge_rate_kwh_15min: Max nabíjení ze sítě pro HOME UPS (kWh/15min)

        Returns:
            dict:
                new_soc_kwh: Nový SoC (kWh)
                grid_import_kwh: Import ze sítě (kWh)
                grid_export_kwh: Export do sítě (kWh)
                battery_charge_kwh: Nabití baterie (kWh)
                battery_discharge_kwh: Vybití baterie (kWh)
                grid_cost_czk: Náklady na import (Kč)
                export_revenue_czk: Příjem z exportu (Kč)
                net_cost_czk: Čisté náklady (Kč)
        """
        effective_min = (
            planning_min_capacity_kwh
            if planning_min_capacity_kwh is not None
            else hw_min_capacity_kwh
        )

        flows = simulate_interval(
            mode=mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_soc_kwh,
            capacity_kwh=capacity_kwh,
            hw_min_capacity_kwh=effective_min,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            home_charge_rate_kwh_15min=home_charge_rate_kwh_15min,
        )

        grid_cost_czk = flows.grid_import_kwh * spot_price_czk
        export_revenue_czk = flows.grid_export_kwh * export_price_czk
        net_cost_czk = grid_cost_czk - export_revenue_czk

        return {
            "new_soc_kwh": flows.new_soc_kwh,
            "grid_import_kwh": flows.grid_import_kwh,
            "grid_export_kwh": flows.grid_export_kwh,
            "battery_charge_kwh": flows.battery_charge_kwh,
            "battery_discharge_kwh": flows.battery_discharge_kwh,
            "grid_cost_czk": grid_cost_czk,
            "export_revenue_czk": export_revenue_czk,
            "net_cost_czk": net_cost_czk,
        }

    # =========================================================================
    # STARÉ FUNKCE ODSTRANĚNY (TODO 6: Cleanup)
    # =========================================================================
    # _simulate_interval_with_mode() - SMAZÁNO (původně line 1296-1666, 370 řádků)
    #   → Nahrazeno centrální funkcí _simulate_interval() (line 1026-1343)
    #   → Všechna volání migrována v TODO 3 (lines 1790, 1995, 2125, 3836)
    #   → Zdroj pravdy: CBB_MODES_DEFINITIVE.md
    # =========================================================================

    def _calculate_interval_cost(
        self,
        simulation_result: Dict[str, Any],
        spot_price: float,
        export_price: float,
        time_of_day: str,
    ) -> Dict[str, Any]:
        """
        Vypočítat ekonomické náklady pro jeden interval.

        Phase 2.5: Zahrnuje opportunity cost - cena za použití baterie TEĎ vs POZDĚJI.

        Args:
            simulation_result: Výsledek z _simulate_interval_with_mode()
            spot_price: Spotová cena nákupu (Kč/kWh)
            export_price: Prodejní cena exportu (Kč/kWh)
            time_of_day: Časová kategorie ("night", "morning", "midday", "evening")

        Returns:
            Dict s náklady:
                - direct_cost: Přímé náklady (grid_import * spot - grid_export * export)
                - opportunity_cost: Oportunitní náklad použití baterie
                - total_cost: Celkové náklady (direct + opportunity)
        """
        direct_cost = simulation_result["net_cost"]

        # Opportunity cost: Kolik "stojí" vybít baterii TEĎ místo POZDĚJI
        # Pokud vybíjíme baterii během dne, mohli bychom ji ušetřit na večerní peak
        battery_discharge = simulation_result.get("battery_discharge", 0.0)

        # Evening peak price assumption (můžeme použít max(spot_prices) nebo config)
        # Pro začátek: pevná hodnota 6 Kč/kWh (typický večerní peak)
        evening_peak_price = 6.0

        opportunity_cost = 0.0
        if battery_discharge > 0.001:
            # Pokud vybíjíme během "cheap" období, ztrácíme možnost použít baterii večer
            if time_of_day in ["night", "midday"]:
                # Opportunity cost = kolik bychom ušetřili, kdybychom baterii použili večer
                # Discharge now costs us: (evening_peak - spot_price) * discharge
                opportunity_cost = (evening_peak_price - spot_price) * battery_discharge

        total_cost = direct_cost + opportunity_cost

        return {
            "direct_cost": direct_cost,
            "opportunity_cost": opportunity_cost,
            "total_cost": total_cost,
        }

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
        """
        Vypočítat celkové náklady pokud by uživatel zůstal v jednom režimu celou dobu.

        Phase 2.6: What-if Analysis - Srovnání s fixed-mode strategií.
        Phase 2.7: Cache timeline for HOME I (for savings calculation).
        Phase 2.10: 4-Baseline Comparison - Use physical minimum for baseline simulations.

        Args:
            fixed_mode: CBB režim (0=HOME I, 1=HOME II, 2=HOME III, 3=HOME UPS)
            current_capacity: Aktuální SoC baterie (kWh)
            max_capacity: Max kapacita baterie (kWh)
            min_capacity: Min kapacita baterie (kWh) - Planning minimum (33% = 5.07 kWh)
            spot_prices: Timeline spot cen
            export_prices: Timeline export cen
            solar_forecast: Solární předpověď
            load_forecast: Předpověď spotřeby (kWh per interval)
            physical_min_capacity: Physical/HW minimum (20% = 3.07 kWh). If None, use min_capacity.
                                   For baseline simulations, pass physical minimum.
                                   For HYBRID optimization, pass None to use planning minimum.

        Returns:
            Dict s výsledky:
                - total_cost: Celkové náklady v Kč
                - grid_import_kwh: Celkový import ze sítě (kWh)
                - final_battery_kwh: Finální stav baterie (kWh)
                - penalty_cost: Penalizace za porušení planning minima (Kč)
                - planning_violations: Počet intervalů pod planning minimem
        """
        # Use physical minimum for baselines, planning minimum for HYBRID
        effective_min = (
            physical_min_capacity if physical_min_capacity is not None else min_capacity
        )

        # Planning minimum penalty tracking
        planning_minimum = min_capacity  # 33% = 5.07 kWh
        penalty_cost = 0.0
        planning_violations = 0
        efficiency = self._get_battery_efficiency()

        total_cost = 0.0
        total_grid_import = 0.0
        battery_soc = current_capacity
        timeline_cache = []  # Phase 2.7: Cache for savings calculation

        for t in range(len(spot_prices)):
            timestamp_str = spot_prices[t].get("time", "")
            spot_price = spot_prices[t].get("price", 0.0)
            export_price = (
                export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
            )
            load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

            # Get solar
            solar_kwh = 0.0
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            # Simulovat s fixed režimem - NOVÁ centrální funkce!
            # PHASE 3: Přechod ze staré _simulate_interval_with_mode() na novou _simulate_interval()
            sim_result = self._simulate_interval(
                mode=fixed_mode,
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=battery_soc,  # NEW: explicit kwh suffix
                capacity_kwh=max_capacity,  # NEW: explicit kwh suffix
                hw_min_capacity_kwh=effective_min,  # NEW: hw_min instead of min_capacity
                spot_price_czk=spot_price,  # NEW: explicit czk suffix
                export_price_czk=export_price,  # NEW: explicit czk suffix
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
            )

            total_cost += sim_result["net_cost_czk"]  # NEW: explicit czk suffix
            total_grid_import += sim_result.get(
                "grid_import_kwh", 0.0
            )  # NEW: explicit kwh suffix
            battery_soc = sim_result["new_soc_kwh"]  # NEW: explicit kwh suffix

            # Planning minimum penalty: když baseline klesne pod planning minimum,
            # penalizujeme je jako by museli tu energii koupit z gridu
            if battery_soc < planning_minimum:
                deficit = planning_minimum - battery_soc
                # Penalty = deficit musí být pokryt z gridu (s efficiency losses)
                interval_penalty = (deficit * spot_price) / efficiency
                penalty_cost += interval_penalty
                planning_violations += 1

            # Phase 2.7: Cache timeline for HOME I (mode 0)
            if fixed_mode == CBB_MODE_HOME_I:
                timeline_cache.append(
                    {
                        "time": timestamp_str,
                        "net_cost": sim_result["net_cost_czk"],
                    }  # NEW: czk suffix
                )

        # Calculate adjusted total cost (includes penalty)
        adjusted_total_cost = total_cost + penalty_cost

        return {
            "total_cost": round(total_cost, 2),
            "grid_import_kwh": round(total_grid_import, 2),
            "final_battery_kwh": round(battery_soc, 2),
            "penalty_cost": round(penalty_cost, 2),
            "planning_violations": planning_violations,
            "adjusted_total_cost": round(adjusted_total_cost, 2),
        }

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
        """
        Vypočítat baseline scénáře pro všechny 4 CBB režimy.

        ZDROJ PRAVDY:
        - CBB_MODES_DEFINITIVE.md - chování režimů
        - REFACTORING_IMPLEMENTATION_GUIDE.md - hw_min vs planning_min

        Phase 2.10: 4-Baseline Comparison

        Tato funkce simuluje co by se stalo kdyby uživatel zůstal celý den v jednom
        z fixních CBB režimů (HOME I/II/III/UPS) bez využití HYBRID optimalizace.

        DŮLEŽITÉ - Oddělení odpovědností:
        - Baseline používá hw_min_capacity (20% fyzické minimum invertoru)
        - HYBRID plánovač používá planning_min_capacity (33% user minimum)
        - Všechna fyzika přes centrální _simulate_interval()

        Args:
            current_capacity: Aktuální SoC baterie (kWh)
            max_capacity: Max kapacita baterie (kWh)
            physical_min_capacity: Fyzické/HW minimum (20% = 3.07 kWh)
            spot_prices: Timeline spot cen
            export_prices: Timeline export cen
            solar_forecast: Solární předpověď
            load_forecast: Předpověď spotřeby (kWh per interval)

        Returns:
            Dict s baseline pro každý režim:
            {
                "HOME_I": {
                    "total_cost": float,  # Kč
                    "grid_import_kwh": float,  # kWh
                    "final_battery_kwh": float,  # kWh
                },
                "HOME_II": {...},
                "HOME_III": {...},
                "HOME_UPS": {...},
            }
        """
        baselines = {}

        mode_mapping = [
            (CBB_MODE_HOME_I, "HOME_I"),
            (CBB_MODE_HOME_II, "HOME_II"),
            (CBB_MODE_HOME_III, "HOME_III"),
            (CBB_MODE_HOME_UPS, "HOME_UPS"),
        ]

        _LOGGER.debug(
            f"🔍 Calculating 4 baselines: physical_min={physical_min_capacity:.2f} kWh "
            f"({physical_min_capacity / max_capacity * 100:.0f}%)"
        )

        for mode_id, mode_name in mode_mapping:
            result = self._calculate_fixed_mode_cost(
                fixed_mode=mode_id,
                current_capacity=current_capacity,
                max_capacity=max_capacity,
                min_capacity=physical_min_capacity,  # DUMMY - not used with physical_min
                spot_prices=spot_prices,
                export_prices=export_prices,
                solar_forecast=solar_forecast,
                load_forecast=load_forecast,
                physical_min_capacity=physical_min_capacity,  # Use physical minimum!
            )

            baselines[mode_name] = result

            # Log baseline s penalty informací
            penalty_info = ""
            if result["planning_violations"] > 0:
                penalty_info = (
                    f", penalty={result['penalty_cost']:.2f} Kč "
                    f"({result['planning_violations']} violations)"
                )

            _LOGGER.debug(
                f"  {mode_name}: cost={result['total_cost']:.2f} Kč{penalty_info}, "
                f"grid_import={result['grid_import_kwh']:.2f} kWh, "
                f"final_battery={result['final_battery_kwh']:.2f} kWh, "
                f"adjusted_cost={result['adjusted_total_cost']:.2f} Kč"
            )

        return baselines

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
        """
        Vypočítat náklady pokud uživatel NIC NEZMĚNÍ.

        Phase 2.6: What-if Analysis - DO NOTHING = současný režim bez změn.

        OPRAVA 29.10.2025:
        - PŘED: Simuloval HOME I jako "pasivní" režim (nesprávně)
        - PO: Simuluje SOUČASNÝ CBB REŽIM po celý den BEZ ZMĚN

        Logika:
        - Načíst aktuální režim ze sensoru box_prms_mode
        - Simulovat celých 24h s tímto režimem
        - Uživatel vidí: "Co kdybyste nechali současný režim (HOME II) celý den?"

        Args:
            current_capacity: Aktuální SoC baterie (kWh)
            max_capacity: Max kapacita baterie (kWh)
            min_capacity: Min kapacita baterie (kWh)
            spot_prices: Timeline spot cen
            export_prices: Timeline export cen
            solar_forecast: Solární předpověď
            load_forecast: Předpověď spotřeby (kWh per interval)

        Returns:
            Celkové náklady v Kč pokud uživatel nechá současný režim
        """
        # OPRAVA: Načíst současný režim místo fixed HOME I
        current_mode = self._get_current_mode()
        efficiency = self._get_battery_efficiency()

        _LOGGER.debug(
            f"[DO NOTHING] Calculating cost for current mode: {current_mode} "
            f"({['HOME I', 'HOME II', 'HOME III', 'HOME UPS'][current_mode]})"
        )

        total_cost = 0.0
        battery_soc = current_capacity

        for t in range(len(spot_prices)):
            timestamp_str = spot_prices[t].get("time", "")
            spot_price = spot_prices[t].get("price", 0.0)
            export_price = (
                export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
            )
            load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

            # Get solar
            solar_kwh = 0.0
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            # OPRAVA: Použít současný režim místo HOME I
            # PHASE 3: Přechod na novou _simulate_interval()
            sim_result = self._simulate_interval(
                mode=current_mode,  # ← OPRAVA: Prostě nech to být!
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=battery_soc,  # NEW: explicit kwh
                capacity_kwh=max_capacity,  # NEW: explicit kwh
                hw_min_capacity_kwh=min_capacity,  # NEW: hw_min (here used as planning min - suboptimal but works)
                spot_price_czk=spot_price,  # NEW: explicit czk
                export_price_czk=export_price,  # NEW: explicit czk
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
            )

            total_cost += sim_result["net_cost_czk"]  # NEW: czk suffix
            battery_soc = sim_result["new_soc_kwh"]  # NEW: kwh suffix

        return total_cost

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
        """
        Vypočítat náklady pokud uživatel nabíjí baterii na 100% ASAP v nejlevnějších nočních intervalech.

        Phase 2.6: What-if Analysis - Optimální noční nabíjení na 100%.

        OPRAVA 29.10.2025:
        - PŘED: Nabíjel celou noc (22-06h) bez ohledu na cenu (8 hodin)
        - PO: Nabíjí ASAP v nejlevnějších nočních intervalech (pouze potřebný čas)

        Logika:
        1. Spočítat potřebu: needed_kwh = max_capacity - current_capacity
        2. AC charging limit: 2.8 kW = 0.7 kWh/15min
        3. Intervals needed: ceil(needed_kwh / 0.7)
        4. Najít N nejlevnějších nočních intervalů (22-06h)
        5. Nabít pouze v těchto intervalech
        6. Zbytek dne: HOME I

        Výsledek: Úspora vs nabíjení celou noc, lepší ekonomie

        Args:
            current_capacity: Aktuální SoC baterie (kWh)
            max_capacity: Max kapacita baterie (kWh)
            min_capacity: Min kapacita baterie (kWh)
            spot_prices: Timeline spot cen
            export_prices: Timeline export cen
            solar_forecast: Solární předpověď
            load_forecast: Předpověď spotřeby (kWh per interval)

        Returns:
            Celkové náklady v Kč s optimálním nočním nabíjením
        """
        # Get battery efficiency for calculations
        efficiency = self._get_battery_efficiency()

        # 1. Spočítat potřebu dobití
        needed_kwh = max_capacity - current_capacity

        # 2. AC charging limit per 15min interval
        ac_charging_limit = 0.7  # kWh per 15min (2.8 kW AC path)

        # 3. Kolik intervalů potřebujeme na dobití?
        if needed_kwh > 0.001:
            intervals_needed = int(math.ceil(needed_kwh / ac_charging_limit))
        else:
            intervals_needed = 0  # Battery už plná

        _LOGGER.debug(
            f"[FULL UPS] Need {needed_kwh:.2f} kWh to reach {max_capacity:.2f} kWh, "
            f"requires {intervals_needed} intervals (×15min)"
        )

        # 4. Najít noční intervaly (22:00-06:00) a seřadit podle ceny
        night_intervals = []
        for t, price_data in enumerate(spot_prices):
            timestamp_str = price_data.get("time", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                hour = timestamp.hour

                # Noční hodiny: 22-23, 0-5
                if 22 <= hour or hour < 6:
                    night_intervals.append((t, price_data.get("price", 0.0)))
            except Exception:
                continue

        # 5. Seřadit podle ceny a vybrat N nejlevnějších
        night_sorted = sorted(
            night_intervals, key=lambda x: x[1]
        )  # Sort by price (ascending)
        cheapest_intervals = set(
            [idx for idx, price in night_sorted[:intervals_needed]]
        )

        if cheapest_intervals:
            _LOGGER.debug(
                f"[FULL UPS] Selected {len(cheapest_intervals)} cheapest night intervals "
                f"from {len(night_intervals)} total night intervals"
            )

        # 6. Simulovat s optimálním nabíjením
        total_cost = 0.0
        battery_soc = current_capacity

        for t in range(len(spot_prices)):
            timestamp_str = spot_prices[t].get("time", "")
            spot_price = spot_prices[t].get("price", 0.0)
            export_price = (
                export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
            )
            load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

            # Get solar
            solar_kwh = 0.0
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            # OPRAVA: Nabíjet pouze v nejlevnějších nočních intervalech
            if t in cheapest_intervals and battery_soc < max_capacity:
                # Optimální nabíjení v levném intervalu
                mode = CBB_MODE_HOME_UPS  # 3 - Grid charging enabled
            else:
                # Normální provoz (nebo battery už plná)
                mode = CBB_MODE_HOME_I  # 0 - Battery priority

            # PHASE 3: Přechod na novou _simulate_interval()
            sim_result = self._simulate_interval(
                mode=mode,
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=battery_soc,  # NEW: kwh suffix
                capacity_kwh=max_capacity,  # NEW: kwh suffix
                hw_min_capacity_kwh=min_capacity,  # NEW: hw_min
                spot_price_czk=spot_price,  # NEW: czk suffix
                export_price_czk=export_price,  # NEW: czk suffix
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
            )

            total_cost += sim_result["net_cost_czk"]  # NEW: czk suffix
            battery_soc = sim_result["new_soc_kwh"]  # NEW: kwh suffix

        return total_cost

    def _create_mode_recommendations(
        self, optimal_timeline: List[Dict[str, Any]], hours_ahead: int = 48
    ) -> List[Dict[str, Any]]:
        """
        Vytvořit user-friendly doporučení režimů pro DNES a ZÍTRA.

        Phase 2.6: Mode Recommendations - Seskupí po sobě jdoucí stejné režimy
        do časových bloků s DETAILNÍM zdůvodněním.

        Phase 2.8: Oprava rozsahu dat a splitování přes půlnoc
        - Pouze DNES (od teď) a ZÍTRA (celý den)
        - Bloky přes půlnoc se rozdělí na 2 samostatné bloky

        Args:
            optimal_timeline: Timeline z plánovače
            hours_ahead: Kolik hodin do budoucna zahrnout (default 48h)

        Returns:
            List[Dict]: Seskupené režimy s časovými bloky a ekonomickými detaily
                [{
                    "mode": int,
                    "mode_name": str,
                    "from_time": str (ISO),
                    "to_time": str (ISO),
                    "duration_hours": float,
                    "intervals_count": int,
                    "avg_spot_price": float,      # Průměrná spot cena (Kč/kWh)
                    "avg_solar_kw": float,         # Průměrná FVE výroba (kW)
                    "avg_load_kw": float,          # Průměrná spotřeba (kW)
                    "total_cost": float,           # Celkové náklady bloku (Kč)
                    "cost_savings_vs_home_i": float,  # Úspora vs HOME I (Kč)
                    "rationale": str,              # Vysvětlení proč tento režim
                }]
        """
        if not optimal_timeline:
            return []

        try:
            now = datetime.now()

            # OPRAVA Phase 2.8: Mode recommendations jen BUDOUCNOST (od NOW)
            # DNES: od NOW do 23:59:59
            # ZÍTRA: celý den (00:00:00 - 23:59:59)
            # Důvod: optimal_timeline už je filtrovaný od NOW (řádek 400-408)
            tomorrow_end = datetime.combine(
                now.date() + timedelta(days=1), datetime.max.time()
            )

            # Filter pouze intervaly od NOW do konce zítřka
            future_intervals = [
                interval
                for interval in optimal_timeline
                if interval.get("time")
                and now <= datetime.fromisoformat(interval["time"]) <= tomorrow_end
            ]

            if not future_intervals:
                return []

            # Group consecutive same-mode intervals WITH detailed metrics
            recommendations = []
            current_block = None
            block_intervals = []  # Store intervals for current block

            for interval in future_intervals:
                mode = interval.get("mode")
                mode_name = interval.get("mode_name", f"MODE_{mode}")
                time_str = interval.get("time", "")

                if current_block is None:
                    # Start new block - to_time will be set when we know it's the last interval
                    current_block = {
                        "mode": mode,
                        "mode_name": mode_name,
                        "from_time": time_str,
                        "to_time": None,  # Will be set later
                        "intervals_count": 1,
                    }
                    block_intervals = [interval]
                elif current_block["mode"] == mode:
                    # Extend current block - just increment counter
                    current_block["intervals_count"] += 1
                    block_intervals.append(interval)
                else:
                    # Mode changed - finalize previous block
                    # Set to_time = last interval's time + 15min
                    if block_intervals:
                        last_interval_time = block_intervals[-1].get("time", "")
                        try:
                            last_dt = datetime.fromisoformat(last_interval_time)
                            end_dt = last_dt + timedelta(minutes=15)
                            current_block["to_time"] = end_dt.isoformat()
                        except Exception:
                            current_block["to_time"] = last_interval_time

                    self._add_block_details(current_block, block_intervals)
                    # Store intervals for potential splitting later
                    current_block["_intervals"] = block_intervals
                    recommendations.append(current_block)

                    # Start new block
                    current_block = {
                        "mode": mode,
                        "mode_name": mode_name,
                        "from_time": time_str,
                        "to_time": None,  # Will be set later
                        "intervals_count": 1,
                    }
                    block_intervals = [interval]

            # Don't forget last block
            if current_block and block_intervals:
                # Set to_time for last block
                last_interval_time = block_intervals[-1].get("time", "")
                try:
                    last_dt = datetime.fromisoformat(last_interval_time)
                    end_dt = last_dt + timedelta(minutes=15)
                    current_block["to_time"] = end_dt.isoformat()
                except Exception:
                    current_block["to_time"] = last_interval_time

                self._add_block_details(current_block, block_intervals)
                # Store intervals for potential splitting later
                current_block["_intervals"] = block_intervals
                recommendations.append(current_block)

            # OPRAVA Phase 2.8: Splitovat bloky přes půlnoc
            # Pokud blok začíná v jeden den a končí v druhý, rozdělit ho
            split_recommendations = []
            for block in recommendations:
                from_dt = datetime.fromisoformat(block["from_time"])
                to_dt = datetime.fromisoformat(block["to_time"])

                # Pokud blok je ve stejném dni, přidat bez změny
                if from_dt.date() == to_dt.date():
                    # Remove temporary intervals before returning
                    block.pop("_intervals", None)
                    split_recommendations.append(block)
                else:
                    # Blok přes půlnoc - rozdělit na 2
                    midnight = datetime.combine(
                        from_dt.date() + timedelta(days=1), datetime.min.time()
                    )

                    # Get original intervals for precise cost calculation
                    intervals = block.get("_intervals", [])

                    # Split intervals by midnight
                    intervals1 = [
                        i
                        for i in intervals
                        if datetime.fromisoformat(i.get("time", "")) < midnight
                    ]
                    intervals2 = [
                        i
                        for i in intervals
                        if datetime.fromisoformat(i.get("time", "")) >= midnight
                    ]

                    # První část: od from_time do půlnoci
                    block1 = {
                        "mode": block["mode"],
                        "mode_name": block["mode_name"],
                        "from_time": block["from_time"],
                        "to_time": midnight.isoformat(),
                        "intervals_count": len(intervals1),
                    }
                    duration1 = (midnight - from_dt).total_seconds() / 3600
                    block1["duration_hours"] = round(duration1, 2)

                    # Recalculate costs from actual intervals (no rounding errors)
                    if intervals1:
                        self._add_block_details(block1, intervals1)

                    split_recommendations.append(block1)

                    # Druhá část: od půlnoci do to_time
                    block2 = {
                        "mode": block["mode"],
                        "mode_name": block["mode_name"],
                        "from_time": midnight.isoformat(),
                        "to_time": block["to_time"],
                        "intervals_count": len(intervals2),
                    }
                    duration2 = (to_dt - midnight).total_seconds() / 3600
                    block2["duration_hours"] = round(duration2, 2)

                    # Recalculate costs from actual intervals (no rounding errors)
                    if intervals2:
                        self._add_block_details(block2, intervals2)

                    split_recommendations.append(block2)

            return split_recommendations

        except Exception as e:
            _LOGGER.error(f"Failed to create mode recommendations: {e}")
            return []

    def _add_block_details(
        self, block: Dict[str, Any], intervals: List[Dict[str, Any]]
    ) -> None:
        """
        Přidat detailní metriky do bloku doporučení.

        Phase 2.6: Rozšířeno o lidské vysvětlení a ekonomické zdůvodnění.
        Phase 2.7: Přidána kalkulace úspor vs HOME I režim.

        Args:
            block: Block dictionary to enhance
            intervals: List of intervals in this block
        """
        try:
            # Calculate duration
            from_dt = datetime.fromisoformat(block["from_time"])
            to_dt = datetime.fromisoformat(block["to_time"])
            duration = (
                to_dt - from_dt
            ).total_seconds() / 3600 + 0.25  # +15min last interval
            block["duration_hours"] = round(duration, 2)
        except Exception:
            block["duration_hours"] = block["intervals_count"] * 0.25

        # Calculate average metrics across intervals
        if not intervals:
            return

        # We need spot prices and solar/load data
        # These should be available from timeline data
        total_cost = sum(i.get("net_cost", 0) for i in intervals)

        block["total_cost"] = round(total_cost, 2)

        # Phase 2.7: Savings calculation removed - cache nepotřebujeme
        # (savings se počítají v build_mode_recommendations pokud je potřeba)
        block["savings_vs_home_i"] = 0.0

        # Try to extract solar/load info if available
        # (This requires timeline to have been enriched with solar/load data)
        solar_vals = [i.get("solar_kwh", 0) * 4 for i in intervals]  # Convert to kW
        load_vals = [i.get("load_kwh", 0) * 4 for i in intervals]
        spot_prices = [i.get("spot_price", 0) for i in intervals]

        if solar_vals and any(v > 0 for v in solar_vals):
            block["avg_solar_kw"] = round(sum(solar_vals) / len(solar_vals), 2)
        else:
            block["avg_solar_kw"] = 0.0

        if load_vals:
            block["avg_load_kw"] = round(sum(load_vals) / len(load_vals), 2)
        else:
            block["avg_load_kw"] = 0.0

        if spot_prices:
            block["avg_spot_price"] = round(sum(spot_prices) / len(spot_prices), 2)
        else:
            block["avg_spot_price"] = 0.0

        # Generate human-friendly rationale with economic reasoning
        mode = block["mode"]
        solar_kw = block["avg_solar_kw"]
        load_kw = block["avg_load_kw"]
        spot_price = block["avg_spot_price"]

        # Get from_time as datetime for expensive period lookup
        from_dt = None
        try:
            from_dt = datetime.fromisoformat(block["from_time"])
        except Exception:
            pass

        # HOME I - Battery Priority
        if mode == CBB_MODE_HOME_I:
            if (
                solar_kw > load_kw + 0.1
            ):  # FVE surplus (threshold 0.1kW to avoid tiny values)
                surplus_kw = solar_kw - load_kw
                block["rationale"] = (
                    f"Nabíjíme baterii z FVE přebytku ({surplus_kw:.1f} kW) - ukládáme levnou energii na později"
                )
            elif solar_kw > 0.2:  # Meaningful FVE production
                deficit_kw = load_kw - solar_kw
                block["rationale"] = (
                    f"FVE pokrývá část spotřeby ({solar_kw:.1f} kW), baterie doplňuje {deficit_kw:.1f} kW"
                )
            else:  # Night or minimal FVE
                block["rationale"] = (
                    f"Vybíjíme baterii pro pokrytí spotřeby - šetříme {spot_price:.1f} Kč/kWh ze sítě"
                )

        # HOME II - Grid Supplements (battery saved for expensive periods)
        elif mode == CBB_MODE_HOME_II:
            if solar_kw > load_kw + 0.1:  # FVE surplus
                surplus_kw = solar_kw - load_kw
                block["rationale"] = (
                    f"Nabíjíme baterii z FVE přebytku ({surplus_kw:.1f} kW) - připravujeme na večerní špičku"
                )
            else:
                # Grid supplements - battery saving mode
                if spot_price > 4.0:  # Relatively expensive
                    block["rationale"] = (
                        f"Grid pokrývá spotřebu ({spot_price:.1f} Kč/kWh) - ale ještě ne vrcholová cena"
                    )
                else:  # Cheap period
                    block["rationale"] = (
                        f"Levný proud ze sítě ({spot_price:.1f} Kč/kWh) - šetříme baterii na dražší období"
                    )

        # HOME III - All Solar to Battery
        elif mode == CBB_MODE_HOME_III:
            if solar_kw > 0.2:  # Meaningful FVE production
                block["rationale"] = (
                    f"Maximální nabíjení baterie - veškeré FVE ({solar_kw:.1f} kW) jde do baterie, spotřeba ze sítě"
                )
            else:  # Night
                block["rationale"] = (
                    f"Vybíjíme baterii pro pokrytí spotřeby - šetříme {spot_price:.1f} Kč/kWh ze sítě"
                )

        # HOME UPS - Grid Charging
        elif mode == CBB_MODE_HOME_UPS:
            if spot_price < 3.0:  # Very cheap
                block["rationale"] = (
                    f"Nabíjíme ze sítě - velmi levný proud ({spot_price:.1f} Kč/kWh), připravujeme plnou baterii"
                )
            else:  # More expensive but still worth it
                block["rationale"] = (
                    f"Nabíjíme ze sítě ({spot_price:.1f} Kč/kWh) - připravujeme na dražší špičku"
                )
        else:
            block["rationale"] = "Optimalizovaný režim podle aktuálních podmínek"

    def _find_next_expensive_hour(
        self, from_time: datetime, current_intervals: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Najít následující drahé období (pro vysvětlení proč šetříme baterii).

        Args:
            from_time: Od kdy hledáme
            current_intervals: Aktuální intervaly (pro získání kontextu cen)

        Returns:
            String s časem typu "19-21h" nebo None
        """
        try:
            # Get average price of current block
            current_prices = [i.get("spot_price", 0) for i in current_intervals]
            if not current_prices:
                return None

            avg_current_price = sum(current_prices) / len(current_prices)

            # Look for next period where price is significantly higher (>30%)
            # Check next 12 hours
            if not hasattr(self, "_timeline_data") or not self._timeline_data:
                return None

            # _timeline_data is List[Dict], not Dict with "timeline" key
            timeline = self._timeline_data

            expensive_start = None
            for interval in timeline:
                interval_time_str = interval.get("time", "")
                if not interval_time_str:
                    continue

                try:
                    interval_time = datetime.fromisoformat(interval_time_str)

                    # Skip if before from_time
                    if interval_time <= from_time:
                        continue

                    # Check only next 12 hours
                    if (interval_time - from_time).total_seconds() > 12 * 3600:
                        break

                    interval_price = interval.get("spot_price", 0)

                    # Is this significantly more expensive? (>30% more)
                    if interval_price > avg_current_price * 1.3:
                        expensive_start = interval_time
                        break

                except (ValueError, TypeError):
                    continue

            if expensive_start:
                hour = expensive_start.hour
                # Return range like "19-21h" (2h window)
                return f"{hour:02d}-{(hour + 2) % 24:02d}h"

            return None

        except Exception as e:
            _LOGGER.debug(f"Failed to find next expensive period: {e}")
            return None

    def _parse_balancing_context(
        self,
        balancing_plan: Optional[Dict[str, Any]],
        max_capacity: float,
        target_capacity: float,
    ) -> tuple[
        bool,
        Optional[datetime],
        Optional[datetime],
        Optional[datetime],
        set[datetime],
        str,
        float,
    ]:
        """Parse balancing plan into a normalized runtime context.

        Returns:
            (is_balancing_mode, charging_deadline, holding_start, holding_end,
             preferred_charging_intervals, balancing_reason, effective_target_capacity)
        """
        if not balancing_plan:
            return False, None, None, None, set(), "unknown", target_capacity

        try:
            holding_start_raw = balancing_plan["holding_start"]
            holding_end_raw = balancing_plan["holding_end"]

            holding_start = (
                datetime.fromisoformat(holding_start_raw)
                if isinstance(holding_start_raw, str)
                else holding_start_raw
            )
            holding_end = (
                datetime.fromisoformat(holding_end_raw)
                if isinstance(holding_end_raw, str)
                else holding_end_raw
            )

            if holding_start.tzinfo is None:
                holding_start = dt_util.as_local(holding_start)
            if holding_end.tzinfo is None:
                holding_end = dt_util.as_local(holding_end)

            preferred_charging_intervals: set[datetime] = set()

            raw_preferred = balancing_plan.get("charging_intervals")
            # Some producers store the planned UPS schedule under `intervals` as a list
            # of objects like {"ts": "...", "mode": 3}.
            if not raw_preferred:
                raw_preferred = balancing_plan.get("intervals", [])

            for iv in raw_preferred or []:
                iv_ts: str | None
                if isinstance(iv, str):
                    iv_ts = iv
                elif isinstance(iv, dict):
                    iv_ts = (
                        iv.get("ts")
                        or iv.get("time")
                        or iv.get("start")
                        or iv.get("from")
                        or iv.get("from_time")
                    )
                else:
                    iv_ts = None

                if not iv_ts:
                    continue

                ts = datetime.fromisoformat(iv_ts)
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)
                preferred_charging_intervals.add(ts)

            charging_deadline = holding_start
            balancing_reason = balancing_plan.get("reason", "unknown")
            effective_target_capacity = max_capacity

            self._log_rate_limited(
                "balancing_mode_active",
                "debug",
                "🔋 BALANCING MODE ACTIVE: reason=%s, target=100%%, deadline=%s, holding until %s, preferred_intervals=%d",
                balancing_reason,
                charging_deadline.strftime("%H:%M"),
                holding_end.strftime("%H:%M"),
                len(preferred_charging_intervals),
                cooldown_s=600.0,
            )

            return (
                True,
                charging_deadline,
                holding_start,
                holding_end,
                preferred_charging_intervals,
                balancing_reason,
                effective_target_capacity,
            )
        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.error(f"Failed to parse balancing_plan: {e}", exc_info=True)
            return False, None, None, None, set(), "unknown", target_capacity

    def _forward_pass_home_i(
        self,
        *,
        current_capacity: float,
        max_capacity: float,
        physical_min_capacity: float,
        efficiency: float,
        spot_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        is_balancing_mode: bool,
        holding_end: Optional[datetime],
    ) -> tuple[
        List[float],
        List[Optional[float]],
        List[Optional[float]],
        float,
        float,
        Optional[int],
    ]:
        """Simulate HOME I trajectory (forward pass) and compute min/final SoC."""
        n = len(spot_prices)
        battery_trajectory = [current_capacity]
        battery = current_capacity
        forward_soc_before: List[Optional[float]] = [None] * n
        forward_soc_after: List[Optional[float]] = [None] * n

        start_index = 0
        if is_balancing_mode and holding_end:
            battery = max_capacity
            for i in range(n):
                try:
                    interval_ts = datetime.fromisoformat(spot_prices[i]["time"])
                    if interval_ts.tzinfo is None:
                        interval_ts = dt_util.as_local(interval_ts)
                    if interval_ts >= holding_end:
                        start_index = i
                        battery_trajectory = [max_capacity]
                        _LOGGER.info(
                            f"📊 Balancing forward pass: starting from holding_end index {start_index} "
                            f"({holding_end.strftime('%H:%M')}) with battery=100%"
                        )
                        break
                except Exception:
                    continue

        for i in range(start_index, n):
            forward_soc_before[i] = battery
            try:
                timestamp = datetime.fromisoformat(spot_prices[i]["time"])
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125

            if solar_kwh >= load_kwh:
                net_energy = solar_kwh - load_kwh
            else:
                net_energy = -(load_kwh - solar_kwh) / efficiency

            battery += net_energy
            battery = max(physical_min_capacity, min(max_capacity, battery))
            battery_trajectory.append(battery)
            forward_soc_after[i] = battery

        holding_end_index_for_validation: Optional[int] = None
        if is_balancing_mode and holding_end:
            holding_end_index = None
            for i in range(n):
                try:
                    interval_ts = datetime.fromisoformat(spot_prices[i]["time"])
                    if interval_ts.tzinfo is None:
                        interval_ts = dt_util.as_local(interval_ts)
                    if interval_ts >= holding_end:
                        holding_end_index = i
                        break
                except Exception:
                    continue

            holding_end_index_for_validation = holding_end_index
            if holding_end_index is not None and holding_end_index < len(
                battery_trajectory
            ):
                min_reached = min(battery_trajectory[holding_end_index:])
                self._log_rate_limited(
                    "balancing_min_check",
                    "debug",
                    "📊 Balancing: checking min from index %d/%d (after holding_end %s): min=%.2f kWh",
                    holding_end_index,
                    len(battery_trajectory),
                    holding_end.strftime("%H:%M"),
                    min_reached,
                    cooldown_s=600.0,
                )
            else:
                min_reached = min(battery_trajectory)
                self._log_rate_limited(
                    "balancing_holding_end_index_missing",
                    "debug",
                    "Balancing: holding_end_index not found/invalid; using full trajectory min",
                    cooldown_s=600.0,
                )
        else:
            min_reached = min(battery_trajectory)

        final_capacity = battery_trajectory[-1]
        return (
            battery_trajectory,
            forward_soc_before,
            forward_soc_after,
            min_reached,
            final_capacity,
            holding_end_index_for_validation,
        )

    def _evaluate_target_charging_economics(
        self,
        *,
        spot_prices: List[Dict[str, Any]],
        charging_power_kw: float,
        target_capacity: float,
        final_capacity: float,
        needs_charging_for_minimum: bool,
        needs_charging_for_target: bool,
        is_balancing_mode: bool,
    ) -> tuple[Optional[float], bool]:
        """Compute cheap-price threshold and decide if target charging is feasible.

        Returns:
            (cheap_price_threshold, should_skip_target_charging)
        """
        if is_balancing_mode:
            self._log_rate_limited(
                "balancing_skip_economics",
                "debug",
                "🔋 Balancing mode - skipping economic checks (MUST charge to 100%)",
                cooldown_s=3600.0,
            )
            return None, False

        cheap_percentile = self._config_entry.options.get("cheap_window_percentile", 30)
        sorted_prices = sorted(float(sp.get("price", 0) or 0) for sp in spot_prices)
        percentile_index = int(len(sorted_prices) * cheap_percentile / 100)
        cheap_price_threshold = (
            sorted_prices[percentile_index] if sorted_prices else 999
        )

        avg_price = sum(sorted_prices) / len(sorted_prices) if sorted_prices else 0
        if sorted_prices:
            min_price = min(sorted_prices)
            max_price = max(sorted_prices)
        else:
            min_price = 0
            max_price = 0

        self._log_rate_limited(
            "price_analysis",
            "debug",
            "💰 Price analysis: avg=%.2f Kč/kWh, cheap_threshold (P%d)=%.2f Kč/kWh, min=%.2f, max=%.2f",
            avg_price,
            cheap_percentile,
            cheap_price_threshold,
            min_price,
            max_price,
            cooldown_s=3600.0,
        )

        if not needs_charging_for_minimum and needs_charging_for_target:
            cheap_intervals = [
                i
                for i, sp in enumerate(spot_prices)
                if float(sp.get("price", 999) or 999) <= cheap_price_threshold
            ]

            deficit_kwh = target_capacity - final_capacity
            max_charge_per_interval = charging_power_kw / 4.0
            required_cheap_intervals = int(deficit_kwh / max_charge_per_interval) + 1

            if len(cheap_intervals) < required_cheap_intervals:
                self._log_rate_limited(
                    "skip_target_not_enough_cheap",
                    "debug",
                    "Skipping target charging - not enough cheap hours: need=%d, have=%d, deficit=%.2f kWh",
                    required_cheap_intervals,
                    len(cheap_intervals),
                    deficit_kwh,
                    cooldown_s=900.0,
                )
                return cheap_price_threshold, True

            self._log_rate_limited(
                "target_feasible",
                "debug",
                "Target charging feasible in cheap hours: have=%d, need=%d, deficit=%.2f kWh",
                len(cheap_intervals),
                required_cheap_intervals,
                deficit_kwh,
                cooldown_s=900.0,
            )

        return cheap_price_threshold, False

    def _find_first_index_at_or_after(
        self, *, spot_prices: List[Dict[str, Any]], target: datetime
    ) -> Optional[int]:
        """Return the first interval index whose timestamp is >= target."""
        for i, sp in enumerate(spot_prices):
            try:
                ts = datetime.fromisoformat(sp["time"])
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)
                if ts >= target:
                    return i
            except (ValueError, TypeError):
                continue
        return None

    def _compute_required_battery(
        self,
        *,
        n: int,
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        target_capacity: float,
        spot_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        efficiency: float,
        is_balancing_mode: bool,
        charging_deadline: Optional[datetime],
    ) -> tuple[List[float], Optional[int]]:
        """Backward pass: compute required battery at start of each interval."""
        required_battery = [0.0] * (n + 1)

        if is_balancing_mode and charging_deadline:
            deadline_index = self._find_first_index_at_or_after(
                spot_prices=spot_prices, target=charging_deadline
            )

            if deadline_index is None:
                _LOGGER.warning(
                    f"⚠️  Charging deadline {charging_deadline.strftime('%H:%M')} "
                    f"not found in spot_prices range. Using last interval."
                )
                deadline_index = n

            _LOGGER.info(
                f"🎯 Balancing deadline: index={deadline_index}/{n}, "
                f"time={charging_deadline.strftime('%H:%M')}"
            )

            required_battery[deadline_index] = max_capacity

            for i in range(deadline_index - 1, -1, -1):
                try:
                    timestamp = datetime.fromisoformat(spot_prices[i]["time"])
                    solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
                except Exception:
                    solar_kwh = 0.0

                load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125

                if solar_kwh >= load_kwh:
                    net_energy = solar_kwh - load_kwh
                    required_battery[i] = required_battery[i + 1] - net_energy
                else:
                    drain = (load_kwh - solar_kwh) / efficiency
                    required_battery[i] = required_battery[i + 1] + drain

                required_battery[i] = min(required_battery[i], max_capacity)

            for i in range(deadline_index, n + 1):
                required_battery[i] = max_capacity

            self._log_rate_limited(
                "balancing_backward_pass",
                "debug",
                "Balancing backward pass: required_start=%.2f kWh, required_at_deadline=%.2f kWh, current=%.2f, deficit=%.2f",
                required_battery[0],
                required_battery[deadline_index],
                current_capacity,
                max(0, required_battery[0] - current_capacity),
                cooldown_s=900.0,
            )

            return required_battery, deadline_index

        required_battery[n] = max(target_capacity, min_capacity)

        for i in range(n - 1, -1, -1):
            try:
                timestamp = datetime.fromisoformat(spot_prices[i]["time"])
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125

            if solar_kwh >= load_kwh:
                net_energy = solar_kwh - load_kwh
                required_battery[i] = required_battery[i + 1] - net_energy
            else:
                drain = (load_kwh - solar_kwh) / efficiency
                required_battery[i] = required_battery[i + 1] + drain

            required_battery[i] = min(required_battery[i], max_capacity)

        self._log_rate_limited(
            "backward_pass",
            "debug",
            "Backward pass: required_start=%.2f kWh (current=%.2f, deficit=%.2f)",
            required_battery[0],
            current_capacity,
            max(0, required_battery[0] - current_capacity),
            cooldown_s=900.0,
        )

        return required_battery, None

    def _enforce_min_mode_duration(self, modes: List[int]) -> List[int]:
        """
        PHASE 6.5: Vynucení minimální doby trvání režimu (MIN_MODE_DURATION).

        Podle REFACTORING_IMPLEMENTATION_GUIDE.md:
        - HOME UPS musí běžet minimálně 2 intervaly (30 minut)
        - HOME I/II musí běžet minimálně 1 interval (15 minut)

        Důvod: Časté přepínání způsobuje:
        - Ztráty energie při přechodu mezi režimy
        - Opotřebení hardware (relé, měnič)
        - Nestabilní chování systému

        Args:
            modes: Seznam režimů (list of int, 0-3)

        Returns:
            Upravený seznam režimů s vynucenou minimální dobou trvání
        """
        if not modes:
            return modes

        # Mode name mapping for logging
        mode_names = {
            CBB_MODE_HOME_I: MODE_LABEL_HOME_I,
            CBB_MODE_HOME_II: MODE_LABEL_HOME_II,
            CBB_MODE_HOME_III: MODE_LABEL_HOME_III,
            CBB_MODE_HOME_UPS: MODE_LABEL_HOME_UPS,
        }

        result = modes.copy()
        n = len(result)
        i = 0
        violations_fixed = 0

        while i < n:
            current_mode = result[i]
            mode_name = mode_names.get(current_mode, f"Mode {current_mode}")

            # Najít délku aktuálního bloku
            block_start = i
            while i < n and result[i] == current_mode:
                i += 1
            block_length = i - block_start

            # Kontrola min duration
            min_duration = MIN_MODE_DURATION.get(mode_name, 1)

            if block_length < min_duration:
                # Violation! Krátký blok - rozšířit nebo odstranit
                violations_fixed += 1

                # Strategie: Převést na sousední režim (jednodušší než extension)
                # Pokud je to první blok → vezmi následující režim
                # Pokud je to poslední blok → vezmi předchozí režim
                # Jinak → vezmi ten co je častější v okolí

                if block_start == 0:
                    # První blok → vezmi následující
                    replacement_mode = result[i] if i < n else CBB_MODE_HOME_I
                elif i >= n:
                    # Poslední blok → vezmi předchozí
                    replacement_mode = result[block_start - 1]
                else:
                    # Uprostřed → vezmi předchozí (konzervativní přístup)
                    replacement_mode = result[block_start - 1]

                # Převeď celý blok
                for j in range(block_start, min(i, n)):
                    result[j] = replacement_mode

                _LOGGER.debug(
                    f"[MIN_DURATION] Fixed violation: {mode_name} block @ {block_start} "
                    f"(length {block_length} < min {min_duration}) → {mode_names.get(replacement_mode, 'unknown')}"
                )

                # Reset index aby se re-evaluoval merged blok
                i = block_start

        if violations_fixed > 0:
            _LOGGER.info(f"✅ MIN_MODE_DURATION: Fixed {violations_fixed} violations")

        return result

    def _get_mode_guard_context(
        self, now: datetime
    ) -> Tuple[Optional[int], Optional[datetime]]:
        """Zjistit aktuální režim a konec guard okna po poslední změně."""
        if not self._hass or MODE_GUARD_MINUTES <= 0:
            return None, None

        sensor_id = f"sensor.oig_{self._box_id}_box_prms_mode"
        state = self._hass.states.get(sensor_id)
        if not state or state.state in ["unknown", "unavailable", None]:
            return None, None

        current_mode = self._get_current_mode()
        last_changed = getattr(state, "last_changed", None)
        if not isinstance(last_changed, datetime):
            return current_mode, None

        if last_changed.tzinfo is None:
            last_changed = dt_util.as_local(last_changed)

        guard_until = last_changed + timedelta(minutes=MODE_GUARD_MINUTES)
        if guard_until <= now:
            return current_mode, None

        return current_mode, guard_until

    def _get_plan_lock(
        self,
        now: datetime,
        spot_prices: List[Dict[str, Any]],
        modes: List[int],
    ) -> Tuple[Optional[datetime], Dict[str, int]]:
        """Vrátit uzamčený plán pro nejbližších MODE_GUARD_MINUTES minut."""
        if MODE_GUARD_MINUTES <= 0:
            return None, {}

        lock_until = self._plan_lock_until
        lock_modes = self._plan_lock_modes or {}
        if isinstance(lock_until, datetime) and now < lock_until and lock_modes:
            return lock_until, lock_modes

        lock_until = now + timedelta(minutes=MODE_GUARD_MINUTES)
        lock_modes = {}
        for i, sp in enumerate(spot_prices):
            if i >= len(modes):
                break
            ts_value = sp.get("time")
            start_dt = self._parse_timeline_timestamp(str(ts_value or ""))
            if not start_dt:
                start_dt = now + timedelta(minutes=15 * i)
            if start_dt >= lock_until:
                break
            if ts_value:
                lock_modes[str(ts_value)] = modes[i]

        self._plan_lock_until = lock_until
        self._plan_lock_modes = lock_modes
        return lock_until, lock_modes

    def _apply_mode_guard(
        self,
        *,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        solar_kwh_list: List[float],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        hw_min_capacity: float,
        efficiency: float,
        home_charge_rate_kw: float,
        planning_min_kwh: float,
        previous_timeline: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[int], List[Dict[str, Any]], Optional[datetime], Optional[int]]:
        """Uzamknout plán v guard okně na potvrzený plán, výjimka jen při nízkém SoC."""
        if not modes:
            return modes, [], None, None

        now = dt_util.now()
        guard_until, lock_modes = self._get_plan_lock(now, spot_prices, modes)
        if guard_until is None or not lock_modes:
            return modes, [], None, None

        guarded_modes = list(modes)
        overrides: List[Dict[str, Any]] = []
        soc = current_capacity
        charge_rate_kwh_15min = home_charge_rate_kw / 4.0

        for i, planned_mode in enumerate(modes):
            if i >= len(spot_prices):
                break

            ts_value = spot_prices[i].get("time")
            start_dt = self._parse_timeline_timestamp(str(ts_value or ""))
            if not start_dt:
                start_dt = now + timedelta(minutes=15 * i)

            if start_dt >= guard_until:
                break

            solar_kwh = solar_kwh_list[i] if i < len(solar_kwh_list) else 0.0
            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125
            locked_mode = lock_modes.get(str(ts_value or ""))

            # Držíme potvrzený plán v rámci lock okna.
            forced_mode = locked_mode if locked_mode is not None else planned_mode
            res = simulate_interval(
                mode=forced_mode,
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=soc,
                capacity_kwh=max_capacity,
                hw_min_capacity_kwh=hw_min_capacity,
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
                home_charge_rate_kwh_15min=charge_rate_kwh_15min,
            )
            next_soc = res.new_soc_kwh

            if next_soc < planning_min_kwh:
                # Výjimka: plánovací minimum by bylo porušeno → necháme plán.
                if planned_mode != forced_mode:
                    overrides.append(
                        {
                            "idx": i,
                            "type": "guard_exception_soc",
                            "planned_mode": planned_mode,
                            "forced_mode": planned_mode,
                        }
                    )
                forced_mode = planned_mode
                res = simulate_interval(
                    mode=forced_mode,
                    solar_kwh=solar_kwh,
                    load_kwh=load_kwh,
                    battery_soc_kwh=soc,
                    capacity_kwh=max_capacity,
                    hw_min_capacity_kwh=hw_min_capacity,
                    charge_efficiency=efficiency,
                    discharge_efficiency=efficiency,
                    home_charge_rate_kwh_15min=charge_rate_kwh_15min,
                )
                next_soc = res.new_soc_kwh
            else:
                if planned_mode != forced_mode:
                    guarded_modes[i] = forced_mode
                    overrides.append(
                        {
                            "idx": i,
                            "type": "guard_locked_plan",
                            "planned_mode": planned_mode,
                            "forced_mode": forced_mode,
                        }
                    )

            soc = next_soc

        if overrides:
            self._log_rate_limited(
                "mode_guard_applied",
                "info",
                "🛡️ Guard aktivní: zamknuto %s intervalů (do %s)",
                len(overrides),
                guard_until.isoformat(),
                cooldown_s=900.0,
            )

        return guarded_modes, overrides, guard_until, None

    def _apply_guard_reasons_to_timeline(
        self,
        timeline: List[Dict[str, Any]],
        overrides: List[Dict[str, Any]],
        guard_until: Optional[datetime],
        current_mode: Optional[int],
    ) -> None:
        if not timeline or not overrides:
            return

        current_mode_name = (
            CBB_MODE_NAMES.get(current_mode, "HOME I")
            if current_mode is not None
            else ""
        )
        guard_until_str = guard_until.isoformat() if guard_until else None

        for override in overrides:
            idx = override.get("idx")
            if idx is None or idx >= len(timeline):
                continue

            entry = timeline[idx]
            planned_mode = override.get("planned_mode")
            forced_mode = override.get("forced_mode")
            override_type = override.get("type")

            planned_name = CBB_MODE_NAMES.get(planned_mode, "HOME I")
            forced_name = CBB_MODE_NAMES.get(forced_mode, planned_name)

            if override_type == "guard_exception_soc":
                reason = (
                    "Výjimka guardu: SoC pod plánovacím minimem – "
                    f"povolujeme změnu na {planned_name}."
                )
            elif override_type == "guard_locked_plan":
                guard_until_label = self._format_time_label(guard_until_str)
                if guard_until_label != "--:--":
                    reason = (
                        "Stabilizace: držíme potvrzený plán "
                        f"{forced_name} do {guard_until_label}."
                    )
                else:
                    reason = (
                        "Stabilizace: držíme potvrzený plán "
                        f"{forced_name} 60 min po poslední změně."
                    )
            else:
                reason = (
                    "Stabilizace: držíme aktuální režim "
                    f"{current_mode_name or forced_name} 60 min po poslední změně."
                )

            metrics = entry.get("decision_metrics") or {}
            existing_reason = entry.get("decision_reason")
            if existing_reason:
                metrics.setdefault("guard_original_reason", existing_reason)

            metrics.update(
                {
                    "guard_active": True,
                    "guard_type": override_type,
                    "guard_until": guard_until_str,
                    "guard_planned_mode": planned_name,
                    "guard_forced_mode": forced_name,
                }
            )
            entry["decision_metrics"] = metrics
            entry["decision_reason"] = reason

    def _build_strategy_balancing_plan(
        self,
        spot_prices: List[Dict[str, Any]],
        active_plan: Any,
    ) -> Optional[StrategyBalancingPlan]:
        """Convert BalancingManager plan into HybridStrategy balancing plan."""
        if not active_plan:
            return None

        if hasattr(active_plan, "active") and not active_plan.active:
            return None

        plan_mode = getattr(active_plan, "mode", None)
        plan_mode_value = (
            plan_mode.value
            if hasattr(plan_mode, "value")
            else (str(plan_mode) if plan_mode else None)
        )
        intervals = getattr(active_plan, "intervals", None) or []
        if plan_mode_value == "natural" and not intervals:
            return None

        holding_start_raw = getattr(active_plan, "holding_start", None)
        holding_end_raw = getattr(active_plan, "holding_end", None)
        if not holding_start_raw or not holding_end_raw:
            return None

        def _coerce_dt(value: Any) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                ts = value
            else:
                try:
                    ts = datetime.fromisoformat(str(value))
                except Exception:
                    return None
            if ts.tzinfo is None:
                ts = dt_util.as_local(ts)
            return ts

        holding_start = _coerce_dt(holding_start_raw)
        holding_end = _coerce_dt(holding_end_raw)
        if not holding_start or not holding_end:
            return None

        interval_delta = timedelta(minutes=15)
        spot_times: List[Optional[datetime]] = []
        idx_by_ts: Dict[datetime, int] = {}
        idx_by_naive: Dict[datetime, int] = {}

        for idx, sp in enumerate(spot_prices):
            ts_raw = sp.get("time")
            if not ts_raw:
                spot_times.append(None)
                continue
            ts = _coerce_dt(ts_raw)
            spot_times.append(ts)
            if ts is None:
                continue
            idx_by_ts[ts] = idx
            idx_by_naive[ts.replace(tzinfo=None)] = idx

        def _find_index(ts: Optional[datetime]) -> Optional[int]:
            if ts is None:
                return None
            idx = idx_by_ts.get(ts)
            if idx is not None:
                return idx
            naive = ts.replace(tzinfo=None)
            idx = idx_by_naive.get(naive)
            if idx is not None:
                return idx
            for i, base in enumerate(spot_times):
                if base is None:
                    continue
                if base <= ts < (base + interval_delta):
                    return i
            return None

        holding_indices: set[int] = set()
        for idx, ts in enumerate(spot_times):
            if ts is None:
                continue
            if ts < holding_end and (ts + interval_delta) > holding_start:
                holding_indices.add(idx)

        mode_overrides: Dict[int, int] = {}
        for interval in intervals:
            ts_value = getattr(interval, "ts", None)
            if ts_value is None and isinstance(interval, dict):
                ts_value = interval.get("ts")
            mode_value = getattr(interval, "mode", None)
            if mode_value is None and isinstance(interval, dict):
                mode_value = interval.get("mode")
            if ts_value is None or mode_value is None:
                continue
            ts = _coerce_dt(ts_value)
            idx = _find_index(ts)
            if idx is None:
                continue
            try:
                mode_int = int(mode_value)
            except (TypeError, ValueError):
                continue
            mode_overrides[idx] = mode_int

        charging_indices: set[int] = set()
        for idx, mode_int in mode_overrides.items():
            if idx in holding_indices:
                continue
            if mode_int == CBB_MODE_HOME_UPS:
                charging_indices.add(idx)

        return StrategyBalancingPlan(
            deadline=holding_start,
            holding_start=holding_start,
            holding_end=holding_end,
            charging_intervals=charging_indices,
            holding_intervals=holding_indices,
            is_active=True,
            reason=str(getattr(active_plan, "reason", "balancing")),
            mode_overrides=mode_overrides,
        )

    def _build_planner_timeline(
        self,
        *,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        hw_min_capacity: float,
        efficiency: float,
        home_charge_rate_kw: float,
    ) -> List[Dict[str, Any]]:
        """Build timeline in legacy format from planner modes."""
        timeline: List[Dict[str, Any]] = []
        soc = current_capacity
        charge_rate_kwh_15min = home_charge_rate_kw / 4.0

        for i, mode in enumerate(modes):
            if i >= len(spot_prices):
                break
            ts_str = str(spot_prices[i].get("time", ""))
            spot_price = float(spot_prices[i].get("price", 0.0) or 0.0)
            export_price = (
                float(export_prices[i].get("price", 0.0) or 0.0)
                if i < len(export_prices)
                else 0.0
            )

            solar_kwh = 0.0
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)
                solar_kwh = self._get_solar_for_timestamp(ts, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125

            res = simulate_interval(
                mode=mode,
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=soc,
                capacity_kwh=max_capacity,
                hw_min_capacity_kwh=hw_min_capacity,
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
                home_charge_rate_kwh_15min=charge_rate_kwh_15min,
            )
            soc = res.new_soc_kwh

            net_cost = (res.grid_import_kwh * spot_price) - (
                res.grid_export_kwh * export_price
            )

            timeline.append(
                {
                    "time": ts_str,
                    "timestamp": ts_str,
                    "battery_soc": round(soc, 6),
                    "battery_capacity_kwh": round(soc, 6),
                    "mode": int(mode),
                    "mode_name": CBB_MODE_NAMES.get(int(mode), "HOME I"),
                    "solar_kwh": round(solar_kwh, 6),
                    "load_kwh": round(load_kwh, 6),
                    "grid_import": round(res.grid_import_kwh, 6),
                    "grid_export": round(res.grid_export_kwh, 6),
                    "grid_net": round(res.grid_import_kwh - res.grid_export_kwh, 6),
                    "spot_price": round(spot_price, 6),
                    "spot_price_czk": round(spot_price, 6),
                    "export_price_czk": round(export_price, 6),
                    "net_cost": round(net_cost, 6),
                    "solar_charge_kwh": round(max(0.0, res.solar_charge_kwh), 6),
                    "grid_charge_kwh": round(max(0.0, res.grid_charge_kwh), 6),
                }
            )

        return timeline

    def _format_planner_reason(
        self,
        reason_code: Optional[str],
        *,
        spot_price: Optional[float] = None,
    ) -> Optional[str]:
        """Map planner reason codes to user-facing text."""
        if not reason_code:
            return None

        if reason_code.startswith("planned_charge"):
            if spot_price is not None:
                return f"Plánované nabíjení ze sítě ({spot_price:.2f} Kč/kWh)"
            return "Plánované nabíjení ze sítě"

        if reason_code == "price_band_hold":
            if spot_price is not None:
                return (
                    f"UPS držíme v cenovém pásmu dle účinnosti "
                    f"({spot_price:.2f} Kč/kWh)"
                )
            return "UPS držíme v cenovém pásmu dle účinnosti"

        if reason_code in {"balancing_charge", "balancing_override"}:
            return "Balancování: nabíjení na 100 %"
        if reason_code == "holding_period":
            return "Balancování: držení 100 %"

        if reason_code in {"negative_price_charge", "auto_negative_charge"}:
            return "Negativní cena: nabíjení ze sítě"
        if reason_code in {"negative_price_curtail", "auto_negative_curtail"}:
            return "Negativní cena: omezení exportu (HOME III)"
        if reason_code in {"negative_price_consume", "auto_negative_consume"}:
            return "Negativní cena: maximalizace spotřeby"

        return None

    def _attach_planner_reasons(
        self,
        timeline: List[Dict[str, Any]],
        decisions: List[Any],
    ) -> None:
        """Attach planner reasons and decision metrics to timeline entries."""
        for idx, decision in enumerate(decisions):
            if idx >= len(timeline):
                break
            reason_code = getattr(decision, "reason", None)
            metrics = timeline[idx].get("decision_metrics") or {}
            if reason_code:
                metrics.setdefault("planner_reason_code", reason_code)
                metrics.setdefault("planner_reason", reason_code)
            metrics.setdefault(
                "planner_is_balancing", bool(getattr(decision, "is_balancing", False))
            )
            metrics.setdefault(
                "planner_is_holding", bool(getattr(decision, "is_holding", False))
            )
            metrics.setdefault(
                "planner_is_negative_price",
                bool(getattr(decision, "is_negative_price", False)),
            )
            timeline[idx]["decision_metrics"] = metrics

            reason_text = self._format_planner_reason(
                reason_code, spot_price=timeline[idx].get("spot_price")
            )
            if reason_text:
                timeline[idx]["decision_reason"] = reason_text

    def _add_decision_reasons_to_timeline(
        self,
        timeline: List[Dict[str, Any]],
        *,
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        efficiency: float,
    ) -> None:
        """Attach decision reason strings and metrics to each timeline interval."""
        if not timeline:
            return

        battery = current_capacity

        future_ups_avg_price: List[Optional[float]] = [None] * len(timeline)
        cumulative_charge = 0.0
        cumulative_cost = 0.0

        for idx in range(len(timeline) - 1, -1, -1):
            entry = timeline[idx]
            if entry.get("mode") == CBB_MODE_HOME_UPS:
                charge_kwh = entry.get("grid_charge_kwh", 0.0) or 0.0
                if charge_kwh > 0:
                    cumulative_charge += charge_kwh
                    cumulative_cost += charge_kwh * (entry.get("spot_price", 0) or 0)

            if cumulative_charge > 0:
                future_ups_avg_price[idx] = cumulative_cost / cumulative_charge

        for idx, entry in enumerate(timeline):
            entry["battery_soc_start"] = battery

            mode = entry.get("mode")
            load_kwh = entry.get("load_kwh", 0.0) or 0.0
            solar_kwh = entry.get("solar_kwh", 0.0) or 0.0
            price = entry.get("spot_price", 0.0) or 0.0

            existing_reason = entry.get("decision_reason")
            existing_metrics = entry.get("decision_metrics") or {}

            decision_reason = None
            decision_metrics: Dict[str, Any] = {}

            deficit = max(0.0, load_kwh - solar_kwh)

            if mode == CBB_MODE_HOME_II:
                if deficit > 0:
                    available_battery = max(0.0, battery - min_capacity)
                    discharge_kwh = (
                        min(deficit / efficiency, available_battery)
                        if efficiency > 0
                        else 0.0
                    )
                    covered_kwh = discharge_kwh * efficiency
                    interval_saving = covered_kwh * price
                    avg_price = future_ups_avg_price[idx]
                    recharge_cost = (
                        (discharge_kwh / efficiency) * avg_price
                        if avg_price is not None and efficiency > 0
                        else None
                    )

                    decision_metrics = {
                        "home1_saving_czk": round(interval_saving, 2),
                        "soc_drop_kwh": round(discharge_kwh, 2),
                        "recharge_avg_price_czk": (
                            round(avg_price, 2) if avg_price is not None else None
                        ),
                        "recharge_cost_czk": (
                            round(recharge_cost, 2)
                            if recharge_cost is not None
                            else None
                        ),
                    }

                    if recharge_cost is not None:
                        decision_reason = (
                            f"Drzeni baterie: HOME I by usetril {interval_saving:.2f} Kc, "
                            f"dobiti ~{recharge_cost:.2f} Kc"
                        )
                    else:
                        decision_reason = (
                            f"Drzeni baterie: HOME I by usetril {interval_saving:.2f} Kc, "
                            "chybi UPS okno pro dobiti"
                        )
                else:
                    decision_reason = "Prebytky ze solaru do baterie (bez vybijeni)"
            elif mode == CBB_MODE_HOME_UPS:
                charge_kwh = entry.get("grid_charge_kwh", 0.0) or 0.0
                if charge_kwh > 0:
                    decision_reason = f"Nabijeni ze site: +{charge_kwh:.2f} kWh pri {price:.2f} Kc/kWh"
                else:
                    decision_reason = "UPS rezim (ochrana/udrzovani)"
            elif mode == CBB_MODE_HOME_III:
                decision_reason = "Max nabijeni z FVE, spotreba ze site"
            else:
                if deficit > 0:
                    decision_reason = "Vybijeni baterie misto odberu ze site"
                else:
                    decision_reason = "Solar pokryva spotrebu, prebytky do baterie"

            if existing_reason:
                decision_reason = existing_reason
            if existing_metrics:
                decision_metrics = {**decision_metrics, **existing_metrics}

            avg_ups_price = future_ups_avg_price[idx]
            decision_metrics.setdefault("spot_price_czk", round(price, 2))
            decision_metrics.setdefault(
                "future_ups_avg_price_czk",
                round(avg_ups_price, 2) if avg_ups_price is not None else None,
            )
            decision_metrics.setdefault("load_kwh", round(load_kwh, 3))
            decision_metrics.setdefault("solar_kwh", round(solar_kwh, 3))
            decision_metrics.setdefault("deficit_kwh", round(deficit, 3))
            decision_metrics.setdefault(
                "grid_charge_kwh",
                round(entry.get("grid_charge_kwh", 0.0) or 0.0, 3),
            )
            decision_metrics.setdefault(
                "battery_start_kwh",
                round(entry.get("battery_soc_start", battery), 2),
            )
            decision_metrics.setdefault(
                "battery_end_kwh",
                round(
                    entry.get("battery_soc", entry.get("battery_soc_start", battery)), 2
                ),
            )

            entry["decision_reason"] = decision_reason
            entry["decision_metrics"] = decision_metrics

            # Advance battery for next interval (end-of-interval stored in timeline)
            try:
                battery = float(entry.get("battery_soc", battery))
            except (TypeError, ValueError):
                battery = battery

    def _validate_planning_minimum(
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,  # planning_min = 33%
        physical_min_capacity: float,  # hw_min = 20%
        efficiency: float,
        start_index: int = 0,
        starting_soc: Optional[float] = None,
        min_candidate_index: int = 0,
        forward_soc_before: Optional[List[Optional[float]]] = None,
    ) -> List[int]:
        """
        PHASE 7: Validace planning minimum (33% = 5.07 kWh).

        PREEMPTIVE MULTI-INTERVAL CHARGING (B+light D strategy):
        - Simuluje timeline s HW minimum (fyzika nezná planning_min!)
        - Detekuje první violation planning_min
        - Spočítá deficit_kwh (kolik chybí k planning_min + rezerva)
        - Vybere VÍCE levných intervalů PŘED violation (ne jen 1 noční!)
        - Iteruje dokud není porušení opraveno (max 5 iterací)

        Podle REFACTORING_IMPLEMENTATION_GUIDE.md:
        - Simulace používá POUZE physical_min_capacity (hw_min)
        - Planning_min je plánovací constraint (validace výsledku)
        - Žádný clamp na planning_min v simulaci!

        Args:
            modes: Aktuální režimy (list of int)
            spot_prices: Timeline spot cen
            export_prices: Timeline export cen
            solar_forecast: Solární předpověď
            load_forecast: Předpověď spotřeby
            current_capacity: Aktuální SoC (kWh)
            max_capacity: Max kapacita (kWh)
            min_capacity: Planning minimum (kWh, typicky 33% = 5.07)
            physical_min_capacity: HW minimum (kWh, typicky 20% = 3.07)
            efficiency: Účinnost baterie
            start_index: Index od kterého validujeme (balancing → po holding_end)
            starting_soc: Volitelné přepsání úvodního SoC pro simulaci
            min_candidate_index: Nejnižší index, který lze přepsat na HOME UPS
            forward_soc_before: SoC před každým intervalem (z forward passu) pro detekci dostupné kapacity

        Returns:
            Upravený seznam režimů garantující dodržení planning_min
        """
        MAX_ITERATIONS = 5
        SAFETY_MARGIN = 1.10  # Nabít +10% nad planning_min pro rezervu

        # Načíst charging power z konfigurace
        config = self._get_config()
        charging_power_kw = config.get("home_charge_rate", 2.8)
        max_charge_per_interval = charging_power_kw / 4.0  # kWh za 15min

        for iteration in range(MAX_ITERATIONS):
            # 1. Simuluj timeline a najdi porušení (s violation SoC)
            violation_result = self._find_first_planning_violation_with_soc(
                modes=modes,
                spot_prices=spot_prices,
                export_prices=export_prices,
                solar_forecast=solar_forecast,
                load_forecast=load_forecast,
                current_capacity=current_capacity,
                max_capacity=max_capacity,
                min_capacity=min_capacity,
                physical_min_capacity=physical_min_capacity,
                efficiency=efficiency,
                start_index=start_index,
                starting_soc=starting_soc,
            )

            if violation_result is None:
                # Žádné porušení → hotovo!
                if iteration > 0:
                    self._log_rate_limited(
                        "planning_min_fixed",
                        "debug",
                        "✅ PLANNING_MIN validation: Fixed all violations in %s iterations",
                        iteration,
                        cooldown_s=1800.0,
                    )
                return modes

            violation_index, soc_at_violation, recovery_idx = violation_result

            # 2. Spočítej deficit s bezpečnostní rezervou
            target_soc = min_capacity * SAFETY_MARGIN
            deficit_kwh = max(0.1, target_soc - soc_at_violation)  # Min 100Wh

            # 3. Určit PŘED jakým intervalem nabíjet:
            #    - Pokud recovery_idx > 0: violation začíná OD ZAČÁTKU (interval 0)
            #      → musíme nabít PŘED/V intervalu 0 (nebo co nejdřív)
            #    - Pokud recovery_idx == 0: violation JE až na violation_index
            #      → můžeme nabít PŘED violation_index
            candidate_floor = max(min_candidate_index, 0)
            if recovery_idx is not None and recovery_idx > candidate_floor:
                charge_before_index = recovery_idx
            else:
                charge_before_index = violation_index

            self._log_rate_limited(
                "planning_min_violation_iter",
                "debug",
                "[PLANNING_MIN iter %s] Violation @ interval %s: SoC=%.2f kWh < planning_min=%.2f kWh, deficit=%.2f kWh (target=%.2f), recovery=%s, charge_before=%s",
                iteration + 1,
                violation_index,
                soc_at_violation,
                min_capacity,
                deficit_kwh,
                target_soc,
                recovery_idx,
                charge_before_index,
                cooldown_s=900.0,
            )

            # 4. Vyber kandidátní intervaly PŘED charge_before_index (cost-aware)
            config_options = (
                self._config_entry.options
                if self._config_entry and self._config_entry.options
                else {}
            )
            CHARGING_LOOKBACK_INTERVALS = int(
                config_options.get("planning_min_lookback_intervals", 48)
            )  # default ≈12h
            effective_min_index = max(
                min_candidate_index, charge_before_index - CHARGING_LOOKBACK_INTERVALS
            )

            candidate_intervals = self._select_charging_intervals_before(
                modes=modes,
                spot_prices=spot_prices,
                before_index=charge_before_index,
                deficit_kwh=deficit_kwh,
                max_charge_per_interval=max_charge_per_interval,
                max_capacity=max_capacity,
                min_index=effective_min_index,
                soc_before=forward_soc_before,
            )

            if not candidate_intervals and effective_min_index > min_candidate_index:
                candidate_intervals = self._select_charging_intervals_before(
                    modes=modes,
                    spot_prices=spot_prices,
                    before_index=charge_before_index,
                    deficit_kwh=deficit_kwh,
                    max_charge_per_interval=max_charge_per_interval,
                    max_capacity=max_capacity,
                    min_index=min_candidate_index,
                    soc_before=forward_soc_before,
                )

            if not candidate_intervals:
                # Nelze opravit (žádné dostupné intervaly)
                self._log_rate_limited(
                    "planning_min_unfixable",
                    "debug",
                    "⚠️ PLANNING_MIN violation @ interval %s cannot be fixed (no charging intervals available before, deficit=%.2f kWh)",
                    violation_index,
                    deficit_kwh,
                    cooldown_s=3600.0,
                )
                return modes  # Vrátit co je (lepší než crash)

            # 4. Přidej HOME UPS v těchto intervalech
            modes = modes.copy()
            for idx in candidate_intervals:
                modes[idx] = CBB_MODE_HOME_UPS

            expected_charge = len(candidate_intervals) * max_charge_per_interval
            self._log_rate_limited(
                "planning_min_added_ups",
                "debug",
                "→ Added HOME UPS @ %s intervals (expected_charge=%.2f kWh need %.2f kWh)",
                len(candidate_intervals),
                expected_charge,
                deficit_kwh,
                cooldown_s=900.0,
            )

        # Max iterace dosaženo
        self._log_rate_limited(
            "planning_min_max_iters",
            "debug",
            "⚠️ PLANNING_MIN validation: Reached max iterations (%s), some violations may remain",
            MAX_ITERATIONS,
            cooldown_s=3600.0,
        )
        return modes

    def _find_first_planning_violation(
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        physical_min_capacity: float,
        efficiency: float,
    ) -> Optional[int]:
        """
        Najít první interval kde baterie klesne pod planning_min.

        LEGACY VERSION - vrací jen index.
        Pro novou logiku použij _find_first_planning_violation_with_soc().

        ZÁSADY:
        - Simulace vždy používá physical_min_capacity (HW minimum ~20%)
        - Planning_min (~25%) je PLÁNOVACÍ constraint, ne fyzikální limit
        - Kontrola začíná od recovery_index (kdy SoC >= planning_min)
        - Pokud current_soc < planning_min, snažíme se dostat zpět nad, pak kontrolujeme

        Returns:
            Index prvního intervalu s porušením, nebo None pokud žádné
        """
        result = self._find_first_planning_violation_with_soc(
            modes=modes,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            physical_min_capacity=physical_min_capacity,
            efficiency=efficiency,
        )
        return result[0] if result else None

    def _find_first_planning_violation_with_soc(
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        physical_min_capacity: float,
        efficiency: float,
        start_index: int = 0,
        starting_soc: Optional[float] = None,
    ) -> Optional[tuple[int, float, int]]:
        """
        Najít první interval kde baterie klesne pod planning_min.

        ENHANCED VERSION - vrací (index, soc_at_violation, recovery_index) pro deficit calculation.

        ZÁSADY:
        - Simulace vždy používá physical_min_capacity (HW minimum ~20%)
        - Planning_min (~25%) je PLÁNOVACÍ constraint, ne fyzikální limit
        - Kontrola začíná od recovery_index (kdy SoC >= planning_min)
        - Pokud current_soc < planning_min, snažíme se dostat zpět nad, pak kontrolujeme
        - start_index / starting_soc umožňuje balancingu začít kontrolu až po holding period

        Returns:
            Tuple (violation_index, soc_at_violation, recovery_index) nebo None pokud žádné porušení
        """
        n = len(modes)
        if n == 0:
            return None

        start_index = max(0, min(start_index, n - 1))

        battery_soc = starting_soc if starting_soc is not None else current_capacity
        recovery_index = None  # První interval kde SoC >= planning_min

        # Pokud už začínáme nad planning_min, recovery je hned
        if battery_soc >= min_capacity:
            recovery_index = start_index

        for i in range(start_index, n):
            mode = modes[i]
            # Získat data pro interval
            spot_price = (
                spot_prices[i].get("price", 0.0) if i < len(spot_prices) else 0.0
            )
            export_price = (
                export_prices[i].get("price", 0.0) if i < len(export_prices) else 0.0
            )
            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.0

            # Get solar
            solar_kwh = 0.0
            try:
                timestamp_str = spot_prices[i].get("time", "")
                timestamp = datetime.fromisoformat(timestamp_str)
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            # Simuluj interval s FYZICKÝM HW minimem (NIKDY planning_min!)
            sim_result = self._simulate_interval(
                mode=mode,
                solar_kwh=solar_kwh,
                load_kwh=load_kwh,
                battery_soc_kwh=battery_soc,
                capacity_kwh=max_capacity,
                hw_min_capacity_kwh=physical_min_capacity,  # Reálné HW minimum!
                spot_price_czk=spot_price,
                export_price_czk=export_price,
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
            )

            battery_soc = sim_result["new_soc_kwh"]

            # Najít recovery_index (kdy se poprvé dostaneme nad planning_min)
            if recovery_index is None and battery_soc >= min_capacity:
                recovery_index = i
                _LOGGER.debug(
                    f"[PLANNING_MIN] Recovery @ interval {i}: SoC={battery_soc:.2f} kWh >= {min_capacity:.2f} kWh"
                )

            # Kontrola planning_min violation JEN PO recovery
            # Pokud jsme se jednou dostali nad planning_min, nesmíme zpět pod
            if recovery_index is not None and i > recovery_index:
                if battery_soc < min_capacity - 0.01:  # 10Wh tolerance
                    _LOGGER.debug(
                        f"[PLANNING_MIN] Violation @ interval {i}: "
                        f"SoC={battery_soc:.2f} kWh < planning_min={min_capacity:.2f} kWh "
                        f"(recovery was @ {recovery_index})"
                    )
                    return (i, battery_soc, recovery_index)

        # Pokud jsme nikdy nedosáhli recovery
        if recovery_index is None:
            _LOGGER.warning(
                f"[PLANNING_MIN] Cannot reach planning_min in entire timeline "
                f"(started @ {current_capacity:.2f} kWh, need {min_capacity:.2f} kWh)"
            )

        return None  # Žádné porušení

    def _select_charging_intervals_before(
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        before_index: int,
        deficit_kwh: float,
        max_charge_per_interval: float,
        max_capacity: float,
        min_index: int = 0,
        soc_before: Optional[List[Optional[float]]] = None,
    ) -> List[int]:
        """
        Vybrat více levných intervalů PŘED violation pro proaktivní nabíjení.

        PREEMPTIVE MULTI-INTERVAL STRATEGY (B+light D):
        - Kandidáti = všechny intervaly 0..before_index-1
        - Filtr: nejsou už HOME UPS, mají volnou kapacitu
        - Seřazení: podle ceny (levné první), sekundárně podle času (blíže k violation)
        - Výběr: tolik intervalů, aby součet nabití ≥ deficit_kwh

        Args:
            modes: Aktuální režimy
            spot_prices: Timeline spot cen
            before_index: Violation index (vybíráme PŘED tímto indexem)
            deficit_kwh: Kolik kWh potřebujeme dobít
            max_charge_per_interval: Max nabíjecí výkon za 15min (kWh)
            max_capacity: Max kapacita baterie (kWh)
            min_index: Nejnižší index který smíme přepisovat (balancing → po holding)
            soc_before: SoC před začátkem intervalu (z forward passu) pro zjištění volné kapacity

        Returns:
            Seznam indexů pro HOME UPS nabíjení (seřazeno podle času)
        """
        candidates = []

        start = max(min_index, 0)
        HEADROOM_THRESHOLD = 0.05  # kWh

        for i in range(start, before_index):
            # Skip pokud už je HOME UPS (nepřepisujeme existující logiku)
            if modes[i] == CBB_MODE_HOME_UPS:
                continue

            # Skip pokud nemáme cenu
            if i >= len(spot_prices):
                continue

            if soc_before is not None:
                soc_val = None
                if 0 <= i < len(soc_before):
                    soc_val = soc_before[i]
                if soc_val is not None and soc_val >= max_capacity - HEADROOM_THRESHOLD:
                    # Baterie už je prakticky plná → UPS by nenabila
                    continue

            price = spot_prices[i].get("price", 999.0)

            # Přidat jako kandidáta
            # (index, price, time_distance_to_violation)
            time_distance = before_index - i  # Čím menší, tím blíž k violation
            candidates.append((i, price, time_distance))

        if not candidates:
            return []

        # Seřadit: primárně podle ceny (ASC), sekundárně podle času (DESC = blíž k violation)
        # Cost-aware: preferujeme levnější intervaly
        # Time-aware: při stejné ceně preferujeme bližší k violation
        candidates.sort(key=lambda x: (x[1], -x[2]))

        # Vybrat tolik intervalů, aby součet nabití ≥ deficit_kwh
        selected_indices = []
        accumulated_charge = 0.0

        for idx, price, _ in candidates:
            selected_indices.append(idx)
            accumulated_charge += max_charge_per_interval

            # Pokud máme dost, končíme
            if accumulated_charge >= deficit_kwh:
                break

            # Ochrana před příliš mnoha intervaly (max 20 = 5h nabíjení)
            if len(selected_indices) >= 20:
                _LOGGER.warning(
                    f"⚠️ Reached max charging intervals (20), "
                    f"accumulated={accumulated_charge:.2f} kWh < deficit={deficit_kwh:.2f} kWh"
                )
                break

        # Seřadit výsledek podle času (pro konzistentní timeline)
        selected_indices.sort()

        return selected_indices

    def _find_cheapest_night_interval_before(
        self,
        spot_prices: List[Dict[str, Any]],
        before_index: int,
    ) -> Optional[int]:
        """
        Najít nejlevnější noční interval (22:00-06:00) před daným indexem.

        Args:
            spot_prices: Timeline spot cen
            before_index: Index před kterým hledat

        Returns:
            Index nejlevnějšího nočního intervalu, nebo None
        """
        night_intervals = []

        for i in range(before_index):
            try:
                timestamp_str = spot_prices[i].get("time", "")
                timestamp = datetime.fromisoformat(timestamp_str)
                hour = timestamp.hour

                # Noční hodiny: 22:00-06:00
                if hour >= 22 or hour < 6:
                    price = spot_prices[i].get("price", 999.0)
                    night_intervals.append((i, price))
            except Exception:
                continue

        if not night_intervals:
            return None

        # Seřadit podle ceny (ascending)
        night_intervals.sort(key=lambda x: x[1])

        # Vrátit index nejlevnějšího
        return night_intervals[0][0]

    def _build_result(  # noqa: C901
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        export_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, Any],
        load_forecast: List[float],
        current_capacity: float,
        max_capacity: float,
        min_capacity: float,
        efficiency: float,
        baselines: Dict[str, Dict[str, Any]] | None = None,
        physical_min_capacity: float | None = None,
        effective_floor_capacity: float | None = None,
    ) -> Dict[str, Any]:
        """
        Sestavit výsledek ve formátu kompatibilní s timeline.

        Args:
            baselines: Optional 4-baseline comparison results from _calculate_mode_baselines()
        """
        config = self._get_config()
        charging_power_kw = config.get("home_charge_rate", 2.8)
        max_charge_per_interval = charging_power_kw / 4.0

        # Default physical minimum to 20% if not provided
        if physical_min_capacity is None:
            physical_min_capacity = max_capacity * 0.20

        # Default effective floor to planning minimum if not provided (backward compatibility)
        # For planning-min guard, this will be min_capacity + floor_margin
        if effective_floor_capacity is None:
            effective_floor_capacity = min_capacity
            _LOGGER.debug(
                f"[BUILD_RESULT] effective_floor_capacity not provided, defaulting to min_capacity={min_capacity:.2f} kWh"
            )
        else:
            _LOGGER.debug(
                f"[BUILD_RESULT] Using effective_floor_capacity={effective_floor_capacity:.2f} kWh (min={min_capacity:.2f}, margin={effective_floor_capacity - min_capacity:.2f})"
            )

        # Create export price lookup by timestamp
        export_price_lookup = {
            ep["time"]: ep["price"]
            for ep in export_prices
            if "time" in ep and "price" in ep
        }

        timeline = []
        battery = current_capacity
        total_cost = 0.0

        for i, mode in enumerate(modes):
            battery_start = battery
            timestamp_str = spot_prices[i].get("time", "")
            price = spot_prices[i].get("price", 0)
            export_price = export_price_lookup.get(timestamp_str, 0)

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
            except Exception:
                solar_kwh = 0.0

            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125

            # Initialize variables for this interval
            grid_import = 0.0
            grid_export = 0.0
            solar_charge_kwh = 0.0  # For stacked graph - calculated in physics
            grid_charge_kwh = 0.0  # For stacked graph - calculated in physics
            available_space = max_capacity - battery

            # Fyzika podle módu - OPRAVENO: Dopředný výpočet místo zpětného
            # Charge hodnoty se počítají PŘED změnou battery, ne po ní
            if mode == CBB_MODE_HOME_UPS:
                # UPS: spotřeba ze sítě, baterie nabíjí ze solaru + gridu
                # KROK 1: Vypočítat kolik REÁLNĚ půjde do baterie (respektovat available_space)
                actual_grid_charge = min(
                    max_charge_per_interval, available_space / efficiency
                )
                space_after_grid = max(0, available_space - actual_grid_charge)
                actual_solar_charge = min(solar_kwh, space_after_grid)

                # KROK 2: Fyzika - aktualizovat battery s okamžitým clampingem
                grid_import = load_kwh + actual_grid_charge
                battery += actual_solar_charge + actual_grid_charge
                battery = min(battery, max_capacity)  # Clamp okamžitě

                # KROK 3: Export přebytku solaru (pokud se nevešel do baterie)
                solar_surplus = solar_kwh - actual_solar_charge
                if solar_surplus > 0.001:  # Tolerance pro zaokrouhlovací chyby
                    grid_export = solar_surplus
                    total_cost -= grid_export * export_price

                total_cost += grid_import * price

                # KROK 4: Uložit charge hodnoty pro graf
                solar_charge_kwh = actual_solar_charge
                grid_charge_kwh = actual_grid_charge

            elif mode == CBB_MODE_HOME_II:
                # HOME II: FVE → spotřeba, grid doplňuje, baterie jen přebytek
                if solar_kwh >= load_kwh:
                    # Přebytek po spotřebě
                    surplus = solar_kwh - load_kwh

                    # KROK 1: Kolik reálně půjde do baterie
                    actual_solar_charge = min(surplus, available_space)

                    # KROK 2: Fyzika
                    battery += actual_solar_charge
                    battery = min(battery, max_capacity)  # Clamp

                    # KROK 3: Export přebytku
                    solar_surplus = surplus - actual_solar_charge
                    if solar_surplus > 0.001:
                        grid_export = solar_surplus
                        total_cost -= grid_export * export_price

                    # KROK 4: Uložit pro graf
                    solar_charge_kwh = actual_solar_charge
                else:
                    # Deficit → GRID doplňuje (baterie se nemění)
                    deficit = load_kwh - solar_kwh
                    grid_import = deficit
                    total_cost += grid_import * price
                    # solar_charge_kwh a grid_charge_kwh zůstávají 0

            elif mode == CBB_MODE_HOME_III:
                # HOME III: CELÁ FVE → baterie, spotřeba → grid
                # KROK 1: Kolik reálně půjde do baterie
                actual_solar_charge = min(solar_kwh, available_space)

                # KROK 2: Fyzika
                battery += actual_solar_charge
                battery = min(battery, max_capacity)  # Clamp

                # KROK 3: Export přebytku
                solar_surplus = solar_kwh - actual_solar_charge
                if solar_surplus > 0.001:
                    grid_export = solar_surplus
                    total_cost -= grid_export * export_price

                # Spotřeba vždy ze sítě
                grid_import = load_kwh
                total_cost += grid_import * price

                # KROK 4: Uložit pro graf
                solar_charge_kwh = actual_solar_charge

            else:  # HOME I (default)
                # HOME I: solar → baterie nebo baterie → load
                if solar_kwh >= load_kwh:
                    # Přebytek
                    surplus = solar_kwh - load_kwh

                    # KROK 1: Kolik reálně půjde do baterie
                    actual_solar_charge = min(surplus, available_space)

                    # KROK 2: Fyzika
                    battery += actual_solar_charge
                    battery = min(battery, max_capacity)  # Clamp

                    # KROK 3: Export přebytku
                    solar_surplus = surplus - actual_solar_charge
                    if solar_surplus > 0.001:
                        grid_export = solar_surplus
                        total_cost -= grid_export * export_price

                    # KROK 4: Uložit pro graf
                    solar_charge_kwh = actual_solar_charge
                else:
                    # Deficit → baterie vybíjí (HOME I fyzika)
                    deficit = load_kwh - solar_kwh  # Kolik chybí po solaru

                    # Kolik máme k dispozici v baterii (nad EFFECTIVE FLOOR!)
                    # _build_result musí respektovat effective_floor (planning_min + margin)
                    available_battery = max(0, battery - effective_floor_capacity)

                    # Kolik reálně vybereme (s účinností)
                    actual_discharge = min(deficit / efficiency, available_battery)
                    battery -= actual_discharge

                    # Pokrytí ze sítě = zbytek deficitu (co baterie nepokryje)
                    covered_by_battery = actual_discharge * efficiency
                    grid_import = deficit - covered_by_battery

                    if grid_import > 0.001:  # Potřebujeme grid
                        total_cost += grid_import * price

                    # Clamp na EFFECTIVE FLOOR (planning_min + margin), ne planning minimum!
                    # This ensures simulation never touches planning minimum
                    battery = max(battery, effective_floor_capacity)

                    # solar_charge_kwh a grid_charge_kwh zůstávají 0 (vybíjení)

            # Validace (pro debugging)
            if battery > max_capacity + 0.001:  # Tolerance
                _LOGGER.warning(
                    f"Battery exceeds max capacity: {battery:.3f} > {max_capacity:.3f} "
                    f"at {timestamp_str}, mode={mode}"
                )
            if solar_charge_kwh < -0.001 or grid_charge_kwh < -0.001:
                _LOGGER.warning(
                    f"Negative charge values: solar={solar_charge_kwh:.3f}, grid={grid_charge_kwh:.3f} "
                    f"at {timestamp_str}, mode={mode}"
                )

            interval_cost = grid_import * price - grid_export * price

            timeline.append(
                {
                    "time": timestamp_str,
                    "timestamp": timestamp_str,  # Alias pro zpětnou kompatibilitu s dashboardem
                    "battery_soc": battery,
                    "battery_soc_start": battery_start,
                    "battery_capacity_kwh": battery,  # Alias pro zpětnou kompatibilitu s dashboardem
                    "mode": mode,
                    "mode_name": CBB_MODE_NAMES.get(mode, "Unknown"),
                    "solar_kwh": solar_kwh,
                    "load_kwh": load_kwh,
                    "grid_import": grid_import,
                    "grid_export": grid_export,
                    "grid_net": round(grid_import - grid_export, 3),
                    "spot_price": price,
                    "spot_price_czk": price,  # Alias pro zpětnou kompatibilitu
                    "export_price_czk": export_price,  # Phase 1.5: Export (sell) price
                    "net_cost": interval_cost,
                    "solar_charge_kwh": round(solar_charge_kwh, 3),  # For stacked graph
                    "grid_charge_kwh": round(grid_charge_kwh, 3),  # For stacked graph
                }
            )

        # Build future UPS average price lookup for decision diagnostics
        future_ups_avg_price: List[Optional[float]] = [None] * len(timeline)
        cumulative_charge = 0.0
        cumulative_cost = 0.0

        for idx in range(len(timeline) - 1, -1, -1):
            entry = timeline[idx]
            if entry.get("mode") == CBB_MODE_HOME_UPS:
                charge_kwh = entry.get("grid_charge_kwh", 0.0) or 0.0
                if charge_kwh > 0:
                    cumulative_charge += charge_kwh
                    cumulative_cost += charge_kwh * (entry.get("spot_price", 0) or 0)

            if cumulative_charge > 0:
                future_ups_avg_price[idx] = cumulative_cost / cumulative_charge

        # Decision diagnostics for UI (per interval)
        for idx, entry in enumerate(timeline):
            decision_reason = None
            decision_metrics: Dict[str, Any] = {}

            mode = entry.get("mode")
            battery_start = entry.get("battery_soc_start", entry.get("battery_soc", 0))
            load_kwh = entry.get("load_kwh", 0) or 0
            solar_kwh = entry.get("solar_kwh", 0) or 0
            price = entry.get("spot_price", 0) or 0

            deficit = max(0.0, load_kwh - solar_kwh)

            if mode == CBB_MODE_HOME_II:
                if deficit > 0:
                    available_battery = max(
                        0.0, battery_start - effective_floor_capacity
                    )
                    discharge_kwh = (
                        min(deficit / efficiency, available_battery)
                        if efficiency > 0
                        else 0
                    )
                    covered_kwh = discharge_kwh * efficiency
                    interval_saving = covered_kwh * price
                    avg_price = future_ups_avg_price[idx]
                    recharge_cost = (
                        (discharge_kwh / efficiency) * avg_price
                        if avg_price is not None and efficiency > 0
                        else None
                    )

                    decision_metrics = {
                        "home1_saving_czk": round(interval_saving, 2),
                        "soc_drop_kwh": round(discharge_kwh, 2),
                        "recharge_avg_price_czk": (
                            round(avg_price, 2) if avg_price is not None else None
                        ),
                        "recharge_cost_czk": (
                            round(recharge_cost, 2)
                            if recharge_cost is not None
                            else None
                        ),
                    }

                    if recharge_cost is not None:
                        decision_reason = (
                            f"Drzeni baterie: HOME I by usetril {interval_saving:.2f} Kc, "
                            f"dobiti ~{recharge_cost:.2f} Kc"
                        )
                    else:
                        decision_reason = (
                            f"Drzeni baterie: HOME I by usetril {interval_saving:.2f} Kc, "
                            "chybi UPS okno pro dobiti"
                        )
                else:
                    decision_reason = "Prebytky ze solaru do baterie (bez vybijeni)"
            elif mode == CBB_MODE_HOME_UPS:
                charge_kwh = entry.get("grid_charge_kwh", 0.0) or 0.0
                if charge_kwh > 0:
                    decision_reason = f"Nabijeni ze site: +{charge_kwh:.2f} kWh pri {price:.2f} Kc/kWh"
                else:
                    decision_reason = "UPS rezim (ochrana/udrzovani)"
            elif mode == CBB_MODE_HOME_III:
                decision_reason = "Max nabijeni z FVE, spotreba ze site"
            else:  # HOME I
                if deficit > 0:
                    decision_reason = "Vybijeni baterie misto odberu ze site"
                else:
                    decision_reason = "Solar pokryva spotrebu, prebytky do baterie"

            entry["decision_reason"] = decision_reason
            entry["decision_metrics"] = decision_metrics

        # Mode recommendations - použít _create_mode_recommendations() pro bloky s detaily
        mode_recommendations = self._create_mode_recommendations(
            timeline, hours_ahead=48
        )

        # Calculate 48h cost for dashboard (DNES+ZÍTRA only, bez včera)
        now = dt_util.now()
        today_start = datetime.combine(now.date(), datetime.min.time())
        today_start = dt_util.as_local(today_start)  # Always timezone-aware
        tomorrow_end = today_start + timedelta(hours=48)

        total_cost_48h = 0.0
        for interval in timeline:
            if not interval.get("time"):
                continue
            try:
                interval_time = datetime.fromisoformat(interval["time"])
                # Normalize timezone for comparison
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)
                if today_start <= interval_time < tomorrow_end:
                    total_cost_48h += interval.get("net_cost", 0)
            except Exception:
                continue

        # Calculate HOME I baseline cost for 48h (pro výpočet úspory)
        baseline_cost_48h = 0.0
        battery_baseline = current_capacity
        for interval in timeline:
            if not interval.get("time"):
                continue
            try:
                interval_time = datetime.fromisoformat(interval["time"])
                # Normalize timezone for comparison
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)
                if not (today_start <= interval_time < tomorrow_end):
                    continue
            except Exception:
                continue

            # HOME I simulation
            solar_kwh = interval.get("solar_kwh", 0)
            load_kwh = interval.get("load_kwh", 0.125)
            price = interval.get("spot_price", 0)

            grid_import = 0.0
            grid_export = 0.0

            if solar_kwh >= load_kwh:
                surplus = solar_kwh - load_kwh
                battery_baseline += surplus
                if battery_baseline > max_capacity:
                    grid_export = battery_baseline - max_capacity
                    battery_baseline = max_capacity
                    baseline_cost_48h -= grid_export * price
            else:
                deficit = load_kwh - solar_kwh
                battery_baseline -= deficit / efficiency
                if battery_baseline < 0:
                    grid_import = -battery_baseline * efficiency
                    battery_baseline = 0
                    baseline_cost_48h += grid_import * price

            battery_baseline = max(0, min(battery_baseline, max_capacity))

        total_savings_48h = max(0, baseline_cost_48h - total_cost_48h)

        # Generate what-if alternatives for dashboard tile
        alternatives = self._generate_alternatives(
            spot_prices=spot_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
            optimal_cost_48h=total_cost_48h,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            efficiency=efficiency,
        )

        # PHASE 2.10: Add baseline comparison and validation
        result = {
            "optimal_timeline": timeline,
            "optimal_modes": modes,
            "total_cost": total_cost,
            "total_cost_48h": total_cost_48h,  # For dashboard tile (DNES+ZÍTRA)
            "total_savings_48h": total_savings_48h,  # Savings vs HOME I baseline
            "mode_recommendations": mode_recommendations,
            "alternatives": alternatives,  # What-if analysis for tile
        }

        # Add 4-baseline comparison if available
        if baselines:
            result["baselines"] = baselines

            # Find best baseline - používá ADJUSTED cost (cost + penalty)
            best_baseline_name = min(
                baselines.items(), key=lambda x: x[1]["adjusted_total_cost"]
            )[0]
            best_baseline = baselines[best_baseline_name]
            best_baseline_cost = best_baseline["total_cost"]
            best_baseline_adjusted = best_baseline["adjusted_total_cost"]
            best_baseline_penalty = best_baseline["penalty_cost"]
            best_baseline_violations = best_baseline["planning_violations"]

            # Calculate savings vs best baseline (using adjusted costs for fair comparison)
            savings_vs_best = max(0, best_baseline_adjusted - total_cost)
            savings_percentage = (
                (savings_vs_best / best_baseline_adjusted * 100)
                if best_baseline_adjusted > 0
                else 0
            )

            result["best_baseline"] = best_baseline_name
            result["best_baseline_cost"] = best_baseline_cost
            result["best_baseline_adjusted"] = best_baseline_adjusted
            result["best_baseline_penalty"] = best_baseline_penalty
            result["hybrid_cost"] = total_cost
            result["savings_vs_best"] = round(savings_vs_best, 2)
            result["savings_percentage"] = round(savings_percentage, 1)

            # Build penalty info string for logging
            penalty_info = ""
            if best_baseline_violations > 0:
                penalty_info = (
                    f" (penalty: {best_baseline_penalty:.2f} Kč "
                    f"for {best_baseline_violations} violations)"
                )

            # VALIDATION: HYBRID must be <= best baseline (adjusted cost)
            if total_cost > best_baseline_adjusted + 0.01:  # 0.01 Kč tolerance
                self._log_rate_limited(
                    "hybrid_validation_bug",
                    "debug",
                    "HYBRID validation failed: hybrid=%.2f Kč > best %s (%.2f Kč adjusted)%s",
                    total_cost,
                    best_baseline_name,
                    best_baseline_adjusted,
                    penalty_info,
                    cooldown_s=3600.0,
                )
            else:
                self._log_rate_limited(
                    "hybrid_validation_ok",
                    "debug",
                    "HYBRID validation ok: hybrid=%.2f Kč <= best %s (%.2f Kč adjusted)%s (saves %.2f Kč, %.1f%%)",
                    total_cost,
                    best_baseline_name,
                    best_baseline_adjusted,
                    penalty_info,
                    savings_vs_best,
                    savings_percentage,
                    cooldown_s=900.0,
                )

        return result

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
        """
        Generate what-if alternatives: what would cost be if we used only one mode all day?

        Returns dict with structure:
        {
            "HOME I": {"cost_czk": 50.5, "delta_czk": 5.2},
            "HOME II": {"cost_czk": 48.0, "delta_czk": 2.7},
            ...
        }
        """
        now = dt_util.now()
        today_start = datetime.combine(now.date(), datetime.min.time())
        today_start = dt_util.as_local(today_start)
        tomorrow_end = today_start + timedelta(hours=48)

        # Phase 2.7: Cache timeline for HOME I
        home_i_timeline_cache = []

        def simulate_mode(mode: int) -> float:
            """Simulate 48h cost with fixed mode"""
            battery = current_capacity
            total_cost = 0.0

            for i, price_data in enumerate(spot_prices):
                timestamp_str = price_data.get("time", "")
                if not timestamp_str:
                    continue

                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp.tzinfo is None:
                        timestamp = dt_util.as_local(timestamp)
                    if not (today_start <= timestamp < tomorrow_end):
                        continue
                except Exception:
                    continue

                # Get input data from forecasts
                try:
                    solar_kwh = self._get_solar_for_timestamp(timestamp, solar_forecast)
                except Exception:
                    solar_kwh = 0.0

                load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125
                price = price_data.get("price", 0)

                grid_import = 0.0
                grid_export = 0.0
                net_cost = 0.0

                # HOME I: Battery priority (NO GRID CHARGING - this is the baseline)
                if mode == 0:
                    if solar_kwh >= load_kwh:
                        surplus = solar_kwh - load_kwh
                        battery += surplus
                        if battery > max_capacity:
                            grid_export = battery - max_capacity
                            battery = max_capacity
                            net_cost = -grid_export * price
                            total_cost += net_cost
                    else:
                        deficit = load_kwh - solar_kwh
                        battery -= deficit / efficiency
                        if battery < 0:
                            grid_import = -battery * efficiency
                            battery = 0
                            net_cost = grid_import * price
                            total_cost += net_cost

                    # Phase 2.7: Cache timeline for HOME I
                    home_i_timeline_cache.append(
                        {"time": timestamp_str, "net_cost": net_cost}
                    )

                # HOME II: Grid supplements, battery saved
                elif mode == 1:
                    if solar_kwh >= load_kwh:
                        surplus = solar_kwh - load_kwh
                        battery += surplus
                        if battery > max_capacity:
                            grid_export = battery - max_capacity
                            battery = max_capacity
                            total_cost -= grid_export * price
                    else:
                        # Grid covers load, battery untouched
                        grid_import = load_kwh - solar_kwh
                        total_cost += grid_import * price

                # HOME III: Max charge
                elif mode == 2:
                    battery += solar_kwh
                    if battery > max_capacity:
                        grid_export = battery - max_capacity
                        battery = max_capacity
                        total_cost -= grid_export * price
                    # Load from grid
                    grid_import = load_kwh
                    total_cost += grid_import * price

                # HOME UPS: Grid charging allowed
                elif mode == 3:
                    # Nabít baterii z gridu pokud je levné
                    if price < 1.5:  # Threshold for charging
                        charge_amount = min(2.8 / 4.0, max_capacity - battery)
                        if charge_amount > 0:
                            grid_import += charge_amount
                            total_cost += charge_amount * price
                            battery += charge_amount * efficiency

                    # Stejná logika jako HOME I pro FVE
                    if solar_kwh >= load_kwh:
                        surplus = solar_kwh - load_kwh
                        battery += surplus
                        if battery > max_capacity:
                            grid_export = battery - max_capacity
                            battery = max_capacity
                            total_cost -= grid_export * price
                    else:
                        deficit = load_kwh - solar_kwh
                        battery -= deficit / efficiency
                        if battery < 0:
                            extra_import = -battery * efficiency
                            battery = 0
                            grid_import += extra_import
                            total_cost += extra_import * price

                battery = max(0, min(battery, max_capacity))

            return total_cost

        alternatives = {}
        mode_names = {
            0: "HOME I",
            1: "HOME II",
            2: "HOME III",
            3: "HOME UPS",
        }

        for mode, name in mode_names.items():
            cost = simulate_mode(mode)
            delta = cost - optimal_cost_48h
            alternatives[name] = {
                "cost_czk": round(cost, 2),
                "delta_czk": round(delta, 2),
            }

        # Add DO NOTHING (current optimized plan)
        alternatives["DO NOTHING"] = {
            "cost_czk": round(optimal_cost_48h, 2),
            "delta_czk": 0.0,
            "current_mode": "Optimized",
        }

        return alternatives

    def _update_balancing_plan_snapshot(self, plan: Optional[Dict[str, Any]]) -> None:
        """Keep BalancingManager plan snapshot in sync with legacy plan handling."""

        def _is_balancing_requester(requester: Optional[str]) -> bool:
            if not requester:
                return False
            return requester.lower() in {"balancingmanager", "balancing_manager"}

        self._balancing_plan_snapshot = plan

        if plan:
            if not self._active_charging_plan or _is_balancing_requester(
                self._active_charging_plan.get("requester")
            ):
                self._active_charging_plan = plan
        else:
            if self._active_charging_plan and _is_balancing_requester(
                self._active_charging_plan.get("requester")
            ):
                self._active_charging_plan = None

    def _get_total_battery_capacity(self) -> Optional[float]:
        """Získat CELKOVOU kapacitu baterie z API (box_prms.p_bat → kWh).

        Toto je FYZICKÁ celková kapacita baterie (0-100%).
        """
        if not self._hass:
            return None

        # Prefer dedicated sensor (available in both cloud and local mode)
        installed_sensor = f"sensor.oig_{self._box_id}_installed_battery_capacity_kwh"
        installed_state = self._hass.states.get(installed_sensor)
        if installed_state and installed_state.state not in [
            "unknown",
            "unavailable",
            None,
            "",
        ]:
            try:
                # Stored as Wh (Wp) → convert to kWh
                total_kwh = float(installed_state.state) / 1000.0
                if total_kwh > 0:
                    return total_kwh
            except (ValueError, TypeError):
                pass

        # Zkusit získat z PV data (box_prms.p_bat)
        pv_data_sensor = f"sensor.oig_{self._box_id}_pv_data"
        state = self._hass.states.get(pv_data_sensor)

        if state and hasattr(state, "attributes"):
            try:
                pv_data = state.attributes.get("data", {})
                if isinstance(pv_data, dict):
                    p_bat_wp = pv_data.get("box_prms", {}).get("p_bat")
                    if p_bat_wp:
                        total_kwh = float(p_bat_wp) / 1000.0
                        _LOGGER.debug(
                            f"Total battery capacity from API: {p_bat_wp} Wp = {total_kwh:.2f} kWh"
                        )
                        return total_kwh
            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.debug(f"Error reading p_bat from pv_data: {e}")

        # Fallback: vypočítat z usable_battery_capacity (backwards compatibility)
        usable_sensor = f"sensor.oig_{self._box_id}_usable_battery_capacity"
        usable_state = self._hass.states.get(usable_sensor)

        if usable_state and usable_state.state not in ["unknown", "unavailable"]:
            try:
                usable_kwh = float(usable_state.state)
                total_kwh = usable_kwh / 0.8  # Usable je 80% z total
                _LOGGER.debug(
                    f"Total battery capacity from usable: {usable_kwh:.2f} kWh × 1.25 = {total_kwh:.2f} kWh"
                )
                return total_kwh
            except (ValueError, TypeError):
                pass

        self._log_rate_limited(
            "battery_capacity_missing",
            "debug",
            "Battery total capacity not available yet; waiting for sensors",
            cooldown_s=600.0,
        )
        return None

    def _get_current_battery_soc_percent(self) -> Optional[float]:
        """Získat aktuální SoC v % z API (actual.bat_c).

        Toto je SKUTEČNÝ SoC% vůči celkové kapacitě (0-100%).
        """
        if not self._hass:
            return None

        # Hlavní sensor: batt_bat_c (Battery Percent z API)
        soc_sensor = f"sensor.oig_{self._box_id}_batt_bat_c"
        state = self._hass.states.get(soc_sensor)

        if state and state.state not in ["unknown", "unavailable"]:
            try:
                soc_percent = float(state.state)
                _LOGGER.debug(f"Battery SoC from API: {soc_percent:.1f}%")
                return soc_percent
            except (ValueError, TypeError):
                _LOGGER.debug(f"Invalid SoC value: {state.state}")

        self._log_rate_limited(
            "battery_soc_missing",
            "debug",
            "Battery SoC%% not available yet; waiting for sensors",
            cooldown_s=600.0,
        )
        return None

    def _get_current_battery_capacity(self) -> Optional[float]:
        """Získat aktuální kapacitu baterie v kWh.

        NOVÝ VÝPOČET: total_capacity × soc_percent / 100
        (místo remaining_usable_capacity computed sensoru)
        """
        total = self._get_total_battery_capacity()
        soc_percent = self._get_current_battery_soc_percent()
        if total is None or soc_percent is None:
            return None
        current_kwh = total * soc_percent / 100.0

        _LOGGER.debug(
            f"Current battery capacity: {total:.2f} kWh × {soc_percent:.1f}% = {current_kwh:.2f} kWh"
        )
        return current_kwh

    def _get_max_battery_capacity(self) -> Optional[float]:
        """Získat maximální kapacitu baterie (= total capacity).

        DEPRECATED: Kept for backwards compatibility.
        Use _get_total_battery_capacity() instead.
        """
        return self._get_total_battery_capacity()

    def _get_min_battery_capacity(self) -> Optional[float]:
        """Získat minimální kapacitu baterie z config flow.

        NOVÝ VÝPOČET: min_percent × total_capacity
        (místo min_percent × usable_capacity)
        """
        total = self._get_total_battery_capacity()
        if total is None:
            return None

        if self._config_entry:
            min_percent = (
                self._config_entry.options.get("min_capacity_percent")
                if self._config_entry.options
                else self._config_entry.data.get("min_capacity_percent", 33.0)
            )
            if min_percent is None:
                min_percent = 33.0
            min_kwh = total * float(min_percent) / 100.0

            _LOGGER.debug(
                f"Min battery capacity: {min_percent:.0f}% × {total:.2f} kWh = {min_kwh:.2f} kWh "
                f"(source={'options' if self._config_entry.options else 'data'})"
            )
            return min_kwh

        # Default: 33% z total
        return total * 0.33

    def _get_target_battery_capacity(self) -> Optional[float]:
        """Získat cílovou kapacitu baterie z config flow.

        Cílová kapacita (kWh) pro plánovač.
        """
        total = self._get_total_battery_capacity()
        if total is None:
            return None

        if self._config_entry:
            target_percent = (
                self._config_entry.options.get("target_capacity_percent")
                if self._config_entry.options
                else self._config_entry.data.get("target_capacity_percent", 80.0)
            )
            if target_percent is None:
                target_percent = 80.0
            target_kwh = total * float(target_percent) / 100.0

            _LOGGER.debug(
                f"Target battery capacity: {target_percent:.0f}% × {total:.2f} kWh = {target_kwh:.2f} kWh "
                f"(source={'options' if self._config_entry.options else 'data'})"
            )
            return target_kwh

        # Default: 80% z total
        return total * 0.80

    # =========================================================================
    # PHASE 2.9: DAILY PLAN TRACKING - Historie vs Plán
    # =========================================================================

    async def _maybe_fix_daily_plan(self) -> None:  # noqa: C901
        """
        Fixovat denní plán při prvním výpočtu po půlnoci.

        Phase 2.9: Daily Plan Tracking
        - Volá se po HYBRID optimalizaci
        - Kontroluje jestli je nový den
        - Fixuje plán z HYBRID optimalizace pro celý dnešek
        - Ukládá do self._daily_plan_state pro pozdější tracking

        Phase 3.0: Storage Helper Integration
        - Po půlnoci (00:10-00:30): Vytvoř baseline plán do Storage Helper
        - Baseline = 96 intervalů s plánovanými hodnotami
        - Persists across HA restarts

        Logika:
        1. Je nový den? (plan_date != today)
        2. Máme fresh HYBRID výsledek? (optimal_timeline existuje)
        3. FIXUJ: Ulož celý dnešní plán do daily_plan_state
        4. STORAGE: Ulož baseline do Storage Helper (persistent)
        """
        now = dt_util.now()
        today_str = now.strftime(DATE_FMT)

        # Inicializace state při prvním běhu
        if not hasattr(self, "_daily_plan_state"):
            self._daily_plan_state = None

        # PHASE 3.0: Pokus o vytvoření baseline plánu po půlnoci
        # Spustí se pokud je nový den A čas je mezi 00:10 a 01:00
        if now.hour == 0 and 10 <= now.minute < 60:
            # Check if baseline already exists
            plan_exists = await self._plan_exists_in_storage(today_str)
            if not plan_exists:
                _LOGGER.info(
                    f"⏰ Post-midnight baseline creation window: {now.strftime('%H:%M')}"
                )
                # Attempt to create baseline (will be implemented properly later)
                # For now, just log
                baseline_created = await self._create_baseline_plan(today_str)
                if baseline_created:
                    _LOGGER.info(
                        f"✅ Baseline plan created in Storage Helper for {today_str}"
                    )
                else:
                    _LOGGER.warning(f"⚠️ Failed to create baseline plan for {today_str}")
            else:
                _LOGGER.debug(f"Baseline plan already exists for {today_str}")

        # PHASE 3.0: Storage Helper Integration
        # _maybe_fix_daily_plan() je zodpovědná POUZE za:
        # 1. Vytvoření baseline plánu po půlnoci (00:10-01:00)
        # 2. Fixování dnešního plánu do in-memory state
        #
        # NEPOTŘEBUJEME číst Storage tady - to se děje až v build_timeline_extended()
        # když API endpoint potřebuje data (on-demand loading)

        # Pokud už máme plán v paměti pro dnešek s intervaly, NEPŘEPISOVAT
        if (
            self._daily_plan_state
            and self._daily_plan_state.get("date") == today_str
            and len(self._daily_plan_state.get("plan", [])) > 0
        ):
            _LOGGER.debug(
                f"Daily plan for {today_str} already in memory with {len(self._daily_plan_state['plan'])} intervals, keeping it"
            )
            return

        # Je nový den? NEBO ještě nemáme dnešní plán?
        if (
            self._daily_plan_state is None
            or self._daily_plan_state.get("date") != today_str
        ):
            # Archivovat včerejší plán pokud existuje
            if self._daily_plan_state:
                yesterday_date = self._daily_plan_state.get("date")

                # NOVĚ: Uložit do archivu (max 7 dní)
                self._daily_plans_archive[yesterday_date] = (
                    self._daily_plan_state.copy()
                )

                # Vyčistit staré plány (starší než 7 dní)
                cutoff_date = (now.date() - timedelta(days=7)).strftime(DATE_FMT)
                self._daily_plans_archive = {
                    date: plan
                    for date, plan in self._daily_plans_archive.items()
                    if date >= cutoff_date
                }

                _LOGGER.info(
                    f"📦 Archived daily plan for {yesterday_date} "
                    f"(archive size: {len(self._daily_plans_archive)} days)"
                )

                # PHASE 3.1: Persist archive to storage (pro Unified Cost Tile)
                if self._plans_store:
                    try:
                        storage_data = await self._plans_store.async_load() or {}
                        storage_data["daily_archive"] = self._daily_plans_archive
                        await self._plans_store.async_save(storage_data)
                        _LOGGER.info(
                            f"💾 Saved daily plans archive to storage ({len(self._daily_plans_archive)} days)"
                        )
                    except Exception as e:
                        _LOGGER.error(
                            f"Failed to save daily plans archive: {e}", exc_info=True
                        )

            # Máme výsledek z plánovače?
            if (
                hasattr(self, "_mode_optimization_result")
                and self._mode_optimization_result
            ):
                # Použít _timeline_data pro kompletní timeline (včetně minulých intervalů)
                optimal_timeline = getattr(self, "_timeline_data", [])

                # Fallback na mode_optimization pokud _timeline_data není k dispozici
                if not optimal_timeline:
                    optimal_timeline = self._mode_optimization_result.get(
                        "optimal_timeline", []
                    )

                mode_recommendations = self._mode_optimization_result.get(
                    "mode_recommendations", []
                )

                # Filtrovat jen dnešní intervaly (00:00 - 23:45)
                today_start = datetime.combine(now.date(), datetime.min.time())
                today_start = dt_util.as_local(today_start)  # Timezone-aware
                today_end = datetime.combine(now.date(), datetime.max.time())
                today_end = dt_util.as_local(today_end)  # Timezone-aware

                today_timeline = []
                for interval in optimal_timeline:
                    if not interval.get("time"):
                        continue
                    try:
                        interval_time = datetime.fromisoformat(interval["time"])
                        if interval_time.tzinfo is None:
                            interval_time = dt_util.as_local(interval_time)
                        if today_start <= interval_time <= today_end:
                            today_timeline.append(interval)
                    except Exception:
                        continue

                today_blocks = []
                for block in mode_recommendations:
                    if not block.get("from_time"):
                        continue
                    try:
                        block_time = datetime.fromisoformat(block["from_time"])
                        if block_time.tzinfo is None:
                            block_time = dt_util.as_local(block_time)
                        if today_start <= block_time <= today_end:
                            today_blocks.append(block)
                    except Exception:
                        continue

                expected_total_cost = sum(i.get("net_cost", 0) for i in today_timeline)

                # ========================================
                # MEMORY STORAGE: Store plan in memory (NOT in files!)
                # Storage Helper je ONLY pro baseline plány po půlnoci
                # ========================================

                # Build plan intervals z today_timeline
                plan_intervals = []
                for interval in today_timeline:
                    plan_intervals.append(
                        {
                            "time": interval.get("timestamp"),
                            "solar_kwh": round(interval.get("solar_kwh", 0), 4),
                            "consumption_kwh": round(interval.get("load_kwh", 0), 4),
                            "battery_soc": round(interval.get("battery_soc", 0), 2),
                            "battery_capacity_kwh": round(
                                interval.get("battery_capacity_kwh", 0), 2
                            ),
                            "grid_import_kwh": round(interval.get("grid_import", 0), 4),
                            "grid_export_kwh": round(interval.get("grid_export", 0), 4),
                            "mode": interval.get("mode", 0),
                            "mode_name": interval.get("mode_name", "N/A"),
                            "spot_price": round(interval.get("spot_price", 0), 2),
                            "net_cost": round(interval.get("net_cost", 0), 2),
                        }
                    )

                # Zachovat existing actual data pokud fixujeme během dne
                existing_actual = []
                if (
                    hasattr(self, "_daily_plan_state")
                    and self._daily_plan_state
                    and self._daily_plan_state.get("date") == today_str
                ):
                    existing_actual = self._daily_plan_state.get("actual", [])
                    _LOGGER.debug(
                        f"[Fix Plan] Preserving {len(existing_actual)} existing actual intervals"
                    )

                # SIMPLE struktura (memory only!)
                self._daily_plan_state = {
                    "date": today_str,
                    "created_at": now.isoformat(),
                    "plan": plan_intervals,  # Plán intervalů pro celý dnešní den
                    "actual": existing_actual,  # Postupně se bude plnit každých 15 min
                }

                _LOGGER.info(
                    f"🎯 Fixed daily plan for {today_str}: "
                    f"{len(plan_intervals)} plan intervals, "
                    f"{len(existing_actual)} existing actual intervals, "
                    f"expected_cost={expected_total_cost:.2f} Kč"
                )

                # NO FILE SAVE - keep in memory only!
                # Storage Helper je ONLY pro baseline plány (po půlnoci)
            else:
                _LOGGER.warning(
                    f"No HYBRID optimization result available to fix daily plan for {today_str}"
                )
                # Vytvořit prázdný stav
                self._daily_plan_state = {
                    "date": today_str,
                    "created_at": now.isoformat(),
                    "plan": [],
                    "actual": [],
                }

    async def _fetch_interval_from_history(  # noqa: C901
        self, start_time: datetime, end_time: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Načíst actual data pro jeden 15min interval z HA history.

        Args:
            start_time: Začátek intervalu (timezone-aware)
            end_time: Konec intervalu (timezone-aware)

        Returns:
            Dict s actual hodnotami nebo None pokud data nejsou k dispozici
        """
        if not self._hass:
            _LOGGER.debug("[fetch_interval_from_history] No _hass instance")
            return None

        # Avoid per-interval spam in HA logs (even at DEBUG).
        self._log_rate_limited(
            "fetch_interval_range",
            "debug",
            "[fetch_interval_from_history] Fetching sample interval %s - %s",
            start_time,
            end_time,
            cooldown_s=900.0,
        )

        try:
            from homeassistant.components.recorder.history import get_significant_states

            # Senzory které potřebujeme
            entity_ids = [
                f"sensor.oig_{self._box_id}_ac_out_en_day",  # Spotřeba [Wh kumulativně]
                f"sensor.oig_{self._box_id}_ac_in_ac_ad",  # Grid import [Wh kumulativně]
                f"sensor.oig_{self._box_id}_ac_in_ac_pd",  # Grid export [Wh kumulativně]
                f"sensor.oig_{self._box_id}_dc_in_fv_ad",  # Solar [Wh kumulativně]
                f"sensor.oig_{self._box_id}_batt_bat_c",  # Baterie [%] - OPRAVENO: správný název senzoru
                f"sensor.oig_{self._box_id}_box_prms_mode",  # Režim střídače (box_prms_mode)
                f"sensor.oig_{self._box_id}_spot_price_current_15min",  # Import spot price [Kč/kWh]
                f"sensor.oig_{self._box_id}_export_price_current_15min",  # Export price [Kč/kWh]
            ]

            # Načíst historii
            from homeassistant.components.recorder import get_instance

            states = await get_instance(self._hass).async_add_executor_job(
                get_significant_states,
                self._hass,
                start_time,
                end_time,
                entity_ids,
                None,  # filters
                True,  # include_start_time_state
            )

            if not states:
                return None

            # Extrahovat hodnoty na ZAČÁTKU a KONCI intervalu
            def get_delta(entity_id: str) -> float:
                """Získat delta (konec - začátek) pro kumulativní senzor."""
                entity_states = states.get(entity_id, [])
                if not entity_states:
                    return 0.0

                # Normalizovat interval na UTC pro porovnání
                # (states.last_updated jsou v UTC, start_time/end_time mohou být v lokálním čase)
                start_utc = (
                    start_time.astimezone(timezone.utc)
                    if start_time.tzinfo
                    else start_time
                )
                end_utc = (
                    end_time.astimezone(timezone.utc) if end_time.tzinfo else end_time
                )

                # Filtrovat states uvnitř intervalu [start_time, end_time]
                interval_states = [
                    s
                    for s in entity_states
                    if start_utc <= s.last_updated.astimezone(timezone.utc) <= end_utc
                ]

                # Pokud nejsou žádné states v intervalu, najdi nejbližší před a po
                if not interval_states:
                    # Najdi poslední state PŘED intervalem
                    before_states = [
                        s
                        for s in entity_states
                        if s.last_updated.astimezone(timezone.utc) < start_utc
                    ]
                    # Najdi první state PO intervalu
                    after_states = [
                        s
                        for s in entity_states
                        if s.last_updated.astimezone(timezone.utc) > end_utc
                    ]

                    # Pokud máme oba, použij je pro aproximaci
                    if before_states and after_states:
                        interval_states = [before_states[-1], after_states[0]]
                    else:
                        # Jinak vrať 0 (není dost dat pro výpočet)
                        return 0.0

                if len(interval_states) < 2:
                    return 0.0

                try:
                    start_val = float(interval_states[0].state)
                    end_val = float(interval_states[-1].state)
                    delta_wh = end_val - start_val

                    # Reset check (denní kumulativní senzory se resetují o půlnoci)
                    if delta_wh < 0:
                        delta_wh = end_val

                    return delta_wh / 1000.0  # Wh → kWh
                except (ValueError, AttributeError):
                    return 0.0

            def get_value_at_end(entity_id: str) -> Any:
                """
                Získat hodnotu NA KONCI intervalu (= end_time).

                Pro battery_soc a mode je důležité mít hodnotu přesně NA KONCI intervalu,
                aby byla sladěná s planned hodnotami (které reprezentují stav NA KONCI).

                Hledáme state CO NEJBLÍŽE end_time, ne prostě poslední v seznamu!
                """
                entity_states = states.get(entity_id, [])
                if not entity_states:
                    return None

                # Normalizovat end_time na UTC
                end_utc = (
                    end_time.astimezone(timezone.utc) if end_time.tzinfo else end_time
                )

                # Najít state s časem NEJBLÍŽE end_time (může být před i po)
                closest_state = min(
                    entity_states,
                    key=lambda s: abs(
                        (
                            s.last_updated.astimezone(timezone.utc) - end_utc
                        ).total_seconds()
                    ),
                )

                try:
                    return float(closest_state.state)
                except (ValueError, AttributeError):
                    return None

            def get_last_value(entity_id: str) -> Any:
                """Získat poslední hodnotu pro snapshot senzor (ceny)."""
                entity_states = states.get(entity_id, [])
                if not entity_states:
                    return None
                try:
                    return float(entity_states[-1].state)
                except (ValueError, AttributeError):
                    return None

            # Vypočítat actual values
            consumption_kwh = get_delta(f"sensor.oig_{self._box_id}_ac_out_en_day")
            grid_import_kwh = get_delta(f"sensor.oig_{self._box_id}_ac_in_ac_ad")
            grid_export_kwh = get_delta(f"sensor.oig_{self._box_id}_ac_in_ac_pd")
            solar_kwh = get_delta(f"sensor.oig_{self._box_id}_dc_in_fv_ad")

            # OPRAVA: Použít hodnotu NA KONCI intervalu (end_time), ne prostě poslední
            battery_soc = get_value_at_end(f"sensor.oig_{self._box_id}_batt_bat_c")
            mode_raw = get_value_at_end(f"sensor.oig_{self._box_id}_box_prms_mode")

            # Vypočítat battery_kwh z SOC
            battery_kwh = 0.0
            if battery_soc is not None:
                total_capacity = self._get_total_battery_capacity() or 0.0
                if total_capacity > 0:
                    battery_kwh = (battery_soc / 100.0) * total_capacity

            # Načíst spot price a export price pro tento interval (z history)
            spot_price = (
                get_last_value(f"sensor.oig_{self._box_id}_spot_price_current_15min")
                or 0.0
            )
            export_price = (
                get_last_value(f"sensor.oig_{self._box_id}_export_price_current_15min")
                or 0.0
            )

            # Spočítat net_cost
            import_cost = grid_import_kwh * spot_price
            export_revenue = grid_export_kwh * export_price
            net_cost = import_cost - export_revenue

            # Převést mode z textové hodnoty na int
            # box_prms_mode vrací "Home 1", "Home 3", "Home UPS" atd.
            mode = 0  # Default HOME I
            if mode_raw is not None:
                mode_str = str(mode_raw).strip()
                # Mapování textových hodnot na mode ID
                if SERVICE_MODE_HOME_1 in mode_str or "HOME I" in mode_str:
                    mode = 0
                elif SERVICE_MODE_HOME_3 in mode_str or "HOME III" in mode_str:
                    mode = 2
                elif "UPS" in mode_str or SERVICE_MODE_HOME_UPS in mode_str:
                    mode = 3
                elif SERVICE_MODE_HOME_2 in mode_str or "HOME II" in mode_str:
                    mode = 1

            mode_name = CBB_MODE_NAMES.get(mode, "HOME I")

            result = {
                "battery_kwh": round(battery_kwh, 2),
                "battery_soc": (
                    round(battery_soc, 1) if battery_soc is not None else 0.0
                ),
                "mode": mode,
                "mode_name": mode_name,
                "solar_kwh": round(solar_kwh, 3),
                "consumption_kwh": round(consumption_kwh, 3),
                "grid_import": round(grid_import_kwh, 3),
                "grid_export": round(grid_export_kwh, 3),
                "spot_price": round(spot_price, 2),
                "export_price": round(export_price, 2),
                "net_cost": round(net_cost, 2),
            }

            self._log_rate_limited(
                "fetch_interval_sample",
                "debug",
                "[fetch_interval_from_history] sample %s -> soc=%s kwh=%.2f cons=%.3f net=%.2f",
                start_time.strftime("%Y-%m-%d %H:%M"),
                battery_soc,
                battery_kwh,
                result["consumption_kwh"],
                result["net_cost"],
                cooldown_s=900.0,
            )

            return result

        except Exception as e:
            _LOGGER.warning(f"Failed to fetch history for {start_time}: {e}")
            return None

    async def _update_actual_from_history(self) -> None:
        """
        Načíst actual values z HA history pro dnešní den.

        OPTIMALIZOVANÁ verze:
        - Načte jen CHYBĚJÍCÍ 15min intervaly (ne všechny od půlnoci!)
        - Doplní je do existing "actual" array
        - Žádné nested struktury, žádné delta - jen čistá actual data
        """
        now = dt_util.now()
        today_str = now.strftime(DATE_FMT)

        # Načíst existing plan z Storage Helper (FAST)
        # PHASE 3.0: Use Storage Helper instead of file I/O
        plan_storage = await self._load_plan_from_storage(today_str)
        if not plan_storage:
            _LOGGER.debug(
                f"No plan in Storage for {today_str}, skipping history update"
            )
            return

        # Convert to daily_plan_state format
        plan_data = {
            "date": today_str,
            "plan": plan_storage.get("intervals", []),
            "actual": [],  # Will be filled/overwritten below
        }

        if not plan_data:
            _LOGGER.debug(f"No plan for {today_str}, skipping actual update")
            return

        existing_actual: List[Dict[str, Any]] = []
        if self._daily_plan_state and self._daily_plan_state.get("date") == today_str:
            existing_actual = copy.deepcopy(self._daily_plan_state.get("actual", []))
            plan_data["actual"] = existing_actual
        else:
            existing_actual = plan_data.get("actual", [])

        _LOGGER.info(f"📊 Updating actual values from history for {today_str}...")

        # Doplň chybějící net_cost do existujících intervalů (zpětná kompatibilita)
        patched_existing: List[Dict[str, Any]] = []
        for interval in existing_actual:
            if interval.get("net_cost") is not None:
                patched_existing.append(interval)
                continue
            ts = interval.get("time")
            if not ts:
                patched_existing.append(interval)
                continue
            start_dt = dt_util.parse_datetime(ts)
            if start_dt is None:
                try:
                    start_dt = datetime.fromisoformat(ts)
                except Exception:
                    start_dt = None
            if start_dt is None:
                patched_existing.append(interval)
                continue
            if start_dt.tzinfo is None:
                start_dt = dt_util.as_local(start_dt)
            interval_end = start_dt + timedelta(minutes=15)
            historical_patch = await self._fetch_interval_from_history(
                start_dt, interval_end
            )
            if historical_patch:
                interval = {
                    **interval,
                    "net_cost": round(historical_patch.get("net_cost", 0), 2),
                    "spot_price": round(historical_patch.get("spot_price", 0), 2),
                    "export_price": round(historical_patch.get("export_price", 0), 2),
                }
            patched_existing.append(interval)
        existing_actual = patched_existing
        plan_data["actual"] = existing_actual

        # Vytvořit set existujících časů pro rychlé vyhledávání
        existing_times = {interval.get("time") for interval in existing_actual}

        _LOGGER.debug(f"Found {len(existing_actual)} existing actual intervals")

        # Najít chybějící intervaly od půlnoci do teď
        start_time = dt_util.start_of_local_day(now)
        current_time = start_time
        new_intervals = []

        while current_time <= now:
            interval_time_str = current_time.isoformat()

            # Přeskočit pokud už existuje
            if interval_time_str in existing_times:
                current_time += timedelta(minutes=15)
                continue

            # Načíst z historie - JEN CHYBĚJÍCÍ INTERVAL
            actual_data = await self._fetch_interval_from_history(
                current_time, current_time + timedelta(minutes=15)
            )

            if actual_data:
                new_intervals.append(
                    {
                        "time": interval_time_str,
                        "solar_kwh": round(actual_data.get("solar_kwh", 0), 4),
                        "consumption_kwh": round(
                            actual_data.get("consumption_kwh", 0), 4
                        ),
                        "battery_soc": round(actual_data.get("battery_soc", 0), 2),
                        "battery_capacity_kwh": round(
                            actual_data.get("battery_capacity_kwh", 0), 2
                        ),
                        "grid_import_kwh": round(actual_data.get("grid_import", 0), 4),
                        "grid_export_kwh": round(actual_data.get("grid_export", 0), 4),
                        "net_cost": round(actual_data.get("net_cost", 0), 2),
                        "spot_price": round(actual_data.get("spot_price", 0), 2),
                        "export_price": round(actual_data.get("export_price", 0), 2),
                        "mode": actual_data.get("mode", 0),
                        "mode_name": actual_data.get("mode_name", "N/A"),
                    }
                )

            current_time += timedelta(minutes=15)

        # DOPLNIT nové intervaly k existujícím (ne přepsat!)
        if new_intervals:
            plan_data["actual"] = existing_actual + new_intervals
            _LOGGER.info(
                f"✅ Added {len(new_intervals)} new actual intervals (total: {len(plan_data['actual'])})"
            )
        else:
            _LOGGER.debug("No new actual intervals to add")

        # Update in-memory state pouze pokud byly přidány nové intervaly
        if new_intervals:
            self._daily_plan_state = plan_data
        else:
            _LOGGER.debug("No changes, skipping storage update")

    # ========================================================================
    # PHASE 3.0: STORAGE HELPER METHODS - Persistent Battery Plans
    # ========================================================================
    # Storage structure:
    # {
    #   "detailed": {
    #     "2025-11-06": {
    #       "created_at": "2025-11-06T00:15:00+01:00",
    #       "baseline": true,
    #       "filled_intervals": null,
    #       "intervals": [...]  # 96 intervals
    #     }
    #   },
    #   "daily": {
    #     "2025-11-05": {"planned": {...}}  # Daily aggregates
    #   },
    #   "weekly": {
    #     "2025-W45": {"planned": {...}}  # Weekly aggregates
    #   }
    # }

    async def _load_plan_from_storage(self, date_str: str) -> Optional[Dict[str, Any]]:
        """
        Load plan from Storage Helper for given date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Plan data with 96 intervals or None if not found

        Example:
            plan = await self._load_plan_from_storage("2025-11-06")
            if plan:
                intervals = plan.get("intervals", [])  # 96 intervals
        """
        if not self._plans_store:
            _LOGGER.error("Storage Helper not initialized")
            # Fallback: Check in-memory cache
            if hasattr(self, "_in_memory_plan_cache"):
                cached = self._in_memory_plan_cache.get(date_str)
                if cached:
                    _LOGGER.warning(
                        f"Using in-memory cached plan for {date_str} "
                        f"(Storage Helper not initialized)"
                    )
                    return cached
            return None

        try:
            # Load entire storage
            data = await self._plans_store.async_load()
            if not data:
                _LOGGER.debug("No storage data found")
                # Fallback: Check in-memory cache
                if hasattr(self, "_in_memory_plan_cache"):
                    cached = self._in_memory_plan_cache.get(date_str)
                    if cached:
                        _LOGGER.warning(
                            f"Using in-memory cached plan for {date_str} "
                            f"(Storage empty)"
                        )
                        return cached
                return None

            # Get detailed plan for date
            detailed = data.get("detailed", {})
            plan = detailed.get(date_str)

            if plan:
                interval_count = len(plan.get("intervals", []))
                _LOGGER.debug(
                    f"📂 Loaded plan from Storage: date={date_str}, "
                    f"intervals={interval_count}, baseline={plan.get('baseline')}"
                )
            else:
                _LOGGER.debug(f"No plan found in Storage for {date_str}")
                # Fallback: Check in-memory cache
                if hasattr(self, "_in_memory_plan_cache"):
                    cached = self._in_memory_plan_cache.get(date_str)
                    if cached:
                        _LOGGER.warning(
                            f"Using in-memory cached plan for {date_str} "
                            f"(not in Storage)"
                        )
                        return cached

            return plan

        except Exception as e:
            _LOGGER.error(f"Error loading plan from Storage: {e}", exc_info=True)
            # Fallback: Check in-memory cache
            if hasattr(self, "_in_memory_plan_cache"):
                cached = self._in_memory_plan_cache.get(date_str)
                if cached:
                    _LOGGER.warning(
                        f"Using in-memory cached plan for {date_str} "
                        f"(Storage error)"
                    )
                    return cached
            return None

    async def _save_plan_to_storage(
        self,
        date_str: str,
        intervals: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Save plan to Storage Helper.

        Args:
            date_str: Date in YYYY-MM-DD format
            intervals: List of 96 intervals with planned values
            metadata: Optional metadata (baseline, filled_intervals, etc.)

        Returns:
            True if saved successfully

        Example:
            success = await self._save_plan_to_storage(
                "2025-11-06",
                intervals,
                {"baseline": True, "filled_intervals": "00:00-06:00"}
            )
        """
        if not self._plans_store:
            _LOGGER.error("Storage Helper not initialized")
            return False

        try:
            # Load current data
            data = await self._plans_store.async_load() or {}

            # Ensure structure
            if "detailed" not in data:
                data["detailed"] = {}
            if "daily" not in data:
                data["daily"] = {}
            if "weekly" not in data:
                data["weekly"] = {}

            # Build plan object
            plan = {
                "created_at": dt_util.now().isoformat(),
                "baseline": metadata.get("baseline", False) if metadata else False,
                "filled_intervals": (
                    metadata.get("filled_intervals") if metadata else None
                ),
                "intervals": intervals,
            }

            # Save to detailed
            data["detailed"][date_str] = plan

            # Save to storage (atomic write)
            await self._plans_store.async_save(data)

            _LOGGER.info(
                f"💾 Saved plan to Storage: date={date_str}, "
                f"intervals={len(intervals)}, baseline={plan['baseline']}"
            )
            return True

        except Exception as e:
            _LOGGER.error(f"Error saving plan to Storage: {e}", exc_info=True)

            # PHASE 3.0: Graceful degradation - fallback to in-memory cache
            if not hasattr(self, "_in_memory_plan_cache"):
                self._in_memory_plan_cache = {}

            # Store in memory as fallback
            self._in_memory_plan_cache[date_str] = {
                "created_at": dt_util.now().isoformat(),
                "baseline": metadata.get("baseline", False) if metadata else False,
                "filled_intervals": (
                    metadata.get("filled_intervals") if metadata else None
                ),
                "intervals": intervals,
            }

            _LOGGER.warning(
                f"⚠️ Stored plan in memory cache (Storage failed): "
                f"date={date_str}, intervals={len(intervals)}"
            )

            # Schedule retry in 5 minutes
            if self._hass:
                from homeassistant.helpers.event import async_call_later

                async def retry_save(now):
                    """Retry saving to Storage."""
                    _LOGGER.info(f"Retrying Storage save for {date_str}...")
                    cached_plan = self._in_memory_plan_cache.get(date_str)
                    if cached_plan:
                        success = await self._save_plan_to_storage(
                            date_str,
                            cached_plan["intervals"],
                            {
                                "baseline": cached_plan["baseline"],
                                "filled_intervals": cached_plan["filled_intervals"],
                            },
                        )
                        if success:
                            _LOGGER.info(f"✅ Retry successful for {date_str}")
                            # Remove from memory cache
                            del self._in_memory_plan_cache[date_str]
                        else:
                            _LOGGER.warning(f"Retry failed for {date_str}")

                async_call_later(self._hass, 300, retry_save)  # 5 minutes

            # Send persistent notification to user
            if self._hass:
                self._hass.components.persistent_notification.create(
                    f"Battery plan storage failed for {date_str}. "
                    f"Data is cached in memory only (will be lost on restart). "
                    f"Check disk space and permissions.",
                    title="OIG Cloud Storage Warning",
                    notification_id=f"oig_storage_fail_{date_str}",
                )

            # Return False to indicate storage failure (but data is cached)
            return False

    async def _plan_exists_in_storage(self, date_str: str) -> bool:
        """
        Check if plan exists in Storage for given date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            True if plan exists
        """
        if not self._plans_store:
            return False

        try:
            data = await self._plans_store.async_load()
            if not data:
                return False

            detailed = data.get("detailed", {})
            exists = date_str in detailed

            _LOGGER.debug(f"Plan existence check: date={date_str}, exists={exists}")
            return exists

        except Exception as e:
            _LOGGER.error(f"Error checking plan existence: {e}", exc_info=True)
            return False

    def _is_baseline_plan_invalid(self, plan: Optional[Dict[str, Any]]) -> bool:
        if not plan:
            return True

        intervals = plan.get("intervals") or []
        if len(intervals) < 90:
            return True

        filled_intervals = str(plan.get("filled_intervals") or "").strip()
        if filled_intervals in ("00:00-23:45", "00:00-23:59"):
            return True

        nonzero_consumption = sum(
            1
            for interval in intervals
            if abs(float(interval.get("consumption_kwh", 0) or 0)) > 1e-6
        )
        if nonzero_consumption < max(4, len(intervals) // 24):
            return True

        return False

    async def _create_baseline_plan(self, date_str: str) -> bool:
        """
        Create baseline plan for given date.

        This is called after first HYBRID run after midnight (00:15+).

        Process:
        1. Get HYBRID plan (future intervals from NOW onwards)
        2. Fill missing past intervals (00:00 → NOW):
           - Option A (preferred): From Recorder (historical reality)
           - Option B (fallback): Extrapolate from first HYBRID interval
        3. Merge into 96 intervals
        4. Save to Storage with baseline=True

        Args:
            date_str: Date in YYYY-MM-DD format (e.g., "2025-11-06")

        Returns:
            True if baseline created successfully
        """
        if not self._plans_store:
            _LOGGER.error("Cannot create baseline - Storage Helper not initialized")
            return False

        _LOGGER.info(f"🔨 Creating baseline plan for {date_str}")

        try:
            # PHASE 3.0: Real implementation with HYBRID + Recorder

            # 1. Get HYBRID timeline (future intervals from NOW onwards)
            # Use existing _timeline_data if available (set by async_update)
            hybrid_timeline = getattr(self, "_timeline_data", [])

            if not hybrid_timeline:
                fallback_intervals: List[Dict[str, Any]] = []

                if self._plans_store:
                    try:
                        storage_plans = await self._plans_store.async_load() or {}
                        archive_day = (
                            storage_plans.get("daily_archive", {}).get(date_str, {})
                            or {}
                        )
                        if archive_day.get("plan"):
                            fallback_intervals = archive_day.get("plan") or []
                        if not fallback_intervals:
                            detailed_day = storage_plans.get("detailed", {}).get(
                                date_str, {}
                            )
                            if detailed_day.get("intervals"):
                                fallback_intervals = detailed_day.get("intervals") or []
                    except Exception as err:
                        _LOGGER.debug(
                            "Failed to load fallback plans for %s: %s",
                            date_str,
                            err,
                        )

                if (
                    not fallback_intervals
                    and getattr(self, "_daily_plan_state", None)
                    and self._daily_plan_state.get("date") == date_str
                ):
                    fallback_intervals = self._daily_plan_state.get("plan") or []

                if fallback_intervals:
                    fallback_plan = {
                        "intervals": fallback_intervals,
                        "filled_intervals": None,
                    }
                    if not self._is_baseline_plan_invalid(fallback_plan):
                        _LOGGER.info(
                            "Using fallback plan to create baseline for %s",
                            date_str,
                        )
                        return await self._save_plan_to_storage(
                            date_str,
                            fallback_intervals,
                            {"baseline": True, "filled_intervals": None},
                        )

                _LOGGER.warning(
                    "No HYBRID timeline available - cannot create baseline plan"
                )
                return False

            _LOGGER.debug(
                f"Using HYBRID timeline with {len(hybrid_timeline)} intervals"
            )

            # 2. Determine date range for baseline (00:00 - 23:45)
            date_obj = datetime.strptime(date_str, DATE_FMT).date()
            day_start = datetime.combine(date_obj, datetime.min.time())
            day_start = dt_util.as_local(day_start)  # Make timezone-aware

            # 3. Build 96 intervals
            intervals = []
            filled_count = 0
            first_hybrid_time = None

            for i in range(96):
                interval_start = day_start + timedelta(minutes=i * 15)
                interval_time_str = interval_start.strftime("%H:%M")

                # Try to find matching interval in HYBRID timeline
                hybrid_interval = None
                for hi in hybrid_timeline:
                    hi_time_str = hi.get("time") or hi.get("timestamp", "")
                    if not hi_time_str:
                        continue

                    # Parse time (can be HH:MM or ISO format)
                    try:
                        if "T" in hi_time_str:
                            # ISO format
                            hi_dt = datetime.fromisoformat(hi_time_str)
                            if hi_dt.tzinfo is None:
                                hi_dt = dt_util.as_local(hi_dt)
                            hi_time_only = hi_dt.strftime("%H:%M")
                        else:
                            # Just time HH:MM
                            hi_time_only = hi_time_str

                        if hi_time_only == interval_time_str:
                            hybrid_interval = hi
                            if first_hybrid_time is None:
                                first_hybrid_time = interval_time_str
                            break
                    except Exception:
                        continue

                # Build interval
                if hybrid_interval:
                    # Use HYBRID data (planned values)
                    interval = {
                        "time": interval_time_str,
                        "solar_kwh": round(hybrid_interval.get("solar_kwh", 0), 4),
                        "consumption_kwh": round(hybrid_interval.get("load_kwh", 0), 4),
                        "battery_soc": round(
                            hybrid_interval.get("battery_soc", 50.0), 2
                        ),
                        "battery_kwh": round(
                            hybrid_interval.get("battery_capacity_kwh", 7.68), 2
                        ),
                        "grid_import_kwh": round(
                            hybrid_interval.get("grid_import", 0), 4
                        ),
                        "grid_export_kwh": round(
                            hybrid_interval.get("grid_export", 0), 4
                        ),
                        "mode": hybrid_interval.get("mode", 2),
                        "mode_name": hybrid_interval.get("mode_name", "HOME III"),
                        "spot_price": round(hybrid_interval.get("spot_price", 3.45), 2),
                        "net_cost": round(hybrid_interval.get("net_cost", 0), 2),
                    }
                else:
                    # Missing interval - try to fill from Recorder (historical reality)
                    # This happens for intervals before HYBRID started (00:00 → NOW)
                    interval_end = interval_start + timedelta(minutes=15)

                    # Try to fetch from history
                    historical_data = await self._fetch_interval_from_history(
                        interval_start, interval_end
                    )

                    if historical_data:
                        # Use reality as baseline for missing past intervals
                        interval = {
                            "time": interval_time_str,
                            "solar_kwh": round(historical_data.get("solar_kwh", 0), 4),
                            "consumption_kwh": round(
                                historical_data.get("consumption_kwh", 0.065), 4
                            ),
                            "battery_soc": round(
                                historical_data.get("battery_soc", 50.0), 2
                            ),
                            "battery_kwh": round(
                                historical_data.get("battery_kwh", 7.68), 2
                            ),
                            "grid_import_kwh": round(
                                historical_data.get("grid_import_kwh", 0), 4
                            ),
                            "grid_export_kwh": round(
                                historical_data.get("grid_export_kwh", 0), 4
                            ),
                            "mode": historical_data.get("mode", 2),
                            "mode_name": historical_data.get("mode_name", "HOME III"),
                            "spot_price": round(
                                historical_data.get("spot_price", 3.45), 2
                            ),
                            "net_cost": round(historical_data.get("net_cost", 0), 2),
                        }
                        filled_count += 1
                    else:
                        # Fallback: Extrapolate from first HYBRID interval
                        # or use defaults if HYBRID not available yet
                        first_soc = 50.0
                        first_mode = 2
                        first_mode_name = "HOME III"

                        if hybrid_timeline:
                            first_hi = hybrid_timeline[0]
                            first_soc = first_hi.get("battery_soc", 50.0)
                            first_mode = first_hi.get("mode", 2)
                            first_mode_name = first_hi.get("mode_name", "HOME III")

                        interval = {
                            "time": interval_time_str,
                            "solar_kwh": 0.0,
                            "consumption_kwh": 0.065,
                            "battery_soc": round(first_soc, 2),
                            "battery_kwh": round((first_soc / 100.0) * 15.36, 2),
                            "grid_import_kwh": 0.065,
                            "grid_export_kwh": 0.0,
                            "mode": first_mode,
                            "mode_name": first_mode_name,
                            "spot_price": 3.45,
                            "net_cost": 0.22,
                        }
                        filled_count += 1

                intervals.append(interval)

            # Track which intervals were filled
            filled_intervals_str = None
            if filled_count > 0 and first_hybrid_time:
                # Calculate filled range (00:00 → first_hybrid_time)
                filled_intervals_str = f"00:00-{first_hybrid_time}"

            _LOGGER.info(
                f"Baseline plan built: {len(intervals)} intervals, "
                f"{len(intervals) - filled_count} from HYBRID, "
                f"{filled_count} filled from Recorder/extrapolation"
            )

            # Save to storage
            success = await self._save_plan_to_storage(
                date_str,
                intervals,
                {
                    "baseline": True,
                    "filled_intervals": filled_intervals_str,
                },
            )

            if success:
                _LOGGER.info(
                    f"✅ Baseline plan created: date={date_str}, "
                    f"intervals={len(intervals)}, filled={filled_intervals_str}"
                )
            else:
                _LOGGER.error(f"Failed to save baseline plan for {date_str}")

            return success

        except Exception as e:
            _LOGGER.error(
                f"Error creating baseline plan for {date_str}: {e}", exc_info=True
            )
            return False

    async def ensure_plan_exists(self, date_str: str) -> bool:
        """
        Guarantee that a plan exists for given date.

        Phase 3.0: Edge Case - Plan Availability Guarantee

        This is the main entry point for ensuring plan data availability.
        Called by API endpoints and other components that need plan data.

        Strategy:
        1. Check Storage Helper - if exists, done ✅
        2. Check current time:
           - If midnight window (00:10-01:00): Create baseline
           - If retry windows (06:00, 12:00): Create baseline
           - Otherwise: Create emergency baseline
        3. If all fails: Return False (caller must handle gracefully)

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            True if plan exists or was created successfully

        Example:
            if not await self.ensure_plan_exists("2025-11-06"):
                return {"error": "Plan unavailable"}
        """
        # 1. Check if plan already exists
        exists = await self._plan_exists_in_storage(date_str)
        if exists:
            _LOGGER.debug(f"Plan exists for {date_str}")
            return True

        _LOGGER.warning(f"Plan missing for {date_str}, attempting to create...")

        # 2. Determine creation strategy based on current time
        now = dt_util.now()
        today_str = now.strftime(DATE_FMT)

        # Only create plan for today (not future/past dates)
        if date_str != today_str:
            _LOGGER.warning(
                f"Cannot create plan for {date_str} (not today {today_str})"
            )
            return False

        # 3. Scheduled baseline windows
        current_hour = now.hour
        current_minute = now.minute

        # Midnight window (00:10-01:00)
        if current_hour == 0 and 10 <= current_minute < 60:
            _LOGGER.info(f"⏰ Midnight baseline window - creating plan for {date_str}")
            return await self._create_baseline_plan(date_str)

        # Retry windows (06:00-06:10, 12:00-12:10)
        if (current_hour == 6 and current_minute < 10) or (
            current_hour == 12 and current_minute < 10
        ):
            _LOGGER.info(
                f"⏰ Retry window ({current_hour:02d}:{current_minute:02d}) - "
                f"creating plan for {date_str}"
            )
            return await self._create_baseline_plan(date_str)

        # 4. Emergency: Create baseline anytime during the day
        _LOGGER.warning(
            f"🚨 Emergency baseline creation at {now.strftime('%H:%M')} for {date_str}"
        )
        success = await self._create_baseline_plan(date_str)

        if success:
            _LOGGER.info(f"✅ Emergency baseline created for {date_str}")
        else:
            _LOGGER.error(f"❌ Failed to create emergency baseline for {date_str}")

        return success

    # ========================================================================
    # PHASE 3.0: DAILY & WEEKLY AGGREGATION
    # ========================================================================

    async def _aggregate_daily(self, date_str: str) -> bool:
        """
        Aggregate daily plan into daily summary.

        Called every day at 00:05 to summarize YESTERDAY's plan.

        Process:
        1. Load yesterday's detailed plan (96 intervals)
        2. Calculate aggregates:
           - Total: cost, solar, consumption, grid_import, grid_export
           - Average: battery_soc
           - Min/Max: battery_soc
        3. Save to daily section
        4. Delete detailed plan older than 7 days

        Args:
            date_str: Date to aggregate (YYYY-MM-DD), typically yesterday

        Returns:
            True if aggregation successful
        """
        if not self._plans_store:
            _LOGGER.error("Cannot aggregate - Storage Helper not initialized")
            return False

        _LOGGER.info(f"📊 Aggregating daily plan for {date_str}")

        try:
            # 1. Load detailed plan
            plan = await self._load_plan_from_storage(date_str)
            if not plan:
                _LOGGER.warning(
                    f"No detailed plan found for {date_str}, skipping aggregation"
                )
                return False

            intervals = plan.get("intervals", [])
            if not intervals:
                _LOGGER.warning(f"Empty intervals for {date_str}, skipping aggregation")
                return False

            # 2. Calculate aggregates
            total_cost = sum(iv.get("net_cost", 0) for iv in intervals)
            total_solar = sum(iv.get("solar_kwh", 0) for iv in intervals)
            total_consumption = sum(iv.get("consumption_kwh", 0) for iv in intervals)
            total_grid_import = sum(iv.get("grid_import_kwh", 0) for iv in intervals)
            total_grid_export = sum(iv.get("grid_export_kwh", 0) for iv in intervals)

            soc_values = [
                iv.get("battery_soc", 0)
                for iv in intervals
                if iv.get("battery_soc") is not None
            ]
            avg_battery_soc = sum(soc_values) / len(soc_values) if soc_values else 0
            min_battery_soc = min(soc_values) if soc_values else 0
            max_battery_soc = max(soc_values) if soc_values else 0

            daily_aggregate = {
                "planned": {
                    "total_cost": round(total_cost, 2),
                    "total_solar": round(total_solar, 2),
                    "total_consumption": round(total_consumption, 2),
                    "total_grid_import": round(total_grid_import, 2),
                    "total_grid_export": round(total_grid_export, 2),
                    "avg_battery_soc": round(avg_battery_soc, 1),
                    "min_battery_soc": round(min_battery_soc, 1),
                    "max_battery_soc": round(max_battery_soc, 1),
                }
            }

            # 3. Save to Storage
            data = await self._plans_store.async_load() or {}
            if "daily" not in data:
                data["daily"] = {}

            data["daily"][date_str] = daily_aggregate
            await self._plans_store.async_save(data)

            _LOGGER.info(
                f"✅ Daily aggregate saved for {date_str}: "
                f"cost={total_cost:.2f} Kč, solar={total_solar:.2f} kWh, "
                f"consumption={total_consumption:.2f} kWh"
            )

            # 4. Cleanup: Delete detailed plans older than 7 days
            cutoff_date = (
                datetime.strptime(date_str, DATE_FMT).date() - timedelta(days=7)
            ).strftime(DATE_FMT)

            detailed = data.get("detailed", {})
            dates_to_delete = [d for d in detailed.keys() if d < cutoff_date]

            if dates_to_delete:
                for old_date in dates_to_delete:
                    del data["detailed"][old_date]
                    _LOGGER.debug(
                        f"🗑️ Deleted detailed plan for {old_date} (>7 days old)"
                    )

                await self._plans_store.async_save(data)
                _LOGGER.info(f"Cleaned up {len(dates_to_delete)} old detailed plans")

            return True

        except Exception as e:
            _LOGGER.error(
                f"Error aggregating daily plan for {date_str}: {e}", exc_info=True
            )
            return False

    async def _aggregate_weekly(
        self, week_str: str, start_date: str, end_date: str
    ) -> bool:
        """
        Aggregate weekly plan into weekly summary.

        Called every Sunday at 23:55 to summarize last week's daily plans.

        Process:
        1. Load daily plans for Mon-Sun (7 days)
        2. Calculate weekly totals (sum of daily totals)
        3. Save to weekly section
        4. Delete daily plans older than 30 days
        5. Delete weekly plans older than 52 weeks

        Args:
            week_str: Week identifier (e.g., "2025-W45")
            start_date: Week start date (YYYY-MM-DD), Monday
            end_date: Week end date (YYYY-MM-DD), Sunday

        Returns:
            True if aggregation successful
        """
        if not self._plans_store:
            _LOGGER.error("Cannot aggregate - Storage Helper not initialized")
            return False

        _LOGGER.info(
            f"📊 Aggregating weekly plan for {week_str} ({start_date} to {end_date})"
        )

        try:
            # 1. Load daily plans for the week
            data = await self._plans_store.async_load() or {}
            daily_plans = data.get("daily", {})

            # Get all days in week range
            start = datetime.strptime(start_date, DATE_FMT).date()
            end = datetime.strptime(end_date, DATE_FMT).date()

            week_days = []
            current = start
            while current <= end:
                day_str = current.strftime(DATE_FMT)
                if day_str in daily_plans:
                    week_days.append(daily_plans[day_str])
                current += timedelta(days=1)

            if not week_days:
                _LOGGER.warning(
                    f"No daily plans found for {week_str}, skipping aggregation"
                )
                return False

            # 2. Calculate weekly totals - PHASE 3.0 FIX: Use safe_nested_get
            total_cost = sum(
                safe_nested_get(day, "planned", "total_cost", default=0)
                for day in week_days
            )
            total_solar = sum(
                safe_nested_get(day, "planned", "total_solar", default=0)
                for day in week_days
            )
            total_consumption = sum(
                safe_nested_get(day, "planned", "total_consumption", default=0)
                for day in week_days
            )
            total_grid_import = sum(
                safe_nested_get(day, "planned", "total_grid_import", default=0)
                for day in week_days
            )
            total_grid_export = sum(
                safe_nested_get(day, "planned", "total_grid_export", default=0)
                for day in week_days
            )

            weekly_aggregate = {
                "start_date": start_date,
                "end_date": end_date,
                "days_count": len(week_days),
                "planned": {
                    "total_cost": round(total_cost, 2),
                    "total_solar": round(total_solar, 2),
                    "total_consumption": round(total_consumption, 2),
                    "total_grid_import": round(total_grid_import, 2),
                    "total_grid_export": round(total_grid_export, 2),
                },
            }

            # 3. Save to Storage
            if "weekly" not in data:
                data["weekly"] = {}

            data["weekly"][week_str] = weekly_aggregate
            await self._plans_store.async_save(data)

            _LOGGER.info(
                f"✅ Weekly aggregate saved for {week_str}: "
                f"cost={total_cost:.2f} Kč, solar={total_solar:.2f} kWh, "
                f"{len(week_days)} days"
            )

            # 4. Cleanup: Delete daily plans older than 30 days
            cutoff_daily = (
                datetime.strptime(end_date, DATE_FMT).date() - timedelta(days=30)
            ).strftime(DATE_FMT)

            daily_to_delete = [d for d in daily_plans.keys() if d < cutoff_daily]

            if daily_to_delete:
                for old_date in daily_to_delete:
                    del data["daily"][old_date]
                    _LOGGER.debug(f"🗑️ Deleted daily plan for {old_date} (>30 days old)")

                _LOGGER.info(f"Cleaned up {len(daily_to_delete)} old daily plans")

            # 5. Cleanup: Delete weekly plans older than 52 weeks
            weekly_plans = data.get("weekly", {})

            # Parse week numbers and delete old ones
            current_year_week = datetime.now().isocalendar()[:2]  # (year, week)
            cutoff_week_number = current_year_week[1] - 52
            cutoff_year = (
                current_year_week[0]
                if cutoff_week_number > 0
                else current_year_week[0] - 1
            )

            weekly_to_delete = []
            for week_key in weekly_plans.keys():
                try:
                    # Parse "2025-W45" format
                    year, week = week_key.split("-W")
                    year, week = int(year), int(week)

                    # Simple check: if year is older or (same year but week older)
                    if year < cutoff_year or (
                        year == cutoff_year and week < cutoff_week_number
                    ):
                        weekly_to_delete.append(week_key)
                except Exception:
                    continue

            if weekly_to_delete:
                for old_week in weekly_to_delete:
                    del data["weekly"][old_week]
                    _LOGGER.debug(
                        f"🗑️ Deleted weekly plan for {old_week} (>52 weeks old)"
                    )

                _LOGGER.info(f"Cleaned up {len(weekly_to_delete)} old weekly plans")

            # Save cleanup changes
            if daily_to_delete or weekly_to_delete:
                await self._plans_store.async_save(data)

            return True

        except Exception as e:
            _LOGGER.error(
                f"Error aggregating weekly plan for {week_str}: {e}", exc_info=True
            )
            return False

    async def _precompute_ui_data(self) -> None:
        """
        Precompute UI data (detail_tabs + unified_cost_tile) and save to storage.

        PHASE 3.5: Performance Optimization
        - Called every 15 min after forecast update
        - Saves precomputed data to ~/.storage/oig_cloud_precomputed_data_{box_id}.json
        - API endpoints read from storage → instant response (< 100ms)
        - Eliminates 4s wait time for build_detail_tabs() + build_unified_cost_tile()
        """
        if not self._precomputed_store:
            _LOGGER.warning("⚠️ Precomputed storage not initialized, skipping")
            return

        try:
            _LOGGER.info("📊 Precomputing UI data for instant API responses...")
            start_time = dt_util.now()

            detail_tabs: Dict[str, Any] = {}
            try:
                detail_tabs = await self.build_detail_tabs(plan="active")
            except Exception as err:
                _LOGGER.error("Failed to build detail_tabs: %s", err, exc_info=True)

            unified_cost_tile = await self.build_unified_cost_tile()

            timeline = copy.deepcopy(self._timeline_data or [])

            # Save to storage (single-planner).
            precomputed_data = {
                "detail_tabs": detail_tabs,
                "detail_tabs_hybrid": detail_tabs,  # legacy alias
                "active_planner": "planner",
                "unified_cost_tile": unified_cost_tile,
                "unified_cost_tile_hybrid": unified_cost_tile,  # legacy alias
                "timeline": timeline,
                "timeline_hybrid": timeline,  # legacy alias
                "cost_comparison": {},  # legacy key (dual-planner removed)
                "last_update": dt_util.now().isoformat(),
                "version": 3,  # Single-planner architecture
            }

            await self._precomputed_store.async_save(precomputed_data)
            self._last_precompute_hash = self._data_hash

            if self.hass:
                from homeassistant.helpers.dispatcher import async_dispatcher_send

                signal_name = f"oig_cloud_{self._box_id}_forecast_updated"
                async_dispatcher_send(self.hass, signal_name)

            duration = (dt_util.now() - start_time).total_seconds()
            plan_cost = unified_cost_tile.get("today", {}).get("plan_total_cost") or 0.0
            _LOGGER.info(
                "✅ Precomputed UI data saved in %.2fs (blocks=%s, cost=%.2f Kč)",
                duration,
                len(detail_tabs.get("today", {}).get("mode_blocks", [])),
                float(plan_cost),
            )

        except Exception as e:
            _LOGGER.error(f"Failed to precompute UI data: {e}", exc_info=True)
        finally:
            self._last_precompute_at = dt_util.now()

    def _schedule_precompute(self, force: bool = False) -> None:
        """Schedule precompute job with throttling."""
        if not self.hass or not self._precomputed_store:
            return

        now = dt_util.now()
        if (
            not force
            and self._last_precompute_at
            and (now - self._last_precompute_at) < self._precompute_interval
        ):
            _LOGGER.debug(
                "[Precompute] Skipping (last run %ss ago)",
                (now - self._last_precompute_at).total_seconds(),
            )
            return

        if self._precompute_task and not self._precompute_task.done():
            _LOGGER.debug("[Precompute] Job already running, skipping")
            return

        async def _runner():
            try:
                await self._precompute_ui_data()
            except Exception as err:  # pragma: no cover - logged inside
                _LOGGER.error("[Precompute] Job failed: %s", err, exc_info=True)
            finally:
                self._precompute_task = None

        self._precompute_task = self.hass.async_create_task(_runner())

    def _aggregate_cost_by_day(
        self, timeline: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Aggregate planned cost by day."""

        day_costs: Dict[str, float] = {}
        for interval in timeline:
            ts = interval.get("time")
            if not ts:
                continue
            try:
                day = datetime.fromisoformat(ts).date().isoformat()
            except Exception:
                continue
            day_costs.setdefault(day, 0.0)
            day_costs[day] += interval.get("net_cost", 0.0)
        return day_costs

    def _get_day_cost_from_timeline(
        self, timeline: List[Dict[str, Any]], target_day: date
    ) -> Optional[float]:
        """Sum net_cost for specific date."""

        if not timeline:
            return None

        total = 0.0
        found = False
        for interval in timeline:
            ts = interval.get("time")
            if not ts:
                continue
            try:
                interval_day = datetime.fromisoformat(ts).date()
            except Exception:
                continue
            if interval_day == target_day:
                total += interval.get("net_cost", 0.0)
                found = True
        return total if found else None

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
        now = dt_util.now()
        today = now.date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        # PHASE 3.0: Load Storage Helper data JEDNOU pro všechny dny
        storage_plans = {}
        if self._plans_store:
            try:
                storage_plans = await self._plans_store.async_load() or {}
                _LOGGER.debug(
                    f"📦 Loaded Storage Helper data for timeline building: "
                    f"{len(storage_plans.get('detailed', {}))} days"
                )
            except Exception as e:
                _LOGGER.error(f"Failed to load Storage Helper data: {e}")
                storage_plans = {}

        # Build timelines (pass storage_plans to _build_day_timeline)
        yesterday_data = await self._build_day_timeline(yesterday, storage_plans)
        today_data = await self._build_day_timeline(today, storage_plans)
        tomorrow_data = await self._build_day_timeline(tomorrow, storage_plans)

        # NOVÉ: Build today tile summary pro dlaždici "Dnes - Plnění plánu"
        today_tile_summary = self._build_today_tile_summary(
            today_data.get("intervals", []), now
        )

        return {
            "yesterday": yesterday_data,
            "today": today_data,
            "tomorrow": tomorrow_data,
            "today_tile_summary": today_tile_summary,  # ← NOVÉ pro dlaždici
        }

    async def build_detail_tabs(
        self, tab: Optional[str] = None, plan: str = "hybrid"
    ) -> Dict[str, Any]:
        """
        Build Detail Tabs data (aggregated mode blocks).
        """
        _ = plan  # legacy parameter (dual-planner removed)

        timeline_extended = await self.build_timeline_extended()
        hybrid_tabs = await self._build_hybrid_detail_tabs(
            tab=tab, timeline_extended=timeline_extended
        )

        # Keep output schema compatible with older UI which expects metadata fields.
        return self._decorate_plan_tabs(
            primary_tabs=hybrid_tabs,
            secondary_tabs={},
            primary_plan="hybrid",
            secondary_plan="none",
        )

    async def _build_hybrid_detail_tabs(
        self,
        tab: Optional[str] = None,
        timeline_extended: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Internal helper that builds hybrid detail tabs."""

        if tab is None:
            tabs_to_process = ["yesterday", "today", "tomorrow"]
        elif tab in ["yesterday", "today", "tomorrow"]:
            tabs_to_process = [tab]
        else:
            _LOGGER.warning(f"Invalid tab requested: {tab}, returning all tabs")
            tabs_to_process = ["yesterday", "today", "tomorrow"]

        result: Dict[str, Any] = {}
        if timeline_extended is None:
            timeline_extended = await self.build_timeline_extended()

        for tab_name in tabs_to_process:
            tab_data = timeline_extended.get(tab_name, {})
            intervals = tab_data.get("intervals", [])
            date_str = tab_data.get("date", "")

            if not intervals:
                tab_result = {
                    "date": date_str,
                    "mode_blocks": [],
                    "summary": {
                        "total_cost": 0.0,
                        "overall_adherence": 100,
                        "mode_switches": 0,
                        "metrics": self._default_metrics_summary(),
                    },
                    "intervals": [],
                }
            else:
                mode_blocks = self._build_mode_blocks_for_tab(intervals, tab_name)
                summary = self._calculate_tab_summary(mode_blocks, intervals)
                tab_result = {
                    "date": date_str,
                    "mode_blocks": mode_blocks,
                    "summary": summary,
                    "intervals": intervals,
                }

            result[tab_name] = tab_result

        return result

    def _decorate_plan_tabs(
        self,
        primary_tabs: Dict[str, Any],
        secondary_tabs: Dict[str, Any],
        primary_plan: str,
        secondary_plan: str,
    ) -> Dict[str, Any]:
        """Attach metadata and optional comparison blocks to plan tabs."""

        result: Dict[str, Any] = {}

        for key, tab_data in primary_tabs.items():
            tab_copy = {
                "date": tab_data.get("date"),
                "mode_blocks": copy.deepcopy(tab_data.get("mode_blocks", [])),
                "summary": copy.deepcopy(tab_data.get("summary", {})),
                "intervals": copy.deepcopy(tab_data.get("intervals", [])),
            }

            metadata = tab_data.get("metadata", {}).copy()
            metadata["active_plan"] = primary_plan
            metadata["comparison_plan_available"] = (
                secondary_plan if secondary_tabs.get(key) else None
            )
            tab_copy["metadata"] = metadata

            comparison_source = secondary_tabs.get(key)
            if comparison_source:
                has_current = any(
                    block.get("status") == "current"
                    for block in tab_copy.get("mode_blocks", [])
                )
                if not has_current:
                    comparison_blocks = [
                        block
                        for block in comparison_source.get("mode_blocks", [])
                        if block.get("status") in ("current", "planned")
                    ]
                    if comparison_blocks:
                        tab_copy["comparison"] = {
                            "plan": secondary_plan,
                            "mode_blocks": comparison_blocks,
                        }

            result[key] = tab_copy

        return result

    def _auto_mode_switch_enabled(self) -> bool:
        options = (self._config_entry.options or {}) if self._config_entry else {}
        return bool(options.get(CONF_AUTO_MODE_SWITCH, False))

    def _normalize_service_mode(
        self, mode_value: Optional[Union[str, int]]
    ) -> Optional[str]:
        if mode_value is None:
            return None
        if isinstance(mode_value, int):
            return CBB_MODE_SERVICE_MAP.get(mode_value)

        mode_str = str(mode_value).strip()
        if not mode_str:
            return None
        upper = mode_str.upper()
        # Accept legacy strings used by older UI/APIs.
        legacy_map = {
            "HOME I": SERVICE_MODE_HOME_1,
            "HOME 1": SERVICE_MODE_HOME_1,
            "HOME II": SERVICE_MODE_HOME_2,
            "HOME 2": SERVICE_MODE_HOME_2,
            "HOME III": SERVICE_MODE_HOME_3,
            "HOME 3": SERVICE_MODE_HOME_3,
            "HOME UPS": SERVICE_MODE_HOME_UPS,
        }
        if upper in legacy_map:
            return legacy_map[upper]

        # Attempt to standardize other strings (e.g., Home 1)
        title = mode_str.title()
        if title in legacy_map.values():
            return title

        return None

    def _parse_timeline_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        dt_obj = dt_util.parse_datetime(value)
        if dt_obj is None:
            try:
                dt_obj = datetime.fromisoformat(value)
            except ValueError:
                return None
        if dt_obj.tzinfo is None:
            dt_obj = dt_util.as_local(dt_obj)
        return dt_obj

    def _get_current_box_mode(self) -> Optional[str]:
        if not self._hass:
            return None
        entity_id = f"sensor.oig_{self._box_id}_box_prms_mode"
        state = self._hass.states.get(entity_id)
        if not state or not state.state:
            return None
        normalized = self._normalize_service_mode(state.state)
        return normalized

    def _cancel_auto_switch_schedule(self) -> None:
        if self._auto_switch_handles:
            for unsub in self._auto_switch_handles:
                try:
                    unsub()
                except Exception as err:
                    _LOGGER.debug(f"Failed to cancel scheduled auto switch: {err}")
        self._auto_switch_handles = []
        self._clear_auto_switch_retry()

    def _clear_auto_switch_retry(self) -> None:
        if not self._auto_switch_retry_unsub:
            return
        try:
            self._auto_switch_retry_unsub()
        except Exception as err:
            _LOGGER.debug(f"Failed to cancel delayed auto switch sync: {err}")
        finally:
            self._auto_switch_retry_unsub = None

    def _start_auto_switch_watchdog(self) -> None:
        """Ensure periodic enforcement of planned modes is running."""
        if (
            not self._hass
            or self._auto_switch_watchdog_unsub
            or not self._auto_mode_switch_enabled()
        ):
            return

        if _async_track_time_interval is None:
            _LOGGER.debug(
                "[AutoModeSwitch] async_track_time_interval unavailable; watchdog disabled"
            )
            return

        self._auto_switch_watchdog_unsub = _async_track_time_interval(
            self._hass,
            self._auto_switch_watchdog_tick,
            self._auto_switch_watchdog_interval,
        )
        _LOGGER.debug(
            "[AutoModeSwitch] Watchdog started (interval=%ss)",
            int(self._auto_switch_watchdog_interval.total_seconds()),
        )

    def _stop_auto_switch_watchdog(self) -> None:
        """Stop watchdog if running."""
        if self._auto_switch_watchdog_unsub:
            self._auto_switch_watchdog_unsub()
            self._auto_switch_watchdog_unsub = None
            _LOGGER.debug("[AutoModeSwitch] Watchdog stopped")

    async def _auto_switch_watchdog_tick(self, now: datetime) -> None:
        """Periodic check that correct mode is applied."""
        if not self._auto_mode_switch_enabled():
            self._stop_auto_switch_watchdog()
            return

        timeline, _ = self._get_mode_switch_timeline()
        if not timeline:
            return

        desired_mode = self._get_planned_mode_for_time(now, timeline)
        if not desired_mode:
            return

        current_mode = self._get_current_box_mode()
        if current_mode == desired_mode:
            return

        _LOGGER.warning(
            "[AutoModeSwitch] Watchdog correcting mode from %s -> %s",
            current_mode or "unknown",
            desired_mode,
        )
        await self._ensure_current_mode(desired_mode, "watchdog enforcement")

    def _get_planned_mode_for_time(
        self, reference_time: datetime, timeline: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Return planned mode for the interval covering reference_time."""
        planned_mode: Optional[str] = None

        for interval in timeline:
            timestamp = interval.get("time") or interval.get("timestamp")
            mode_label = self._normalize_service_mode(
                interval.get("mode_name")
            ) or self._normalize_service_mode(interval.get("mode"))
            if not timestamp or not mode_label:
                continue

            start_dt = self._parse_timeline_timestamp(timestamp)
            if not start_dt:
                continue

            if start_dt <= reference_time:
                planned_mode = mode_label
                continue

            # Timeline is sorted; once we pass reference_time we can stop
            break

        return planned_mode

    def _schedule_auto_switch_retry(self, delay_seconds: float) -> None:
        if not self._hass or delay_seconds <= 0:
            return
        if self._auto_switch_retry_unsub:
            return

        def _retry(now: datetime) -> None:
            self._auto_switch_retry_unsub = None
            self._create_task_threadsafe(self._update_auto_switch_schedule)

        self._auto_switch_retry_unsub = async_call_later(
            self._hass, delay_seconds, _retry
        )
        self._log_rate_limited(
            "auto_mode_switch_delay_sync",
            "debug",
            "[AutoModeSwitch] Delaying auto-switch sync by %.0f seconds",
            delay_seconds,
            cooldown_s=60.0,
        )

    def _schedule_forecast_retry(self, delay_seconds: float) -> None:
        if not self._hass or delay_seconds <= 0:
            return
        if self._forecast_retry_unsub:
            return

        def _retry(now: datetime) -> None:
            self._forecast_retry_unsub = None
            self._create_task_threadsafe(self.async_update)

        self._forecast_retry_unsub = async_call_later(self._hass, delay_seconds, _retry)

    def _create_task_threadsafe(self, coro_func, *args) -> None:
        """Create an HA task safely from any thread without leaking an un-awaited coroutine."""
        hass = getattr(self, "_hass", None) or getattr(self, "hass", None)
        if not hass:
            return

        def _runner() -> None:
            try:
                hass.async_create_task(coro_func(*args))
            except Exception as err:  # pragma: no cover - defensive
                _LOGGER.debug(
                    "Failed to schedule task %s: %s",
                    getattr(coro_func, "__name__", str(coro_func)),
                    err,
                )

        try:
            loop = hass.loop
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                _runner()
            else:
                loop.call_soon_threadsafe(_runner)
        except Exception:  # pragma: no cover - defensive
            _runner()

    def _get_mode_switch_offset(self, from_mode: Optional[str], to_mode: str) -> float:
        """Return reaction-time offset based on shield tracker statistics."""
        fallback = 180.0
        if self._config_entry and self._config_entry.options:
            fallback = float(
                self._config_entry.options.get(
                    "auto_mode_switch_lead_seconds",
                    self._config_entry.options.get(
                        "autonomy_switch_lead_seconds", 180.0
                    ),
                )
            )
        if not from_mode or not self._hass or not self._config_entry:
            return fallback

        try:
            entry = self._hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
            service_shield = entry.get("service_shield")
            mode_tracker = getattr(service_shield, "mode_tracker", None)
            if not mode_tracker:
                return fallback

            offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)
            if offset_seconds is None or offset_seconds <= 0:
                return fallback

            return float(offset_seconds)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.warning(
                "[AutoModeSwitch] Failed to read mode switch offset %s→%s: %s",
                from_mode,
                to_mode,
                err,
            )
            return fallback

    def _get_service_shield(self) -> Optional[Any]:
        """Safe helper to get ServiceShield instance."""
        if not self._hass or not self._config_entry:
            return None

        entry = self._hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        return entry.get("service_shield")

    async def _execute_mode_change(self, target_mode: str, reason: str) -> None:
        if not self._hass or not self._side_effects_enabled:
            return

        now = dt_util.now()
        service_shield = self._get_service_shield()
        if service_shield and hasattr(service_shield, "has_pending_mode_change"):
            if service_shield.has_pending_mode_change(target_mode):
                _LOGGER.debug(
                    "[AutoModeSwitch] Skipping %s (%s) - shield already processing mode change",
                    target_mode,
                    reason,
                )
                return

        if (
            self._last_auto_switch_request
            and self._last_auto_switch_request[0] == target_mode
            and (now - self._last_auto_switch_request[1]).total_seconds() < 90
        ):
            _LOGGER.debug(
                f"[AutoModeSwitch] Skipping duplicate request for {target_mode} ({reason})"
            )
            return

        try:
            await self._hass.services.async_call(
                DOMAIN,
                "set_box_mode",
                {
                    "mode": target_mode,
                    "acknowledgement": True,
                },
                blocking=False,
            )
            self._last_auto_switch_request = (target_mode, now)
            _LOGGER.info(f"[AutoModeSwitch] Requested mode '{target_mode}' ({reason})")
        except Exception as err:
            _LOGGER.error(
                f"[AutoModeSwitch] Failed to switch to {target_mode}: {err}",
                exc_info=True,
            )

    async def _ensure_current_mode(self, desired_mode: str, reason: str) -> None:
        current_mode = self._get_current_box_mode()
        if current_mode == desired_mode:
            _LOGGER.debug(
                f"[AutoModeSwitch] Mode already {desired_mode} ({reason}), no action"
            )
            return
        await self._execute_mode_change(desired_mode, reason)

    def _get_mode_switch_timeline(self) -> Tuple[List[Dict[str, Any]], str]:
        """
        Return the best available timeline for automatic mode switching.

        Single-planner: always use active timeline.
        """
        timeline = getattr(self, "_timeline_data", None) or []
        if timeline:
            return timeline, "hybrid"
        return [], "none"

    async def _update_auto_switch_schedule(self) -> None:
        """Sync scheduled set_box_mode calls with planned timeline."""
        # Always cancel previous schedule first
        self._cancel_auto_switch_schedule()

        if not self._hass or not self._auto_mode_switch_enabled():
            _LOGGER.debug("[AutoModeSwitch] Auto mode switching disabled")
            self._stop_auto_switch_watchdog()
            return

        now = dt_util.now()
        if self._auto_switch_ready_at:
            if now < self._auto_switch_ready_at:
                wait_seconds = (self._auto_switch_ready_at - now).total_seconds()
                self._log_rate_limited(
                    "auto_mode_switch_startup_delay",
                    "debug",
                    "[AutoModeSwitch] Startup delay active (%.0fs remaining)",
                    wait_seconds,
                    cooldown_s=60.0,
                )
                self._schedule_auto_switch_retry(wait_seconds)
                return
            self._auto_switch_ready_at = None
            self._clear_auto_switch_retry()

        timeline, timeline_source = self._get_mode_switch_timeline()
        if not timeline:
            _LOGGER.debug(
                "[AutoModeSwitch] No timeline available for auto switching (source=%s)",
                timeline_source,
            )
            return

        current_mode: Optional[str] = None
        last_mode: Optional[str] = None
        scheduled_events: List[Tuple[datetime, str, Optional[str]]] = []

        for interval in timeline:
            timestamp = interval.get("time") or interval.get("timestamp")
            mode_label = self._normalize_service_mode(
                interval.get("mode_name")
            ) or self._normalize_service_mode(interval.get("mode"))
            if not timestamp or not mode_label:
                continue

            start_dt = self._parse_timeline_timestamp(timestamp)
            if not start_dt:
                continue

            if start_dt <= now:
                current_mode = mode_label
                last_mode = mode_label
                continue

            if mode_label == last_mode:
                continue

            previous_mode = last_mode
            last_mode = mode_label
            scheduled_events.append((start_dt, mode_label, previous_mode))

        if current_mode:
            await self._ensure_current_mode(current_mode, "current planned block")

        if not scheduled_events:
            _LOGGER.debug("[AutoModeSwitch] No upcoming mode changes to schedule")
            self._start_auto_switch_watchdog()
            return

        for when, mode, prev_mode in scheduled_events:
            adjusted_when = when
            if adjusted_when <= now:
                adjusted_when = now + timedelta(seconds=1)

            async def _callback(event_time: datetime, desired_mode: str = mode) -> None:
                await self._execute_mode_change(
                    desired_mode, f"scheduled {event_time.isoformat()}"
                )

            unsub = async_track_point_in_time(self._hass, _callback, adjusted_when)
            self._auto_switch_handles.append(unsub)
            _LOGGER.info(
                f"[AutoModeSwitch] Scheduled switch to {mode} at {adjusted_when.isoformat()}"
            )
        self._start_auto_switch_watchdog()

    def _build_mode_blocks_for_tab(  # noqa: C901
        self, intervals: List[Dict[str, Any]], tab_name: str
    ) -> List[Dict[str, Any]]:
        """
        Postavit mode bloky pro jeden tab.

        Args:
            intervals: Seznam intervalů z _build_day_timeline()
            tab_name: "yesterday" | "today" | "tomorrow"

        Returns:
            Seznam mode bloků s detailními metrikami
        """
        if not intervals:
            return []

        # Určit data_type podle tabu
        now = dt_util.now()

        if tab_name == "yesterday":
            # VČERA - pouze historical data
            data_type = "completed"
        elif tab_name == "today":
            # DNES - historical (minulost) + planned (budoucnost)
            # Potřebujeme rozdělít na completed vs future
            data_type = "both"
        else:  # tomorrow
            # ZÍTRA - pouze planned
            data_type = "planned"

        # Použít existující _group_intervals_by_mode() pro agregaci
        mode_groups = self._group_intervals_by_mode(intervals, data_type)

        _LOGGER.info(
            f"[build_mode_blocks_for_tab] tab={tab_name}, data_type={data_type}, intervals_count={len(intervals)}, mode_groups_count={len(mode_groups)}"
        )

        total_capacity = self._get_total_battery_capacity() or 0.0

        def _extract_soc_payload(
            interval_entry: Dict[str, Any], branch: str
        ) -> Tuple[float, float]:
            """
            Vrátit dvojici (percent, kWh) pro daný interval a větev (actual/planned).

            Hodnoty v datech jsou bohužel nekonzistentní:
            - Actual intervaly mají battery_soc v % a battery_kwh v kWh
            - Planned intervaly ukládají battery_soc jako kWh (historický formát)

            Aby FE dostal konzistentní % SOC, normalizujeme zde.
            """

            source = (
                interval_entry.get(branch) if isinstance(interval_entry, dict) else None
            )
            if not isinstance(source, dict):
                return (0.0, 0.0)

            raw_soc = source.get("battery_soc")
            raw_kwh = source.get("battery_kwh")

            # Některé planned záznamy používají battery_capacity_kwh místo battery_kwh
            if raw_kwh is None:
                raw_kwh = source.get("battery_capacity_kwh")

            soc_percent = None
            kwh_value = raw_kwh

            if raw_soc is not None:
                if total_capacity > 0 and raw_soc <= total_capacity + 0.01:
                    # Hodnota je pravděpodobně v kWh (<= fyzická kapacita)
                    kwh_value = raw_soc if kwh_value is None else kwh_value
                else:
                    # Hodnota je v procentech (větší než fyzická kapacita)
                    soc_percent = raw_soc

            if soc_percent is None and kwh_value is not None and total_capacity > 0:
                soc_percent = (kwh_value / total_capacity) * 100.0

            if soc_percent is not None and kwh_value is None and total_capacity > 0:
                kwh_value = (soc_percent / 100.0) * total_capacity

            return (
                round(soc_percent or 0.0, 1),
                round(kwh_value or 0.0, 2),
            )

        # Helper pro grid net
        def _interval_net(
            interval_entry: Dict[str, Any], branch: str
        ) -> Optional[float]:
            if not isinstance(interval_entry.get(branch), dict):
                return None
            import_val = safe_nested_get(
                interval_entry, branch, "grid_import", default=None
            )
            if import_val is None:
                import_val = safe_nested_get(
                    interval_entry, branch, "grid_import_kwh", default=None
                )
            export_val = safe_nested_get(
                interval_entry, branch, "grid_export", default=None
            )
            if export_val is None:
                export_val = safe_nested_get(
                    interval_entry, branch, "grid_export_kwh", default=None
                )
            if import_val is None and export_val is None:
                return None
            return (import_val or 0.0) - (export_val or 0.0)

        # Rozšířit o detailní metriky pro Detail Tabs
        mode_blocks = []
        for group in mode_groups:
            group_intervals = group.get("intervals", [])
            if not group_intervals:
                continue

            # Základní info z group
            block = {
                "mode_historical": group.get("mode", "Unknown"),
                "mode_planned": group.get("mode", "Unknown"),  # Pro planned-only
                "mode_match": True,  # Default pro planned-only
                "status": self._determine_block_status(
                    group_intervals[0], group_intervals[-1], tab_name, now
                ),
                "start_time": group.get("start_time", ""),
                "end_time": group.get("end_time", ""),
                "interval_count": group.get("interval_count", 0),
            }

            # Duration v hodinách
            duration_hours = block["interval_count"] * 0.25  # 15min = 0.25h
            block["duration_hours"] = round(duration_hours, 2)

            # Náklady
            if data_type in ["completed", "both"]:
                block["cost_historical"] = group.get("actual_cost", 0.0)
                block["cost_planned"] = group.get("planned_cost", 0.0)
                block["cost_delta"] = group.get("delta", 0.0)

                # Mode match detection (porovnat historical vs planned mode)
                historical_mode = self._get_mode_from_intervals(
                    group_intervals, "actual"
                )
                planned_mode = self._get_mode_from_intervals(group_intervals, "planned")
                block["mode_historical"] = historical_mode or "Unknown"
                block["mode_planned"] = planned_mode or "Unknown"
                block["mode_match"] = historical_mode == planned_mode
            else:  # planned-only
                block["cost_planned"] = group.get("planned_cost", 0.0)
                block["cost_historical"] = None
                block["cost_delta"] = None

            # Battery SOC (začátek a konec bloku)
            first_interval = group_intervals[0]
            last_interval = group_intervals[-1]

            if data_type in ["completed", "both"]:
                start_soc_pct, start_soc_kwh = _extract_soc_payload(
                    first_interval, "actual"
                )
                end_soc_pct, end_soc_kwh = _extract_soc_payload(last_interval, "actual")
            else:
                start_soc_pct, start_soc_kwh = _extract_soc_payload(
                    first_interval, "planned"
                )
                end_soc_pct, end_soc_kwh = _extract_soc_payload(
                    last_interval, "planned"
                )

            block["battery_soc_start"] = start_soc_pct
            block["battery_soc_end"] = end_soc_pct
            block["battery_kwh_start"] = start_soc_kwh
            block["battery_kwh_end"] = end_soc_kwh

            # Energie totals (plan vs actual)
            solar_plan_total = 0.0
            solar_actual_total = 0.0
            solar_actual_samples = 0

            consumption_plan_total = 0.0
            consumption_actual_total = 0.0
            consumption_actual_samples = 0

            grid_plan_net_total = 0.0
            grid_actual_net_total = 0.0
            grid_actual_samples = 0

            grid_plan_export_total = 0.0
            grid_actual_export_total = 0.0
            grid_export_actual_samples = 0

            for iv in group_intervals:
                # Planned values
                solar_plan_total += safe_nested_get(
                    iv, "planned", "solar_kwh", default=0
                )
                consumption_plan_total += safe_nested_get(
                    iv, "planned", "consumption_kwh", default=0
                )
                grid_plan_net_total += _interval_net(iv, "planned") or 0.0
                grid_plan_export_total += safe_nested_get(
                    iv, "planned", "grid_export", default=0
                ) or safe_nested_get(iv, "planned", "grid_export_kwh", default=0)

                # Actual values
                actual_solar = safe_nested_get(iv, "actual", "solar_kwh", default=None)
                if actual_solar is not None:
                    solar_actual_total += actual_solar
                    solar_actual_samples += 1

                actual_consumption = safe_nested_get(
                    iv, "actual", "consumption_kwh", default=None
                )
                if actual_consumption is not None:
                    consumption_actual_total += actual_consumption
                    consumption_actual_samples += 1

                actual_net = _interval_net(iv, "actual")
                if actual_net is not None:
                    grid_actual_net_total += actual_net
                    grid_actual_samples += 1

                actual_export = safe_nested_get(
                    iv, "actual", "grid_export", default=None
                )
                if actual_export is None:
                    actual_export = safe_nested_get(
                        iv, "actual", "grid_export_kwh", default=None
                    )
                if actual_export is not None:
                    grid_actual_export_total += actual_export
                    grid_export_actual_samples += 1

            def _round_or_none(value: float, samples: int) -> Optional[float]:
                return round(value, 2) if samples > 0 else None

            block["solar_planned_kwh"] = round(solar_plan_total, 2)
            block["solar_actual_kwh"] = _round_or_none(
                solar_actual_total, solar_actual_samples
            )

            block["consumption_planned_kwh"] = round(consumption_plan_total, 2)
            block["consumption_actual_kwh"] = _round_or_none(
                consumption_actual_total, consumption_actual_samples
            )

            block["grid_import_planned_kwh"] = round(grid_plan_net_total, 2)
            block["grid_import_actual_kwh"] = _round_or_none(
                grid_actual_net_total, grid_actual_samples
            )

            block["grid_export_planned_kwh"] = round(grid_plan_export_total, 2)
            block["grid_export_actual_kwh"] = _round_or_none(
                grid_actual_export_total, grid_export_actual_samples
            )

            # Backwards compatible totals (use actual if available else planned)
            block["solar_total_kwh"] = (
                block["solar_actual_kwh"]
                if block["solar_actual_kwh"] is not None
                else block["solar_planned_kwh"]
            )
            block["consumption_total_kwh"] = (
                block["consumption_actual_kwh"]
                if block["consumption_actual_kwh"] is not None
                else block["consumption_planned_kwh"]
            )
            block["grid_import_total_kwh"] = (
                block["grid_import_actual_kwh"]
                if block["grid_import_actual_kwh"] is not None
                else block["grid_import_planned_kwh"]
            )
            block["grid_export_total_kwh"] = (
                block["grid_export_actual_kwh"]
                if block["grid_export_actual_kwh"] is not None
                else block["grid_export_planned_kwh"]
            )

            # Delta helpers
            def _calc_delta(
                actual_val: Optional[float], planned_val: float
            ) -> Optional[float]:
                if actual_val is None:
                    return None
                return round(actual_val - planned_val, 2)

            block["solar_delta_kwh"] = _calc_delta(
                block["solar_actual_kwh"], block["solar_planned_kwh"]
            )
            block["consumption_delta_kwh"] = _calc_delta(
                block["consumption_actual_kwh"], block["consumption_planned_kwh"]
            )
            block["grid_import_delta_kwh"] = _calc_delta(
                block["grid_import_actual_kwh"], block["grid_import_planned_kwh"]
            )
            block["grid_export_delta_kwh"] = _calc_delta(
                block["grid_export_actual_kwh"], block["grid_export_planned_kwh"]
            )

            block_reason = self._summarize_block_reason(group_intervals, block)
            if block_reason:
                block["interval_reasons"] = [
                    {
                        "time": block.get("start_time", ""),
                        "reason": block_reason,
                    }
                ]

            # Adherence % (pro completed bloky)
            if data_type in ["completed", "both"] and block["mode_match"]:
                block["adherence_pct"] = 100
            elif data_type in ["completed", "both"]:
                # Mode nesouhlasí - částečná adherence
                block["adherence_pct"] = 0
            else:
                # Planned-only - N/A
                block["adherence_pct"] = None

            mode_blocks.append(block)

        return mode_blocks

    def _format_time_label(self, iso_ts: Optional[str]) -> str:
        """Format ISO timestamp to local HH:MM string."""
        if not iso_ts:
            return "--:--"
        try:
            ts = iso_ts
            if iso_ts.endswith("Z"):
                ts = iso_ts.replace("Z", ISO_TZ_OFFSET)
            dt_obj = datetime.fromisoformat(ts)
            if dt_obj.tzinfo is None:
                dt_obj = dt_util.as_local(dt_obj)
            else:
                dt_obj = dt_obj.astimezone(dt_util.DEFAULT_TIME_ZONE)
            return dt_obj.strftime("%H:%M")
        except Exception:
            return iso_ts

    def _summarize_block_reason(
        self, group_intervals: List[Dict[str, Any]], block: Dict[str, Any]
    ) -> Optional[str]:
        planned_entries = [
            iv.get("planned")
            for iv in group_intervals
            if isinstance(iv.get("planned"), dict)
        ]
        actual_entries = [
            iv.get("actual")
            for iv in group_intervals
            if isinstance(iv.get("actual"), dict)
        ]
        entries_source = planned_entries if planned_entries else actual_entries
        if not entries_source:
            return None

        metrics_list = (
            [p.get("decision_metrics") or {} for p in planned_entries]
            if planned_entries
            else []
        )

        guard_metrics = (
            next((m for m in metrics_list if m.get("guard_active")), None)
            if metrics_list
            else None
        )
        if guard_metrics:
            guard_type = guard_metrics.get("guard_type")
            if guard_type == "guard_exception_soc":
                planned_mode = guard_metrics.get("guard_planned_mode") or block.get(
                    "mode_planned"
                )
                return (
                    "Výjimka guardu: SoC pod plánovacím minimem – "
                    f"povolujeme {planned_mode}."
                )

            forced_mode = guard_metrics.get("guard_forced_mode") or block.get(
                "mode_planned"
            )
            guard_until = guard_metrics.get("guard_until")
            guard_until_label = self._format_time_label(guard_until)
            if guard_until_label != "--:--":
                return (
                    f"Stabilizace: držíme režim {forced_mode} do {guard_until_label}."
                )
            return f"Stabilizace: držíme režim {forced_mode} 60 min po poslední změně."

        reason_codes = [
            m.get("planner_reason_code")
            for m in metrics_list
            if m.get("planner_reason_code")
        ]
        dominant_code = (
            Counter(reason_codes).most_common(1)[0][0] if reason_codes else None
        )

        def _mean(values: List[Optional[float]]) -> Optional[float]:
            vals = [
                v for v in values if isinstance(v, (int, float)) and not math.isnan(v)
            ]
            if not vals:
                return None
            return sum(vals) / len(vals)

        def _avg_from_metrics(key: str) -> Optional[float]:
            if not metrics_list:
                return None
            return _mean([m.get(key) for m in metrics_list if m.get(key) is not None])

        def _avg_from_entries(key: str) -> Optional[float]:
            return _mean(
                [
                    entry.get(key)
                    for entry in entries_source
                    if isinstance(entry.get(key), (int, float))
                ]
            )

        prices: List[Optional[float]] = []
        for entry in entries_source:
            price = entry.get("spot_price")
            if price is None:
                price = entry.get("spot_price_czk")
            if price is None:
                price = (entry.get("decision_metrics") or {}).get("spot_price_czk")
            prices.append(price)
        avg_price = _mean(prices)

        avg_future_ups = _avg_from_metrics("future_ups_avg_price_czk")
        avg_grid_charge = _avg_from_metrics("grid_charge_kwh")
        avg_home1_saving = _avg_from_metrics("home1_saving_czk")
        avg_recharge_cost = _avg_from_metrics("recharge_cost_czk")
        avg_solar = _avg_from_entries("solar_kwh")
        avg_load = _avg_from_entries("consumption_kwh")

        start_kwh = block.get("battery_kwh_start")
        end_kwh = block.get("battery_kwh_end")
        delta_kwh = (
            (end_kwh - start_kwh)
            if isinstance(start_kwh, (int, float)) and isinstance(end_kwh, (int, float))
            else None
        )

        opts = self._config_entry.options if self._config_entry else {}
        max_ups_price = float(opts.get("max_ups_price_czk", 10.0))
        efficiency = float(self._get_battery_efficiency() or 0.0)
        if 0 < efficiency <= 1.0:
            band_pct = max(0.08, (1.0 / efficiency) - 1.0)
        else:
            band_pct = 0.08

        mode_label = block.get("mode_planned") or block.get("mode_historical") or ""
        mode_upper = str(mode_label).upper()

        if dominant_code:
            if dominant_code == "price_band_hold":
                if avg_price is not None:
                    if (
                        avg_future_ups is not None
                        and avg_price <= avg_future_ups - 0.01
                    ):
                        return (
                            "UPS držíme v cenovém pásmu ±"
                            f"{band_pct * 100:.0f}% "
                            f"(průměr {avg_price:.2f} Kč/kWh, "
                            f"levnější než další okna {avg_future_ups:.2f} Kč/kWh)."
                        )
                    return (
                        "UPS držíme v cenovém pásmu ±"
                        f"{band_pct * 100:.0f}% "
                        f"(průměr {avg_price:.2f} Kč/kWh)."
                    )
                return "UPS držíme v cenovém pásmu dle účinnosti."

            reason_text = self._format_planner_reason(
                dominant_code, spot_price=avg_price
            )
            if reason_text:
                if avg_price is not None and "Kč/kWh" not in reason_text:
                    reason_text = f"{reason_text} (průměr {avg_price:.2f} Kč/kWh)."
                return reason_text

        if "UPS" in mode_upper:
            charge_kwh = None
            if avg_grid_charge is not None and avg_grid_charge > 0.01:
                charge_kwh = avg_grid_charge
            elif delta_kwh is not None and delta_kwh > 0.05:
                charge_kwh = delta_kwh

            if avg_price is not None:
                if avg_price <= max_ups_price + 0.0001:
                    detail = (
                        "Nabíjíme ze sítě"
                        + (f" (+{charge_kwh:.2f} kWh)" if charge_kwh else "")
                        + f": {avg_price:.2f} Kč/kWh ≤ limit {max_ups_price:.2f}."
                    )
                    if (
                        avg_future_ups is not None
                        and avg_price <= avg_future_ups - 0.01
                    ):
                        detail += f" Je levnější než další UPS okna ({avg_future_ups:.2f} Kč/kWh)."
                    return detail
                detail = (
                    f"UPS režim i přes vyšší cenu {avg_price:.2f} Kč/kWh "
                    f"(limit {max_ups_price:.2f})"
                )
                if charge_kwh:
                    detail += f", nabíjení +{charge_kwh:.2f} kWh."
                else:
                    detail += "."
                return detail
            return "UPS režim (plánované nabíjení)."

        if "HOME II" in mode_upper or "HOME 2" in mode_upper:
            if avg_home1_saving is not None and avg_recharge_cost is not None:
                return (
                    "Držíme baterii (HOME II): HOME I by ušetřil ~"
                    f"{avg_home1_saving:.2f} Kč, dobíjení v UPS ~{avg_recharge_cost:.2f} Kč."
                )
            return "Držíme baterii (HOME II), bez vybíjení do zátěže."

        if "HOME III" in mode_upper or "HOME 3" in mode_upper:
            if avg_solar is not None and avg_load is not None and avg_solar > avg_load:
                return (
                    "HOME III: FVE pokrývá spotřebu "
                    f"({avg_solar:.2f} kWh > {avg_load:.2f} kWh), "
                    "maximalizujeme nabíjení."
                )
            return "Maximalizujeme nabíjení z FVE, spotřeba jde ze sítě."

        if "HOME I" in mode_upper or "HOME 1" in mode_upper:
            if delta_kwh is not None and delta_kwh < -0.05:
                if avg_price is not None and avg_future_ups is not None:
                    delta_price = avg_price - avg_future_ups
                    if delta_price > 0.01:
                        return (
                            "Vybíjíme baterii (-"
                            f"{abs(delta_kwh):.2f} kWh), protože UPS by byl "
                            f"o {delta_price:.2f} Kč/kWh dražší "
                            f"(nyní {avg_price:.2f}, UPS okna {avg_future_ups:.2f})."
                        )
                if avg_price is not None and avg_price > max_ups_price + 0.0001:
                    return (
                        "Vybíjíme baterii (-"
                        f"{abs(delta_kwh):.2f} kWh), cena {avg_price:.2f} Kč/kWh "
                        f"je nad limitem UPS {max_ups_price:.2f} Kč/kWh."
                    )
                return (
                    "Vybíjíme baterii (-"
                    f"{abs(delta_kwh):.2f} kWh) místo odběru ze sítě."
                )
            if delta_kwh is not None and delta_kwh > 0.05:
                return (
                    "Solár pokrývá spotřebu, přebytky ukládáme do baterie "
                    f"(+{delta_kwh:.2f} kWh)."
                )
            if avg_solar is not None and avg_load is not None and avg_solar >= avg_load:
                return (
                    "Solár pokrývá spotřebu "
                    f"({avg_solar:.2f} kWh ≥ {avg_load:.2f} kWh), "
                    "baterie se výrazně nemění."
                )
            return "Solár pokrývá spotřebu, baterie se výrazně nemění."

        reasons = [
            p.get("decision_reason") for p in entries_source if p.get("decision_reason")
        ]
        if reasons:
            return Counter(reasons).most_common(1)[0][0]

        return None

    def _determine_block_status(
        self,
        first_interval: Dict[str, Any],
        last_interval: Dict[str, Any],
        tab_name: str,
        now: datetime,
    ) -> str:
        """
        Určit status bloku: completed | current | planned.

        Args:
            first_interval: První interval v bloku (start time)
            last_interval: Poslední interval v bloku (end time)
            tab_name: "yesterday" | "today" | "tomorrow"
            now: Aktuální čas

        Returns:
            "completed" | "current" | "planned"
        """
        if tab_name == "yesterday":
            return "completed"
        elif tab_name == "tomorrow":
            return "planned"
        else:  # today
            start_time_str = first_interval.get("time", "")
            end_time_str = last_interval.get("time", "")

            if not start_time_str or not end_time_str:
                return "planned"

            try:
                start_time = datetime.fromisoformat(start_time_str)
                end_time = datetime.fromisoformat(end_time_str)

                if start_time.tzinfo is None:
                    start_time = dt_util.as_local(start_time)
                if end_time.tzinfo is None:
                    end_time = dt_util.as_local(end_time)

                # Konec intervalu je začátek + 15 minut
                end_time = end_time + timedelta(minutes=15)

                current_minute = (now.minute // 15) * 15
                current_interval_time = now.replace(
                    minute=current_minute, second=0, microsecond=0
                )

                # Remove timezone for comparison
                start_time_naive = (
                    start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
                )
                end_time_naive = (
                    end_time.replace(tzinfo=None) if end_time.tzinfo else end_time
                )
                current_interval_naive = current_interval_time.replace(tzinfo=None)

                # Celý blok v minulosti?
                if end_time_naive <= current_interval_naive:
                    return "completed"
                # Začátek v minulosti, konec v budoucnosti?
                elif start_time_naive <= current_interval_naive < end_time_naive:
                    return "current"
                # Celý blok v budoucnosti
                else:
                    return "planned"
            except Exception as e:
                _LOGGER.warning(f"[_determine_block_status] Error parsing times: {e}")
                return "planned"

    def _get_mode_from_intervals(
        self, intervals: List[Dict[str, Any]], key: str
    ) -> Optional[str]:
        """
        Získat mode z intervalů (actual nebo planned).

        Args:
            intervals: Seznam intervalů
            key: "actual" nebo "planned"

        Returns:
            Mode name nebo None
        """
        for interval in intervals:
            data = interval.get(key)
            if data and isinstance(data, dict):
                mode = data.get("mode")
                if isinstance(mode, int):
                    return CBB_MODE_NAMES.get(mode, f"Mode {mode}")
                elif mode:
                    return str(mode)
        return None

    def _calculate_tab_summary(
        self, mode_blocks: List[Dict[str, Any]], intervals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Spočítat summary pro tab.

        Args:
            mode_blocks: Seznam mode bloků
            intervals: Raw intervaly

        Returns:
            Summary dict s total_cost, adherence, mode_switches
            + pro TODAY: completed_summary a planned_summary
        """
        if not mode_blocks:
            return {
                "total_cost": 0.0,
                "overall_adherence": 100,
                "mode_switches": 0,
                "metrics": self._default_metrics_summary(),
            }

        # Total cost (historical pokud máme, jinak planned)
        total_cost = 0.0
        adherent_blocks = 0
        total_blocks = len(mode_blocks)

        # Sub-summaries pro TODAY
        completed_blocks = []
        planned_blocks = []

        for block in mode_blocks:
            cost = block.get("cost_historical")
            if cost is not None:
                total_cost += cost
            else:
                total_cost += block.get("cost_planned", 0.0)

            # Adherence counting
            if block.get("adherence_pct") == 100:
                adherent_blocks += 1

            # Separate completed vs planned for TODAY
            if block.get("status") == "completed":
                completed_blocks.append(block)
            elif block.get("status") in ("current", "planned"):
                planned_blocks.append(block)

        # Overall adherence %
        overall_adherence = (
            round((adherent_blocks / total_blocks) * 100, 1)
            if total_blocks > 0
            else 100
        )

        # Mode switches = počet bloků - 1
        mode_switches = max(0, total_blocks - 1)

        metrics = self._aggregate_interval_metrics(intervals)

        summary = {
            "total_cost": round(total_cost, 2),
            "overall_adherence": overall_adherence,
            "mode_switches": mode_switches,
            "metrics": metrics,
        }

        # Add sub-summaries if we have both completed and planned (TODAY case)
        if completed_blocks and planned_blocks:
            # Completed summary
            completed_cost = sum(b.get("cost_historical", 0) for b in completed_blocks)
            completed_adherent = sum(
                1 for b in completed_blocks if b.get("adherence_pct") == 100
            )

            summary["completed_summary"] = {
                "count": len(completed_blocks),
                "total_cost": round(completed_cost, 2),
                "adherence_pct": (
                    round((completed_adherent / len(completed_blocks)) * 100, 1)
                    if completed_blocks
                    else 100
                ),
            }

            # Planned summary
            planned_cost = sum(b.get("cost_planned", 0) for b in planned_blocks)

            summary["planned_summary"] = {
                "count": len(planned_blocks),
                "total_cost": round(planned_cost, 2),
            }

        return summary

    def _aggregate_interval_metrics(
        self, intervals: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate plan vs actual metrics for summary tiles."""

        def _get_plan_value(interval: Dict[str, Any], key: str) -> float:
            return safe_nested_get(interval, "planned", key, default=0.0)

        def _get_actual_value(interval: Dict[str, Any], key: str) -> Optional[float]:
            actual = interval.get("actual")
            if not actual:
                return None
            value = actual.get(key)
            if value is None:
                # Some actual payloads use _kwh suffix
                return actual.get(f"{key}_kwh")
            return value

        def _get_grid_net(payload: Dict[str, Any], prefix: str) -> float:
            import_key = "grid_import"
            export_key = "grid_export"
            import_val = safe_nested_get(payload, prefix, import_key, default=None)
            if import_val is None:
                import_val = safe_nested_get(
                    payload, prefix, f"{import_key}_kwh", default=0.0
                )
            export_val = safe_nested_get(payload, prefix, export_key, default=None)
            if export_val is None:
                export_val = safe_nested_get(
                    payload, prefix, f"{export_key}_kwh", default=0.0
                )
            return (import_val or 0.0) - (export_val or 0.0)

        metrics_template = {
            "plan": 0.0,
            "actual": 0.0,
            "actual_samples": 0,
        }

        metrics = {
            "cost": dict(metrics_template),
            "solar": dict(metrics_template),
            "consumption": dict(metrics_template),
            "grid": dict(metrics_template),
        }

        for interval in intervals or []:
            plan_cost = _get_plan_value(interval, "net_cost")
            actual_cost = _get_actual_value(interval, "net_cost")
            metrics["cost"]["plan"] += plan_cost
            if actual_cost is not None:
                metrics["cost"]["actual"] += actual_cost
                metrics["cost"]["actual_samples"] += 1
            else:
                metrics["cost"]["actual"] += plan_cost

            plan_solar = _get_plan_value(interval, "solar_kwh")
            actual_solar = _get_actual_value(interval, "solar_kwh")
            metrics["solar"]["plan"] += plan_solar
            if actual_solar is not None:
                metrics["solar"]["actual"] += actual_solar
                metrics["solar"]["actual_samples"] += 1
            else:
                metrics["solar"]["actual"] += plan_solar

            plan_consumption = _get_plan_value(interval, "consumption_kwh")
            actual_consumption = _get_actual_value(interval, "consumption_kwh")
            metrics["consumption"]["plan"] += plan_consumption
            if actual_consumption is not None:
                metrics["consumption"]["actual"] += actual_consumption
                metrics["consumption"]["actual_samples"] += 1
            else:
                metrics["consumption"]["actual"] += plan_consumption

            plan_grid = _get_grid_net(interval, "planned")
            actual_grid = None
            actual_payload = interval.get("actual")
            if actual_payload:
                actual_grid = (
                    actual_payload.get("grid_import")
                    or actual_payload.get("grid_import_kwh")
                    or 0.0
                ) - (
                    actual_payload.get("grid_export")
                    or actual_payload.get("grid_export_kwh")
                    or 0.0
                )
            metrics["grid"]["plan"] += plan_grid
            if actual_grid is not None:
                metrics["grid"]["actual"] += actual_grid
                metrics["grid"]["actual_samples"] += 1
            else:
                metrics["grid"]["actual"] += plan_grid

        formatted_metrics: Dict[str, Dict[str, Any]] = {}
        metric_units = {
            "cost": "Kč",
            "solar": "kWh",
            "consumption": "kWh",
            "grid": "kWh",
        }

        for key, value in metrics.items():
            formatted_metrics[key] = {
                "plan": round(value["plan"], 2),
                "actual": round(value["actual"], 2),
                "unit": metric_units.get(key, ""),
                "has_actual": value["actual_samples"] > 0,
            }

        return formatted_metrics

    def _default_metrics_summary(self) -> Dict[str, Dict[str, Any]]:
        return {
            "cost": {"plan": 0.0, "actual": 0.0, "unit": "Kč", "has_actual": False},
            "solar": {"plan": 0.0, "actual": 0.0, "unit": "kWh", "has_actual": False},
            "consumption": {
                "plan": 0.0,
                "actual": 0.0,
                "unit": "kWh",
                "has_actual": False,
            },
            "grid": {"plan": 0.0, "actual": 0.0, "unit": "kWh", "has_actual": False},
        }

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
        now = dt_util.now()

        # Build fresh data (bez cache)
        _LOGGER.info("Unified Cost Tile: Building fresh data...")
        build_start = dt_util.now()

        # Build data for each day
        try:
            today_data = await self._build_today_cost_data()
        except Exception as e:
            _LOGGER.error(f"Failed to build today cost data: {e}", exc_info=True)
            today_data = {
                "plan_total_cost": 0.0,
                "actual_total_cost": 0.0,
                "delta": 0.0,
                "performance": "on_plan",
                "completed_intervals": 0,
                "total_intervals": 0,
                "progress_pct": 0,
                "eod_prediction": {
                    "predicted_total": 0.0,
                    "vs_plan": 0.0,
                    "confidence": "low",
                },
                "error": str(e),
            }

        try:
            # Yesterday is always the same for both planners (historical data)
            yesterday_data = self._get_yesterday_cost_from_archive()
        except Exception as e:
            _LOGGER.error(f"Failed to get yesterday cost data: {e}", exc_info=True)
            yesterday_data = {
                "plan_total_cost": 0.0,
                "actual_total_cost": 0.0,
                "delta": 0.0,
                "performance": "on_plan",
                "error": str(e),
            }

        try:
            tomorrow_data = await self._build_tomorrow_cost_data()
        except Exception as e:
            _LOGGER.error(f"Failed to build tomorrow cost data: {e}", exc_info=True)
            tomorrow_data = {
                "plan_total_cost": 0.0,
                "error": str(e),
            }

        result = {
            "today": today_data,
            "yesterday": yesterday_data,
            "tomorrow": tomorrow_data,
            "metadata": {
                "last_update": str(now),
                "timezone": str(now.tzinfo),
            },
        }

        build_duration = (dt_util.now() - build_start).total_seconds()
        _LOGGER.info(f"Unified Cost Tile: Built in {build_duration:.2f}s")

        return result

    def _group_intervals_by_mode(
        self, intervals: List[Dict[str, Any]], data_type: str = "both"
    ) -> List[Dict[str, Any]]:
        """
        Seskupit intervaly podle režimu do časových bloků.

        Args:
            intervals: Seznam intervalů
            data_type: "completed" (má actual), "planned" (jen plan), "both" (oboje)

        Returns:
            Seznam skupin [{mode, start_time, end_time, interval_count, costs...}]
        """
        if not intervals:
            return []

        groups = []
        current_group = None

        for interval in intervals:
            # Skip None intervals
            if interval is None:
                continue

            # Určit režim podle data_type
            if data_type == "completed":
                actual = interval.get("actual") or {}
                planned = interval.get("planned") or {}
                actual_mode = actual.get("mode")
                planned_mode = planned.get("mode")
                # Pro completed: použít actual mode, fallback na planned
                if actual_mode is not None:
                    mode = actual_mode
                elif planned_mode is not None:
                    mode = planned_mode
                else:
                    mode = "Unknown"
                # Log prvních 3 intervalů pro debug
                if len(groups) < 3:
                    _LOGGER.info(
                        f"[_group_intervals_by_mode] COMPLETED: time={interval.get('time', '?')[:16]}, "
                        f"actual_mode={actual_mode}, planned_mode={planned_mode}, final_mode={mode}, "
                        f"has_actual={bool(actual)}"
                    )
            elif data_type == "planned":
                planned = interval.get("planned") or {}
                mode = planned.get("mode", "Unknown")
            else:  # both - priorita actual, fallback na planned
                actual = interval.get("actual") or {}
                planned = interval.get("planned") or {}
                # POZOR: 0 je validní mode, nesmíme použít simple `or`!
                actual_mode = actual.get("mode")
                planned_mode = planned.get("mode")
                if actual_mode is not None:
                    mode = actual_mode
                elif planned_mode is not None:
                    mode = planned_mode
                else:
                    mode = "Unknown"
                _LOGGER.debug(
                    f"[_group_intervals_by_mode] data_type=both: "
                    f"actual_mode={actual_mode}, planned_mode={planned_mode}, final_mode={mode}"
                )

            # Převést mode ID na jméno (mode může být int nebo string)
            if isinstance(mode, int):
                mode = CBB_MODE_NAMES.get(mode, f"Mode {mode}")
            elif mode != "Unknown":
                mode = str(mode).strip()

            # Fallback pokud je mode prázdný
            if not mode or mode == "":
                mode = "Unknown"

            # Nová skupina nebo pokračování?
            if not current_group or current_group["mode"] != mode:
                current_group = {
                    "mode": mode,
                    "start_time": interval.get("time", ""),
                    "end_time": interval.get("time", ""),
                    "intervals": [interval],
                }
                groups.append(current_group)
            else:
                current_group["intervals"].append(interval)
                current_group["end_time"] = interval.get("time", "")

        # Agregovat náklady pro každou skupinu
        for group in groups:
            interval_count = len(group["intervals"])
            group["interval_count"] = interval_count

            if data_type in ["completed", "both"]:
                # Actual cost POUZE z intervalů, které už nastaly (mají actual data)
                actual_cost = sum(
                    iv.get("actual", {}).get("net_cost", 0)
                    for iv in group["intervals"]
                    if iv.get("actual") is not None
                )
                planned_cost = sum(
                    (iv.get("planned") or {}).get("net_cost", 0)
                    for iv in group["intervals"]
                )
                actual_savings = sum(
                    iv.get("actual", {}).get("savings_vs_home_i", 0)
                    for iv in group["intervals"]
                    if iv.get("actual") is not None
                )
                planned_savings = sum(
                    (iv.get("planned") or {}).get("savings_vs_home_i", 0)
                    for iv in group["intervals"]
                )
                delta = actual_cost - planned_cost
                delta_pct = (delta / planned_cost * 100) if planned_cost > 0 else 0.0

                group["actual_cost"] = round(actual_cost, 2)
                group["planned_cost"] = round(planned_cost, 2)
                group["actual_savings"] = round(actual_savings, 2)
                group["planned_savings"] = round(planned_savings, 2)
                group["delta"] = round(delta, 2)
                group["delta_pct"] = round(delta_pct, 1)

            if data_type == "planned":
                # Jen plánovaná data
                planned_cost = sum(
                    (iv.get("planned") or {}).get("net_cost", 0)
                    for iv in group["intervals"]
                )
                planned_savings = sum(
                    (iv.get("planned") or {}).get("savings_vs_home_i", 0)
                    for iv in group["intervals"]
                )
                group["planned_cost"] = round(planned_cost, 2)
                group["planned_savings"] = round(planned_savings, 2)

            # Formátovat časy
            if group["start_time"]:
                try:
                    start_dt = datetime.fromisoformat(group["start_time"])
                    group["start_time"] = start_dt.strftime("%H:%M")
                except Exception:
                    pass

            if group["end_time"]:
                try:
                    end_dt = datetime.fromisoformat(group["end_time"])
                    # Přidat 15 minut pro konec intervalu
                    end_dt = end_dt + timedelta(minutes=15)
                    group["end_time"] = end_dt.strftime("%H:%M")
                except Exception:
                    pass

            # PHASE 3.0: KEEP intervals for Detail Tabs API
            # Původně se mazaly pro úsporu paměti, ale Detail Tabs je potřebuje
            # del group["intervals"]

        return groups

    def _build_baseline_comparison(self, hybrid_cost: float) -> Dict[str, Any]:
        """
        Build baseline comparison data for cost tile.

        Compares HYBRID optimization cost against best fixed mode baseline.

        Args:
            hybrid_cost: Total cost of HYBRID plan (Kč)

        Returns:
            Dict with baseline comparison:
            {
                "hybrid_cost": 51.19,
                "best_baseline": "HOME_III",
                "best_baseline_cost": 59.64,
                "savings": 8.45,
                "savings_pct": 14.2,
                "all_baselines": {...}
            }
        """
        # Get baselines from mode_optimization_result
        if (
            not hasattr(self, "_mode_optimization_result")
            or not self._mode_optimization_result
        ):
            return {}

        baselines = self._mode_optimization_result.get("baselines", {})
        if not baselines:
            return {}

        # Find best baseline (lowest adjusted cost, excluding HOME_UPS)
        best_baseline = None
        best_cost = float("inf")

        for mode_name in ["HOME_I", "HOME_II", "HOME_III"]:
            if mode_name in baselines:
                cost = baselines[mode_name].get("adjusted_total_cost", float("inf"))
                if cost < best_cost:
                    best_cost = cost
                    best_baseline = mode_name

        if not best_baseline:
            return {}

        # Calculate savings
        savings = best_cost - hybrid_cost
        savings_pct = (savings / best_cost * 100) if best_cost > 0 else 0

        # Build all baselines summary (only HOME I/II/III for display)
        all_baselines = {}
        for mode_name in ["HOME_I", "HOME_II", "HOME_III"]:
            if mode_name in baselines:
                all_baselines[mode_name] = round(
                    baselines[mode_name].get("adjusted_total_cost", 0), 2
                )

        return {
            "hybrid_cost": round(hybrid_cost, 2),
            "best_baseline": best_baseline,
            "best_baseline_cost": round(best_cost, 2),
            "savings": round(savings, 2),
            "savings_pct": round(savings_pct, 1),
            "all_baselines": all_baselines,
        }

    def _analyze_today_variance(
        self, intervals: List[Dict], plan_total: float, predicted_total: float
    ) -> str:
        """
        Analyze today's variance from plan and generate human-readable explanation.

        Compares planned vs actual for completed intervals, identifies biggest impacts.

        Returns:
            Human-readable text explaining what happened and why costs differ from plan.
        """
        # Separate completed intervals
        completed = [i for i in intervals if i.get("actual")]

        if not completed:
            return f"Dnes plánujeme utratit {plan_total:.0f} Kč. Den právě začal, zatím žádná data."

        # Aggregate planned vs actual metrics
        total_plan_solar = sum(
            i.get("planned", {}).get("solar_kwh", 0) for i in completed
        )
        total_actual_solar = sum(
            i.get("actual", {}).get("solar_kwh", 0) for i in completed
        )

        total_plan_load = sum(
            i.get("planned", {}).get("load_kwh", 0) for i in completed
        )
        total_actual_load = sum(
            i.get("actual", {}).get("load_kwh", 0) for i in completed
        )

        # Calculate variances
        solar_diff = total_actual_solar - total_plan_solar
        load_diff = total_actual_load - total_plan_load
        cost_diff = predicted_total - plan_total

        # Build explanation
        text = f"Měli jsme naplánováno {plan_total:.0f} Kč, ale vypadá to na {predicted_total:.0f} Kč"

        if abs(cost_diff) >= 1:
            text += f" ({cost_diff:+.0f} Kč).\n"
        else:
            text += " (přesně dle plánu).\n"

        # Solar variance
        if abs(solar_diff) >= 0.5:
            text += f"Slunce svítilo o {abs(solar_diff):.1f} kWh {'VÍC' if solar_diff > 0 else 'MÉNĚ'} než odhad (plán: {total_plan_solar:.1f} kWh, real: {total_actual_solar:.1f} kWh).\n"

        # Load variance
        if abs(load_diff) >= 0.5:
            text += f"Spotřeba byla o {abs(load_diff):.1f} kWh {'VĚTŠÍ' if load_diff > 0 else 'MENŠÍ'} (plán: {total_plan_load:.1f} kWh, real: {total_actual_load:.1f} kWh).\n"

        # Identify biggest impact
        solar_cost_impact = abs(solar_diff) * 4.0  # rough estimate Kč/kWh
        load_cost_impact = abs(load_diff) * 4.0

        if solar_cost_impact > load_cost_impact and abs(solar_diff) >= 0.5:
            text += f"Největší dopad: {'menší' if solar_diff < 0 else 'větší'} solární výroba ({solar_cost_impact:+.0f} Kč)."
        elif abs(load_diff) >= 0.5:
            text += f"Největší dopad: {'vyšší' if load_diff > 0 else 'nižší'} spotřeba ({load_cost_impact:+.0f} Kč)."

        return text

    async def _analyze_yesterday_performance(self) -> str:
        """
        Analyze yesterday's performance - post-mortem of plan vs actual.

        Returns:
            Human-readable explanation of what happened yesterday and biggest variances.
        """
        now = dt_util.now()
        yesterday = (now - timedelta(days=1)).date()

        yesterday_timeline = await self._build_day_timeline(yesterday)
        if not yesterday_timeline:
            return "Včera: Žádná data k dispozici."

        intervals = yesterday_timeline.get("intervals", [])
        if not intervals:
            return "Včera: Žádné intervaly."

        # Aggregate full day
        total_plan_solar = sum(
            i.get("planned", {}).get("solar_kwh", 0) for i in intervals
        )
        total_actual_solar = sum(
            i.get("actual", {}).get("solar_kwh", 0)
            for i in intervals
            if i.get("actual")
        )

        total_plan_load = sum(
            i.get("planned", {}).get("load_kwh", 0) for i in intervals
        )
        total_actual_load = sum(
            i.get("actual", {}).get("load_kwh", 0) for i in intervals if i.get("actual")
        )

        total_plan_cost = sum(
            i.get("planned", {}).get("net_cost", 0) for i in intervals
        )
        total_actual_cost = sum(
            i.get("actual", {}).get("net_cost", 0) for i in intervals if i.get("actual")
        )

        cost_diff = total_actual_cost - total_plan_cost
        solar_diff = total_actual_solar - total_plan_solar
        load_diff = total_actual_load - total_plan_load

        # Build text
        text = f"Včera jsme plánovali {total_plan_cost:.0f} Kč, utratili jsme {total_actual_cost:.0f} Kč"

        if abs(cost_diff) >= 1:
            text += f" ({cost_diff:+.0f} Kč).\n"
        else:
            text += " (přesně dle plánu).\n"

        if abs(solar_diff) >= 0.5:
            text += f"Solární výroba: plán {total_plan_solar:.1f} kWh, real {total_actual_solar:.1f} kWh ({solar_diff:+.1f} kWh).\n"

        if abs(load_diff) >= 0.5:
            text += f"Spotřeba: plán {total_plan_load:.1f} kWh, real {total_actual_load:.1f} kWh ({load_diff:+.1f} kWh).\n"

        # Biggest impacts
        impacts = []
        if abs(solar_diff) >= 0.5:
            impacts.append(
                f"{'menší' if solar_diff < 0 else 'větší'} solár ({abs(solar_diff) * 4:.0f} Kč)"
            )
        if abs(load_diff) >= 0.5:
            impacts.append(
                f"{'vyšší' if load_diff > 0 else 'nižší'} spotřeba ({abs(load_diff) * 4:.0f} Kč)"
            )

        if impacts:
            text += f"Největší dopad: {', '.join(impacts)}."

        return text

    async def _analyze_tomorrow_plan(self) -> str:
        """
        Analyze tomorrow's plan - expected production, consumption, charging, battery state.

        Returns:
            Human-readable explanation of tomorrow's plan and expectations.
        """
        now = dt_util.now()
        tomorrow = (now + timedelta(days=1)).date()

        tomorrow_timeline = await self._build_day_timeline(tomorrow)
        if not tomorrow_timeline:
            return "Zítra: Žádný plán k dispozici."

        intervals = tomorrow_timeline.get("intervals", [])
        if not intervals:
            return "Zítra: Žádné intervaly naplánované."

        # Aggregate planned metrics - PHASE 3.0 FIX: Use safe_nested_get
        total_solar = sum(
            safe_nested_get(i, "planned", "solar_kwh", default=0) for i in intervals
        )
        total_load = sum(
            safe_nested_get(i, "planned", "load_kwh", default=0) for i in intervals
        )
        total_cost = sum(
            safe_nested_get(i, "planned", "net_cost", default=0) for i in intervals
        )

        # Find charging intervals (HOME_UPS mode)
        charging_intervals = [
            i for i in intervals if safe_nested_get(i, "planned", "mode") == "HOME_UPS"
        ]
        total_charging = sum(
            safe_nested_get(i, "planned", "grid_charge_kwh", default=0)
            for i in charging_intervals
        )

        # Get last interval battery state
        last_interval = intervals[-1] if intervals else None
        final_battery = (
            safe_nested_get(last_interval, "planned", "battery_kwh", default=0)
            if last_interval
            else 0
        )
        final_battery_pct = (
            (final_battery / 10.0 * 100) if final_battery else 0
        )  # assuming 10 kWh capacity

        # Build text
        text = f"Zítra plánujeme {total_cost:.0f} Kč.\n"
        text += f"Očekávaná solární výroba: {total_solar:.1f} kWh"

        if total_solar < 5:
            text += " (zataženo)"
        elif total_solar > 15:
            text += " (slunečno)"
        text += ".\n"

        text += f"Očekávaná spotřeba: {total_load:.1f} kWh.\n"

        if total_charging >= 0.5:
            avg_charging_price = (
                sum(
                    i.get("planned", {}).get("spot_price", 0)
                    for i in charging_intervals
                )
                / len(charging_intervals)
                if charging_intervals
                else 0
            )
            text += f"Plánované nabíjení: {total_charging:.1f} kWh v noci (průměr {avg_charging_price:.1f} Kč/kWh).\n"

        text += f"Stav baterie na konci dne: {final_battery:.1f} kWh ({final_battery_pct:.0f}%)."

        return text

    async def _build_today_cost_data(self) -> Dict[str, Any]:  # noqa: C901
        """
        Build today's cost data with actual vs plan tracking.

        UCT-BE-002: Implementovat _build_today_cost_data()
        """
        now = dt_util.now()
        today = now.date()

        # Load storage plans for timeline building
        storage_plans = {}
        if self._plans_store:
            try:
                storage_plans = await self._plans_store.async_load() or {}
            except Exception as e:
                _LOGGER.warning(f"Failed to load storage plans: {e}")
                storage_plans = {}

        # Get today's timeline
        today_timeline = await self._build_day_timeline(today, storage_plans)
        _LOGGER.info(
            f"[UCT] _build_day_timeline returned: type={type(today_timeline)}, value={today_timeline is not None}"
        )
        if not today_timeline:
            _LOGGER.warning("_build_day_timeline returned None for today")
            today_timeline = {}
        intervals = today_timeline.get("intervals", [])
        _LOGGER.info(f"[UCT] Intervals count: {len(intervals)}")

        # Extract spot prices for today (for minigraph visualization)
        spot_prices_today = []
        if self.coordinator and self.coordinator.data:
            spot_data = self.coordinator.data.get("spot_prices", {})
            timeline = spot_data.get("timeline", [])

            if timeline:
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = now.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )

                for sp in timeline:
                    sp_time_str = sp.get("time", "")
                    if not sp_time_str:
                        continue

                    sp_time = datetime.fromisoformat(sp_time_str)
                    if sp_time.tzinfo is None:
                        sp_time = dt_util.as_local(sp_time)

                    if today_start <= sp_time <= today_end:
                        spot_prices_today.append(
                            {
                                "time": sp_time_str,
                                "price": sp.get("spot_price_czk", 0.0),
                            }
                        )

                _LOGGER.info(
                    f"[UCT] Extracted {len(spot_prices_today)} spot prices for today"
                )

        if not intervals:
            return {
                "plan_total_cost": 0.0,
                "actual_total_cost": 0.0,
                "delta": 0.0,
                "performance": "on_plan",
                "completed_intervals": 0,
                "total_intervals": 0,
                "progress_pct": 0,
                "eod_prediction": {
                    "predicted_total": 0.0,
                    "vs_plan": 0.0,
                    "confidence": "low",
                },
                "spot_prices_today": spot_prices_today,
            }

        # Separate completed vs future intervals
        completed = []
        future = []
        active = None

        current_minute = (now.minute // 15) * 15
        current_interval_time = now.replace(
            minute=current_minute, second=0, microsecond=0
        )

        # Konec dnešního dne (půlnoc)
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        for interval in intervals:
            # PHASE 3.0 FIX: Skip None intervals
            if interval is None:
                continue

            # PHASE 3.0 FIX: Type check
            if not isinstance(interval, dict):
                continue

            interval_time_str = interval.get("time", "")
            if not interval_time_str:
                continue

            interval_time = datetime.fromisoformat(interval_time_str)
            if interval_time.tzinfo is None:
                interval_time = dt_util.as_local(interval_time)

            # Skip intervals after midnight (patří do zítřka)
            if interval_time > end_of_today:
                continue

            # Compare naive datetimes to avoid timezone issues
            interval_time_naive = (
                interval_time.replace(tzinfo=None)
                if interval_time.tzinfo
                else interval_time
            )
            current_interval_naive = (
                current_interval_time.replace(tzinfo=None)
                if current_interval_time.tzinfo
                else current_interval_time
            )

            if interval_time_naive < current_interval_naive:
                if interval.get("actual"):
                    completed.append(interval)
            elif interval_time_naive == current_interval_naive:
                active = interval
            else:
                future.append(interval)

        # Calculate totals - PHASE 3.0 FIX: Use safe_get_cost helper
        completed = [c for c in completed if c is not None]
        future = [f for f in future if f is not None]

        # PHASE 3.0 FIX: Safe sum with None handling
        def safe_get_cost(interval: Dict[str, Any], key: str) -> float:
            """Safely get cost from interval, handling None values."""
            data = interval.get(key)
            if data is None:
                return 0.0
            if isinstance(data, dict):
                return float(data.get("net_cost", 0))
            return 0.0

        plan_completed = sum(safe_get_cost(c, "planned") for c in completed)
        actual_completed = sum(safe_get_cost(c, "actual") for c in completed)

        _LOGGER.debug(
            f"💰 Cost calculation: plan_completed={plan_completed:.2f}, "
            f"actual_completed={actual_completed:.2f}, "
            f"completed_count={len(completed)}"
        )
        if completed:
            first = completed[0]
            _LOGGER.debug(
                f"   First completed: plan={safe_nested_get(first, 'planned', 'net_cost', default=0):.2f}, "
                f"actual={safe_nested_get(first, 'actual', 'net_cost', default=0):.2f}"
            )

        plan_future = sum(
            safe_nested_get(f, "planned", "net_cost", default=0) for f in future
        )
        if active:
            plan_future += safe_nested_get(active, "planned", "net_cost", default=0)

        plan_total = plan_completed + plan_future
        actual_total = actual_completed  # Skutečnost jen za completed

        delta = actual_completed - plan_completed

        # Performance classification (±2% tolerance)
        if plan_completed > 0:
            delta_pct = (delta / plan_completed) * 100
            if delta_pct < -2:
                performance = "better"
            elif delta_pct > 2:
                performance = "worse"
            else:
                performance = "on_plan"
        else:
            performance = "on_plan"

        # Progress - % času dne (nikoli % intervalů!)
        now_time = now.time()
        seconds_since_midnight = (
            now_time.hour * 3600 + now_time.minute * 60 + now_time.second
        )
        total_seconds_in_day = 24 * 3600
        progress_pct = seconds_since_midnight / total_seconds_in_day * 100

        total_intervals = len(intervals)
        completed_count = len(completed)

        # EOD = actual (dosud) + plánované budoucí náklady
        eod_predicted = actual_completed + plan_future
        eod_vs_plan = eod_predicted - plan_total

        # Confidence based on how much data we have
        if completed_count < 10:
            confidence = "low"
        elif completed_count < 48:
            confidence = "medium"
        else:
            confidence = "high"

        # Calculate savings vs HOME I (v2.1 requirement)
        plan_savings_completed = sum(
            c.get("planned", {}).get("savings_vs_home_i", 0) for c in completed
        )
        actual_savings_completed = sum(
            c.get("actual", {}).get("savings_vs_home_i", 0) for c in completed
        )
        plan_savings_future = sum(
            f.get("planned", {}).get("savings_vs_home_i", 0) for f in future
        )
        if active:
            plan_savings_future += active.get("planned", {}).get("savings_vs_home_i", 0)

        plan_savings_total = plan_savings_completed + plan_savings_future
        # ZMĚNA: Používáme plán pro budoucí úspory, ne drift
        predicted_savings = actual_savings_completed + plan_savings_future

        # Count mode switches and blocks (v2.1 metadata requirement)
        mode_switches = 0
        total_blocks = 0
        last_mode = None
        for interval in intervals:
            current_mode = interval.get("planned", {}).get("mode", "")
            if current_mode != last_mode:
                if last_mode is not None:
                    mode_switches += 1
                total_blocks += 1
                last_mode = current_mode

        # Calculate partial performance for active interval (v2.1 requirement)
        active_interval_data = None
        if active:
            interval_time_str = active.get("time", "")
            if interval_time_str:
                interval_time = datetime.fromisoformat(interval_time_str)
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)

                duration_minutes = active.get("duration_minutes", 120)
                elapsed_minutes = int((now - interval_time).total_seconds() / 60)
                interval_progress_pct = min(
                    100, max(0, (elapsed_minutes / duration_minutes) * 100)
                )

                # Get planned values
                planned_cost = active.get("planned", {}).get("net_cost", 0)
                planned_savings = active.get("planned", {}).get("savings", 0)

                # Expected values at current progress
                expected_cost = planned_cost * (interval_progress_pct / 100)
                expected_savings = planned_savings * (interval_progress_pct / 100)

                # Get actual values so far (if available)
                actual_data = active.get("actual") or {}
                actual_cost_so_far = actual_data.get("net_cost", expected_cost)
                actual_savings_so_far = actual_data.get("savings", expected_savings)

                # Calculate partial performance
                cost_delta = actual_cost_so_far - expected_cost
                cost_delta_pct = (
                    (cost_delta / expected_cost * 100) if expected_cost > 0 else 0
                )

                if cost_delta < -0.5:
                    active_interval_performance = "better"
                elif cost_delta > 0.5:
                    active_interval_performance = "worse"
                else:
                    active_interval_performance = "on_plan"

                active_interval_data = {
                    "time": interval_time_str,
                    "duration_minutes": duration_minutes,
                    "elapsed_minutes": elapsed_minutes,
                    "progress_pct": round(interval_progress_pct, 1),
                    "planned_cost": round(planned_cost, 2),
                    "planned_savings": round(planned_savings, 2),
                    "expected_cost_at_progress": round(expected_cost, 2),
                    "expected_savings_at_progress": round(expected_savings, 2),
                    "actual_cost_so_far": round(actual_cost_so_far, 2),
                    "actual_savings_so_far": round(actual_savings_so_far, 2),
                    "cost_delta": round(cost_delta, 2),
                    "cost_delta_pct": round(cost_delta_pct, 1),
                    "performance": active_interval_performance,
                }

        # FÁZE 1 - Nové metriky pro FE (BE-centralizace)
        # remaining_to_eod = zbývající PLÁNOVANÉ náklady (ne predikce!)
        remaining_to_eod = plan_future
        vs_plan_pct = (eod_vs_plan / plan_total * 100) if plan_total > 0 else 0.0

        # Performance klasifikace (±2% tolerance)
        if vs_plan_pct <= -2:
            performance_class = "better"
            performance_icon = "✅"
        elif vs_plan_pct >= 2:
            performance_class = "worse"
            performance_icon = "❌"
        else:
            performance_class = "on_plan"
            performance_icon = "⚪"

        # FÁZE 1.2 - Seskupené intervaly podle režimů
        completed_groups = self._group_intervals_by_mode(completed, "completed")
        future_groups = self._group_intervals_by_mode(future, "planned")

        # Active group (pokud existuje)
        active_group = None
        if active is not None:
            active_groups = self._group_intervals_by_mode([active], "both")
            if active_groups:
                active_group = active_groups[0]

        # PHASE 2.10: Baseline comparison for cost tile
        baseline_comparison = self._build_baseline_comparison(plan_total)

        # Generate human-readable tooltips for cost analysis
        today_tooltip = self._analyze_today_variance(
            intervals, plan_total, eod_predicted
        )
        yesterday_tooltip = await self._analyze_yesterday_performance()
        tomorrow_tooltip = await self._analyze_tomorrow_plan()

        return {
            "plan_total_cost": round(plan_total, 2),
            "actual_total_cost": round(actual_total, 2),
            "delta": round(delta, 2),
            "blended_total_cost": round(actual_completed + plan_future, 2),
            "actual_cost_so_far": round(actual_completed, 2),
            "performance": performance,
            "completed_intervals": completed_count,
            "total_intervals": total_intervals,
            "progress_pct": round(progress_pct, 1),
            "eod_prediction": {
                "predicted_total": round(eod_predicted, 2),
                "vs_plan": round(eod_vs_plan, 2),
                "confidence": confidence,
                "predicted_savings": round(predicted_savings, 2),
                "planned_savings": round(plan_savings_total, 2),
            },
            # FÁZE 1 - Nové metriky
            "remaining_to_eod": round(remaining_to_eod, 2),
            "future_plan_cost": round(plan_future, 2),
            "future_plan_savings": round(plan_savings_future, 2),
            "vs_plan_pct": round(vs_plan_pct, 1),
            "performance_class": performance_class,
            "performance_icon": performance_icon,
            # PHASE 2.10 - Baseline comparison
            "baseline_comparison": baseline_comparison,
            # Spot prices for visualization (minigraph)
            "spot_prices_today": spot_prices_today,
            # Human-readable tooltips
            "tooltips": {
                "today": today_tooltip,
                "yesterday": yesterday_tooltip,
                "tomorrow": tomorrow_tooltip,
            },
            # FÁZE 1.2 - Seskupené intervaly
            "completed_groups": completed_groups,
            "active_group": active_group,
            "future_groups": future_groups,
            "completed_so_far": {
                "actual_cost": round(actual_completed, 2),
                "planned_cost": round(plan_completed, 2),
                "delta_cost": round(delta, 2),
                "delta_pct": round(delta_pct if plan_completed > 0 else 0, 1),
                "actual_savings": round(actual_savings_completed, 2),
                "planned_savings": round(plan_savings_completed, 2),
                "performance": performance,
            },
            "active_interval": active_interval_data,
            "metadata": {
                "mode_switches": mode_switches,
                "total_blocks": total_blocks,
                "completed_intervals": completed_count,
                "active_intervals": 1 if active else 0,
                "future_intervals": len(future),
            },
        }

    async def _backfill_daily_archive_from_storage(self) -> None:
        """
        Backfill daily plans archive from storage detailed plans.

        PHASE 3.1: Zpětné doplnění archivu z již uložených daily plans.
        Použije se při startu, pokud archiv chybí (např. po restartu před implementací persistence).
        """
        if not self._plans_store:
            _LOGGER.warning("Cannot backfill - no storage helper")
            return

        try:
            storage_data = await self._plans_store.async_load() or {}
            detailed_plans = storage_data.get("detailed", {})

            if not detailed_plans:
                _LOGGER.info("No detailed plans in storage - nothing to backfill")
                return

            now = dt_util.now()

            # Backfill posledních 7 dní (kromě dneška)
            backfilled_count = 0
            for days_ago in range(1, 8):  # 1-7 dní zpátky
                date = (now.date() - timedelta(days=days_ago)).strftime(DATE_FMT)

                # Skip if already in archive
                if date in self._daily_plans_archive:
                    continue

                # Check if we have this date in detailed plans
                if date in detailed_plans:
                    plan_data = detailed_plans[date]
                    intervals = plan_data.get("intervals", [])

                    # Build daily_plan_state structure from detailed plan
                    self._daily_plans_archive[date] = {
                        "date": date,
                        "plan": intervals,
                        "actual": intervals,  # Pro starší dny nemáme rozlišení plan vs actual
                        "created_at": plan_data.get("created_at"),
                    }
                    backfilled_count += 1
                    _LOGGER.debug(
                        f"Backfilled archive for {date} from storage ({len(intervals)} intervals)"
                    )

            if backfilled_count > 0:
                _LOGGER.info(f"✅ Backfilled {backfilled_count} days into archive")

                # Save updated archive back to storage
                storage_data["daily_archive"] = self._daily_plans_archive
                await self._plans_store.async_save(storage_data)
                _LOGGER.info("💾 Saved backfilled archive to storage")
            else:
                _LOGGER.debug("No days needed backfilling")

        except Exception as e:
            _LOGGER.error(f"Failed to backfill daily archive: {e}", exc_info=True)

    def _get_yesterday_cost_from_archive(self) -> Dict[str, Any]:
        """
        Get yesterday's cost data from archive.

        UCT-BE-003: Implementovat _get_yesterday_cost_from_archive()
        DŮLEŽITÉ: Bereme z archivu, NEPOČÍTÁME!
        """
        yesterday = (dt_util.now().date() - timedelta(days=1)).strftime(DATE_FMT)

        # Get from archive
        if yesterday in self._daily_plans_archive:
            archive_data = self._daily_plans_archive[yesterday]
            actual_intervals = archive_data.get("actual", [])

            # Calculate from archived data
            plan_total = sum(
                self._resolve_interval_cost(interval, prefer_actual=False)
                for interval in archive_data.get("plan", [])
            )
            actual_total = sum(
                self._resolve_interval_cost(interval, prefer_actual=True)
                for interval in actual_intervals
            )
            delta = actual_total - plan_total

            # Performance classification
            if plan_total > 0:
                delta_pct = (delta / plan_total) * 100
                if delta_pct < -2:
                    performance = "better"
                    performance_icon = "✅"
                elif delta_pct > 2:
                    performance = "worse"
                    performance_icon = "❌"
                else:
                    performance = "on_plan"
                    performance_icon = "⚪"
            else:
                performance = "on_plan"
                performance_icon = "⚪"
                delta_pct = 0.0

            # FÁZE 2 - Mode statistiky a skupiny
            mode_groups = self._group_intervals_by_mode(actual_intervals, "completed")

            # Helper: normalizace mode na jméno
            def normalize_mode(mode_raw):
                if isinstance(mode_raw, int):
                    return CBB_MODE_NAMES.get(mode_raw, f"Mode {mode_raw}")
                elif mode_raw:
                    return str(mode_raw).strip()
                return "Unknown"

            # Přidat mode matching statistiky ke každé skupině
            for group in mode_groups:
                # Najít originální intervaly pro tuto skupinu
                group_intervals = [
                    iv
                    for iv in actual_intervals
                    if iv is not None
                    and (
                        normalize_mode((iv.get("actual") or {}).get("mode"))
                        == group["mode"]
                        or normalize_mode((iv.get("planned") or {}).get("mode"))
                        == group["mode"]
                    )
                ]

                mode_matches = sum(
                    1
                    for iv in group_intervals
                    if normalize_mode((iv.get("actual") or {}).get("mode"))
                    == normalize_mode((iv.get("planned") or {}).get("mode"))
                )
                mode_mismatches = len(group_intervals) - mode_matches
                adherence_pct = (
                    (mode_matches / len(group_intervals) * 100)
                    if len(group_intervals) > 0
                    else 0.0
                )

                group["mode_matches"] = mode_matches
                group["mode_mismatches"] = mode_mismatches
                group["adherence_pct"] = round(adherence_pct, 1)

            # Celková shoda režimů
            total_matches = sum(
                1
                for iv in actual_intervals
                if iv is not None
                and normalize_mode((iv.get("actual") or {}).get("mode"))
                == normalize_mode((iv.get("planned") or {}).get("mode"))
            )
            mode_adherence_pct = (
                (total_matches / len(actual_intervals) * 100)
                if len(actual_intervals) > 0
                else 0.0
            )

            # Top 3 největší odchylky
            variances = []
            for iv in actual_intervals:
                planned_cost = iv.get("planned", {}).get("net_cost", 0)
                actual_cost = iv.get("actual", {}).get("net_cost", 0)
                variance = actual_cost - planned_cost
                if abs(variance) > 0.5:  # Jen významné odchylky
                    variances.append(
                        {
                            "time": iv.get("time", ""),
                            "planned": round(planned_cost, 2),
                            "actual": round(actual_cost, 2),
                            "variance": round(variance, 2),
                            "variance_pct": round(
                                (
                                    (variance / planned_cost * 100)
                                    if planned_cost > 0
                                    else 0
                                ),
                                1,
                            ),
                        }
                    )

            # Seřadit podle absolutní velikosti odchylky
            variances.sort(key=lambda x: abs(x["variance"]), reverse=True)
            top_variances = variances[:3]

            return {
                "plan_total_cost": round(plan_total, 2),
                "actual_total_cost": round(actual_total, 2),
                "delta": round(delta, 2),
                "performance": performance,
                # FÁZE 2 - Nové metriky
                "performance_icon": performance_icon,
                "vs_plan_pct": round(delta_pct, 1),
                "mode_groups": mode_groups,
                "mode_adherence_pct": round(mode_adherence_pct, 1),
                "top_variances": top_variances,
            }
        else:
            # No archive data
            return {
                "plan_total_cost": 0.0,
                "actual_total_cost": 0.0,
                "delta": 0.0,
                "performance": "on_plan",
                "note": "No archive data available",
            }

    def _resolve_interval_cost(
        self, interval: Optional[Dict[str, Any]], prefer_actual: bool = True
    ) -> float:
        """Extract or derive interval cost from archived payload."""

        if not interval:
            return 0.0

        payload_candidates: List[Optional[Dict[str, Any]]] = []
        if isinstance(interval, dict):
            if prefer_actual:
                payload_candidates.append(interval.get("actual"))
                payload_candidates.append(
                    interval if not interval.get("actual") else None
                )
                payload_candidates.append(interval.get("planned"))
            else:
                payload_candidates.append(interval.get("planned"))
                payload_candidates.append(
                    interval if not interval.get("planned") else None
                )
                payload_candidates.append(interval.get("actual"))
        else:
            payload_candidates.append(interval)  # type: ignore[arg-type]

        for payload in payload_candidates:
            if not payload or not isinstance(payload, dict):
                continue
            value = payload.get("net_cost")
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

            # Derive from energy + price data if available
            grid_import = payload.get("grid_import_kwh", payload.get("grid_import"))
            grid_export = payload.get("grid_export_kwh", payload.get("grid_export"))
            spot_price = payload.get("spot_price_czk", payload.get("spot_price"))
            export_price = payload.get("export_price_czk", payload.get("export_price"))

            if grid_import is not None and spot_price is not None:
                try:
                    import_cost = float(grid_import) * float(spot_price)
                    export_cost = float(grid_export or 0) * float(export_price or 0)
                    return round(import_cost - export_cost, 2)
                except (TypeError, ValueError):
                    continue

        return 0.0

    async def _build_tomorrow_cost_data(self) -> Dict[str, Any]:
        """
        Build tomorrow's cost data (plan only).

        UCT-BE-004: Implementovat _build_tomorrow_cost_data()
        """
        tomorrow = dt_util.now().date() + timedelta(days=1)

        # Get tomorrow's timeline
        tomorrow_timeline = await self._build_day_timeline(tomorrow)
        intervals = tomorrow_timeline.get("intervals", [])

        if not intervals:
            return {
                "plan_total_cost": 0.0,
            }

        # Calculate total plan
        plan_total = sum(
            interval.get("planned", {}).get("net_cost", 0) for interval in intervals
        )

        # FÁZE 3 - Mode distribuce a skupiny
        mode_distribution = {}
        for interval in intervals:
            if interval is None:
                continue
            mode_raw = (interval.get("planned") or {}).get("mode", "Unknown")

            # Převést mode ID na jméno
            if isinstance(mode_raw, int):
                mode = CBB_MODE_NAMES.get(mode_raw, f"Mode {mode_raw}")
            elif mode_raw and mode_raw != "Unknown":
                mode = str(mode_raw).strip()
            else:
                mode = "Unknown"

            mode_distribution[mode] = mode_distribution.get(mode, 0) + 1

        # Dominantní režim
        if mode_distribution:
            dominant_mode = max(mode_distribution.items(), key=lambda x: x[1])
            dominant_mode_name = dominant_mode[0]
            dominant_mode_count = dominant_mode[1]
            dominant_mode_pct = (
                (dominant_mode_count / len(intervals) * 100)
                if len(intervals) > 0
                else 0.0
            )
        else:
            dominant_mode_name = "Unknown"
            dominant_mode_count = 0
            dominant_mode_pct = 0.0

        # Seskupené intervaly
        planned_groups = self._group_intervals_by_mode(intervals, "planned")

        return {
            "plan_total_cost": round(plan_total, 2),
            # FÁZE 3 - Nové metriky
            "mode_distribution": mode_distribution,
            "dominant_mode_name": dominant_mode_name,
            "dominant_mode_count": dominant_mode_count,
            "dominant_mode_pct": round(dominant_mode_pct, 1),
            "planned_groups": planned_groups,
        }

    async def _fetch_mode_history_from_recorder(
        self, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        """
        Načíst historical režimy ze senzoru box_prms_mode z HA Recorderu.

        Phase 3.0: Historical Mode Tracking
        - Implementuje Recorder-based historical fetching podle dokumentace
        - "Historical se NEUKLÁDÁ (z Recorderu on-demand)"
        - Načítá změny režimu ze sensor.oig_{box_id}_box_prms_mode

        Args:
            start_time: Začátek periody (timezone-aware)
            end_time: Konec periody (timezone-aware)

        Returns:
            List intervalů s actual modes:
            [
                {
                    "time": "2025-11-06T00:51:44+00:00",
                    "mode_name": MODE_LABEL_HOME_UPS,
                    "mode": 5
                },
                ...
            ]
        """
        if not self._hass:
            _LOGGER.warning("HASS not available, cannot fetch mode history")
            return []

        sensor_id = f"sensor.oig_{self._box_id}_box_prms_mode"

        try:
            from homeassistant.components.recorder import history

            # Načíst změny stavu ze sensoru
            from homeassistant.components.recorder import get_instance

            history_data = await get_instance(self._hass).async_add_executor_job(
                history.state_changes_during_period,
                self._hass,
                start_time,
                end_time,
                sensor_id,
            )

            if not history_data or sensor_id not in history_data:
                _LOGGER.debug(
                    f"No mode history found for {sensor_id} between {start_time} - {end_time}"
                )
                return []

            states = history_data[sensor_id]
            if not states:
                return []

            # Konvertovat stavy na intervaly
            mode_intervals = []
            for state in states:
                mode_name = state.state
                if mode_name in ["unavailable", "unknown", None]:
                    continue

                # Mapovat mode name na mode ID
                mode_id = self._map_mode_name_to_id(mode_name)

                mode_intervals.append(
                    {
                        "time": state.last_changed.isoformat(),
                        "mode_name": mode_name,
                        "mode": mode_id,
                    }
                )

            _LOGGER.debug(
                f"📊 Fetched {len(mode_intervals)} mode changes from Recorder "
                f"for {sensor_id} ({start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%Y-%m-%d %H:%M')})"
            )

            return mode_intervals

        except ImportError:
            _LOGGER.error("Recorder component not available")
            return []
        except Exception as e:
            _LOGGER.error(f"Error fetching mode history from Recorder: {e}")
            return []

    def _map_mode_name_to_id(self, mode_name: str) -> int:
        """
        Mapovat mode name (z sensoru) na mode ID.

        Args:
            mode_name: Např. "Home 1", "Home UPS", "Home 3"

        Returns:
            Mode ID (0-3)
        """
        # Mapping podle CBB_MODE_NAMES constants
        mode_mapping = {
            SERVICE_MODE_HOME_1: CBB_MODE_HOME_I,  # 0
            SERVICE_MODE_HOME_2: CBB_MODE_HOME_II,  # 1
            SERVICE_MODE_HOME_3: CBB_MODE_HOME_III,  # 2
            SERVICE_MODE_HOME_UPS: CBB_MODE_HOME_UPS,  # 3
            # Home 5/6 are not simulated; map them to HOME I without warnings.
            SERVICE_MODE_HOME_5: CBB_MODE_HOME_I,
            SERVICE_MODE_HOME_6: CBB_MODE_HOME_I,
        }

        # Normalizovat string (remove extra spaces, case-insensitive)
        normalized = str(mode_name or "").strip()
        if not normalized:
            return 0
        if normalized.lower() in {"unknown", "neznámý", "neznamy"}:
            # Avoid noisy warning for placeholder/unknown values.
            return 0

        mode_id = mode_mapping.get(normalized)
        if mode_id is None:
            _LOGGER.warning(
                f"Unknown mode name '{mode_name}', using fallback mode ID 0 (HOME I)"
            )
            return 0

        return mode_id

    async def _build_historical_modes_lookup(
        self,
        *,
        day_start: datetime,
        fetch_end: datetime,
        date_str: str,
        source: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Load historical mode changes from Recorder and expand to 15-min intervals."""
        if not self._hass:
            return {}

        mode_history = await self._fetch_mode_history_from_recorder(
            day_start, fetch_end
        )

        mode_changes: list[dict[str, Any]] = []
        for mode_entry in mode_history:
            time_key = mode_entry.get("time", "")
            if not time_key:
                continue
            try:
                dt = datetime.fromisoformat(time_key)
                if dt.tzinfo is None:
                    dt = dt_util.as_local(dt)
                mode_changes.append(
                    {
                        "time": dt,
                        "mode": mode_entry.get("mode"),
                        "mode_name": mode_entry.get("mode_name"),
                    }
                )
            except Exception:
                continue

        mode_changes.sort(key=lambda x: x["time"])

        historical_modes_lookup: Dict[str, Dict[str, Any]] = {}
        interval_time = day_start
        while interval_time <= fetch_end:
            active_mode = None
            for change in mode_changes:
                if change["time"] <= interval_time:
                    active_mode = change
                else:
                    break

            if active_mode:
                interval_time_str = interval_time.strftime(DATETIME_FMT)
                historical_modes_lookup[interval_time_str] = {
                    "time": interval_time_str,
                    "mode": active_mode["mode"],
                    "mode_name": active_mode["mode_name"],
                }

            interval_time += timedelta(minutes=15)

        _LOGGER.debug(
            f"📊 Loaded {len(historical_modes_lookup)} historical mode intervals "
            f"from Recorder for {date_str} ({source}) (expanded from {len(mode_changes)} changes)"
        )
        return historical_modes_lookup

    async def _build_day_timeline(  # noqa: C901
        self, date: date, storage_plans: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """

        Postavit timeline pro jeden den.

        Phase 3.0: Načítá historical MODES z HA Recorderu (on-demand)
        Phase 2.9: Načítá actual_intervals z JSON storage místo z paměti.

        Args:
            date: Datum dne
            storage_plans: Optional Storage Helper data (pro planned intervaly včera)

        Returns:
            Dict s intervals a summary pro daný den
        """
        now = dt_util.now()
        today = now.date()

        # Make day_start and day_end timezone-aware
        day_start = dt_util.as_local(datetime.combine(date, datetime.min.time()))
        day_end = dt_util.as_local(datetime.combine(date, datetime.max.time()))

        intervals: List[Dict[str, Any]] = []
        date_str = date.strftime(DATE_FMT)

        # Určit zdroj dat podle dne
        if date < today:
            # VČERA - pouze historical (načíst z JSON storage)
            source = "historical_only"
        elif date == today:
            # DNES - historical (00:00-NOW) + planned (NOW-23:45)
            source = "mixed"
        else:
            # ZÍTRA - pouze planned
            source = "planned_only"

        # PHASE 3.0: Načíst historical modes z Recorderu (pro včera a dnes)
        historical_modes_lookup = {}
        if source in ["historical_only", "mixed"] and self._hass:
            try:
                # Determine fetch end time
                fetch_end = day_end if source == "historical_only" else now
                historical_modes_lookup = await self._build_historical_modes_lookup(
                    day_start=day_start,
                    fetch_end=fetch_end,
                    date_str=date_str,
                    source=source,
                )

            except Exception as e:
                _LOGGER.error(
                    f"Failed to fetch historical modes from Recorder for {date_str}: {e}"
                )
                historical_modes_lookup = {}

        # Build intervals podle source
        if source == "historical_only":
            # ========================================
            # VČERA - historical modes z Recorderu + planned z Storage
            # Historical modes: Z Recorderu (actual)
            # Planned data: Z Storage Helper (baseline plan)
            # ========================================

            # Pro včera NEMÁME planned data v paměti (optimal_timeline je pro dnes+zítra)
            # ALE máme baseline plan v Storage Helper!

            # Získat planned intervaly z Storage
            planned_intervals_map = {}
            if storage_plans:
                planned_intervals_list = []
                yesterday_plan = storage_plans.get("detailed", {}).get(date_str, {})
                if yesterday_plan and not self._is_baseline_plan_invalid(
                    yesterday_plan
                ):
                    planned_intervals_list = yesterday_plan.get("intervals", [])
                else:
                    archive_day = storage_plans.get("daily_archive", {}).get(
                        date_str, {}
                    )
                    if archive_day and archive_day.get("plan"):
                        planned_intervals_list = archive_day.get("plan", [])
                        archive_plan = {
                            "intervals": planned_intervals_list,
                            "filled_intervals": None,
                        }
                        if self._plans_store and not self._is_baseline_plan_invalid(
                            archive_plan
                        ):
                            try:
                                await self._save_plan_to_storage(
                                    date_str,
                                    planned_intervals_list,
                                    {"baseline": True, "filled_intervals": None},
                                )
                                _LOGGER.info(
                                    "Rebuilt baseline plan for %s from daily archive",
                                    date_str,
                                )
                            except Exception as err:
                                _LOGGER.debug(
                                    "Failed to persist archive baseline for %s: %s",
                                    date_str,
                                    err,
                                )
                        else:
                            _LOGGER.info(
                                "Using daily archive plan for %s (baseline invalid)",
                                date_str,
                            )
                    else:
                        planned_intervals_list = yesterday_plan.get("intervals", [])

                # Build lookup table: time -> planned_data
                for planned_entry in planned_intervals_list:
                    time_key = planned_entry.get("time", "")
                    if time_key:
                        # Normalize to full datetime format
                        try:
                            if "T" in time_key:
                                planned_dt = datetime.fromisoformat(
                                    time_key.replace("Z", "+00:00")
                                )
                            else:
                                planned_dt = datetime.combine(
                                    date, datetime.strptime(time_key, "%H:%M").time()
                                )
                            planned_dt = dt_util.as_local(planned_dt)
                            time_str = planned_dt.strftime(DATETIME_FMT)
                            planned_intervals_map[time_str] = planned_entry
                        except Exception:
                            continue

                _LOGGER.debug(
                    f"📊 Loaded {len(planned_intervals_map)} planned intervals "
                    f"from Storage for {date_str}"
                )

            # Build 96 intervalů s historical + planned data
            interval_time = day_start
            while interval_time.date() == date:
                interval_time_str = interval_time.strftime(DATETIME_FMT)

                # Historical mode z Recorderu
                mode_from_recorder = historical_modes_lookup.get(interval_time_str)

                # Planned data z Storage
                planned_from_storage = planned_intervals_map.get(interval_time_str, {})

                # Build interval data
                actual_data = {}
                if mode_from_recorder:
                    # Fetch actual consumption/costs from history
                    interval_end = interval_time + timedelta(minutes=15)
                    historical_metrics = await self._fetch_interval_from_history(
                        interval_time, interval_end
                    )

                    if historical_metrics:
                        actual_data = {
                            "mode": mode_from_recorder.get("mode", 0),
                            "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                            "consumption_kwh": historical_metrics.get(
                                "consumption_kwh", 0
                            ),
                            "solar_kwh": historical_metrics.get("solar_kwh", 0),
                            "battery_soc": historical_metrics.get("battery_soc", 0),
                            "battery_kwh": historical_metrics.get("battery_kwh", 0),
                            "grid_import_kwh": historical_metrics.get(
                                "grid_import",
                                0,  # Function returns "grid_import" not "grid_import_kwh"
                            ),
                            "grid_export_kwh": historical_metrics.get(
                                "grid_export",
                                0,  # Function returns "grid_export" not "grid_export_kwh"
                            ),
                            "net_cost": historical_metrics.get("net_cost", 0),
                            "savings": 0,  # Savings requires baseline comparison
                        }
                    else:
                        # Fallback if history unavailable
                        actual_data = {
                            "mode": mode_from_recorder.get("mode", 0),
                            "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                            "consumption_kwh": 0,
                            "solar_kwh": 0,
                            "battery_soc": 0,
                            "battery_kwh": 0,
                            "grid_import_kwh": 0,
                            "grid_export_kwh": 0,
                            "net_cost": 0,
                            "savings": 0,
                        }

                planned_data = {}
                if planned_from_storage:
                    planned_data = {
                        "mode": planned_from_storage.get("mode", 0),
                        "mode_name": planned_from_storage.get("mode_name", "Unknown"),
                        "consumption_kwh": planned_from_storage.get(
                            "consumption_kwh", 0
                        ),
                        "solar_kwh": planned_from_storage.get("solar_kwh", 0),
                        "battery_soc": planned_from_storage.get("battery_soc", 0),
                        "net_cost": planned_from_storage.get("net_cost", 0),
                    }

                # Mode match detection
                mode_match = None
                if actual_data and planned_data:
                    actual_mode = actual_data.get("mode")
                    planned_mode = planned_data.get("mode")
                    mode_match = actual_mode == planned_mode

                intervals.append(
                    {
                        "time": interval_time_str,
                        "status": "historical",
                        "planned": planned_data,
                        "actual": actual_data,
                        "delta": None,
                        "mode_match": mode_match,
                    }
                )

                interval_time += timedelta(minutes=15)

        elif source == "mixed":
            # ========================================
            # DNES: Historical (Recorder) + Planned (kombinace actual + future)
            # Planned data KOMBINACE:
            #   1. MINULOST: Z uloženého daily plánu (Storage / _daily_plan_state.plan)
            #   2. BUDOUCNOST: Z _timeline_data (aktivní optimalizace)
            # Historical modes: Z Recorderu
            # ========================================

            # Phase 1: Get past planned intervals
            # Priority:
            #   1. Storage Helper (ranní plán uložený v 00:10)
            #   2. Fallback: _daily_plan_state.plan (pokud storage není dostupný / je vadný)
            past_planned = []

            # Try Storage Helper first
            date_str = date.strftime(DATE_FMT)
            storage_day = storage_plans.get("detailed", {}).get(date_str)
            storage_invalid = (
                self._is_baseline_plan_invalid(storage_day) if storage_day else True
            )
            storage_missing = not storage_day or not storage_day.get("intervals")
            if (
                self._plans_store
                and (storage_missing or storage_invalid)
                and date_str not in self._baseline_repair_attempts
            ):
                self._baseline_repair_attempts.add(date_str)
                _LOGGER.info(
                    "Baseline plan missing/invalid for %s, attempting rebuild",
                    date_str,
                )
                try:
                    repaired = await self._create_baseline_plan(date_str)
                except Exception as err:
                    _LOGGER.error(
                        "Baseline rebuild failed for %s: %s",
                        date_str,
                        err,
                        exc_info=True,
                    )
                    repaired = False
                if repaired:
                    try:
                        storage_plans = await self._plans_store.async_load() or {}
                        storage_day = storage_plans.get("detailed", {}).get(date_str)
                        storage_invalid = (
                            self._is_baseline_plan_invalid(storage_day)
                            if storage_day
                            else True
                        )
                    except Exception as err:
                        _LOGGER.error(
                            "Failed to reload baseline plan after rebuild for %s: %s",
                            date_str,
                            err,
                            exc_info=True,
                        )
            if storage_day and storage_day.get("intervals") and not storage_invalid:
                past_planned = storage_day["intervals"]
                _LOGGER.debug(
                    f"📦 Loaded {len(past_planned)} planned intervals from Storage Helper for {date}"
                )
            # Fallback: _daily_plan_state
            elif (
                hasattr(self, "_daily_plan_state")
                and self._daily_plan_state
                and self._daily_plan_state.get("date") == date_str
            ):
                plan_intervals = self._daily_plan_state.get("plan", [])
                if plan_intervals:
                    past_planned = plan_intervals
                    _LOGGER.info(
                        "Using in-memory daily plan for %s (baseline invalid)",
                        date_str,
                    )
                else:
                    actual_intervals = self._daily_plan_state.get("actual", [])
                    for interval in actual_intervals:
                        if interval.get("time"):
                            past_planned.append(interval)
                _LOGGER.debug(
                    f"📋 Loaded {len(past_planned)} intervals from _daily_plan_state for {date}"
                )
            elif storage_day and storage_day.get("intervals"):
                past_planned = storage_day["intervals"]
                _LOGGER.warning(
                    "Using baseline plan for %s despite invalid data (no fallback)",
                    date_str,
                )
            else:
                _LOGGER.debug(f"⚠️  No past planned data available for {date}")

            # Phase 2: Get future planned intervals from active timeline
            future_planned = []
            all_timeline = getattr(self, "_timeline_data", [])
            parse_errors = 0
            wrong_date = 0
            for interval in all_timeline:
                time_str = interval.get("time")
                if time_str:
                    try:
                        interval_dt = datetime.fromisoformat(
                            time_str.replace("Z", "+00:00")
                        )
                        # Keep only intervals from today
                        if interval_dt.date() == date:
                            future_planned.append(interval)
                        else:
                            wrong_date += 1
                    except (ValueError, TypeError):
                        parse_errors += 1
                        continue

            _LOGGER.debug(
                f"📋 Future filter: {len(future_planned)} kept, {wrong_date} wrong_date, "
                f"{parse_errors} parse_errors (from {len(all_timeline)} total)"
            )

            _LOGGER.debug(
                f"📋 Planned data sources for {date}: "
                f"past={len(past_planned)} intervals from daily_plan, "
                f"future={len(future_planned)} intervals from active timeline"
            )

            # Determine current interval
            current_minute = (now.minute // 15) * 15
            current_interval = now.replace(
                minute=current_minute, second=0, microsecond=0
            )
            # Remove timezone for comparison with naive datetimes from timeline
            current_interval_naive = current_interval.replace(tzinfo=None)

            # Phase 3: MERGE - use past_planned for history, future_planned for future
            planned_lookup = {}

            # Add all past planned data (před current_interval)
            for p in past_planned:
                time_str = p.get("time")
                if time_str:
                    try:
                        # Storage uses "HH:MM" format, convert to full datetime
                        if "T" not in time_str:
                            # HH:MM format from storage - prepend date
                            time_str = f"{date_str}T{time_str}:00"

                        interval_dt = datetime.fromisoformat(
                            time_str.replace("Z", "+00:00")
                        )
                        interval_dt_naive = (
                            interval_dt.replace(tzinfo=None)
                            if interval_dt.tzinfo
                            else interval_dt
                        )

                        # Only use past data for intervals BEFORE current
                        if interval_dt_naive < current_interval_naive:
                            # Store with HH:MM:SS format for consistency
                            lookup_key = interval_dt.strftime(DATETIME_FMT)
                            planned_lookup[lookup_key] = p
                    except (ValueError, TypeError):
                        # Fallback: if can't parse, skip it
                        _LOGGER.warning(f"Failed to parse time_str: {time_str}")
                        continue

            # Add future data (od current_interval dál)
            added_future = 0
            skipped_future = 0
            for p in future_planned:
                time_str = p.get("time")
                if time_str:
                    try:
                        interval_dt = datetime.fromisoformat(time_str)
                        # Only use future data for current and future intervals
                        if interval_dt >= current_interval_naive:
                            planned_lookup[time_str] = p
                            added_future += 1
                        else:
                            skipped_future += 1
                    except (ValueError, TypeError) as e:
                        _LOGGER.debug(f"Failed to parse time: {time_str}, error: {e}")
                        continue

            _LOGGER.debug(
                f"📋 Merge stats: added_future={added_future}, skipped_future={skipped_future}, "
                f"current_interval={current_interval_naive}"
            )

            _LOGGER.debug(
                f"📋 Combined planned lookup: {len(planned_lookup)} total intervals for {date}"
            )

            # Build 96 intervals for whole day
            interval_time = day_start
            while interval_time.date() == date:
                interval_time_str = interval_time.strftime(DATETIME_FMT)

                # Determine status (use naive for comparison)
                interval_time_naive = (
                    interval_time.replace(tzinfo=None)
                    if interval_time.tzinfo
                    else interval_time
                )
                if interval_time_naive < current_interval_naive:
                    status = "historical"
                elif interval_time_naive == current_interval_naive:
                    status = "current"
                else:
                    status = "planned"

                # Get planned data (pokud existuje)
                planned_entry = planned_lookup.get(interval_time_str)
                planned_data = None
                if planned_entry:
                    planned_data = self._format_planned_data(planned_entry)

                # Ensure planned_data is never None
                if planned_data is None:
                    planned_data = {}

                # Get actual data (jen pro historical a current)
                actual_data = None
                if status in ("historical", "current"):
                    # Historical mode z Recorderu
                    mode_from_recorder = historical_modes_lookup.get(interval_time_str)
                    if mode_from_recorder:
                        # Fetch actual consumption/costs from history
                        interval_end = interval_time + timedelta(minutes=15)
                        historical_metrics = await self._fetch_interval_from_history(
                            interval_time, interval_end
                        )

                        if historical_metrics:
                            actual_data = {
                                "mode": mode_from_recorder.get("mode", 0),
                                "mode_name": mode_from_recorder.get(
                                    "mode_name", "Unknown"
                                ),
                                "consumption_kwh": historical_metrics.get(
                                    "consumption_kwh", 0
                                ),
                                "solar_kwh": historical_metrics.get("solar_kwh", 0),
                                "battery_soc": historical_metrics.get("battery_soc", 0),
                                "grid_import_kwh": historical_metrics.get(
                                    "grid_import",
                                    0,  # Function returns "grid_import" not "grid_import_kwh"
                                ),
                                "grid_export_kwh": historical_metrics.get(
                                    "grid_export",
                                    0,  # Function returns "grid_export" not "grid_export_kwh"
                                ),
                                "net_cost": historical_metrics.get("net_cost", 0),
                                "savings": 0,  # Savings requires baseline comparison
                            }
                        else:
                            # Fallback if history unavailable
                            actual_data = {
                                "mode": mode_from_recorder.get("mode", 0),
                                "mode_name": mode_from_recorder.get(
                                    "mode_name", "Unknown"
                                ),
                                "consumption_kwh": 0,
                                "solar_kwh": 0,
                                "battery_soc": 0,
                                "grid_import_kwh": 0,
                                "grid_export_kwh": 0,
                                "net_cost": (
                                    planned_data.get("net_cost", 0)
                                    if planned_data
                                    else 0
                                ),
                                "savings": 0,
                            }

                if status == "current":
                    current_mode = self._get_current_mode()
                    current_mode_name = CBB_MODE_NAMES.get(current_mode, "HOME I")
                    current_soc = self._get_current_battery_soc_percent()
                    current_kwh = self._get_current_battery_capacity()

                    if actual_data is None:
                        actual_data = {
                            "consumption_kwh": 0,
                            "solar_kwh": 0,
                            "grid_import_kwh": 0,
                            "grid_export_kwh": 0,
                            "net_cost": 0,
                            "savings": 0,
                        }

                    actual_data["mode"] = current_mode
                    actual_data["mode_name"] = current_mode_name
                    if current_soc is not None:
                        actual_data["battery_soc"] = round(current_soc, 1)
                    if current_kwh is not None:
                        actual_data["battery_kwh"] = round(current_kwh, 2)

                # Přidat interval pokud máme actual NEBO planned
                if actual_data or planned_data:
                    intervals.append(
                        {
                            "time": interval_time_str,
                            "status": status,
                            "planned": planned_data,
                            "actual": actual_data,
                            "delta": None,
                        }
                    )

                interval_time += timedelta(minutes=15)

        elif source == "planned_only":
            # ZÍTRA - planned data z plánovače
            if (
                hasattr(self, "_mode_optimization_result")
                and self._mode_optimization_result
            ):
                optimal_timeline = self._mode_optimization_result.get(
                    "optimal_timeline", []
                )

                for interval in optimal_timeline:
                    interval_time_str = interval.get("time", "")
                    if not interval_time_str:
                        continue

                    try:
                        interval_time = datetime.fromisoformat(interval_time_str)
                        # Make timezone-aware if naive
                        if interval_time.tzinfo is None:
                            interval_time = dt_util.as_local(interval_time)
                    except Exception:
                        continue

                    if day_start <= interval_time <= day_end:
                        intervals.append(
                            {
                                "time": interval_time_str,
                                "status": "planned",
                                "planned": self._format_planned_data(interval),
                                "actual": None,
                                "delta": None,
                            }
                        )

        # Calculate summary
        summary = self._calculate_day_summary(intervals)

        return {
            "date": date.strftime(DATE_FMT),
            "intervals": intervals,
            "summary": summary,
        }

    def _format_planned_data(self, planned: Dict[str, Any]) -> Dict[str, Any]:
        """Formátovat planned data pro API."""

        def _pick(keys, default=0.0):
            for key in keys:
                if key in planned and planned.get(key) is not None:
                    return planned.get(key)
            return default

        battery_kwh = _pick(["battery_kwh", "battery_capacity_kwh", "battery_soc"], 0.0)
        consumption_kwh = _pick(["load_kwh", "consumption_kwh"], 0.0)
        grid_import = _pick(["grid_import", "grid_import_kwh"], 0.0)
        grid_export = _pick(["grid_export", "grid_export_kwh"], 0.0)
        spot_price = _pick(["spot_price", "spot_price_czk"], 0.0)

        return {
            "mode": planned.get("mode", 0),
            "mode_name": planned.get("mode_name", "HOME I"),
            "battery_kwh": round(battery_kwh, 2),
            "solar_kwh": round(_pick(["solar_kwh"], 0.0), 3),
            "consumption_kwh": round(consumption_kwh, 3),
            "grid_import": round(grid_import, 3),
            "grid_export": round(grid_export, 3),
            "spot_price": round(spot_price, 2),
            "net_cost": round(planned.get("net_cost", 0), 2),
            "savings_vs_home_i": round(planned.get("savings_vs_home_i", 0), 2),
            "decision_reason": planned.get("decision_reason"),
            "decision_metrics": planned.get("decision_metrics"),
        }

    def _format_actual_data(
        self, actual: Dict[str, Any], planned: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Formátovat actual data pro API.

        Args:
            actual: Actual data z trackingu
            planned: Planned data pro doplnění chybějících hodnot (optional)
        """
        if not actual:
            return None

        result = {
            "mode": actual.get("mode", 0),
            "mode_name": actual.get("mode_name", "HOME I"),
            "battery_kwh": round(actual.get("battery_kwh", 0), 2),
            "grid_import": round(actual.get("grid_import", 0), 3),
            "grid_export": round(actual.get("grid_export", 0), 3),
            "net_cost": round(actual.get("net_cost", 0), 2),
            "solar_kwh": round(actual.get("solar_kwh", 0), 3),
            "consumption_kwh": round(actual.get("consumption_kwh", 0), 3),
            "spot_price": round(actual.get("spot_price", 0), 2),
            "export_price": round(actual.get("export_price", 0), 2),
        }

        # Savings vs HOME I (pokud je v actual, jinak z planned)
        if "savings_vs_home_i" in actual:
            result["savings_vs_home_i"] = round(actual.get("savings_vs_home_i", 0), 2)
        elif planned:
            result["savings_vs_home_i"] = round(planned.get("savings_vs_home_i", 0), 2)
        else:
            result["savings_vs_home_i"] = 0

        return result

    def _calculate_day_summary(self, intervals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Vypočítat summary pro den."""
        planned_cost = sum(
            i.get("planned", {}).get("net_cost", 0)
            for i in intervals
            if i.get("planned")
        )
        actual_cost = sum(
            i.get("actual", {}).get("net_cost", 0) for i in intervals if i.get("actual")
        )

        historical_count = sum(1 for i in intervals if i.get("status") == "historical")

        delta_cost = actual_cost - planned_cost if historical_count > 0 else None
        accuracy_pct = (
            round((1 - abs(delta_cost) / planned_cost) * 100, 1)
            if planned_cost > 0 and delta_cost is not None
            else None
        )

        return {
            "planned_total_cost": round(planned_cost, 2) if planned_cost > 0 else None,
            "actual_total_cost": round(actual_cost, 2) if actual_cost > 0 else None,
            "delta_cost": round(delta_cost, 2) if delta_cost is not None else None,
            "accuracy_pct": accuracy_pct,
            "intervals_count": len(intervals),
            "historical_count": historical_count,
        }

    def _build_today_tile_summary(
        self, intervals: List[Dict[str, Any]], now: datetime
    ) -> Dict[str, Any]:
        """
        Vytvořit summary pro dlaždici "Dnes - Plnění plánu".

        NOVÉ v Phase 2.9 - pro dlaždici místo 48h okna cen.

        Args:
            intervals: Seznam intervalů pro dnešek
            now: Aktuální čas

        Returns:
            Dict s metrikami pro dlaždici:
            - progress_pct: % dne uběhlo
            - planned_so_far: Plán dosud (00:00 - NOW)
            - actual_so_far: Skutečně dosud
            - delta: Odchylka (Kč)
            - delta_pct: Odchylka (%)
            - eod_prediction: End-of-day predikce
            - eod_plan: EOD plán celkem
            - eod_delta_pct: EOD odchylka (%)
            - mini_chart_data: Data pro mini graf
            - current_time: Aktuální čas (HH:MM)
        """
        if not intervals:
            return self._get_empty_tile_summary(now)

        # Round current time na 15min
        current_minute = (now.minute // 15) * 15
        current_interval_time = now.replace(
            minute=current_minute, second=0, microsecond=0
        )

        # Rozdělit intervaly na historical vs future
        historical = []
        future = []

        for interval in intervals:
            try:
                interval_time_str = interval.get("time", "")
                if not interval_time_str:
                    continue

                interval_time = datetime.fromisoformat(interval_time_str)
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)

                if interval_time < current_interval_time and interval.get("actual"):
                    historical.append(interval)
                else:
                    future.append(interval)
            except Exception:
                continue

        # PHASE 3.0 FIX: Safe cost getter (reuse from _build_today_cost_data)
        def safe_get_cost(interval: Dict[str, Any], key: str) -> float:
            """Safely get cost from interval, handling None values."""
            data = interval.get(key)
            if data is None:
                return 0.0
            if isinstance(data, dict):
                return float(data.get("net_cost", 0))
            return 0.0

        # Spočítat plán vs skutečnost dosud
        planned_so_far = sum(safe_get_cost(h, "planned") for h in historical)
        actual_so_far = sum(safe_get_cost(h, "actual") for h in historical)
        delta = actual_so_far - planned_so_far
        delta_pct = (delta / planned_so_far * 100) if planned_so_far > 0 else 0.0

        # EOD = skutečnost uplynulých + plán budoucích (včetně aktivního)
        planned_future = sum(safe_get_cost(f, "planned") for f in future)
        eod_plan = planned_so_far + planned_future  # Původní celý denní plán

        # NOVÁ LOGIKA: EOD je skutečnost + budoucí plán (BEZ drift ratio)
        eod_prediction = actual_so_far + planned_future
        eod_delta = eod_prediction - eod_plan
        eod_delta_pct = (eod_delta / eod_plan * 100) if eod_plan > 0 else 0.0

        # Progress
        total_intervals = len(intervals)
        historical_count = len(historical)
        progress_pct = (
            (historical_count / total_intervals * 100) if total_intervals > 0 else 0.0
        )

        # Confidence level (pro UI indikátor)
        if progress_pct < 25:
            confidence = "low"
        elif progress_pct < 50:
            confidence = "medium"
        elif progress_pct < 75:
            confidence = "good"
        else:
            confidence = "high"

        # Mini chart data (jen delty pro variance chart)
        mini_chart_data = []
        for interval in intervals:
            interval_time_str = interval.get("time", "")
            if not interval_time_str:
                continue

            try:
                interval_time = datetime.fromisoformat(interval_time_str)
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)

                is_current = (
                    current_interval_time
                    <= interval_time
                    < current_interval_time + timedelta(minutes=15)
                )

                delta_value = None
                if interval.get("actual") and interval.get("delta"):
                    delta_value = interval["delta"].get("net_cost")

                mini_chart_data.append(
                    {
                        "time": interval_time_str,
                        "delta": delta_value,
                        "is_historical": bool(interval.get("actual")),
                        "is_current": is_current,
                    }
                )
            except Exception:
                continue

        return {
            "progress_pct": round(progress_pct, 1),
            "planned_so_far": round(planned_so_far, 2),
            "actual_so_far": round(actual_so_far, 2),
            "delta": round(delta, 2),
            "delta_pct": round(delta_pct, 1),
            "eod_prediction": round(eod_prediction, 2),
            "eod_plan": round(eod_plan, 2),
            "eod_delta": round(eod_delta, 2),
            "eod_delta_pct": round(eod_delta_pct, 1),
            "confidence": confidence,
            "mini_chart_data": mini_chart_data,
            "current_time": now.strftime("%H:%M"),
            "last_updated": now.isoformat(),
            "intervals_total": total_intervals,
            "intervals_historical": historical_count,
            "intervals_future": len(future),
        }

    def _get_empty_tile_summary(self, now: datetime) -> Dict[str, Any]:
        """Prázdné tile summary pokud nejsou data."""
        return {
            "progress_pct": 0.0,
            "planned_so_far": 0.0,
            "actual_so_far": 0.0,
            "delta": 0.0,
            "delta_pct": 0.0,
            "eod_prediction": 0.0,
            "eod_plan": 0.0,
            "eod_delta": 0.0,
            "eod_delta_pct": 0.0,
            "confidence": "none",
            "mini_chart_data": [],
            "current_time": now.strftime("%H:%M"),
            "last_updated": now.isoformat(),
            "intervals_total": 0,
            "intervals_historical": 0,
            "intervals_future": 0,
        }

    # =========================================================================
    # ECONOMIC CHARGING - Nové metody pro ekonomické rozhodování
    # =========================================================================

    def _get_candidate_intervals(
        self,
        timeline: List[Dict[str, Any]],
        max_charging_price: float,
        current_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Získat kandidátní intervaly pro nabíjení.

        Filtruje:
        1. Cena < max_charging_price (pojistka)
        2. Timestamp > now (jen budoucnost)
        3. Seřadí od nejlevnějších

        Args:
            timeline: Timeline data
            max_charging_price: Maximální cena (pojistka)
            current_time: Aktuální čas (nebo None = now)

        Returns:
            Seznam kandidátních intervalů seřazených podle ceny
        """
        if current_time is None:
            current_time = dt_util.now()

        candidates = []

        for i, interval in enumerate(timeline):
            price = interval.get("spot_price_czk", float("inf"))
            timestamp_str = interval.get("timestamp", "")

            # Parse timestamp
            try:
                interval_time = datetime.fromisoformat(
                    timestamp_str.replace("Z", ISO_TZ_OFFSET)
                )
            except Exception:
                continue

            # Filtry
            if price >= max_charging_price:
                continue  # Nad pojistkou

            # Compare naive datetimes to avoid timezone issues
            interval_time_naive = (
                interval_time.replace(tzinfo=None)
                if interval_time.tzinfo
                else interval_time
            )
            current_time_naive = (
                current_time.replace(tzinfo=None)
                if current_time.tzinfo
                else current_time
            )

            if interval_time_naive <= current_time_naive:
                continue  # Minulost

            candidates.append(
                {
                    "index": i,
                    "price": price,
                    "timestamp": timestamp_str,
                    "interval_time": interval_time,
                }
            )

        # Seřadit od nejlevnějších
        candidates.sort(key=lambda x: x["price"])

        if not candidates:
            _LOGGER.warning(
                f"No charging intervals available - all prices above "
                f"max_charging_price ({max_charging_price:.2f} Kč/kWh)"
            )

        return candidates

    def _simulate_forward(
        self,
        timeline: List[Dict[str, Any]],
        start_index: int,
        charge_now: bool,
        charge_amount_kwh: float,
        horizon_hours: int,
        effective_minimum_kwh: float,
        efficiency: float,
    ) -> Dict[str, Any]:
        """
        Forward simulace budoucího SoC.

        Simuluje co se stane s baterií od start_index až +horizon_hours.

        Args:
            timeline: Timeline data
            start_index: Index od kterého simulovat
            charge_now: Nabít v start_index?
            charge_amount_kwh: Kolik nabít (pokud charge_now)
            horizon_hours: Kolik hodin dopředu simulovat
            effective_minimum_kwh: Bezpečné minimum (hard min + safety margin)
            efficiency: Efektivita baterie (0.882)

        Returns:
            Dict s výsledky simulace:
                - total_charging_cost: Celkové náklady na nabíjení
                - min_soc: Nejnižší SoC v horizontu
                - final_soc: Koncové SoC
                - death_valley_reached: True pokud SoC < effective_minimum
                - charging_events: Seznam nabíjecích událostí
        """
        if start_index >= len(timeline):
            return {
                "total_charging_cost": 0,
                "min_soc": 0,
                "final_soc": 0,
                "death_valley_reached": True,
                "charging_events": [],
            }

        # Kopie pro simulaci
        sim_timeline = [dict(point) for point in timeline]

        soc = sim_timeline[start_index].get("battery_capacity_kwh", 0)
        total_cost = 0
        charging_events = []

        # Nabít v prvním intervalu?
        if charge_now and charge_amount_kwh > 0:
            soc += charge_amount_kwh
            price = sim_timeline[start_index].get("spot_price_czk", 0)
            cost = charge_amount_kwh * price
            total_cost += cost

            charging_events.append(
                {
                    "index": start_index,
                    "kwh": charge_amount_kwh,
                    "price": price,
                    "cost": cost,
                    "reason": "scenario_test",
                }
            )

            # Update timeline
            sim_timeline[start_index]["battery_capacity_kwh"] = soc
            sim_timeline[start_index]["grid_charge_kwh"] = charge_amount_kwh

        min_soc = soc
        horizon_intervals = horizon_hours * 4  # 15min intervaly

        # Simulovat následující intervaly
        for i in range(
            start_index + 1, min(start_index + horizon_intervals, len(sim_timeline))
        ):
            prev_soc = sim_timeline[i - 1].get("battery_capacity_kwh", 0)

            # Spočítat změnu SoC podle solar, consumption
            solar_kwh = sim_timeline[i].get("solar_production_kwh", 0)
            load_kwh = sim_timeline[i].get("consumption_kwh", 0)
            grid_kwh = sim_timeline[i].get("grid_charge_kwh", 0)
            reason = sim_timeline[i].get("reason", "")

            # Použít stejnou fyziku jako v hlavní simulaci režimů
            # OPRAVA: Při balancování VŽDY UPS režim
            is_balancing = reason.startswith("balancing_")
            is_ups_mode = grid_kwh > 0 or is_balancing

            if is_ups_mode:
                net_energy = solar_kwh + grid_kwh
            else:
                if solar_kwh >= load_kwh:
                    net_energy = (solar_kwh - load_kwh) + grid_kwh
                else:
                    load_from_battery = load_kwh - solar_kwh
                    battery_drain = load_from_battery / efficiency
                    net_energy = -battery_drain + grid_kwh

            soc = prev_soc + net_energy
            sim_timeline[i]["battery_capacity_kwh"] = soc

            # Track minimum
            min_soc = min(min_soc, soc)

        final_soc = sim_timeline[
            min(start_index + horizon_intervals - 1, len(sim_timeline) - 1)
        ].get("battery_capacity_kwh", 0)
        death_valley_reached = min_soc < effective_minimum_kwh

        return {
            "total_charging_cost": total_cost,
            "min_soc": min_soc,
            "final_soc": final_soc,
            "death_valley_reached": death_valley_reached,
            "charging_events": charging_events,
        }

    def _calculate_minimum_charge(
        self,
        scenario_wait_min_soc: float,
        effective_minimum_kwh: float,
        max_charge_per_interval: float,
    ) -> float:
        """
        Vypočítat minimální potřebné nabití.

        Nabít JEN rozdíl mezi projekcí a bezpečným minimem (ne plnou kapacitu!).

        Args:
            scenario_wait_min_soc: Nejnižší SoC při WAIT scénáři
            effective_minimum_kwh: Bezpečné minimum
            max_charge_per_interval: Max nabití za 15 min

        Returns:
            Kolik kWh nabít (0 pokud není potřeba)
        """
        shortage = effective_minimum_kwh - scenario_wait_min_soc

        if shortage <= 0:
            return 0  # Není potřeba nabíjet

        # Přidat 10% buffer pro nepřesnost predikce
        charge_needed = shortage * 1.1

        # Omezit max nabíjením za interval
        return min(charge_needed, max_charge_per_interval)

    def _calculate_protection_requirement(
        self,
        timeline: List[Dict[str, Any]],
        max_capacity: float,
    ) -> Optional[float]:
        """
        Vypočítat required SoC pro blackout/weather ochranu.

        Args:
            timeline: Timeline data
            max_capacity: Maximální kapacita baterie

        Returns:
            Required SoC v kWh nebo None (pokud vypnuto)
        """
        config = (
            self._config_entry.options
            if self._config_entry.options
            else self._config_entry.data
        )

        required_soc = 0

        # A) Blackout ochrana
        enable_blackout = config.get("enable_blackout_protection", False)
        if enable_blackout:
            blackout_hours = config.get("blackout_protection_hours", 12)
            blackout_target_percent = config.get("blackout_target_soc_percent", 60.0)

            # Spotřeba během blackout period
            current_time = dt_util.now()
            blackout_end = current_time + timedelta(hours=blackout_hours)

            blackout_consumption = 0
            for point in timeline:
                try:
                    timestamp_str = point.get("timestamp", "")
                    point_time = datetime.fromisoformat(
                        timestamp_str.replace("Z", ISO_TZ_OFFSET)
                    )

                    if current_time < point_time <= blackout_end:
                        blackout_consumption += point.get("consumption_kwh", 0)
                except Exception:
                    continue

            blackout_soc = max(
                blackout_consumption, (blackout_target_percent / 100.0) * max_capacity
            )
            required_soc = max(required_soc, blackout_soc)

            _LOGGER.debug(
                f"Blackout protection: required {blackout_soc:.2f} kWh "
                f"(consumption {blackout_consumption:.2f} kWh, target {blackout_target_percent}%)"
            )

        # B) ČHMÚ weather risk
        enable_weather = config.get("enable_weather_risk", False)
        if enable_weather:
            # NOTE: Implementovat až bude sensor.oig_chmu_warning dostupný
            # Pro nyní použít jen target
            weather_target_percent = config.get("weather_target_soc_percent", 70.0)
            weather_soc = (weather_target_percent / 100.0) * max_capacity
            required_soc = max(required_soc, weather_soc)

            _LOGGER.debug(f"Weather risk protection: required {weather_soc:.2f} kWh")

        return required_soc if required_soc > 0 else None

    def _get_battery_efficiency(self) -> float:
        """
        Získat aktuální efektivitu baterie z battery_efficiency sensoru.

        Returns:
            Efektivita jako desetinné číslo (0.882 pro 88.2%)
            Fallback na 0.882 pokud sensor není k dispozici
        """
        if not self._hass:
            _LOGGER.debug("HASS not available, using fallback efficiency 0.882")
            return 0.882

        sensor_id = f"sensor.oig_{self._box_id}_battery_efficiency"
        state = self._hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            # Zakomentováno: Spamuje logy během výpočtu
            # _LOGGER.debug(
            #     f"Battery efficiency sensor {sensor_id} not available, using fallback 0.882"
            # )
            return 0.882

        try:
            # State je v %, převést na desetinné číslo
            efficiency_pct = float(state.state)
            efficiency = efficiency_pct / 100.0

            # Sanity check
            if efficiency < 0.70 or efficiency > 1.0:
                _LOGGER.warning(
                    f"Unrealistic efficiency {efficiency:.3f} ({efficiency_pct}%), using fallback 0.882"
                )
                return 0.882

            # Zakomentováno: Spamuje logy během výpočtu
            # _LOGGER.debug(
            #     f"Using battery efficiency: {efficiency:.3f} ({efficiency_pct}%)"
            # )
            return efficiency

        except (ValueError, TypeError) as e:
            _LOGGER.error(f"Error parsing battery efficiency: {e}")
            return 0.882

    def _get_ac_charging_limit_kwh_15min(self) -> float:
        """
        Získat AC charging limit pro 15min interval z configu.

        Config obsahuje home_charge_rate v kW (hodinový výkon).
        Pro 15min interval: kW / 4 = kWh per 15min

        Example: home_charge_rate = 2.8 kW → 0.7 kWh/15min

        Returns:
            AC charging limit v kWh pro 15min interval
            Default: 2.8 kW → 0.7 kWh/15min
        """
        config = self._config_entry.options if self._config_entry else {}
        charging_power_kw = config.get("home_charge_rate", 2.8)

        # Convert kW to kWh/15min
        limit_kwh_15min = charging_power_kw / 4.0

        # Zakomentováno: Spamuje logy během výpočtu
        # _LOGGER.debug(
        #     f"AC charging limit: {charging_power_kw} kW → {limit_kwh_15min} kWh/15min"
        # )

        return limit_kwh_15min

    def _get_current_mode(self) -> int:
        """
        Získat aktuální CBB režim ze sensoru.

        Čte: sensor.oig_{box_id}_box_prms_mode

        Returns:
            Mode number (0=HOME I, 1=HOME II, 2=HOME III, 3=HOME UPS)
            Default: CBB_MODE_HOME_III (2) pokud sensor není k dispozici
        """
        if not self._hass:
            _LOGGER.debug("HASS not available, using fallback mode HOME III")
            return CBB_MODE_HOME_III

        sensor_id = f"sensor.oig_{self._box_id}_box_prms_mode"
        state = self._hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            _LOGGER.debug(
                f"Mode sensor {sensor_id} not available, using fallback HOME III"
            )
            return CBB_MODE_HOME_III

        try:
            # Sensor může vracet buď int (0-3) nebo string ("Home 1", "Home I", ...)
            mode_value = state.state

            # Pokud je to string, převést na int
            if isinstance(mode_value, str):
                # Mapování string → int (podporuje obě varianty: "Home 1" i "Home I")
                mode_map = {
                    MODE_LABEL_HOME_I: CBB_MODE_HOME_I,
                    MODE_LABEL_HOME_II: CBB_MODE_HOME_II,
                    MODE_LABEL_HOME_III: CBB_MODE_HOME_III,
                    MODE_LABEL_HOME_UPS: CBB_MODE_HOME_UPS,
                    SERVICE_MODE_HOME_1: CBB_MODE_HOME_I,
                    SERVICE_MODE_HOME_2: CBB_MODE_HOME_II,
                    SERVICE_MODE_HOME_3: CBB_MODE_HOME_III,
                    SERVICE_MODE_HOME_5: CBB_MODE_HOME_I,
                    SERVICE_MODE_HOME_6: CBB_MODE_HOME_I,
                }

                if mode_value in mode_map:
                    mode = mode_map[mode_value]
                else:
                    # Zkusit parse jako int
                    mode = int(mode_value)
            else:
                mode = int(mode_value)

            # Validate mode range; Home 5/6 map to HOME I for simulation.
            if mode in (4, 5):
                return CBB_MODE_HOME_I
            if mode not in (
                CBB_MODE_HOME_I,
                CBB_MODE_HOME_II,
                CBB_MODE_HOME_III,
                CBB_MODE_HOME_UPS,
            ):
                _LOGGER.warning(f"Invalid mode {mode}, using fallback HOME III")
                return CBB_MODE_HOME_III

            mode_name = CBB_MODE_NAMES.get(mode, f"UNKNOWN_{mode}")
            _LOGGER.debug(f"Current CBB mode: {mode_name} ({mode})")

            return mode

        except (ValueError, TypeError) as e:
            _LOGGER.error(f"Error parsing CBB mode from '{state.state}': {e}")
            return CBB_MODE_HOME_III

    def _get_boiler_available_capacity(self) -> float:
        """
        Zjistit kolik kWh může bojler přijmout v 15min intervalu.

        Phase 2.5: Boiler support pro přebytkovou energii.

        Pokud je boiler_is_use=on, CBB firmware automaticky směřuje přebytky do bojleru
        až do výše boiler_install_power (kW limit).

        Returns:
            kWh capacity for 15min interval (0 pokud bojler není aktivní)
        """
        if not self._hass:
            return 0.0

        # Check if boiler usage is enabled
        boiler_use_sensor = f"sensor.oig_{self._box_id}_boiler_is_use"
        state = self._hass.states.get(boiler_use_sensor)

        if not state or state.state not in ["on", "1", "true"]:
            # Boiler not active
            return 0.0

        # Get boiler power limit (kW)
        boiler_power_sensor = f"sensor.oig_{self._box_id}_boiler_install_power"
        power_state = self._hass.states.get(boiler_power_sensor)

        if not power_state:
            _LOGGER.warning(
                f"Boiler is enabled but {boiler_power_sensor} not found, using default 2.8 kW"
            )
            # Default to typical 2.8 kW limit (same as AC charging)
            return 0.7  # kWh/15min

        try:
            power_kw = float(power_state.state)
            # Convert kW to kWh/15min
            capacity_kwh_15min = power_kw / 4.0

            _LOGGER.debug(
                f"Boiler available: {power_kw} kW → {capacity_kwh_15min} kWh/15min"
            )

            return capacity_kwh_15min

        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"Error parsing boiler power: {e}, using default 0.7 kWh")
            return 0.7  # Fallback

    def _calculate_final_spot_price(
        self, raw_spot_price: float, target_datetime: datetime
    ) -> float:
        """
        Vypočítat finální spotovou cenu včetně obchodní přirážky, distribuce a DPH.

        KRITICKÉ: Toto je STEJNÝ výpočet jako SpotPrice15MinSensor._calculate_final_price_15min()
        Musí zůstat synchronizovaný!

        Args:
            raw_spot_price: Čistá spotová cena z OTE (Kč/kWh, bez přirážek)
            target_datetime: Datetime pro určení tarifu (VT/NT)

        Returns:
            Finální cena včetně obchodní přirážky, distribuce a DPH (Kč/kWh)
        """
        config = (
            self._config_entry.options
            if self._config_entry.options
            else self._config_entry.data
        )

        # Parametry z konfigurace
        pricing_model = config.get("spot_pricing_model", "percentage")
        positive_fee_percent = config.get("spot_positive_fee_percent", 15.0)
        negative_fee_percent = config.get("spot_negative_fee_percent", 9.0)
        fixed_fee_mwh = config.get("spot_fixed_fee_mwh", 0.0)
        distribution_fee_vt_kwh = config.get("distribution_fee_vt_kwh", 1.50)
        distribution_fee_nt_kwh = config.get("distribution_fee_nt_kwh", 1.20)
        vat_rate = config.get("vat_rate", 21.0)

        # 1. Obchodní cena (spot + přirážka)
        if pricing_model == "percentage":
            if raw_spot_price >= 0:
                commercial_price = raw_spot_price * (1 + positive_fee_percent / 100.0)
            else:
                commercial_price = raw_spot_price * (1 - negative_fee_percent / 100.0)
        else:  # fixed
            fixed_fee_kwh = fixed_fee_mwh / 1000.0
            commercial_price = raw_spot_price + fixed_fee_kwh

        # 2. Tarif pro distribuci (VT/NT)
        current_tariff = self._get_tariff_for_datetime(target_datetime)

        # 3. Distribuční poplatek
        distribution_fee = (
            distribution_fee_vt_kwh
            if current_tariff == "VT"
            else distribution_fee_nt_kwh
        )

        # 4. Cena bez DPH
        price_without_vat = commercial_price + distribution_fee

        # 5. Finální cena s DPH
        final_price = price_without_vat * (1 + vat_rate / 100.0)

        return round(final_price, 2)

    def _get_tariff_for_datetime(self, target_datetime: datetime) -> str:
        """
        Získat tarif (VT/NT) pro daný datetime.

        KRITICKÉ: Kopie logiky z SpotPrice15MinSensor._get_tariff_for_datetime()
        Musí zůstat synchronizovaná!
        """
        config = (
            self._config_entry.options
            if self._config_entry.options
            else self._config_entry.data
        )

        dual_tariff_enabled = config.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            return "VT"

        is_weekend = target_datetime.weekday() >= 5

        if is_weekend:
            nt_times = self._parse_tariff_times(
                config.get("tariff_nt_start_weekend", "0")
            )
            vt_times = self._parse_tariff_times(
                config.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times = self._parse_tariff_times(
                config.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times = self._parse_tariff_times(
                config.get("tariff_vt_start_weekday", "6")
            )

        current_hour = target_datetime.hour
        last_tariff = "NT"
        last_hour = -1

        all_changes = []
        for hour in nt_times:
            all_changes.append((hour, "NT"))
        for hour in vt_times:
            all_changes.append((hour, "VT"))

        all_changes.sort(reverse=True)

        for hour, tariff in all_changes:
            if hour <= current_hour and hour > last_hour:
                last_tariff = tariff
                last_hour = hour

        return last_tariff

    def _parse_tariff_times(self, time_str: str) -> list[int]:
        """Parse tariff times string to list of hours."""
        if not time_str:
            return []
        try:
            return [int(x.strip()) for x in time_str.split(",") if x.strip()]
        except ValueError:
            return []

    async def _get_spot_price_timeline(self) -> List[Dict[str, Any]]:
        """
        Získat timeline spotových cen z coordinator data.

        KRITICKÝ FIX: Vrací FINÁLNÍ ceny včetně obchodní přirážky, distribuce a DPH!
        PŘED: Vracelo jen čistou spot price (2.29 Kč/kWh)
        PO: Vrací finální cenu (4.51 Kč/kWh) = spot + přirážka 15% + distribuce 1.50 Kč/kWh + DPH 21%

        Phase 1.5: Spot prices jsou v coordinator.data["spot_prices"], ne v sensor attributes.
        Sensor attributes obsahují jen summary (current_price, price_min/max/avg).

        Returns:
            List of dicts: [{"time": "2025-10-28T13:15:00", "price": 4.51}, ...]
        """
        if not self.coordinator:
            _LOGGER.warning("Coordinator not available in _get_spot_price_timeline")
            # Continue with fallbacks (sensor/OTE cache) if possible.
            spot_data = {}
        else:
            # Read from coordinator data (Phase 1.5 - lean attributes)
            spot_data = self.coordinator.data.get("spot_prices", {})  # type: ignore[union-attr]

        if not spot_data:
            spot_data = self._get_spot_data_from_price_sensor(price_type="spot") or {}

        if not spot_data and self._hass:
            spot_data = await self._get_spot_data_from_ote_cache() or {}

        if not spot_data:
            _LOGGER.warning("No spot price data available for forecast")
            return []

        # spot_data format: {"prices15m_czk_kwh": {"2025-10-28T13:45:00": 2.29, ...}}
        # Toto je ČISTÁ spotová cena BEZ přirážek, distribuce a DPH!
        raw_prices_dict = spot_data.get("prices15m_czk_kwh", {})

        if not raw_prices_dict:
            # Coordinator payload may contain only hourly prices; try fallbacks that are known
            # to carry 15-minute data.
            fallback = self._get_spot_data_from_price_sensor(price_type="spot") or {}
            if not fallback and self._hass:
                fallback = await self._get_spot_data_from_ote_cache() or {}
            raw_prices_dict = fallback.get("prices15m_czk_kwh", {}) if fallback else {}
            if not raw_prices_dict:
                _LOGGER.warning("No prices15m_czk_kwh in spot price data")
                return []

        # Convert to timeline format WITH FINAL PRICES
        timeline = []
        for timestamp_str, raw_spot_price in sorted(raw_prices_dict.items()):
            try:
                # Validate and parse timestamp
                target_datetime = datetime.fromisoformat(timestamp_str)

                # KRITICKÝ FIX: Vypočítat FINÁLNÍ cenu včetně přirážky, distribuce a DPH
                final_price = self._calculate_final_spot_price(
                    raw_spot_price, target_datetime
                )

                timeline.append({"time": timestamp_str, "price": final_price})

            except ValueError:
                _LOGGER.warning(f"Invalid timestamp in spot prices: {timestamp_str}")
                continue

        _LOGGER.info(
            f"Successfully loaded {len(timeline)} spot price points from coordinator "
            f"(converted from raw spot to final price with distribution + VAT)"
        )
        return timeline

    async def _get_export_price_timeline(self) -> List[Dict[str, Any]]:
        """Získat timeline prodejních cen z coordinator data (Phase 1.5).

        Export prices také v coordinator.data["spot_prices"], protože OTE API vrací obě ceny.
        Sensor attributes obsahují jen summary (current_price, price_min/max/avg).

        Returns:
            List of dicts: [{"time": "2025-10-28T13:15:00", "price": 2.5}, ...]
        """
        if not self.coordinator:
            _LOGGER.warning("Coordinator not available in _get_export_price_timeline")
            spot_data = {}
        else:
            spot_data = self.coordinator.data.get("spot_prices", {})  # type: ignore[union-attr]

        # Prefer coordinator, then sensor internals, then OTE cache.
        if not spot_data:
            spot_data = self._get_spot_data_from_price_sensor(price_type="export") or {}
        if not spot_data:
            spot_data = self._get_spot_data_from_price_sensor(price_type="spot") or {}
        if not spot_data and self._hass:
            spot_data = await self._get_spot_data_from_ote_cache() or {}

        if not spot_data:
            _LOGGER.warning("No spot price data available for export timeline")
            return []

        # Export prices jsou v "export_prices15m_czk_kwh" klíči (stejný formát jako spot)
        # Pokud klíč neexistuje, zkusíme alternativní způsob výpočtu
        export_prices_dict = spot_data.get("export_prices15m_czk_kwh", {})

        if not export_prices_dict:
            # Fallback: Vypočítat z spot prices podle config (percentage model)
            _LOGGER.info("No direct export prices, calculating from spot prices")
            spot_prices_dict = spot_data.get("prices15m_czk_kwh", {})

            if not spot_prices_dict:
                # Coordinator payload may carry only hourly prices; try 15m fallbacks.
                fallback = (
                    self._get_spot_data_from_price_sensor(price_type="spot") or {}
                )
                if not fallback and self._hass:
                    fallback = await self._get_spot_data_from_ote_cache() or {}
                spot_prices_dict = (
                    fallback.get("prices15m_czk_kwh", {})
                    if isinstance(fallback, dict)
                    else {}
                )
                if not spot_prices_dict:
                    _LOGGER.warning("No prices15m_czk_kwh for export price calculation")
                    return []

            # Get export pricing config from coordinator
            config_entry = self.coordinator.config_entry if self.coordinator else None
            config = config_entry.options if config_entry else {}
            export_model = config.get("export_pricing_model", "percentage")
            export_fee = config.get("export_fee_percent", 15.0)

            # Calculate export prices (spot price * (1 - fee/100))
            export_prices_dict = {}
            for timestamp_str, spot_price in spot_prices_dict.items():
                if export_model == "percentage":
                    export_price = spot_price * (1 - export_fee / 100)
                else:
                    # Fixed fee model
                    export_price = max(0, spot_price - export_fee)
                export_prices_dict[timestamp_str] = export_price

        # Convert to timeline format
        timeline = []
        for timestamp_str, price in sorted(export_prices_dict.items()):
            try:
                # Validate timestamp
                datetime.fromisoformat(timestamp_str)
                timeline.append({"time": timestamp_str, "price": price})
            except ValueError:
                _LOGGER.warning(f"Invalid timestamp in export prices: {timestamp_str}")
                continue

        _LOGGER.info(
            f"Successfully loaded {len(timeline)} export price points from coordinator"
        )
        return timeline

    def _get_spot_data_from_price_sensor(
        self, *, price_type: str
    ) -> Optional[Dict[str, Any]]:
        """Read internal 15min spot data from the spot/export price sensor entity.

        This is a robust fallback when coordinator doesn't carry spot_prices (e.g. pricing disabled).
        """
        hass = self._hass
        if not hass:
            return None

        if price_type == "export":
            sensor_id = f"sensor.oig_{self._box_id}_export_price_current_15min"
        else:
            sensor_id = f"sensor.oig_{self._box_id}_spot_price_current_15min"

        try:
            component = None
            # HA 2024+: entity_components registry
            entity_components = (
                hass.data.get("entity_components")
                if isinstance(hass.data, dict)
                else None
            )
            if isinstance(entity_components, dict):
                component = entity_components.get("sensor")

            # Legacy fallback
            if component is None:
                component = (
                    hass.data.get("sensor") if isinstance(hass.data, dict) else None
                )

            entity_obj = None
            if component is not None:
                get_entity = getattr(component, "get_entity", None)
                if callable(get_entity):
                    entity_obj = get_entity(sensor_id)

            if entity_obj is None and component is not None:
                entities = getattr(component, "entities", None)
                if isinstance(entities, list):
                    for ent in entities:
                        if getattr(ent, "entity_id", None) == sensor_id:
                            entity_obj = ent
                            break

            if entity_obj is None:
                return None

            spot_data = getattr(entity_obj, "_spot_data_15min", None)
            if isinstance(spot_data, dict) and spot_data:
                return spot_data
        except Exception as err:
            _LOGGER.debug("Failed to read spot data from %s: %s", sensor_id, err)

        return None

    async def _get_spot_data_from_ote_cache(self) -> Optional[Dict[str, Any]]:
        """Fallback: load spot prices via OTE cache (shared `.storage` file)."""
        hass = self._hass
        if not hass:
            return None
        try:
            cache_path = hass.config.path(".storage", OTE_SPOT_PRICE_CACHE_FILE)
            ote = OteApi(cache_path=cache_path)
            try:
                await ote.async_load_cached_spot_prices()
                data = await ote.get_spot_prices()
                return data if isinstance(data, dict) and data else None
            finally:
                await ote.close()
        except Exception as err:
            _LOGGER.debug("Failed to load OTE spot prices from cache: %s", err)
            return None

    def _get_solar_forecast(self) -> Dict[str, Any]:
        """Získat solární předpověď z solar_forecast senzoru."""
        if not self._hass:
            return {}

        # If solar forecast feature is disabled, don't warn/log.
        if not (
            self._config_entry
            and self._config_entry.options.get("enable_solar_forecast", False)
        ):
            return {}

        sensor_id = f"sensor.oig_{self._box_id}_solar_forecast"
        state = self._hass.states.get(sensor_id)

        if not state:
            # Entity may not be registered yet during startup.
            # Fallback: use coordinator cached solar_forecast_data restored from storage.
            cached = getattr(self.coordinator, "solar_forecast_data", None)
            total_hourly = (
                cached.get("total_hourly") if isinstance(cached, dict) else None
            )
            if isinstance(total_hourly, dict) and total_hourly:
                today = dt_util.now().date()
                tomorrow = today + timedelta(days=1)
                today_total: Dict[str, float] = {}
                tomorrow_total: Dict[str, float] = {}
                for hour_str, watts in total_hourly.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        kw = round(float(watts) / 1000.0, 2)
                        if hour_dt.date() == today:
                            today_total[hour_str] = kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_total[hour_str] = kw
                    except Exception:
                        continue
                self._log_rate_limited(
                    "solar_forecast_fallback",
                    "debug",
                    "Solar forecast entity missing; using coordinator cached data (%s)",
                    sensor_id,
                    cooldown_s=900.0,
                )
                return {"today": today_total, "tomorrow": tomorrow_total}

            self._log_rate_limited(
                "solar_forecast_missing",
                "debug",
                "Solar forecast sensor not found yet: %s",
                sensor_id,
                cooldown_s=900.0,
            )
            return {}

        if not state.attributes:
            self._log_rate_limited(
                "solar_forecast_no_attrs",
                "debug",
                "Solar forecast sensor has no attributes yet: %s",
                sensor_id,
                cooldown_s=900.0,
            )
            return {}

        # Načíst today a tomorrow data (správné názvy atributů)
        today = state.attributes.get("today_hourly_total_kw", {})
        tomorrow = state.attributes.get("tomorrow_hourly_total_kw", {})

        self._log_rate_limited(
            "solar_forecast_loaded",
            "debug",
            "Solar forecast loaded: today=%d tomorrow=%d (%s)",
            len(today) if isinstance(today, dict) else 0,
            len(tomorrow) if isinstance(tomorrow, dict) else 0,
            sensor_id,
            cooldown_s=1800.0,
        )

        return {"today": today, "tomorrow": tomorrow}

    def _get_solar_forecast_strings(self) -> Dict[str, Any]:
        """
        Získat solární předpověď pro String1 a String2 samostatně.

        Returns:
            Dict ve formátu:
            {
                "today_string1_kw": {"2025-11-09T07:00:00": 0.5, ...},
                "today_string2_kw": {"2025-11-09T07:00:00": 0.3, ...},
                "tomorrow_string1_kw": {...},
                "tomorrow_string2_kw": {...}
            }
        """
        if not self._hass:
            return {}

        sensor_id = f"sensor.oig_{self._box_id}_solar_forecast"
        state = self._hass.states.get(sensor_id)

        if not state or not state.attributes:
            return {}

        return {
            "today_string1_kw": state.attributes.get("today_hourly_string1_kw", {}),
            "today_string2_kw": state.attributes.get("today_hourly_string2_kw", {}),
            "tomorrow_string1_kw": state.attributes.get(
                "tomorrow_hourly_string1_kw", {}
            ),
            "tomorrow_string2_kw": state.attributes.get(
                "tomorrow_hourly_string2_kw", {}
            ),
        }

    def _get_balancing_plan(self) -> Optional[Dict[str, Any]]:
        """Získat plán balancování z battery_balancing senzoru."""
        if not self._hass:
            return None

        sensor_id = f"sensor.oig_{self._box_id}_battery_balancing"
        state = self._hass.states.get(sensor_id)

        if not state or not state.attributes:
            _LOGGER.debug(f"Battery balancing sensor {sensor_id} not available")
            return None

        # Načíst planned window z atributů
        planned = state.attributes.get("planned")

        if not planned:
            _LOGGER.debug("No balancing window planned")
            return None

        _LOGGER.info(
            f"Balancing plan: {planned.get('reason')} from {planned.get('holding_start')} "
            f"to {planned.get('holding_end')}"
        )

        return planned

    async def plan_balancing(
        self,
        requested_start: datetime,
        requested_end: datetime,
        target_soc: float,
        mode: str,
    ) -> Dict[str, Any]:
        """
        Vypočítat balancing plán pro požadované okno.

        KRITICKÉ - HLAVNÍ METODA PRO BALANCING:
        - Balancing řekne: "Chci nabít na 100% od 00:00 do 03:00"
        - Forecast vypočítá: "Ano/ne můžu" + vrátí skutečné intervaly

        Args:
            requested_start: Požadovaný start okna
            requested_end: Požadovaný konec okna
            target_soc: Cílový SoC (100% pro balancing)
            mode: "forced" | "opportunistic"

        Returns:
            {
                "can_do": bool,
                "charging_intervals": [...],  # ISO timestampy
                "actual_holding_start": str,
                "actual_holding_end": str,
                "reason": str,
            }
        """
        try:
            _LOGGER.info(
                f"📋 Balancing REQUEST: {mode}, "
                f"window={requested_start.strftime('%H:%M')}-{requested_end.strftime('%H:%M')}, "
                f"target={target_soc}%"
            )

            # TODO: IMPLEMENTOVAT FYZIKU
            # 1. Zjistit aktuální SoC
            # 2. Vypočítat kolik energie potřebuju (target_soc - current_soc)
            # 3. Zjistit spotřebu během okna z profilu
            # 4. Vypočítat charging_intervals aby dosáhl target_soc
            # 5. Vypočítat actual_holding_start/end (kdy začne držet 100%)

            # DOČASNĚ: Vždycky vrať "můžu" s celým oknem
            charging_intervals = []
            current = requested_start
            while current < requested_end:
                charging_intervals.append(current.isoformat())
                current += timedelta(minutes=15)

            return {
                "can_do": True,
                "charging_intervals": charging_intervals,
                "actual_holding_start": requested_start.isoformat(),
                "actual_holding_end": requested_end.isoformat(),
                "reason": "Temporary implementation - always accepts",
            }

        except Exception as e:
            _LOGGER.error(f"❌ Failed to plan balancing: {e}", exc_info=True)
            return {
                "can_do": False,
                "charging_intervals": [],
                "actual_holding_start": None,
                "actual_holding_end": None,
                "reason": f"Error: {e}",
            }

    def _get_load_avg_sensors(self) -> Dict[str, Any]:
        """
        Získat všechny load_avg senzory pro box.

        Používá PŘÍMO konfiguraci ze SENSOR_TYPES_STATISTICS místo hledání v atributech.
        Mapuje entity_id na tuple (start_hour, end_hour, day_type).

        Returns:
            Dict[entity_id] = {
                "value": float,
                "time_range": (start_hour, end_hour),  # tuple!
                "day_type": "weekday" | "weekend"
            }
        """
        if not self._hass:
            _LOGGER.warning("_get_load_avg_sensors: hass not available")
            return {}

        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        load_sensors = {}

        # Projít všechny load_avg senzory z konfigurace
        for sensor_type, config in SENSOR_TYPES_STATISTICS.items():
            # Hledat jen load_avg_* senzory
            if not sensor_type.startswith("load_avg_"):
                continue

            # Zkontrolovat jestli má time_range a day_type v konfiguraci
            if "time_range" not in config or "day_type" not in config:
                continue

            # Sestavit entity_id
            entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

            # Získat stav senzoru
            state = self._hass.states.get(entity_id)
            if not state:
                _LOGGER.debug(f"Sensor {entity_id} not found in HA")
                continue

            if state.state in ["unknown", "unavailable"]:
                _LOGGER.debug(f"Sensor {entity_id} is {state.state}")
                continue

            # Parsovat hodnotu
            try:
                value = float(state.state)
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    f"Failed to parse {entity_id} value '{state.state}': {e}"
                )
                continue

            # Uložit s time_range jako TUPLE (ne string!)
            time_range = config["time_range"]  # (6, 8)
            day_type = config["day_type"]  # "weekday" | "weekend"

            load_sensors[entity_id] = {
                "value": value,
                "time_range": time_range,  # TUPLE!
                "day_type": day_type,
            }

        _LOGGER.info(f"Found {len(load_sensors)} valid load_avg sensors")
        if load_sensors:
            # Log prvního senzoru pro debugging
            first_id = next(iter(load_sensors))
            first = load_sensors[first_id]
            _LOGGER.info(
                f"Example: {first_id}, value={first['value']}W, "
                f"range={first['time_range']}, day={first['day_type']}"
            )

        return load_sensors

    def _get_solar_for_timestamp(
        self, timestamp: datetime, solar_forecast: Dict[str, Any]
    ) -> float:
        """
        Získat solar production pro daný timestamp (kWh za 15min).

        Args:
            timestamp: Timestamp pro který hledat produkci
            solar_forecast: Dict s 'today' a 'tomorrow' hodinovými daty

        Returns:
            Solar production v kWh za 15 minut
        """
        # Rozhodnout jestli today nebo tomorrow
        today = datetime.now().date()
        is_today = timestamp.date() == today

        data = solar_forecast.get("today" if is_today else "tomorrow", {})

        if not data:
            return 0.0

        # Najít hodinovou hodnotu pro daný čas
        # Klíče jsou ve formátu ISO timestamp BEZ timezone: "2025-10-20T14:00:00"
        # Normalizovat timestamp na naive (local time) pro matching
        timestamp_hour = timestamp.replace(minute=0, second=0, microsecond=0)

        # Strip timezone to match solar_forecast key format
        if timestamp_hour.tzinfo is not None:
            # Convert to naive local time (remove timezone info)
            hour_key = timestamp_hour.replace(tzinfo=None).isoformat()
        else:
            hour_key = timestamp_hour.isoformat()

        hourly_kw = data.get(hour_key, 0.0)

        # Keep solar lookup diagnostics strictly rate-limited to avoid log spam.
        if timestamp.hour in (7, 8, 9, 10):
            try:
                keys_count = len(data)
            except Exception:
                keys_count = -1
            self._log_rate_limited(
                "solar_lookup_debug",
                "debug",
                "🔍 SOLAR LOOKUP: ts=%s hour_key=%s keys=%s value=%s",
                timestamp.isoformat(),
                hour_key,
                keys_count,
                hourly_kw,
                cooldown_s=3600.0,
            )

        try:
            hourly_kw = float(hourly_kw)
        except (ValueError, TypeError):
            _LOGGER.warning(
                f"Invalid solar value for {timestamp.strftime('%H:%M')}: "
                f"{hourly_kw} (type={type(hourly_kw)}), key={hour_key}"
            )
            return 0.0

        # Avoid per-interval debug spam (dashboard/API can call this a lot).
        if timestamp.hour in (14, 15, 16):
            self._log_rate_limited(
                "solar_values_debug",
                "debug",
                "Solar sample for %s: key=%s kW=%.3f 15min_kWh=%.3f",
                timestamp.strftime("%H:%M"),
                hour_key,
                hourly_kw,
                hourly_kw / 4.0,
                cooldown_s=3600.0,
            )

        # Převést na 15min interval
        # Hodnota je v kW (průměrný výkon za hodinu)
        # Pro 15min: kW * 0.25h = kWh
        return hourly_kw / 4.0

    def _get_load_avg_for_timestamp(
        self, timestamp: datetime, load_avg_sensors: Dict[str, Any]
    ) -> float:
        """
        Získat load average pro daný timestamp (kWh za 15min).

        Args:
            timestamp: Timestamp pro který hledat spotřebu
            load_avg_sensors: Dict[entity_id] = {
                "value": float,
                "time_range": (start_hour, end_hour),
                "day_type": "weekday" | "weekend"
            }

        Returns:
            Load average v kWh za 15 minut
        """
        if not load_avg_sensors:
            if not hasattr(self, "_empty_load_sensors_logged"):
                _LOGGER.debug(
                    "load_avg_sensors dictionary is empty - using fallback 500W (statistics sensors may not be available yet)"
                )
                self._empty_load_sensors_logged = True
            return 0.125  # 500W fallback

        # Zjistit den v týdnu (0=pondělí, 6=neděle)
        is_weekend = timestamp.weekday() >= 5
        day_type = "weekend" if is_weekend else "weekday"

        current_hour = timestamp.hour

        # Najít odpovídající senzor podle time_range tuple
        for entity_id, sensor_data in load_avg_sensors.items():
            # Zkontrolovat day_type
            sensor_day_type = sensor_data.get("day_type", "")
            if sensor_day_type != day_type:
                continue

            # Získat time_range jako tuple (start_hour, end_hour)
            time_range = sensor_data.get("time_range")
            if (
                not time_range
                or not isinstance(time_range, tuple)
                or len(time_range) != 2
            ):
                continue

            start_hour, end_hour = time_range

            # Zkontrolovat jestli current_hour spadá do rozmezí
            # Ošetřit případ přes půlnoc (např. 22-6)
            if start_hour <= end_hour:
                # Normální rozmezí (např. 6-8, 8-12)
                in_range = start_hour <= current_hour < end_hour
            else:
                # Přes půlnoc (např. 22-6)
                in_range = current_hour >= start_hour or current_hour < end_hour

            if in_range:
                # Hodnota senzoru je ve wattech (W)
                # 143W = 143Wh za hodinu = 0,143 kWh/h
                # Pro 15min interval: 0,143 / 4 = 0,03575 kWh
                watts = sensor_data.get("value", 0.0)

                # FALLBACK: Pokud jsou data 0 (ještě se nesebrala), použít 500W jako rozumný default
                if watts == 0:
                    watts = 500.0  # 500W = rozumná průměrná spotřeba domácnosti
                    _LOGGER.debug(
                        f"No consumption data yet for {timestamp.strftime('%H:%M')}, using fallback: 500W"
                    )

                kwh_per_hour = watts / 1000.0  # W → kW
                kwh_per_15min = kwh_per_hour / 4.0  # kWh/h → kWh/15min
                _LOGGER.debug(
                    f"Matched {entity_id} for {timestamp.strftime('%H:%M')}: "
                    f"{watts}W → {kwh_per_15min:.5f} kWh/15min"
                )
                return kwh_per_15min

        # Žádný senzor nenalezen - použít fallback 500W
        _LOGGER.debug(
            f"No load_avg sensor found for {timestamp.strftime('%H:%M')} ({day_type}), "
            f"searched {len(load_avg_sensors)} sensors - using fallback 500W"
        )
        # 500W = 0.5 kWh/h = 0.125 kWh/15min
        return 0.125

    # ========================================================================
    # GRID CHARGING OPTIMIZATION METHODS
    # ========================================================================

    def _calculate_optimal_night_charge_target(
        self,
        timeline_data: List[Dict[str, Any]],
        max_capacity: float,
        default_target_percent: float,
    ) -> tuple[float, str]:
        """
        Vypočítá optimální target SoC pro noční nabíjení (ne vždy 100%).

        Algoritmus:
        1. Najít ranní solar surplus (FVE > spotřeba)
        2. Rozhodnout jestli je lepší storage nebo export
        3. Vrátit optimální target SoC

        Args:
            timeline_data: Timeline data s predikcí
            max_capacity: Maximální kapacita baterie (kWh)
            default_target_percent: Výchozí target z configu (%)

        Returns:
            (optimal_target_kwh, reason) - optimální target a vysvětlení
        """
        try:
            # Najít ranní hodiny (06:00 - 12:00)
            now = datetime.now()
            morning_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now.hour < 6:
                # Pokud je před 6:00, použít dnešní ráno
                pass
            else:
                # Jinak zítřejší ráno
                morning_start += timedelta(days=1)

            morning_end = morning_start.replace(hour=12, minute=0)

            # Filtrovat ranní intervaly
            morning_intervals = []
            for point in timeline_data:
                try:
                    timestamp = datetime.fromisoformat(point.get("timestamp", ""))
                    if morning_start <= timestamp < morning_end:
                        morning_intervals.append(point)
                except (ValueError, TypeError):
                    continue

            if not morning_intervals:
                _LOGGER.debug(
                    "No morning intervals found for optimal target calculation"
                )
                return (
                    (default_target_percent / 100.0) * max_capacity,
                    f"default ({default_target_percent:.0f}%) - no morning data",
                )

            # Spočítat ranní solar surplus
            morning_surplus_kwh = 0.0
            for interval in morning_intervals:
                solar = interval.get("solar_production_kwh", 0)
                consumption = interval.get("consumption_kwh", 0)
                surplus = max(0, solar - consumption)
                morning_surplus_kwh += surplus

            _LOGGER.debug(
                f"Morning solar surplus ({len(morning_intervals)} intervals): {morning_surplus_kwh:.2f} kWh"
            )

            # Pokud není surplus, použít default
            if morning_surplus_kwh < 0.5:
                return (
                    (default_target_percent / 100.0) * max_capacity,
                    f"default ({default_target_percent:.0f}%) - no morning surplus",
                )

            # Najít průměrnou export price ráno
            export_prices = [
                p.get("export_price_czk", 0)
                for p in morning_intervals
                if p.get("export_price_czk") is not None
            ]
            avg_export_price = (
                sum(export_prices) / len(export_prices) if export_prices else 0
            )

            # Najít večerní spot price (18:00 - 22:00)
            evening_start = morning_start.replace(hour=18, minute=0)
            evening_end = morning_start.replace(hour=22, minute=0)
            evening_prices = []
            for point in timeline_data:
                try:
                    timestamp = datetime.fromisoformat(point.get("timestamp", ""))
                    if evening_start <= timestamp < evening_end:
                        spot = point.get("spot_price_czk")
                        if spot is not None:
                            evening_prices.append(spot)
                except (ValueError, TypeError):
                    continue

            avg_evening_spot = (
                sum(evening_prices) / len(evening_prices) if evening_prices else 6.0
            )

            # ROZHODNUTÍ: Storage value vs Export value
            # Storage: uložit surplus ráno, využít večer (s efficiency loss)
            dc_dc_efficiency = 0.95  # DC/DC charging (solar → battery)
            dc_ac_efficiency = (
                self._get_battery_efficiency()
            )  # DC/AC discharge (battery → consumption)
            storage_efficiency = dc_dc_efficiency * dc_ac_efficiency  # ~83.8%

            storage_value = avg_evening_spot * morning_surplus_kwh * storage_efficiency
            export_value = avg_export_price * morning_surplus_kwh

            _LOGGER.info(
                f"Optimal target calculation: "
                f"morning_surplus={morning_surplus_kwh:.2f}kWh, "
                f"export_price={avg_export_price:.2f}CZK/kWh, "
                f"evening_spot={avg_evening_spot:.2f}CZK/kWh, "
                f"storage_value={storage_value:.2f}CZK, "
                f"export_value={export_value:.2f}CZK"
            )

            # Pokud storage je lepší než export (s 10% tolerance)
            if storage_value > export_value * 1.1:
                # Nechat místo pro ranní solar
                # Kolik místa potřebujeme? morning_surplus / dc_dc_efficiency
                space_needed_kwh = morning_surplus_kwh / dc_dc_efficiency

                # Optimal target = max_capacity - space_needed
                optimal_target_kwh = max_capacity - space_needed_kwh

                # Clamp mezi 50% a 95%
                min_target = max_capacity * 0.50
                max_target = max_capacity * 0.95
                optimal_target_kwh = max(
                    min_target, min(max_target, optimal_target_kwh)
                )

                optimal_percent = (optimal_target_kwh / max_capacity) * 100

                reason = (
                    f"optimized ({optimal_percent:.0f}%) - "
                    f"save {space_needed_kwh:.1f}kWh for morning solar "
                    f"(storage_value={storage_value:.1f}CZK > export={export_value:.1f}CZK)"
                )

                _LOGGER.info(
                    f"OPTIMAL TARGET: {optimal_target_kwh:.2f}kWh ({optimal_percent:.0f}%) - {reason}"
                )

                return (optimal_target_kwh, reason)

            # Export je OK → nabít na default (nebo blízko 100%)
            # Ale nikdy ne víc než 95% (leave margin for rounding)
            safe_target = min(default_target_percent, 95.0)
            target_kwh = (safe_target / 100.0) * max_capacity

            reason = (
                f"default ({safe_target:.0f}%) - "
                f"export profitable (export={export_value:.1f}CZK >= storage={storage_value:.1f}CZK)"
            )

            _LOGGER.info(
                f"OPTIMAL TARGET: {target_kwh:.2f}kWh ({safe_target:.0f}%) - {reason}"
            )

            return (target_kwh, reason)

        except Exception as e:
            _LOGGER.error(
                f"Error calculating optimal night charge target: {e}", exc_info=True
            )
            # Fallback na default
            return (
                (default_target_percent / 100.0) * max_capacity,
                f"default ({default_target_percent:.0f}%) - calculation error",
            )

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
        """
        Ekonomický plán nabíjení s forward simulací.

        Algoritmus:
        1. Kontrola ochran (blackout, weather) - pokud aktivní, nabít okamžitě v nejlevnějším
        2. Forward simulace - porovnání nákladů s/bez nabíjení
        3. Death valley prevence - minimum charge pro přežití
        4. Ekonomické rozhodnutí - nabít jen pokud se to vyplatí

        Args:
            timeline_data: Timeline data
            min_capacity_kwh: Minimální kapacita (kWh)
            effective_minimum_kwh: Minimální kapacita + bezpečnostní margin (kWh)
            target_capacity_kwh: Cílová kapacita na konci (kWh)
            max_charging_price: Maximální cena (CZK/kWh) - SAFETY LIMIT
            min_savings_margin: Minimální úspora pro nabíjení (CZK/kWh)
            charging_power_kw: Nabíjecí výkon (kW)
            max_capacity: Maximální kapacita baterie (kWh)
            enable_blackout_protection: Aktivovat ochranu před blackoutem
            blackout_protection_hours: Počet hodin ochrany
            blackout_target_soc_percent: Cílový SoC pro blackout (%)
            enable_weather_risk: Aktivovat ochranu před počasím
            weather_risk_level: Úroveň rizika (low/medium/high)
            weather_target_soc_percent: Cílový SoC pro weather (%)
            target_reason: Vysvětlení proč byl zvolen tento target

        Returns:
            Optimalizovaná timeline
        """
        # Kopie timeline pro úpravy
        timeline = [dict(point) for point in timeline_data]

        charge_per_interval = charging_power_kw / 4.0  # kWh za 15min
        current_time = datetime.now()

        # KROK 1: PRIORITA MAXIMUM - Protection overrides (blackout, weather)
        protection_soc_kwh = self._calculate_protection_requirement(
            timeline=timeline,
            max_capacity=max_capacity,
        )

        if protection_soc_kwh is not None:
            current_soc = timeline[0].get("battery_capacity_kwh", 0)
            protection_shortage = protection_soc_kwh - current_soc

            if protection_shortage > 0:
                _LOGGER.warning(
                    f"PROTECTION OVERRIDE: Need {protection_shortage:.2f}kWh "
                    f"to reach protection target {protection_soc_kwh:.2f}kWh "
                    f"(current: {current_soc:.2f}kWh)"
                )

                # Najít nejlevnější intervaly bez ohledu na ekonomiku
                # Ale stále respektovat max_charging_price jako safety limit!
                candidates = self._get_candidate_intervals(
                    timeline=timeline,
                    max_charging_price=max_charging_price,  # Safety limit
                    current_time=current_time,
                )

                if not candidates:
                    _LOGGER.error(
                        f"PROTECTION FAILED: No charging candidates under "
                        f"max_price={max_charging_price}CZK"
                    )
                else:
                    # Nabít postupně v nejlevnějších intervalech
                    charged = 0.0
                    for candidate in candidates:
                        if charged >= protection_shortage:
                            break

                        idx = candidate["index"]
                        old_charge = timeline[idx].get("grid_charge_kwh", 0)
                        timeline[idx]["grid_charge_kwh"] = (
                            old_charge + charge_per_interval
                        )
                        # Ponechat existující reason (může být balancing_*)
                        if timeline[idx].get("reason") == "normal":
                            timeline[idx]["reason"] = "protection_charge"
                        charged += charge_per_interval

                        _LOGGER.info(
                            f"PROTECTION: Adding {charge_per_interval:.2f}kWh at "
                            f"{candidate['timestamp']} (price {candidate['price']:.2f}CZK)"
                        )

                        # Přepočítat timeline
                        self._recalculate_timeline_from_index(timeline, idx)

                    _LOGGER.info(
                        f"PROTECTION: Charged {charged:.2f}kWh / {protection_shortage:.2f}kWh needed"
                    )

        # KROK 2: EKONOMICKÁ OPTIMALIZACE
        # Získat kandidáty seřazené podle ceny
        candidates = self._get_candidate_intervals(
            timeline=timeline,
            max_charging_price=max_charging_price,
            current_time=current_time,
        )

        if not candidates:
            _LOGGER.warning(
                f"No economic charging candidates under max_price={max_charging_price}CZK"
            )
            return timeline

        _LOGGER.info(f"Found {len(candidates)} economic charging candidates")

        # Pro každého kandidáta: forward simulace a ekonomické vyhodnocení
        efficiency = self._get_battery_efficiency()

        for candidate in candidates:
            idx = candidate["index"]
            price = candidate["price"]
            timestamp = candidate["timestamp"]

            # Simulovat 48h dopředu (nebo do konce timeline)
            horizon_hours = min(48, len(timeline) - idx)

            # Scénář 1: Nabít tady
            result_charge = self._simulate_forward(
                timeline=timeline,
                start_index=idx,
                charge_now=True,
                charge_amount_kwh=charge_per_interval,
                horizon_hours=horizon_hours,
                effective_minimum_kwh=effective_minimum_kwh,
                efficiency=efficiency,
            )
            cost_charge = result_charge["total_charging_cost"]

            # Scénář 2: Počkat (nenabíjet tady)
            result_wait = self._simulate_forward(
                timeline=timeline,
                start_index=idx,
                charge_now=False,
                charge_amount_kwh=0,
                horizon_hours=horizon_hours,
                effective_minimum_kwh=effective_minimum_kwh,
                efficiency=efficiency,
            )
            cost_wait = result_wait["total_charging_cost"]
            min_soc_wait = result_wait["min_soc"]
            death_valley_wait = result_wait["death_valley_reached"]

            # ROZHODNUTÍ 1: Death valley prevence
            if death_valley_wait:
                # Pokud nenabijeme, spadneme pod effective_minimum
                shortage = effective_minimum_kwh - min_soc_wait

                if shortage > 0:
                    # Spočítat minimum charge
                    min_charge = self._calculate_minimum_charge(
                        scenario_wait_min_soc=min_soc_wait,
                        effective_minimum_kwh=effective_minimum_kwh,
                        max_charge_per_interval=charge_per_interval,
                    )

                    _LOGGER.warning(
                        f"DEATH VALLEY at {timestamp}: Need {min_charge:.2f}kWh "
                        f"(min_soc_wait={min_soc_wait:.2f}kWh, effective_min={effective_minimum_kwh:.2f}kWh)"
                    )

                    # Nabít minimum (ne full charge!)
                    old_charge = timeline[idx].get("grid_charge_kwh", 0)
                    timeline[idx]["grid_charge_kwh"] = old_charge + min_charge
                    # Ponechat existující reason (může být balancing_*)
                    if timeline[idx].get("reason") == "normal":
                        timeline[idx]["reason"] = "death_valley_fix"

                    # Přepočítat timeline
                    self._recalculate_timeline_from_index(timeline, idx)

                    _LOGGER.info(
                        f"DEATH VALLEY FIX: Added {min_charge:.2f}kWh at {timestamp} "
                        f"(price {price:.2f}CZK)"
                    )

                    continue  # Další kandidát

            # ROZHODNUTÍ 2: Ekonomické vyhodnocení
            # Nabíjet jen pokud to ušetří min_savings_margin
            savings_per_kwh = (cost_wait - cost_charge) / charge_per_interval

            if savings_per_kwh >= min_savings_margin:
                # Vyplatí se nabít!
                old_charge = timeline[idx].get("grid_charge_kwh", 0)
                timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
                # Ponechat existující reason (může být balancing_*)
                if timeline[idx].get("reason") == "normal":
                    timeline[idx]["reason"] = "economic_charge"

                # Přepočítat timeline
                self._recalculate_timeline_from_index(timeline, idx)

                _LOGGER.info(
                    f"ECONOMIC: Added {charge_per_interval:.2f}kWh at {timestamp} "
                    f"(price {price:.2f}CZK, savings {savings_per_kwh:.3f}CZK/kWh > {min_savings_margin}CZK/kWh)"
                )
            else:
                _LOGGER.debug(
                    f"ECONOMIC: Skipping {timestamp} "
                    f"(price {price:.2f}CZK, savings {savings_per_kwh:.3f}CZK/kWh < {min_savings_margin}CZK/kWh)"
                )

        # KROK 3: Finální kontrola a metriky
        final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
        target_achieved = final_capacity >= target_capacity_kwh
        min_achieved = final_capacity >= min_capacity_kwh

        # Uložit metriky pro dashboard
        self._charging_metrics = {
            "algorithm": "economic",
            "target_capacity_kwh": target_capacity_kwh,
            "effective_minimum_kwh": effective_minimum_kwh,
            "final_capacity_kwh": final_capacity,
            "min_capacity_kwh": min_capacity_kwh,
            "target_achieved": target_achieved,
            "min_achieved": min_achieved,
            "shortage_kwh": (
                max(0, target_capacity_kwh - final_capacity)
                if not target_achieved
                else 0
            ),
            "protection_enabled": enable_blackout_protection or enable_weather_risk,
            "protection_soc_kwh": protection_soc_kwh,
            "optimal_target_info": {
                "target_kwh": target_capacity_kwh,
                "target_percent": (target_capacity_kwh / max_capacity * 100),
                "reason": target_reason,
            },
        }

        _LOGGER.info(
            f"Economic charging complete: final={final_capacity:.2f}kWh, "
            f"target={target_capacity_kwh:.2f}kWh, achieved={target_achieved}"
        )

        return timeline

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
        """
        Chytrý plán nabíjení - vybírá nejlevnější intervaly kde se baterie SKUTEČNĚ nabije.

        Algoritmus:
        1. Simuluje timeline bez nabíjení
        2. Identifikuje kde baterie potřebuje energii (pod minimum nebo pro target)
        3. Vytvoří seznam kandidátů (levné intervaly kde se baterie může nabít)
        4. Vybere optimální intervaly a naplánuje nabíjení

        Args:
            timeline: Timeline data
            min_capacity: Minimální kapacita (kWh)
            target_capacity: Cílová kapacita na konci (kWh)
            max_price: Maximální cena (CZK/kWh)
            price_threshold: Práh pro špičky (CZK/kWh)
            charging_power_kw: Nabíjecí výkon (kW)
            max_capacity: Maximální kapacita baterie (kWh)

        Returns:
            Optimalizovaná timeline
        """
        charge_per_interval = charging_power_kw / 4.0  # kWh za 15min

        # KROK 1: Najít intervaly kde baterie klesne pod minimum
        critical_intervals = []
        min_capacity_in_timeline = float("inf")
        min_capacity_timestamp = None

        for i, point in enumerate(timeline):
            capacity = point.get("battery_capacity_kwh", 0)
            if capacity < min_capacity:
                critical_intervals.append(i)
            if capacity < min_capacity_in_timeline:
                min_capacity_in_timeline = capacity
                min_capacity_timestamp = point.get("timestamp", "unknown")

        # KROK 2: Spočítat kolik energie potřebujeme na konci
        final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
        energy_needed_for_target = max(0, target_capacity - final_capacity)

        _LOGGER.info(
            f"Smart charging: {len(critical_intervals)} critical intervals, "
            f"min_capacity_in_timeline: {min_capacity_in_timeline:.2f}kWh @ {min_capacity_timestamp}, "
            f"min_threshold: {min_capacity:.2f}kWh, "
            f"need {energy_needed_for_target:.2f}kWh for target"
        )

        # KROK 3: PRIORITA 1 - Opravit kritická místa (minimální nabíjení)
        # Najít první kritické místo
        if critical_intervals:
            first_critical = critical_intervals[0]

            _LOGGER.info(
                f"First critical interval at index {first_critical}, "
                f"capacity: {timeline[first_critical].get('battery_capacity_kwh', 0):.2f}kWh"
            )

            # Spočítat kolik energie potřebujeme pro dosažení min_capacity v prvním kritickém místě
            critical_capacity = timeline[first_critical].get("battery_capacity_kwh", 0)
            energy_needed = min_capacity - critical_capacity

            if energy_needed > 0:
                _LOGGER.info(
                    f"Need {energy_needed:.2f}kWh to reach minimum at critical point"
                )

                # Najít nejlevnější intervaly PŘED kritickým místem
                charging_candidates = []
                for i in range(first_critical):
                    point = timeline[i]
                    price = point.get("spot_price_czk", float("inf"))
                    capacity = point.get("battery_capacity_kwh", 0)

                    # Filtr: cena musí být OK
                    if price > max_price:
                        continue

                    # Filtr: baterie nesmí být plná
                    if capacity >= max_capacity * 0.99:
                        continue

                    charging_candidates.append(
                        {
                            "index": i,
                            "price": price,
                            "capacity": capacity,
                            "timestamp": point.get("timestamp", ""),
                        }
                    )

                # Seřadit podle ceny
                charging_candidates.sort(key=lambda x: x["price"])

                # Přidat nabíjení postupně dokud nedosáhneme min_capacity
                added_energy = 0
                while added_energy < energy_needed and charging_candidates:
                    best = charging_candidates.pop(0)
                    idx = best["index"]

                    old_charge = timeline[idx].get("grid_charge_kwh", 0)
                    timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
                    # Ponechat existující reason (může být balancing_*)
                    if timeline[idx].get("reason") == "normal":
                        timeline[idx]["reason"] = "legacy_critical"
                    added_energy += charge_per_interval

                    _LOGGER.debug(
                        f"Critical fix: Adding {charge_per_interval:.2f}kWh at index {idx} "
                        f"(price {best['price']:.2f}CZK), total added: {added_energy:.2f}kWh"
                    )

                    # Přepočítat timeline
                    self._recalculate_timeline_from_index(timeline, idx)

                    # Zkontrolovat jestli jsme vyřešili kritické místo
                    new_critical_capacity = timeline[first_critical].get(
                        "battery_capacity_kwh", 0
                    )
                    if new_critical_capacity >= min_capacity:
                        _LOGGER.info(
                            f"Critical interval fixed: capacity now {new_critical_capacity:.2f}kWh >= {min_capacity:.2f}kWh"
                        )
                        break

        # KROK 4: PRIORITA 2 - Dosáhnout cílové kapacity na konci (v levných hodinách)
        max_iterations = 100
        iteration = 0

        # Vypočítat effective_target (pro 100% target použít 99%)
        effective_target = target_capacity
        if target_capacity >= max_capacity * 0.99:
            effective_target = max_capacity * 0.99

        while iteration < max_iterations:
            # Zkontrolovat aktuální stav na konci
            current_final_capacity = timeline[-1].get("battery_capacity_kwh", 0)

            if current_final_capacity >= effective_target:
                _LOGGER.info(
                    f"Target capacity achieved: {current_final_capacity:.2f}kWh >= {effective_target:.2f}kWh "
                    f"(original target: {target_capacity:.2f}kWh)"
                )
                break

            # Potřebujeme více energie
            shortage = effective_target - current_final_capacity

            # DŮLEŽITÉ: Přestavět seznam kandidátů s aktuálními kapacitami
            charging_candidates = []
            for i, point in enumerate(timeline):
                price = point.get("spot_price_czk", float("inf"))
                capacity = point.get("battery_capacity_kwh", 0)
                existing_charge = point.get("grid_charge_kwh", 0)

                # Filtr: cena musí být pod max_price (NE price_threshold - to jen pro kritická místa)
                if price > max_price:
                    continue

                # Filtr: baterie nesmí být plná (ponecháme 1% rezervu)
                if capacity >= max_capacity * 0.99:
                    continue

                # Filtr: musí být prostor pro nabití (ne na konci)
                if i >= len(timeline) - 1:
                    continue

                # KRITICKÝ FILTR: Max 1× charge_per_interval per interval (fyzikální limit!)
                # S 2.8 kW můžeme nabít max 0.7 kWh za 15 min
                if existing_charge >= charge_per_interval * 0.99:  # tolerance
                    continue

                charging_candidates.append(
                    {
                        "index": i,
                        "price": price,
                        "capacity": capacity,
                        "timestamp": point.get("timestamp", ""),
                        "existing_charge": existing_charge,
                    }
                )

            # Seřadit podle ceny (nejlevnější první)
            charging_candidates.sort(key=lambda x: x["price"])

            # Najít nejlevnějšího kandidáta
            if not charging_candidates:
                _LOGGER.warning(
                    f"No more charging candidates available, shortage: {shortage:.2f}kWh"
                )
                break

            best_candidate = charging_candidates[0]
            idx = best_candidate["index"]

            # Přidat nabíjení
            old_charge = timeline[idx].get("grid_charge_kwh", 0)
            timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
            # Ponechat existující reason (může být balancing_*)
            if timeline[idx].get("reason") == "normal":
                timeline[idx]["reason"] = "legacy_target"

            _LOGGER.debug(
                f"Target charging: Adding {charge_per_interval:.2f}kWh at index {idx} "
                f"(price {best_candidate['price']:.2f}CZK, timestamp {best_candidate['timestamp']}), "
                f"shortage: {shortage:.2f}kWh, capacity before: {best_candidate['capacity']:.2f}kWh"
            )

            # Přepočítat timeline od tohoto bodu
            self._recalculate_timeline_from_index(timeline, idx)

            iteration += 1

        if iteration >= max_iterations:
            _LOGGER.warning("Reached max iterations in smart charging plan")

        # Zkontrolovat finální stav a uložit metriky pro dashboard
        final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
        target_achieved = final_capacity >= effective_target
        min_achieved = final_capacity >= min_capacity

        # Uložit metriky pro pozdější použití v extra_state_attributes
        self._charging_metrics = {
            "target_capacity_kwh": target_capacity,
            "effective_target_kwh": effective_target,
            "final_capacity_kwh": final_capacity,
            "min_capacity_kwh": min_capacity,
            "target_achieved": target_achieved,
            "min_achieved": min_achieved,
            "shortage_kwh": (
                max(0, effective_target - final_capacity) if not target_achieved else 0
            ),
        }

        return timeline

    def _fix_minimum_capacity_violations(
        self,
        timeline: List[Dict[str, Any]],
        min_capacity: float,
        max_price: float,
        price_threshold: float,
        charging_power_kw: float,
    ) -> List[Dict[str, Any]]:
        """
        Opraví všechna místa kde kapacita klesne pod minimum.

        Args:
            timeline: Timeline data
            min_capacity: Minimální kapacita (kWh)
            max_price: Maximální cena pro nabíjení (CZK/kWh)
            price_threshold: Práh pro špičky (CZK/kWh)
            charging_power_kw: Nabíjecí výkon (kW)

        Returns:
            Opravená timeline
        """
        max_iterations = 50  # Ochrana proti nekonečné smyčce
        iteration = 0

        while iteration < max_iterations:
            violation_index = self._find_first_minimum_violation(timeline, min_capacity)
            if violation_index is None:
                break  # Žádné porušení

            _LOGGER.debug(
                f"Found minimum violation at index {violation_index}, capacity={timeline[violation_index]['battery_capacity_kwh']:.2f}kWh"
            )

            # Najdi nejlevnější vhodnou hodinu PŘED porušením
            charging_index = self._find_cheapest_hour_before(
                timeline, violation_index, max_price, price_threshold
            )

            if charging_index is None:
                _LOGGER.warning(
                    f"Cannot fix minimum violation at index {violation_index} - no suitable charging time found"
                )
                break  # Nelze opravit

            # Přidej nabíjení a přepočítej od tohoto bodu
            charge_kwh = charging_power_kw / 4.0  # kW → kWh za 15min
            old_charge = timeline[charging_index].get("grid_charge_kwh", 0)
            timeline[charging_index]["grid_charge_kwh"] = old_charge + charge_kwh
            # Ponechat existující reason (může být balancing_*)
            if timeline[charging_index].get("reason") == "normal":
                timeline[charging_index]["reason"] = "legacy_violation_fix"

            _LOGGER.debug(
                f"Adding {charge_kwh:.2f}kWh charging at index {charging_index}, price={timeline[charging_index]['spot_price_czk']:.2f}CZK"
            )

            self._recalculate_timeline_from_index(timeline, charging_index)
            iteration += 1

        if iteration >= max_iterations:
            _LOGGER.warning("Reached max iterations in minimum capacity fixing")

        return timeline

    def _ensure_target_capacity_at_end(
        self,
        timeline: List[Dict[str, Any]],
        target_capacity: float,
        max_price: float,
        price_threshold: float,
        charging_power_kw: float,
    ) -> List[Dict[str, Any]]:
        """
        Zajistí cílovou kapacitu na konci intervalu.

        Args:
            timeline: Timeline data
            target_capacity: Cílová kapacita (kWh)
            max_price: Maximální cena pro nabíjení (CZK/kWh)
            price_threshold: Práh pro špičky (CZK/kWh)
            charging_power_kw: Nabíjecí výkon (kW)

        Returns:
            Optimalizovaná timeline
        """
        if not timeline:
            return timeline

        max_iterations = 50  # Ochrana proti nekonečné smyčce
        iteration = 0

        while iteration < max_iterations:
            final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
            if final_capacity >= target_capacity:
                _LOGGER.debug(
                    f"Target capacity achieved: {final_capacity:.2f}kWh >= {target_capacity:.2f}kWh"
                )
                break

            shortage = target_capacity - final_capacity
            _LOGGER.debug(f"Target capacity shortage: {shortage:.2f}kWh")

            # Najdi nejlevnější vhodnou hodinu v celém intervalu
            charging_index = self._find_cheapest_suitable_hour(
                timeline, max_price, price_threshold
            )

            if charging_index is None:
                _LOGGER.warning(
                    "Cannot achieve target capacity - no suitable charging time found"
                )
                break

            # Přidej nabíjení a přepočítej od tohoto bodu
            charge_kwh = charging_power_kw / 4.0  # kW → kWh za 15min
            old_charge = timeline[charging_index].get("grid_charge_kwh", 0)
            timeline[charging_index]["grid_charge_kwh"] = old_charge + charge_kwh
            # Ponechat existující reason (může být balancing_*)
            if timeline[charging_index].get("reason") == "normal":
                timeline[charging_index]["reason"] = "legacy_target_ensure"

            _LOGGER.debug(
                f"Adding {charge_kwh:.2f}kWh charging at index {charging_index} for target capacity"
            )

            self._recalculate_timeline_from_index(timeline, charging_index)
            iteration += 1

        if iteration >= max_iterations:
            _LOGGER.warning("Reached max iterations in target capacity ensuring")

        return timeline

    def _find_first_minimum_violation(
        self, timeline: List[Dict[str, Any]], min_capacity: float
    ) -> Optional[int]:
        """
        Najde první index kde kapacita klesne pod minimum.

        Args:
            timeline: Timeline data
            min_capacity: Minimální kapacita (kWh)

        Returns:
            Index prvního porušení nebo None
        """
        for i, point in enumerate(timeline):
            capacity = point.get("battery_capacity_kwh", 0)
            if capacity < min_capacity:
                return i
        return None

    def _find_cheapest_hour_before(
        self,
        timeline: List[Dict[str, Any]],
        before_index: int,
        max_price: float,
        price_threshold: float,
    ) -> Optional[int]:
        """
        Najde nejlevnější vhodnou hodinu před daným indexem.

        Args:
            timeline: Timeline data
            before_index: Index před kterým hledat
            max_price: Maximální cena (CZK/kWh)
            price_threshold: Práh pro špičky (CZK/kWh)

        Returns:
            Index nejlevnější vhodné hodiny nebo None
        """
        candidates = []

        for i in range(before_index):
            point = timeline[i]
            price = point.get("spot_price_czk", float("inf"))

            # Kontrola podmínek
            if price > max_price:
                continue
            if price > price_threshold:  # Je to špička
                continue

            candidates.append((i, price))

        if not candidates:
            return None

        # Seřadit podle ceny a vrátit nejlevnější
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _find_cheapest_suitable_hour(
        self, timeline: List[Dict[str, Any]], max_price: float, price_threshold: float
    ) -> Optional[int]:
        """
        Najde nejlevnější vhodnou hodinu v celém intervalu.

        Args:
            timeline: Timeline data
            max_price: Maximální cena (CZK/kWh)
            price_threshold: Práh pro špičky (CZK/kWh)

        Returns:
            Index nejlevnější vhodné hodiny nebo None
        """
        candidates = []

        for i, point in enumerate(timeline):
            price = point.get("spot_price_czk", float("inf"))

            # Kontrola podmínek
            if price > max_price:
                continue
            if price > price_threshold:  # Je to špička
                continue

            # PŘESKOČIT sloty, které už mají nějaké nabíjení
            existing_charge = point.get("grid_charge_kwh", 0)
            if existing_charge > 0:
                continue

            candidates.append((i, price))

        if not candidates:
            return None

        # Seřadit podle ceny a vrátit nejlevnější
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _recalculate_timeline_from_index(
        self, timeline: List[Dict[str, Any]], start_index: int
    ) -> None:
        """
        Přepočítá timeline od daného indexu podle vzorce baterie.

        DŮLEŽITÉ: Používá stejnou logiku simulace režimů:
        - GAP #1: Efficiency při vybíjení (DC/AC losses)
        - GAP #3: UPS režim (spotřeba ze sítě)

        Args:
            timeline: Timeline data (modifikuje in-place)
            start_index: Index od kterého přepočítat
        """
        max_capacity = self._get_max_battery_capacity()
        min_capacity_percent = (
            self._config_entry.options.get("min_capacity_percent", 20.0)
            if self._config_entry.options
            else self._config_entry.data.get("min_capacity_percent", 20.0)
        )
        min_capacity = (min_capacity_percent / 100.0) * max_capacity

        # Získat battery efficiency
        efficiency = self._get_battery_efficiency()

        for i in range(start_index, len(timeline)):
            if i == 0:
                # První bod - použij aktuální kapacitu jako základ
                continue

            prev_point = timeline[i - 1]
            curr_point = timeline[i]

            # Načíst hodnoty z timeline
            prev_capacity = prev_point.get("battery_capacity_kwh", 0)
            solar_kwh = curr_point.get("solar_production_kwh", 0)  # CELKOVÝ solar
            grid_kwh = curr_point.get("grid_charge_kwh", 0)
            load_kwh = curr_point.get("consumption_kwh", 0)
            reason = curr_point.get("reason", "")

            # Určit režim (UPS vs Home)
            # OPRAVA: Při balancování VŽDY UPS režim
            is_balancing = reason.startswith("balancing_")
            is_ups_mode = grid_kwh > 0 or is_balancing

            if is_ups_mode:
                # UPS režim: spotřeba ze sítě, baterie roste díky solar + grid
                net_energy = solar_kwh + grid_kwh
            else:
                # Home režim: spotřeba z baterie (s DC/AC losses)
                if solar_kwh >= load_kwh:
                    # Solar pokrývá spotřebu + nabíjí baterii
                    solar_to_battery = solar_kwh - load_kwh
                    net_energy = solar_to_battery + grid_kwh
                else:
                    # Solar nepokrývá spotřebu → vybíjení z baterie (s losses!)
                    load_from_battery = load_kwh - solar_kwh
                    battery_drain = load_from_battery / efficiency
                    net_energy = -battery_drain + grid_kwh

            # Aktualizovat solar_charge_kwh pro zobrazení
            curr_point["solar_charge_kwh"] = round(max(0, solar_kwh - load_kwh), 2)

            new_capacity = prev_capacity + net_energy

            # Clamp na maximum a minimum - MUSÍ být konzistentní se simulací režimů
            # 1. Maximum: max battery capacity
            # 2. Minimum: min_capacity (politika) - baterie nemá klesnout pod 20%
            # 3. HARD FLOOR: 0 kWh (fyzikální limit) - baterie nemůže být záporná
            new_capacity = min(new_capacity, max_capacity)
            if new_capacity < min_capacity:
                # Clamp na policy minimum (stejně jako v simulaci režimů)
                new_capacity = min_capacity
            new_capacity = max(0.0, new_capacity)  # HARD FLOOR - fyzikální limit

            curr_point["battery_capacity_kwh"] = round(new_capacity, 2)

            # Aktualizovat mode pokud se změnilo grid_charge
            curr_point["mode"] = (
                MODE_LABEL_HOME_UPS if is_ups_mode else MODE_LABEL_HOME_I
            )

    # =========================================================================
    # ADAPTIVE LOAD PREDICTION v2
    # =========================================================================

    def _calculate_consumption_summary(self, adaptive_profiles: Dict[str, Any]) -> None:
        """Vypočítá 4 sumarizační hodnoty pro dashboard.

        Výstup do self._consumption_summary:
        - planned_consumption_today: kWh od teď do půlnoci
        - planned_consumption_tomorrow: kWh celý zítřek
        - profile_today: lidsky čitelný popis profilu
        - profile_tomorrow: lidsky čitelný popis profilu
        """
        if not adaptive_profiles or not isinstance(adaptive_profiles, dict):
            self._consumption_summary = {}
            return

        # 1. Plánovaná spotřeba DNES (od current_hour do půlnoci)
        today_profile = adaptive_profiles.get("today_profile")
        current_hour = datetime.now().hour
        planned_today = 0.0

        if today_profile and isinstance(today_profile, dict):
            hourly = today_profile.get("hourly_consumption", [])
            start_hour = today_profile.get(
                "start_hour", 0
            )  # Plovoucí okno: od které hodiny začíná pole

            if isinstance(hourly, list):
                # Převést absolutní hodinu na index v poli
                # current_hour=14, start_hour=13 → index=1
                for hour in range(current_hour, 24):
                    index = hour - start_hour
                    if 0 <= index < len(hourly):
                        planned_today += hourly[index]
            elif isinstance(hourly, dict):
                for hour in range(current_hour, 24):
                    planned_today += hourly.get(hour, 0.0)

        # 2. Plánovaná spotřeba ZÍTRA (celý den 0-23)
        tomorrow_profile = adaptive_profiles.get("tomorrow_profile")
        planned_tomorrow = 0.0

        if tomorrow_profile and isinstance(tomorrow_profile, dict):
            hourly = tomorrow_profile.get("hourly_consumption", [])
            start_hour = tomorrow_profile.get(
                "start_hour", 0
            )  # Vždy 0, ale pro konzistenci

            if isinstance(hourly, list):
                # Zítřek vždy začíná od půlnoci (start_hour=0), takže index=hour
                planned_tomorrow = sum(
                    (
                        hourly[h - start_hour]
                        if 0 <= (h - start_hour) < len(hourly)
                        else 0.0
                    )
                    for h in range(24)
                )
            elif isinstance(hourly, dict):
                planned_tomorrow = sum(hourly.get(h, 0.0) for h in range(24))

        # 3. Formátované popisy profilů
        profile_today_text = self._format_profile_description(today_profile)
        profile_tomorrow_text = self._format_profile_description(tomorrow_profile)

        # Uložit
        self._consumption_summary = {
            "planned_consumption_today": round(planned_today, 1),
            "planned_consumption_tomorrow": round(planned_tomorrow, 1),
            "profile_today": profile_today_text,
            "profile_tomorrow": profile_tomorrow_text,
        }

        _LOGGER.debug(
            f"Consumption summary: today={planned_today:.1f}kWh, "
            f"tomorrow={planned_tomorrow:.1f}kWh"
        )

    def _format_profile_description(self, profile: Optional[Dict[str, Any]]) -> str:
        """Vrátí lidsky čitelný popis profilu.

        Příklad: "Páteční večer (zimní, 15 podobných dnů)"
        """
        if not profile or not isinstance(profile, dict):
            return "Žádný profil"

        # Získat název z profile["ui"]["name"]
        ui = profile.get("ui", {})
        raw_name = ui.get("name", "Neznámý profil") or "Neznámý profil"
        cleaned_name = re.sub(
            r"\s*\([^)]*(podobn|shoda)[^)]*\)",
            "",
            str(raw_name),
            flags=re.IGNORECASE,
        ).strip()
        if not cleaned_name:
            cleaned_name = str(raw_name).strip()
        cleaned_name = re.sub(r"\s{2,}", " ", cleaned_name)

        # Získat season z profile["characteristics"]["season"]
        characteristics = profile.get("characteristics", {})
        season = characteristics.get("season", "")

        # Počet dnů z profile["sample_count"]
        day_count = ui.get("sample_count", profile.get("sample_count", 0))
        similarity_score = ui.get("similarity_score")

        # České názvy ročních období
        season_names = {
            "winter": "zimní",
            "spring": "jarní",
            "summer": "letní",
            "autumn": "podzimní",
        }
        season_cz = season_names.get(season, season)

        suffix_parts: List[str] = []
        if season_cz:
            suffix_parts.append(str(season_cz))
        try:
            day_count_val = int(day_count) if day_count is not None else 0
        except (TypeError, ValueError):
            day_count_val = 0
        if day_count_val > 0:
            suffix_parts.append(f"{day_count_val} dnů")
        try:
            similarity_val = (
                float(similarity_score) if similarity_score is not None else None
            )
        except (TypeError, ValueError):
            similarity_val = None
        if similarity_val is not None:
            suffix_parts.append(f"shoda {similarity_val:.2f}")

        if suffix_parts:
            return f"{cleaned_name} ({', '.join(suffix_parts)})"
        return cleaned_name

    def _process_adaptive_consumption_for_dashboard(
        self, adaptive_profiles: Optional[Dict[str, Any]]
    ) -> None:
        """Zpracuj adaptive data pro dashboard (do attributes).

        Vypočítá:
        - remaining_kwh: zbývající spotřeba do konce dne
        - profile_name: lidsky čitelný název profilu
        - profile_details: season, day_count, shoda
        - charging_cost_today: celková cena za nabíjení dnes
        """
        # Check if adaptive_profiles is valid Dict (not list or None)
        if not adaptive_profiles or not isinstance(adaptive_profiles, dict):
            _LOGGER.debug(
                f"No adaptive profiles for dashboard: type={type(adaptive_profiles)}"
            )
            self._adaptive_consumption_data = {}
            return

        # 1. Zbývající spotřeba do konce dne
        now = datetime.now()
        current_hour = now.hour
        remaining_kwh = 0.0

        today_profile = adaptive_profiles.get("today_profile")
        if today_profile and "hourly_consumption" in today_profile:
            hourly = today_profile["hourly_consumption"]
            if isinstance(hourly, list):
                for hour in range(current_hour, 24):
                    if hour < len(hourly):
                        remaining_kwh += hourly[hour]
            elif isinstance(hourly, dict):
                for hour in range(current_hour, 24):
                    remaining_kwh += hourly.get(hour, 0.0)

        # 2. Profil název a detaily
        profile_name = adaptive_profiles.get("profile_name", "Neznámý profil")
        match_score = adaptive_profiles.get("match_score", 0)

        profile_details = ""
        if today_profile:
            season = today_profile.get("season", "")
            day_count = today_profile.get("day_count", 0)

            season_names = {
                "winter": "zimní",
                "spring": "jarní",
                "summer": "letní",
                "autumn": "podzimní",
            }
            season_cz = season_names.get(season, season)

            profile_details = f"{season_cz}, {day_count} podobných dnů"
            if match_score > 0:
                profile_details += f" • {int(match_score)}% shoda"

        # 3. Cena za nabíjení dnes (sečti z timeline)
        charging_cost_today = 0.0
        today_date = now.date()

        for entry in self._timeline_data:
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue

            try:
                entry_dt = datetime.fromisoformat(
                    timestamp_str.replace("Z", ISO_TZ_OFFSET)
                )
                if entry_dt.date() == today_date:
                    charging_kwh = entry.get("charging_kwh", 0)
                    spot_price = entry.get("spot_price_czk_per_kwh", 0)
                    if charging_kwh > 0 and spot_price > 0:
                        charging_cost_today += charging_kwh * spot_price
            except (ValueError, AttributeError):
                continue

        # Uložit do instance
        self._adaptive_consumption_data = {
            "remaining_kwh": round(remaining_kwh, 1),
            "profile_name": profile_name,
            "profile_details": profile_details,
            "charging_cost_today": round(charging_cost_today, 0),
        }

    async def _get_adaptive_load_prediction(self) -> Optional[Dict[str, Any]]:
        """
        Načte adaptive load prediction přímo z adaptive_load_profiles sensoru.

        Sensor už má předpočítané today_profile a tomorrow_profile z 72h matching algoritmu.

        Returns:
            Dict nebo None:
            {
                "today_profile": {...},      # Profil pro zbytek dneška
                "tomorrow_profile": {...},   # Profil pro zítřek (pokud timeline přes půlnoc)
                "match_score": 0.666,
                "prediction_summary": {...}
            }
        """
        try:
            # Načíst data přímo z adaptive sensor
            profiles_sensor = f"sensor.oig_{self._box_id}_adaptive_load_profiles"

            if not self._hass:
                return None

            profiles_state = self._hass.states.get(profiles_sensor)
            if not profiles_state:
                _LOGGER.debug(f"Adaptive profiles sensor not found: {profiles_sensor}")
                return None

            attrs = profiles_state.attributes

            # Zkontrolovat jestli má today_profile a tomorrow_profile
            if "today_profile" not in attrs or "tomorrow_profile" not in attrs:
                _LOGGER.debug(
                    "Adaptive sensor missing today_profile or tomorrow_profile"
                )
                return None

            # Vrátit profily přímo - sensor už udělal matching a prediction
            result = {
                "today_profile": attrs["today_profile"],
                "tomorrow_profile": attrs["tomorrow_profile"],
                "match_score": attrs.get("prediction_summary", {}).get(
                    "similarity_score", 0.0
                ),
                "prediction_summary": attrs.get("prediction_summary", {}),
            }

            _LOGGER.debug(
                f"✅ Adaptive prediction loaded: "
                f"today={result['today_profile'].get('total_kwh', 0):.2f} kWh, "
                f"match_score={result['match_score']:.3f}"
            )

            return result

        except Exception as e:
            _LOGGER.error(f"Error in adaptive load prediction: {e}", exc_info=True)
            return None

    def _get_profiles_from_sensor(self) -> Dict[str, Any]:
        """Načte profily z adaptive sensor a převede list na dict."""
        try:
            profiles_sensor = f"sensor.oig_{self._box_id}_adaptive_load_profiles"

            if not self._hass:
                return {}

            profiles_state = self._hass.states.get(profiles_sensor)
            if not profiles_state:
                return {}

            profiles_list = profiles_state.attributes.get("profiles", [])

            # Převést list na dict s profile_id jako klíčem
            if isinstance(profiles_list, list):
                return {
                    p.get("profile_id", f"profile_{i}"): p
                    for i, p in enumerate(profiles_list)
                }
            elif isinstance(profiles_list, dict):
                return profiles_list
            else:
                _LOGGER.warning(f"Unexpected profiles type: {type(profiles_list)}")
                return {}

        except Exception as e:
            _LOGGER.debug(f"Error getting profiles: {e}")
            return {}

    async def _get_today_hourly_consumption(self) -> List[float]:
        """
        Načte dnešní spotřebu po hodinách (od půlnoci do teď).

        Returns:
            List hodinových spotřeb v kWh (např. [0.5, 0.4, 0.3, ..., 1.2])
        """
        try:
            consumption_sensor = f"sensor.oig_{self._box_id}_actual_aco_p"

            hass = self.hass or self._hass
            if hass is None:
                return []

            # Načíst ze statistics (hodinové průměry)
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            start_time = dt_util.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_time = dt_util.now()

            from homeassistant.components.recorder import get_instance

            stats = await get_instance(hass).async_add_executor_job(
                statistics_during_period,
                hass,
                start_time,
                end_time,
                {consumption_sensor},
                "hour",
                None,
                {"mean"},
            )

            if not stats or consumption_sensor not in stats:
                return []

            hourly_values = []
            for stat in stats[consumption_sensor]:
                if stat.get("mean") is not None:
                    # Statistics jsou ve wattech, převést na kWh/h
                    kwh = stat["mean"] / 1000
                    hourly_values.append(kwh)

            return hourly_values

        except Exception as e:
            _LOGGER.debug(f"Error getting today hourly consumption: {e}")
            return []

    async def _calculate_recent_consumption_ratio(
        self, adaptive_profiles: Optional[Dict[str, Any]], hours: int = 3
    ) -> Optional[float]:
        """Porovná reálnou spotřebu vs plán za posledních N hodin."""
        if (
            not adaptive_profiles
            or not isinstance(adaptive_profiles, dict)
            or "today_profile" not in adaptive_profiles
        ):
            return None

        actual_hourly = await self._get_today_hourly_consumption()
        if not actual_hourly:
            return None

        total_hours = len(actual_hourly)
        if total_hours == 0:
            return None

        lookback = min(hours, total_hours)
        actual_total = sum(actual_hourly[-lookback:])

        today_profile = adaptive_profiles.get("today_profile") or {}
        hourly_plan = today_profile.get("hourly_consumption")
        if not isinstance(hourly_plan, list):
            return None

        start_hour = today_profile.get("start_hour", 0)
        planned_total = 0.0
        start_index = total_hours - lookback
        avg_fallback = today_profile.get("avg_kwh_h", 0.5)

        for idx in range(lookback):
            hour = start_index + idx
            plan_idx = hour - start_hour
            if 0 <= plan_idx < len(hourly_plan):
                planned_total += hourly_plan[plan_idx]
            else:
                planned_total += avg_fallback

        if planned_total <= 0:
            return None

        ratio = actual_total / planned_total
        _LOGGER.debug(
            "[LoadForecast] Recent consumption ratio (last %dh): actual=%.2f kWh, planned=%.2f kWh → %.2fx",
            lookback,
            actual_total,
            planned_total,
            ratio,
        )
        return ratio

    def _apply_consumption_boost_to_forecast(
        self, load_forecast: List[float], ratio: float, hours: int = 3
    ) -> None:
        """Navýší krátkodobý load forecast podle zjištěné odchylky."""
        if not load_forecast:
            return

        capped_ratio = min(ratio, 3.0)
        intervals = min(
            len(load_forecast),
            max(4, int(math.ceil(hours * 4 * min(capped_ratio, 2.5)))),
        )

        for idx in range(intervals):
            load_forecast[idx] = round(load_forecast[idx] * capped_ratio, 4)

        _LOGGER.info(
            "[LoadForecast] Boosted first %d intervals by %.0f%% due to high consumption drift (ratio %.2fx, capped %.2fx)",
            intervals,
            (capped_ratio - 1) * 100,
            ratio,
            capped_ratio,
        )

    def _calculate_profile_similarity(
        self, today_hourly: List[float], profile_hourly: List[float]
    ) -> float:
        """
        Vypočítá podobnost dnešní křivky s profilem (MAPE scoring).

        Returns:
            float: Score 0-100% (vyšší = lepší match)
        """
        if not today_hourly or len(today_hourly) == 0:
            return 0

        # Porovnat jen hodiny které už proběhly
        compare_length = min(len(today_hourly), len(profile_hourly))

        total_error = 0
        valid_hours = 0

        for i in range(compare_length):
            actual = today_hourly[i]
            expected = profile_hourly[i]

            if actual > 0:  # Ignore zero hours
                error = abs(actual - expected) / actual
                total_error += error
                valid_hours += 1

        if valid_hours == 0:
            return 0

        avg_error = total_error / valid_hours
        score = max(0, 100 - (avg_error * 100))

        return score

    def _select_tomorrow_profile(
        self, profiles: Dict[str, Any], current_time: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Vybere profil pro zítřek podle day_type a transition.

        Args:
            profiles: Všechny dostupné profily
            current_time: Aktuální čas

        Returns:
            Profil pro zítřek nebo None
        """
        try:
            tomorrow = current_time + timedelta(days=1)
            tomorrow_weekday = tomorrow.weekday()
            today_weekday = current_time.weekday()

            # Určit season pro zítřek
            month = tomorrow.month
            if month in [12, 1, 2]:
                season = "winter"
            elif month in [3, 4, 5]:
                season = "spring"
            elif month in [6, 7, 8]:
                season = "summer"
            else:
                season = "autumn"

            # Detekovat transition
            transition_type = None

            # Pátek (4) → Sobota (5)
            if today_weekday == 4 and tomorrow_weekday == 5:
                transition_type = "friday_to_saturday"
            # Neděle (6) → Pondělí (0)
            elif today_weekday == 6 and tomorrow_weekday == 0:
                transition_type = "sunday_to_monday"

            # 1. Zkusit najít transition profil
            if transition_type:
                transition_profile_id = f"{transition_type}_{season}"
                for profile_id, profile in profiles.items():
                    if profile_id.startswith(transition_profile_id):
                        _LOGGER.debug(
                            f"Using transition profile for tomorrow: {profile_id}"
                        )
                        return profile

            # 2. Fallback: standardní profil podle day_type
            tomorrow_is_weekend = tomorrow_weekday >= 5
            day_type = "weekend" if tomorrow_is_weekend else "weekday"
            standard_profile_id = f"{day_type}_{season}"

            best_match = None
            for profile_id, profile in profiles.items():
                if profile_id.startswith(standard_profile_id):
                    # Vezmi první matching profil
                    if (
                        not best_match
                        or "_typical" in profile_id
                        or len(profile_id.split("_")) == 2
                    ):
                        best_match = profile

            if best_match:
                _LOGGER.debug(
                    f"Using standard profile for tomorrow: {day_type}_{season}"
                )

            return best_match

        except Exception as e:
            _LOGGER.debug(f"Error selecting tomorrow profile: {e}")
            return None

    async def _get_consumption_today(self) -> Optional[float]:
        """Získat celkovou spotřebu dnes od půlnoci do teď."""
        try:
            consumption_sensor = f"sensor.oig_{self._box_id}_actual_aco_p"

            start_time = dt_util.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_time = dt_util.now()

            # Načíst states z recorderu
            from homeassistant.components.recorder import history

            from homeassistant.components.recorder import get_instance

            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start_time,
                end_time,
                [consumption_sensor],
            )

            if not states or consumption_sensor not in states:
                return None

            consumption_states = states[consumption_sensor]
            if not consumption_states:
                return None

            # Spočítat průměr a vynásobit hodinami
            import statistics

            valid_values = []
            for state in consumption_states:
                try:
                    value = float(state.state)
                    if 0 <= value <= 20000:  # Sanity check
                        valid_values.append(value)
                except (ValueError, AttributeError):
                    continue

            if not valid_values:
                return None

            avg_watts = statistics.mean(valid_values)
            hours_elapsed = (end_time - start_time).total_seconds() / 3600
            total_kwh = (avg_watts / 1000) * hours_elapsed

            return total_kwh

        except Exception as e:
            _LOGGER.debug(f"Error getting consumption today: {e}")
            return None

    def _get_load_avg_fallback(self) -> float:
        """
        Fallback: Získá průměr z load_avg senzorů pro aktuální čas.

        Returns:
            float: kWh/h
        """
        current_time = dt_util.now()
        is_weekend = current_time.weekday() >= 5
        day_type = "weekend" if is_weekend else "weekday"

        hour = current_time.hour
        if 6 <= hour < 8:
            time_block = "6_8"
        elif 8 <= hour < 12:
            time_block = "8_12"
        elif 12 <= hour < 16:
            time_block = "12_16"
        elif 16 <= hour < 22:
            time_block = "16_22"
        else:
            time_block = "22_6"

        sensor_id = f"sensor.oig_{self._box_id}_load_avg_{time_block}_{day_type}"

        if self._hass:
            sensor_state = self._hass.states.get(sensor_id)
            if sensor_state and sensor_state.state not in ["unknown", "unavailable"]:
                try:
                    watt = float(sensor_state.state)
                    return watt / 1000  # W → kWh/h
                except (ValueError, TypeError):
                    pass

        # Ultimate fallback
        return 0.48

    # ═══════════════════════════════════════════════════════════════════════════


class OigCloudGridChargingPlanSensor(CoordinatorEntity, SensorEntity):
    """Sensor pro plánované nabíjení ze sítě - odvozený z battery_forecast."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        device_info: Dict[str, Any],
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._attr_device_info = device_info

        # Načteme sensor config
        from .sensor_types import SENSOR_TYPES

        self._config = SENSOR_TYPES.get(sensor_type, {})

        # Entity info
        try:
            from .oig_cloud_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"
        # Unique ID má formát oig_cloud_{boxId}_{sensor} pro konzistenci
        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        # Načíst název ze sensor types
        name_cs = self._config.get("name_cs")
        name_en = self._config.get("name")
        self._attr_name = name_cs or name_en or sensor_type

        # Nastavit vlastnosti senzoru
        self._attr_native_unit_of_measurement = self._config.get("unit")
        self._attr_icon = self._config.get("icon", "mdi:battery-charging")

        # Správné typování pro device_class a entity_category
        device_class = self._config.get("device_class")
        if device_class:
            self._attr_device_class = SensorDeviceClass(device_class)

        entity_category = self._config.get("entity_category")
        if entity_category:
            self._attr_entity_category = EntityCategory(entity_category)

        state_class = self._config.get("state_class")
        if state_class:
            self._attr_state_class = SensorStateClass(state_class)

        # Cache pro offsety (aby se nelogoval pokaždé)
        self._last_offset_start = None
        self._last_offset_end = None

        # Cache pro UPS bloky z precomputed storage
        self._cached_ups_blocks: List[Dict[str, Any]] = []

        # Local rate-limit cache for log messages (keeps HA logs clean)
        self._log_rl_last: Dict[str, float] = {}

    def _log_rate_limited(
        self,
        key: str,
        level: str,
        msg: str,
        *args: Any,
        cooldown_s: float = 3600.0,
    ) -> None:
        """Log at most once per cooldown for the given key."""
        now = time.monotonic()
        last = self._log_rl_last.get(key, 0.0)
        if now - last < cooldown_s:
            return
        self._log_rl_last[key] = now
        log_fn = getattr(_LOGGER, level, _LOGGER.debug)
        log_fn(msg, *args)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        # Load initial data
        await self._load_ups_blocks()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        # Schedule async load of UPS blocks
        if self.hass:
            self.hass.async_create_task(self._load_ups_blocks())
        super()._handle_coordinator_update()

    async def _load_ups_blocks(self) -> None:
        """Load UPS blocks from precomputed storage (async)."""
        plan_key = self._get_active_plan_key()
        self._cached_ups_blocks = await self._get_home_ups_blocks_from_detail_tabs(
            plan=plan_key
        )
        _LOGGER.debug(
            f"[GridChargingPlan] Loaded {len(self._cached_ups_blocks)} UPS blocks into cache"
        )
        # Trigger state update after loading cache
        self.async_write_ha_state()

    async def _get_home_ups_blocks_from_detail_tabs(
        self, plan: str = "hybrid"
    ) -> List[Dict[str, Any]]:
        """
        Načte HOME UPS bloky z precomputed storage.
        Vrací pouze AKTIVNÍ a BUDOUCÍ bloky (ne completed z minulosti).
        """
        try:
            # 1. Najít BatteryForecastSensor
            if not self.hass:
                return []

            battery_sensor = None
            component = self.hass.data.get("entity_components", {}).get("sensor")
            if component:
                for entity in component.entities:
                    if (
                        hasattr(entity, "_precomputed_store")
                        and self._box_id in entity.entity_id
                        and "battery_forecast" in entity.entity_id
                    ):
                        battery_sensor = entity
                        break

            if not battery_sensor:
                _LOGGER.warning("[GridChargingPlan] BatteryForecastSensor not found")
                return []

            # 2. Načíst precomputed data ASYNC
            precomputed = await battery_sensor._precomputed_store.async_load()

            if not precomputed:
                _LOGGER.debug("[GridChargingPlan] No precomputed data yet")
                return []

            # 3. Získat today + tomorrow mode_blocks
            _ = plan  # legacy parameter (dual-planner removed)
            plan_key = "hybrid"
            detail_tabs = precomputed.get("detail_tabs", {}) or precomputed.get(
                "detail_tabs_hybrid", {}
            )
            if not detail_tabs:
                _LOGGER.debug(
                    "[GridChargingPlan] No %s detail tabs data available", plan_key
                )
                return []

            # 4. Filtrovat HOME UPS bloky - pouze active + planned (ne completed)
            now = dt_util.now()
            current_time = now.strftime("%H:%M")

            ups_blocks = []

            # Process TODAY blocks
            today = detail_tabs.get("today", {})
            today_blocks = today.get("mode_blocks", [])

            for block in today_blocks:
                # Zkontrolovat zda je to HOME UPS blok
                mode_hist = block.get("mode_historical", "")
                mode_plan = block.get("mode_planned", "")
                if "HOME UPS" not in mode_hist and "HOME UPS" not in mode_plan:
                    continue

                # Filtrovat podle statusu a času
                status = block.get("status", "")
                end_time = block.get("end_time", "")

                # Přeskočit completed bloky z minulosti
                if status == "completed" and end_time < current_time:
                    continue

                # Přidat aktivní nebo budoucí blok
                ups_blocks.append(
                    {
                        "time_from": block.get("start_time", ""),
                        "time_to": end_time,
                        "day": "today",
                        "mode": MODE_LABEL_HOME_UPS,
                        "status": status,
                        "grid_charge_kwh": block.get("grid_import_total_kwh", 0.0),
                        "cost_czk": block.get(
                            (
                                "cost_historical"
                                if status == "completed"
                                else "cost_planned"
                            ),
                            0.0,
                        ),
                        "battery_start_kwh": block.get("battery_soc_start", 0.0),
                        "battery_end_kwh": block.get("battery_soc_end", 0.0),
                        "interval_count": block.get("interval_count", 0),
                        "duration_hours": block.get("duration_hours", 0.0),
                    }
                )

            # Process TOMORROW blocks (všechny jsou planned)
            tomorrow = detail_tabs.get("tomorrow", {})
            tomorrow_blocks = tomorrow.get("mode_blocks", [])

            for block in tomorrow_blocks:
                # Zkontrolovat zda je to HOME UPS blok
                mode_plan = block.get("mode_planned", "")
                if "HOME UPS" not in mode_plan:
                    continue

                # Přidat zítřejší plánovaný blok
                ups_blocks.append(
                    {
                        "time_from": block.get("start_time", ""),
                        "time_to": block.get("end_time", ""),
                        "day": "tomorrow",
                        "mode": MODE_LABEL_HOME_UPS,
                        "status": "planned",  # Všechny zítřejší bloky jsou planned
                        "grid_charge_kwh": block.get("grid_import_total_kwh", 0.0),
                        "cost_czk": block.get("cost_planned", 0.0),
                        "battery_start_kwh": block.get("battery_soc_start", 0.0),
                        "battery_end_kwh": block.get("battery_soc_end", 0.0),
                        "interval_count": block.get("interval_count", 0),
                        "duration_hours": block.get("duration_hours", 0.0),
                    }
                )

            _LOGGER.debug(
                f"[GridChargingPlan] Found {len(ups_blocks)} active/future UPS blocks (today + tomorrow)"
            )
            return ups_blocks

        except Exception as e:
            _LOGGER.error(f"[GridChargingPlan] Error: {e}", exc_info=True)
            return []

    def _get_active_plan_key(self) -> str:
        """Return active plan key (single-planner)."""
        return "hybrid"

    def _calculate_charging_intervals(
        self,
    ) -> tuple[List[Dict[str, Any]], float, float]:
        """Vypočítá intervaly nabíjení ze sítě z CACHED detail_tabs dat."""
        # Použít cache místo async volání
        charging_intervals = self._cached_ups_blocks

        if not charging_intervals:
            return [], 0.0, 0.0

        total_energy = sum(block["grid_charge_kwh"] for block in charging_intervals)
        total_cost = sum(block["cost_czk"] for block in charging_intervals)

        return charging_intervals, total_energy, total_cost

    def _get_dynamic_offset(self, from_mode: str, to_mode: str) -> float:
        """Získá dynamický offset z ModeTransitionTracker.

        Args:
            from_mode: Zdrojový režim (např. "Home 1")
            to_mode: Cílový režim (např. "Home UPS")

        Returns:
            Offset v sekundách (fallback 300s = 5 minut pokud tracker není dostupný)
        """
        try:
            # OPRAVA: Použít self.hass z CoordinatorEntity
            if not self.hass:
                self._log_rate_limited(
                    f"grid_offset_missing_hass_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] hass not available for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0  # Fallback 5 minut

            # Získat config_entry přes coordinator
            config_entry = self.coordinator.config_entry
            if not config_entry:
                self._log_rate_limited(
                    f"grid_offset_missing_entry_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] No config_entry for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            entry_data = self.hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
            if not entry_data:
                self._log_rate_limited(
                    f"grid_offset_missing_entry_data_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] No entry data for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            service_shield = entry_data.get("service_shield")
            if not service_shield or not hasattr(service_shield, "mode_tracker"):
                self._log_rate_limited(
                    f"grid_offset_missing_tracker_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] ServiceShield/mode_tracker not available for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            mode_tracker = service_shield.mode_tracker
            if not mode_tracker:
                self._log_rate_limited(
                    f"grid_offset_tracker_uninit_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] Mode tracker not initialized for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            # Získat doporučený offset
            offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)

            self._log_rate_limited(
                f"grid_offset_ok_{from_mode}_{to_mode}",
                "debug",
                "[GridChargingPlan] Dynamic offset %s→%s: %ss (from tracker)",
                from_mode,
                to_mode,
                offset_seconds,
                cooldown_s=3600.0,
            )

            return offset_seconds

        except Exception as e:
            _LOGGER.warning(
                f"[GridChargingPlan] ❌ Error getting offset {from_mode}→{to_mode}, using fallback 300s: {e}",
                exc_info=True,
            )
            return 300.0  # Fallback 5 minut

    @property
    def native_value(self) -> str:
        """Vrátí ON pokud právě běží nebo brzy začne HOME UPS (s offsetem)."""
        charging_intervals, _, _ = self._calculate_charging_intervals()

        if not charging_intervals:
            return "off"

        # Získat aktuální čas
        now = dt_util.now()

        # Získat aktuální režim z coordinator
        current_mode = self._get_current_mode()

        # Seřadit bloky chronologicky (today před tomorrow)
        sorted_blocks = sorted(
            charging_intervals,
            key=lambda b: (0 if b.get("day") == "today" else 1, b.get("time_from", "")),
        )

        # Projít všechny UPS bloky a zkontrolovat s offsety
        for i, block in enumerate(sorted_blocks):
            start_time_str = block.get("time_from", "00:00")
            end_time_str = block.get("time_to", "23:59")
            day = block.get("day", "today")

            # Parse časy
            try:
                start_hour, start_min = map(int, start_time_str.split(":"))
                end_hour, end_min = map(int, end_time_str.split(":"))

                start_time = now.replace(
                    hour=start_hour, minute=start_min, second=0, microsecond=0
                )
                end_time = now.replace(
                    hour=end_hour, minute=end_min, second=0, microsecond=0
                )

                # Pokud je blok zítra, přidat 1 den
                if day == "tomorrow":
                    start_time = start_time + timedelta(days=1)
                    end_time = end_time + timedelta(days=1)

                # Pokud end_time <= start_time, je to přes půlnoc
                if end_time <= start_time:
                    end_time = end_time + timedelta(days=1)

            except (ValueError, AttributeError):
                _LOGGER.warning(
                    f"[GridChargingPlan] Invalid time format: {start_time_str} - {end_time_str}"
                )
                continue

            # Získat offset pro zapnutí (current_mode → HOME UPS)
            offset_on = self._get_dynamic_offset(current_mode, "HOME UPS")
            start_time_with_offset = start_time - timedelta(seconds=offset_on)

            # Zkontrolovat zda je další blok taky HOME UPS (continuity)
            next_block_is_ups = False
            if i + 1 < len(sorted_blocks):
                next_block = sorted_blocks[i + 1]
                # Pokud další blok začíná hned po tomto (± 1 minuta), je to continuity
                next_start = next_block.get("time_from", "")
                if (
                    next_start == end_time_str
                    or abs(
                        (
                            self._parse_time_to_datetime(
                                next_start, next_block.get("day")
                            )
                            - end_time
                        ).total_seconds()
                    )
                    <= 60
                ):
                    next_block_is_ups = True

            # Získat offset pro vypnutí
            if next_block_is_ups:
                # Další blok je taky UPS, takže NEVYPíNÁME (offset = 0)
                offset_off = 0
            else:
                # Najít následující režim (kam jdeme po UPS)
                next_mode = self._get_next_mode_after_ups(block, sorted_blocks, i)
                offset_off = self._get_dynamic_offset("HOME UPS", next_mode)

            end_time_with_offset = end_time - timedelta(seconds=offset_off)

            # Zkontrolovat zda jsme v časovém okně s offsety
            if start_time_with_offset <= now <= end_time_with_offset:
                _LOGGER.debug(
                    f"[GridChargingPlan] Sensor ON: now={now.strftime('%H:%M:%S')}, "
                    f"block={start_time_str}-{end_time_str}, "
                    f"offset_on={offset_on}s, offset_off={offset_off}s"
                )
                return "on"

        return "off"

    def _get_current_mode(self) -> str:
        """Získá aktuální režim z coordinator data."""
        if not self.coordinator or not self.coordinator.data:
            return "HOME I"  # Fallback

        box_data = self.coordinator.data.get(self._box_id, {})
        current_mode = box_data.get("current_mode", "HOME I")
        return current_mode

    def _get_next_mode_after_ups(
        self, current_block: Dict, all_blocks: List[Dict], current_idx: int
    ) -> str:
        """Získá režim následující po UPS bloku."""
        # Zkusit najít další non-UPS blok v precomputed data
        if current_idx + 1 < len(all_blocks):
            next_block = all_blocks[current_idx + 1]
            next_mode = next_block.get("mode_planned", "HOME I")
            if "HOME UPS" not in next_mode:
                return next_mode

        # Fallback na HOME I (nejčastější режim po nabíjení)
        return "HOME I"

    def _parse_time_to_datetime(self, time_str: str, day: str) -> datetime:
        """Parse time string to datetime."""
        now = dt_util.now()
        try:
            hour, minute = map(int, time_str.split(":"))
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if day == "tomorrow":
                dt = dt + timedelta(days=1)
            return dt
        except (ValueError, AttributeError):
            return now

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Vrátí atributy senzoru - nabíjecí bloky z detail_tabs API."""
        # Vypočítat data on-demand (bez cache)
        charging_intervals, total_energy, total_cost = (
            self._calculate_charging_intervals()
        )

        if not charging_intervals:
            return {
                "charging_blocks": [],
                "total_energy_kwh": 0.0,
                "total_cost_czk": 0.0,
                "next_charging_time_range": None,
                "next_charging_duration": None,
                "is_charging_planned": False,
            }

        # Najít další budoucí nabíjecí blok (status=planned)
        next_charging_block = None
        for interval in charging_intervals:
            if interval.get("status") == "planned":
                next_charging_block = interval
                break

        next_charging_time_range = None
        next_charging_duration = None
        if next_charging_block:
            day_label = (
                "zítra" if next_charging_block.get("day") == "tomorrow" else "dnes"
            )
            next_charging_time_range = f"{day_label} {next_charging_block['time_from']} - {next_charging_block['time_to']}"
            duration_hours = next_charging_block.get("duration_hours", 0)
            duration_minutes = int(duration_hours * 60)
            next_charging_duration = f"{duration_minutes} min"

        # Přejmenovat charging_intervals na charging_blocks pro konzistenci s GUI
        charging_blocks = []
        for interval in charging_intervals:
            # Přemapovat klíče pro zpětnou kompatibilitu
            block = {
                "time_from": interval["time_from"],
                "time_to": interval["time_to"],
                "day": interval["day"],  # Přidat den (today/tomorrow)
                "mode": interval["mode"],
                "status": interval["status"],
                "grid_charge_kwh": interval["grid_charge_kwh"],
                "total_cost_czk": interval["cost_czk"],
                "battery_start_kwh": interval["battery_start_kwh"],
                "battery_end_kwh": interval["battery_end_kwh"],
                "interval_count": interval["interval_count"],
                "is_charging_battery": True,  # Všechny bloky jsou nabíjecí (filtrováno v _calculate_charging_intervals)
                # Průměrná cena
                "avg_spot_price_czk": (
                    round(interval["cost_czk"] / interval["grid_charge_kwh"], 2)
                    if interval["grid_charge_kwh"] > 0
                    else 0.0
                ),
            }
            charging_blocks.append(block)

        return {
            "charging_blocks": charging_blocks,
            "total_energy_kwh": round(total_energy, 2),
            "total_cost_czk": round(total_cost, 2),
            "next_charging_time_range": next_charging_time_range,
            "next_charging_duration": next_charging_duration,
            "is_charging_planned": len(charging_blocks) > 0,
        }


class OigCloudPlannerRecommendedModeSensor(
    RestoreEntity, CoordinatorEntity, SensorEntity
):
    """Text sensor exposing the planner's recommended mode for the current interval."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)
        self._attr_device_info = device_info

        from .sensor_types import SENSOR_TYPES

        self._config = SENSOR_TYPES.get(sensor_type, {})

        try:
            from .oig_cloud_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        self._precomputed_store: Optional[Store] = None
        self._precomputed_payload: Optional[Dict[str, Any]] = None
        if self._hass:
            self._precomputed_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )

        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        name_cs = self._config.get("name_cs")
        name_en = self._config.get("name")
        self._attr_name = name_cs or name_en or sensor_type
        self._attr_icon = self._config.get("icon", "mdi:robot")
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

        entity_category = self._config.get("entity_category")
        if entity_category:
            self._attr_entity_category = EntityCategory(entity_category)

        self._attr_native_value: Optional[str] = None
        self._attr_extra_state_attributes: Dict[str, Any] = {}
        self._last_signature: Optional[str] = None
        self._unsubs: list[callable] = []

    async def _async_refresh_precomputed_payload(self) -> None:
        if not self._precomputed_store:
            return
        try:
            precomputed = await self._precomputed_store.async_load()
        except Exception:
            return
        if not isinstance(precomputed, dict):
            return
        timeline = precomputed.get("timeline") or precomputed.get("timeline_hybrid")
        detail_tabs = precomputed.get("detail_tabs") or precomputed.get(
            "detail_tabs_hybrid"
        )
        if not isinstance(timeline, list) or not timeline:
            return
        self._precomputed_payload = {
            "timeline_data": timeline,
            "calculation_time": precomputed.get("last_update"),
            "detail_tabs": detail_tabs if isinstance(detail_tabs, dict) else None,
        }

    def _get_forecast_payload(self) -> Optional[Dict[str, Any]]:
        # Prefer precomputed payload to stay aligned with detail_tabs output.
        if isinstance(self._precomputed_payload, dict):
            return self._precomputed_payload
        data = getattr(self.coordinator, "battery_forecast_data", None)
        if isinstance(data, dict) and isinstance(data.get("timeline_data"), list):
            return data
        return None

    def _parse_local_start(self, ts: Any) -> Optional[datetime]:
        if not ts:
            return None
        try:
            dt_obj = dt_util.parse_datetime(str(ts)) or datetime.fromisoformat(str(ts))
        except Exception:
            return None
        if dt_obj.tzinfo is None:
            return dt_obj.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_local(dt_obj)

    def _parse_interval_time(
        self, ts: Any, date_hint: Optional[str] = None
    ) -> Optional[datetime]:
        if not ts:
            return None
        ts_str = str(ts)
        if "T" not in ts_str and date_hint:
            ts_str = f"{date_hint}T{ts_str}:00"
        return self._parse_local_start(ts_str)

    def _normalize_mode_label(
        self, mode_name: Optional[str], mode_code: Optional[int]
    ) -> Optional[str]:
        if mode_name:
            upper = str(mode_name).strip().upper()
            if "UPS" in upper:
                return "Home UPS"
            if "HOME I" in upper or upper == "HOME 1":
                return "Home 1"
            if "HOME II" in upper or upper == "HOME 2":
                return "Home 2"
            if "HOME III" in upper or upper == "HOME 3":
                return "Home 3"
            if upper in {"HOME 1", "HOME 2", "HOME 3", "HOME UPS"}:
                return str(mode_name).title()

        if isinstance(mode_code, int):
            if mode_code == 0:
                return "Home 1"
            if mode_code == 1:
                return "Home 2"
            if mode_code == 2:
                return "Home 3"
            if mode_code == 3:
                return "Home UPS"
        return None

    def _get_auto_switch_lead_seconds(
        self, from_mode: Optional[str], to_mode: Optional[str]
    ) -> float:
        fallback = 180.0
        if self._config_entry and self._config_entry.options:
            fallback = float(
                self._config_entry.options.get(
                    "auto_mode_switch_lead_seconds",
                    self._config_entry.options.get(
                        "autonomy_switch_lead_seconds", 180.0
                    ),
                )
            )
        if not from_mode or not to_mode or not self._hass or not self._config_entry:
            return fallback
        try:
            entry = self._hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
            service_shield = entry.get("service_shield")
            mode_tracker = getattr(service_shield, "mode_tracker", None)
            if not mode_tracker:
                return fallback
            offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)
            if offset_seconds is None or offset_seconds <= 0:
                return fallback
            return float(offset_seconds)
        except Exception:
            return fallback

    def _compute_state_and_attrs(self) -> tuple[Optional[str], Dict[str, Any], str]:
        """Compute recommended mode + attributes and return signature for change detection."""
        attrs: Dict[str, Any] = {}
        payload = self._get_forecast_payload() or {}
        detail_tabs = (
            payload.get("detail_tabs")
            if isinstance(payload.get("detail_tabs"), dict)
            else None
        )
        timeline = payload.get("timeline_data")
        attrs["last_update"] = payload.get("calculation_time")
        detail_intervals: Optional[List[Dict[str, Any]]] = None
        detail_date: Optional[str] = None
        if isinstance(detail_tabs, dict):
            today_tab = detail_tabs.get("today") or {}
            if isinstance(today_tab, dict):
                detail_intervals = today_tab.get("intervals")
                detail_date = today_tab.get("date")

        source_intervals = (
            detail_intervals if isinstance(detail_intervals, list) else timeline
        )
        attrs["points_count"] = (
            len(source_intervals) if isinstance(source_intervals, list) else 0
        )

        if not isinstance(source_intervals, list) or not source_intervals:
            sig = json.dumps({"v": None, "a": attrs}, sort_keys=True, default=str)
            return None, attrs, sig

        now = dt_util.now()
        current_idx: Optional[int] = None
        current_mode: Optional[str] = None
        current_mode_code: Optional[int] = None
        current_start: Optional[datetime] = None

        if detail_intervals and isinstance(detail_intervals, list):

            def _planned_mode(
                interval: Dict[str, Any],
            ) -> tuple[Optional[str], Optional[int]]:
                planned = interval.get("planned") or {}
                mode_label = self._normalize_mode_label(
                    planned.get("mode_name"), planned.get("mode")
                )
                mode_code = (
                    planned.get("mode")
                    if isinstance(planned.get("mode"), int)
                    else None
                )
                return mode_label, mode_code

            for i, item in enumerate(detail_intervals):
                start = self._parse_interval_time(
                    item.get("time") or item.get("timestamp"), detail_date
                )
                if not start:
                    continue
                end = start + timedelta(minutes=15)
                mode_label, mode_code = _planned_mode(item)
                if not mode_label:
                    continue
                if start <= now < end:
                    current_idx = i
                    current_start = start
                    current_mode = mode_label
                    current_mode_code = mode_code
                    break
                if start <= now:
                    current_idx = i
                    current_start = start
                    current_mode = mode_label
                    current_mode_code = mode_code
                if start > now and current_idx is not None:
                    break

            if current_mode is None and isinstance(timeline, list):
                for i, item in enumerate(timeline):
                    start = self._parse_local_start(
                        item.get("time") or item.get("timestamp")
                    )
                    if not start:
                        continue
                    end = start + timedelta(minutes=15)
                    if start <= now < end:
                        current_idx = i
                        current_start = start
                        current_mode = self._normalize_mode_label(
                            item.get("mode_name"), item.get("mode")
                        )
                        current_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                        break
                    if start <= now:
                        current_idx = i
                        current_start = start
                        current_mode = self._normalize_mode_label(
                            item.get("mode_name"), item.get("mode")
                        )
                        current_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                    if start > now and current_idx is not None:
                        break
        else:
            for i, item in enumerate(source_intervals):
                start = self._parse_local_start(
                    item.get("time") or item.get("timestamp")
                )
                if not start:
                    continue
                end = start + timedelta(minutes=15)
                if start <= now < end:
                    current_idx = i
                    current_start = start
                    current_mode = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    current_mode_code = (
                        item.get("mode") if isinstance(item.get("mode"), int) else None
                    )
                    break
                if start <= now:
                    current_idx = i
                    current_start = start
                    current_mode = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    current_mode_code = (
                        item.get("mode") if isinstance(item.get("mode"), int) else None
                    )
                if start > now and current_idx is not None:
                    break

        attrs["recommended_interval_start"] = (
            current_start.isoformat() if isinstance(current_start, datetime) else None
        )

        next_change_at: Optional[datetime] = None
        next_mode: Optional[str] = None
        next_mode_code: Optional[int] = None
        if current_idx is not None and current_mode:
            if detail_intervals and isinstance(detail_intervals, list):
                for item in detail_intervals[current_idx + 1 :]:
                    start = self._parse_interval_time(
                        item.get("time") or item.get("timestamp"), detail_date
                    )
                    if not start:
                        continue
                    planned = item.get("planned") or {}
                    candidate = self._normalize_mode_label(
                        planned.get("mode_name"), planned.get("mode")
                    )
                    if candidate and candidate != current_mode:
                        next_change_at = start
                        next_mode = candidate
                        next_mode_code = (
                            planned.get("mode")
                            if isinstance(planned.get("mode"), int)
                            else None
                        )
                        break
            else:
                for item in source_intervals[current_idx + 1 :]:
                    start = self._parse_local_start(
                        item.get("time") or item.get("timestamp")
                    )
                    if not start:
                        continue
                    candidate = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    if candidate and candidate != current_mode:
                        next_change_at = start
                        next_mode = candidate
                        next_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                        break

        attrs["next_mode_change_at"] = (
            next_change_at.isoformat() if next_change_at else None
        )
        attrs["next_mode"] = next_mode
        attrs["next_mode_code"] = next_mode_code

        effective_mode = current_mode
        effective_mode_code = current_mode_code
        lead_seconds: Optional[float] = 0.0
        effective_from: Optional[datetime] = None
        if next_change_at and next_mode and current_mode:
            lead_seconds = self._get_auto_switch_lead_seconds(current_mode, next_mode)
            if lead_seconds and lead_seconds > 0:
                effective_from = next_change_at - timedelta(seconds=lead_seconds)
            else:
                lead_seconds = 0.0

        attrs["planned_interval_mode"] = current_mode
        attrs["planned_interval_mode_code"] = current_mode_code
        attrs["recommended_mode"] = effective_mode
        attrs["recommended_mode_code"] = effective_mode_code
        attrs["recommended_effective_from"] = (
            effective_from.isoformat() if effective_from else None
        )
        attrs["auto_switch_lead_seconds"] = lead_seconds

        # Signature controls when we write HA state; include derived values + last_update.
        sig = json.dumps(
            {
                "v": effective_mode,
                "c": effective_mode_code,
                "cv": current_mode,
                "cc": current_mode_code,
                "s": attrs.get("recommended_interval_start"),
                "n": attrs.get("next_mode_change_at"),
                "nv": next_mode,
                "nc": next_mode_code,
                "ef": attrs.get("recommended_effective_from"),
                "ls": lead_seconds,
                "lu": attrs.get("last_update"),
                "pc": attrs.get("points_count"),
            },
            sort_keys=True,
            default=str,
        )
        return effective_mode, attrs, sig

    async def _async_recompute(self) -> None:
        try:
            await self._async_refresh_precomputed_payload()
            value, attrs, sig = self._compute_state_and_attrs()
            if sig == self._last_signature:
                return
            self._last_signature = sig
            self._attr_native_value = value
            self._attr_extra_state_attributes = attrs
            if self.hass:
                self.async_write_ha_state()
        except Exception:
            # Keep the sensor resilient; do not raise from background callbacks.
            return

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._precomputed_store and self.hass:
            self._precomputed_store = Store(
                self.hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )

        # Do NOT update on every coordinator tick (local telemetry can be very noisy).
        # Recompute only on forecast updates and on 15-minute boundaries.
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from homeassistant.helpers.event import async_track_time_change

        # Forecast updated signal
        signal_name = f"oig_cloud_{self._box_id}_forecast_updated"

        async def _on_forecast_updated() -> None:
            self.hass.async_create_task(self._async_recompute())

        try:
            self._unsubs.append(
                async_dispatcher_connect(self.hass, signal_name, _on_forecast_updated)
            )
        except Exception:
            pass

        # 15-minute boundary recompute (recommended_mode changes with time even if timeline unchanged)
        async def _on_tick(_now: datetime) -> None:
            self.hass.async_create_task(self._async_recompute())

        try:
            for minute in [0, 15, 30, 45]:
                self._unsubs.append(
                    async_track_time_change(
                        self.hass, _on_tick, minute=minute, second=2
                    )
                )
        except Exception:
            pass

        await self._async_recompute()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in getattr(self, "_unsubs", []) or []:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs = []
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return bool(self._attr_extra_state_attributes.get("points_count"))

    @property
    def native_value(self) -> Optional[str]:
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return dict(self._attr_extra_state_attributes)

    def _handle_coordinator_update(self) -> None:
        # Intentionally ignore coordinator updates (local telemetry is noisy).
        return


# =============================================================================
# BATTERY EFFICIENCY SENSOR
# =============================================================================


class OigCloudBatteryEfficiencySensor(RestoreEntity, CoordinatorEntity, SensorEntity):
    """
    Battery round-trip efficiency calculator.

    Calculates battery efficiency using existing monthly sensors:
    - sensor.computed_batt_charge_energy_month
    - sensor.computed_batt_discharge_energy_month
    - sensor.remaining_usable_capacity

    State = Last COMPLETE month efficiency (%)
    Attributes = Current month (partial) efficiency and metrics

    Updates:
    - Daily at 23:55: Update current month partial data
    - Monthly on 1st at 00:10: Calculate last month and save to state

    Formula:
    efficiency = (effective_discharge / charge) * 100
    where: effective_discharge = discharge - (battery_end - battery_start)

    NOTE: RestoreEntity není třeba - všechna data jsou v extra_state_attributes
    které HA automaticky ukládá.
    """

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
    ) -> None:
        """Initialize the battery efficiency sensor."""
        CoordinatorEntity.__init__(self, coordinator)

        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)

        # Stabilní box_id resolution (config entry → proxy → coordinator numeric keys)
        try:
            from .oig_cloud_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        # Set device info early - type: ignore because DeviceInfo is a TypedDict
        self._attr_device_info = device_info  # type: ignore[assignment]

        # Entity setup
        self._attr_unique_id = f"oig_cloud_{self._box_id}_battery_efficiency"
        self.entity_id = f"sensor.oig_{self._box_id}_battery_efficiency"
        self._attr_icon = "mdi:battery-sync"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Načíst název ze sensor types
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")
        self._attr_name = name_cs or name_en or "Efektivita baterie (měsíc)"

        # State tracking
        self._efficiency_last_month: Optional[float] = None  # State = minulý měsíc
        self._battery_kwh_month_start: Optional[float] = None
        self._current_month_partial: Dict[str, Any] = {}
        self._last_month_data: Dict[str, Any] = {}  # Kompletní data minulého měsíce
        self._loading_history: bool = False  # Flag aby se načítání neopakovalo

        # Initialize extra state attributes
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - restore state from attributes."""
        await CoordinatorEntity.async_added_to_hass(self)
        self._hass = self.hass

        # Try to restore from last state (HA automatically stores extra_state_attributes)
        last_state = await self.async_get_last_state()
        if last_state:
            # Restore efficiency minulého měsíce (state)
            try:
                if last_state.state not in ["unknown", "unavailable"]:
                    self._efficiency_last_month = float(last_state.state)
            except (ValueError, TypeError):
                self._efficiency_last_month = None

            # Restore tracking data from attributes
            if last_state.attributes:
                self._battery_kwh_month_start = last_state.attributes.get(
                    "_battery_kwh_month_start"
                )
                self._current_month_partial = last_state.attributes.get(
                    "_current_month_partial", {}
                )
                self._last_month_data = last_state.attributes.get(
                    "_last_month_data", {}
                )
                _LOGGER.info(
                    f"🔋 Restored battery efficiency state: "
                    f"last_month={self._efficiency_last_month}%, "
                    f"month_start={self._battery_kwh_month_start} kWh"
                )

        # Initialize if None
        # Pro první deployment: inicializuj i uprostřed měsíce (data nebudou přesná)
        # Po 1. listopadu to můžeme změnit aby čekalo na začátek měsíce
        now = datetime.now()
        if self._battery_kwh_month_start is None:
            battery_now = self._get_sensor("remaining_usable_capacity") or 0
            self._battery_kwh_month_start = battery_now

            if now.day <= 2:
                _LOGGER.info(
                    f"🔋 Battery efficiency sensor initialized (beginning of month): "
                    f"month_start={battery_now:.2f} kWh"
                )
            else:
                _LOGGER.warning(
                    f"🔋 Battery efficiency sensor initialized mid-month (day {now.day}): "
                    f"month_start={battery_now:.2f} kWh. "
                    f"Current month data will be PARTIAL and may be inaccurate. "
                    f"Full accuracy starts from 1st November."
                )

        # Schedule monthly calculation on 1st day at 00:10
        from homeassistant.helpers.event import async_track_utc_time_change

        # Monthly: 1. den v měsíci v 00:10 UTC
        async_track_utc_time_change(
            self.hass, self._monthly_calculation, hour=0, minute=10, second=0
        )

        # Daily: každý den v 23:55 UTC
        async_track_utc_time_change(
            self.hass, self._daily_update, hour=23, minute=55, second=0
        )

        # Initial update
        await self._daily_update()

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        await CoordinatorEntity.async_will_remove_from_hass(self)

    async def _monthly_calculation(self, now: datetime) -> None:
        """
        1. den měsíce - spočítat efficiency MINULÉHO měsíce.

        Vezme data uložená včera večer v _daily_update a uloží jako state.
        """
        # Kontrola zda je to opravdu 1. den
        if now.day != 1:
            return

        _LOGGER.info("🔋 Monthly calculation: Computing last month efficiency")

        # Použít data z včerejška (uložená v _daily_update)
        charge_last_month = self._current_month_partial.get("charge", 0)
        discharge_last_month = self._current_month_partial.get("discharge", 0)
        battery_month_end = self._current_month_partial.get("battery_end", 0)
        battery_month_start = self._current_month_partial.get("battery_start", 0)

        # Snížený limit z 20 na 5 kWh - umožní výpočet i pro částečná data
        if charge_last_month < 5.0 or discharge_last_month < 5.0:
            _LOGGER.warning(
                f"🔋 Insufficient data for last month: "
                f"charge={charge_last_month:.2f}, discharge={discharge_last_month:.2f}"
            )
            self._efficiency_last_month = None
        else:
            # Výpočet
            delta = battery_month_end - battery_month_start
            effective_discharge = discharge_last_month - delta

            if (
                effective_discharge > 0
                and effective_discharge <= charge_last_month * 1.1
            ):
                efficiency = (effective_discharge / charge_last_month) * 100
                losses_kwh = charge_last_month - effective_discharge
                losses_pct = (losses_kwh / charge_last_month) * 100

                self._efficiency_last_month = round(efficiency, 1)

                # Uložit kompletní data minulého měsíce
                self._last_month_data = {
                    "efficiency_pct": round(efficiency, 1),
                    "losses_kwh": round(losses_kwh, 2),
                    "losses_pct": round(losses_pct, 1),
                    "charge_kwh": round(charge_last_month, 2),
                    "discharge_kwh": round(discharge_last_month, 2),
                    "effective_discharge_kwh": round(effective_discharge, 2),
                    "delta_kwh": round(delta, 2),
                    "battery_start_kwh": round(battery_month_start, 2),
                    "battery_end_kwh": round(battery_month_end, 2),
                }

                _LOGGER.info(
                    f"🔋 Last month: efficiency={self._efficiency_last_month}%, "
                    f"losses={losses_kwh:.2f} kWh ({losses_pct:.1f}%), "
                    f"charge={charge_last_month:.2f}, discharge={discharge_last_month:.2f}, delta={delta:.2f}"
                )
            else:
                _LOGGER.warning(
                    f"🔋 Invalid effective discharge: {effective_discharge:.2f} kWh"
                )
                self._efficiency_last_month = None

        # Reset pro nový měsíc
        battery_now = self._get_sensor("remaining_usable_capacity") or 0
        self._battery_kwh_month_start = battery_now
        self._current_month_partial = {}

        _LOGGER.info(f"🔋 New month started with {battery_now:.2f} kWh")

        # Update state
        self._attr_native_value = self._efficiency_last_month
        self.async_write_ha_state()

    async def _daily_update(self, now: Optional[datetime] = None) -> None:
        """
        Denně v 23:55 - aktualizovat průběžná data TOHOTO měsíce.
        """
        _LOGGER.debug("🔋 Daily update: Computing current month (partial) efficiency")

        # Pokud nemáme month_start, nemůžeme počítat efektivitu
        if self._battery_kwh_month_start is None:
            _LOGGER.warning(
                "🔋 Cannot compute efficiency - battery_kwh_month_start not initialized. "
                "Waiting for next month to start."
            )
            self._attr_native_value = self._efficiency_last_month
            self._update_extra_state_attributes()
            self.async_write_ha_state()
            return

        # Číst aktuální měsíční data
        charge_month_wh = self._get_sensor("computed_batt_charge_energy_month") or 0
        discharge_month_wh = (
            self._get_sensor("computed_batt_discharge_energy_month") or 0
        )
        battery_now = self._get_sensor("remaining_usable_capacity") or 0

        charge_month = charge_month_wh / 1000
        discharge_month = discharge_month_wh / 1000

        # Uložit snapshot pro monthly calculation
        self._current_month_partial = {
            "charge": round(charge_month, 2),
            "discharge": round(discharge_month, 2),
            "battery_start": round(self._battery_kwh_month_start, 2),
            "battery_end": round(battery_now, 2),
            "timestamp": datetime.now().isoformat(),
        }

        # Vypočítat průběžnou efficiency (jen pro atributy)
        if charge_month >= 1.0 and discharge_month >= 1.0:
            delta = battery_now - self._battery_kwh_month_start
            effective_discharge = discharge_month - delta

            if effective_discharge > 0 and effective_discharge <= charge_month * 1.2:
                efficiency_current = (effective_discharge / charge_month) * 100
                self._current_month_partial["efficiency"] = round(efficiency_current, 1)
                self._current_month_partial["delta"] = round(delta, 2)
                self._current_month_partial["effective_discharge"] = round(
                    effective_discharge, 2
                )

        # Update extra state attributes
        self._update_extra_state_attributes()

        # State: Zobraz minulý měsíc pokud máme, jinak aktuální měsíc (partial)
        if self._efficiency_last_month is not None:
            self._attr_native_value = self._efficiency_last_month
        else:
            # Fallback na current month pokud nemáme last month
            self._attr_native_value = self._current_month_partial.get("efficiency")

        self.async_write_ha_state()

    def _update_extra_state_attributes(self) -> None:
        """Update extra state attributes with current data."""
        now = datetime.now()

        # Pokud nemáme kompletní data za minulý měsíc (chybí kWh hodnoty), zkusit načíst z historie
        # Kontrolujeme charge_kwh protože to je klíčová hodnota pro zobrazení v dashboardu
        # A ZÁROVEŇ kontrolujeme flag aby se načítání neopakovalo
        if (
            not self._last_month_data or not self._last_month_data.get("charge_kwh")
        ) and not self._loading_history:
            # Nastavit flag aby se loading neopakoval
            self._loading_history = True
            # Asynchronně spustit načtení (ale nevyčkávat na výsledek)
            self.hass.async_create_task(self._try_load_last_month_from_history())

        # Průběžná data tohoto měsíce
        current_efficiency = self._current_month_partial.get("efficiency")
        current_charge = self._current_month_partial.get("charge")
        current_discharge = self._current_month_partial.get("discharge")
        current_delta = self._current_month_partial.get("delta")
        current_effective_discharge = self._current_month_partial.get(
            "effective_discharge"
        )

        # Výpočet ztrát pro aktuální měsíc
        current_losses_kwh = None
        current_losses_pct = None
        if current_charge and current_effective_discharge:
            current_losses_kwh = round(current_charge - current_effective_discharge, 2)
            current_losses_pct = round((current_losses_kwh / current_charge) * 100, 1)

        # Výpočet ztrát pro minulý měsíc (z uložených dat nebo z efficiency)
        last_month_losses_kwh = self._last_month_data.get("losses_kwh")
        last_month_losses_pct = self._last_month_data.get("losses_pct")
        if last_month_losses_pct is None and self._efficiency_last_month is not None:
            # Fallback pokud nemáme uložená data (starší verze)
            last_month_losses_pct = round(100 - self._efficiency_last_month, 1)

        # Status podle stavu inicializace
        if self._battery_kwh_month_start is None:
            current_month_status = (
                f"not initialized (day {now.day}) - waiting for next month"
            )
        else:
            current_month_status = f"partial ({now.day} days)"

        self._attr_extra_state_attributes = {
            # Minulý měsíc (kompletní) - to je STATE
            "efficiency_last_month_pct": self._efficiency_last_month,
            "losses_last_month_kwh": last_month_losses_kwh,
            "losses_last_month_pct": last_month_losses_pct,
            "last_month_charge_kwh": self._last_month_data.get("charge_kwh"),
            "last_month_discharge_kwh": self._last_month_data.get("discharge_kwh"),
            "last_month_status": "complete",
            # Tento měsíc (průběžné)
            "efficiency_current_month_pct": current_efficiency,
            "losses_current_month_kwh": current_losses_kwh,
            "losses_current_month_pct": current_losses_pct,
            "current_month_charge_kwh": current_charge,
            "current_month_discharge_kwh": current_discharge,
            "current_month_delta_kwh": current_delta,
            "current_month_days": now.day,
            "current_month_status": current_month_status,
            # Battery tracking
            "battery_kwh_month_start": (
                round(self._battery_kwh_month_start, 2)
                if self._battery_kwh_month_start
                else None
            ),
            "battery_kwh_now": round(
                self._get_sensor("remaining_usable_capacity") or 0, 2
            ),
            # Metadata
            "last_daily_update": self._current_month_partial.get("timestamp"),
            "next_monthly_calculation": "1st day of next month at 00:10",
            "calculation_method": "Energy balance with SoC correction",
            "data_source": "computed_batt_charge/discharge_energy_month",
            "formula": "(discharge - ΔE_battery) / charge * 100",
            "formula_losses": "charge - (discharge - ΔE_battery)",
            # Internal (for restore)
            "_battery_kwh_month_start": self._battery_kwh_month_start,
            "_current_month_partial": self._current_month_partial,
            "_last_month_data": self._last_month_data,
        }

    async def _try_load_last_month_from_history(self) -> None:  # noqa: C901
        """
        Pokus o načtení dat za minulý měsíc z historie HA.
        Použije monthly sensors k vypočtení efficiency za minulý měsíc.
        """
        try:
            from homeassistant.components.recorder.history import get_significant_states
        except ImportError:
            _LOGGER.warning("🔋 Recorder component not available")
            return

        _LOGGER.info("🔋 Attempting to load last month efficiency from history...")

        try:
            # Zjistit datum minulého měsíce
            now = datetime.now()
            if now.month == 1:
                last_month_year = now.year - 1
                last_month = 12
            else:
                last_month_year = now.year
                last_month = now.month - 1

            # Poslední den minulého měsíce v 23:59
            import calendar
            from datetime import timezone

            last_day = calendar.monthrange(last_month_year, last_month)[1]
            end_time = datetime(
                last_month_year, last_month, last_day, 23, 59, 59, tzinfo=timezone.utc
            )

            # První den minulého měsíce v 00:00
            start_time = datetime(
                last_month_year, last_month, 1, 0, 0, 0, tzinfo=timezone.utc
            )

            _LOGGER.debug(f"🔋 Looking for history between {start_time} and {end_time}")

            # Načíst historii pro monthly sensors
            charge_sensor = (
                f"sensor.oig_{self._box_id}_computed_batt_charge_energy_month"
            )
            discharge_sensor = (
                f"sensor.oig_{self._box_id}_computed_batt_discharge_energy_month"
            )
            battery_sensor = f"sensor.oig_{self._box_id}_remaining_usable_capacity"

            # Získat stavy na konci měsíce
            from homeassistant.components.recorder import get_instance

            history = await get_instance(self.hass).async_add_executor_job(
                get_significant_states,
                self.hass,
                end_time - timedelta(hours=1),
                end_time,
                [charge_sensor, discharge_sensor, battery_sensor],
            )

            _LOGGER.debug(
                f"🔋 History result type: {type(history)}, keys: {history.keys() if history else 'None'}"
            )
            if history:
                for key, values in history.items():
                    _LOGGER.debug(f"🔋 History[{key}]: {len(values)} entries")

            if not history:
                _LOGGER.warning(
                    f"🔋 No history found for {last_month}/{last_month_year}"
                )
                return

            # Parse hodnoty
            charge_wh = None
            discharge_wh = None
            battery_end = None

            if charge_sensor in history and history[charge_sensor]:
                for item in reversed(history[charge_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            charge_wh = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            if discharge_sensor in history and history[discharge_sensor]:
                for item in reversed(history[discharge_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            discharge_wh = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            if battery_sensor in history and history[battery_sensor]:
                for item in reversed(history[battery_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            battery_end = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            # Načíst stav baterie na začátku měsíce
            history_start = await get_instance(self.hass).async_add_executor_job(
                get_significant_states,
                self.hass,
                start_time,
                start_time + timedelta(hours=1),
                [battery_sensor],
            )

            battery_start = None
            if battery_sensor in history_start and history_start[battery_sensor]:
                for item in history_start[battery_sensor]:
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            battery_start = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            # Vypočítat efficiency
            if (
                charge_wh
                and discharge_wh
                and battery_start is not None
                and battery_end is not None
            ):
                charge_kwh = charge_wh / 1000
                discharge_kwh = discharge_wh / 1000
                delta_kwh = battery_end - battery_start
                effective_discharge = discharge_kwh - delta_kwh

                if effective_discharge > 0 and charge_kwh > 0:
                    efficiency = (effective_discharge / charge_kwh) * 100
                    losses_kwh = charge_kwh - effective_discharge
                    losses_pct = (losses_kwh / charge_kwh) * 100

                    self._efficiency_last_month = round(efficiency, 1)
                    self._last_month_data = {
                        "efficiency_pct": round(efficiency, 1),
                        "losses_kwh": round(losses_kwh, 2),
                        "losses_pct": round(losses_pct, 1),
                        "charge_kwh": round(charge_kwh, 2),
                        "discharge_kwh": round(discharge_kwh, 2),
                        "effective_discharge_kwh": round(effective_discharge, 2),
                        "delta_kwh": round(delta_kwh, 2),
                        "battery_start_kwh": round(battery_start, 2),
                        "battery_end_kwh": round(battery_end, 2),
                    }

                    _LOGGER.info(
                        f"🔋 Loaded {last_month}/{last_month_year} from history: "
                        f"efficiency={efficiency:.1f}%, charge={charge_kwh:.2f} kWh, "
                        f"discharge={discharge_kwh:.2f} kWh, delta={delta_kwh:.2f} kWh"
                    )

                    # Uložit state do HA aby přežil restart
                    self._update_extra_state_attributes()
                    self.async_write_ha_state()
                    _LOGGER.info("🔋 Last month data saved to state storage")
                else:
                    _LOGGER.warning(
                        f"🔋 Invalid data for {last_month}/{last_month_year}: "
                        f"effective_discharge={effective_discharge:.2f}, charge={charge_kwh:.2f}"
                    )
            else:
                _LOGGER.warning(
                    f"🔋 Incomplete data for {last_month}/{last_month_year}: "
                    f"charge={charge_wh}, discharge={discharge_wh}, "
                    f"battery_start={battery_start}, battery_end={battery_end}"
                )

        except Exception as e:
            _LOGGER.error(f"🔋 Error loading history: {e}", exc_info=True)
        finally:
            # Vždy resetovat flag aby se mohl zkusit loading znovu při dalším update
            self._loading_history = False

    def _get_sensor(self, sensor_type: str) -> Optional[float]:
        """Získat hodnotu z existujícího sensoru."""
        if not self._hass:
            return None

        sensor_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        state = self._hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None


# ============================================================================
