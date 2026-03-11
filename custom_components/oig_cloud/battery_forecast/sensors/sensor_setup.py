"""Initialization helpers for the battery forecast sensor."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def initialize_sensor(
    sensor: Any,
    coordinator: Any,
    sensor_type: str,
    config_entry: ConfigEntry,
    device_info: Dict[str, Any],
    hass: Optional[HomeAssistant],
    *,
    side_effects_enabled: bool,
    auto_switch_startup_delay: timedelta,
) -> None:
    """Populate sensor state and caches."""
    sensor._sensor_type = sensor_type
    sensor._config_entry = config_entry
    sensor._device_info = device_info

    # Prefer injected hass, fallback to coordinator.hass
    sensor._hass = hass or getattr(coordinator, "hass", None)
    sensor._side_effects_enabled = bool(side_effects_enabled)

    # Resolve box id for stable entity identifiers.
    try:
        from ...entities.base_sensor import resolve_box_id

        sensor._box_id = resolve_box_id(coordinator)
    except Exception:
        sensor._box_id = "unknown"

    if sensor._box_id == "unknown":
        _LOGGER.warning(
            "Battery forecast sensor: unable to resolve box_id, using 'unknown' (sensor will be unstable)"
        )

    # Entity attributes aligned with statistics sensors.
    sensor._attr_unique_id = f"oig_cloud_{sensor._box_id}_{sensor_type}"
    sensor.entity_id = f"sensor.oig_{sensor._box_id}_{sensor_type}"
    sensor._attr_icon = "mdi:battery-charging-60"
    sensor._attr_native_unit_of_measurement = "kWh"
    sensor._attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    sensor._attr_state_class = SensorStateClass.MEASUREMENT
    sensor._attr_entity_category = None

    from ...sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

    sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
    name_cs = sensor_config.get("name_cs")
    name_en = sensor_config.get("name")
    sensor._attr_name = name_cs or name_en or sensor_type

    # Timeline data cache and throttling state.
    sensor._last_forecast_bucket: Optional[datetime] = None
    sensor._forecast_in_progress = False
    sensor._profiles_dirty = False
    sensor._plan_lock_until: Optional[datetime] = None
    sensor._plan_lock_modes: Dict[str, int] = {}
    sensor._timeline_data: List[Dict[str, Any]] = []
    sensor._baseline_timeline: List[Dict[str, Any]] = []
    sensor._last_update: Optional[datetime] = None
    sensor._charging_metrics: Dict[str, Any] = {}
    sensor._adaptive_consumption_data: Dict[str, Any] = {}
    sensor._consumption_summary: Dict[str, Any] = {}
    sensor._first_update = True
    sensor._auto_switch_handles: List[Any] = []
    sensor._last_auto_switch_request: Optional[Tuple[str, datetime]] = None
    sensor._auto_switch_ready_at = dt_util.now() + auto_switch_startup_delay
    sensor._auto_switch_retry_unsub: Optional[Callable[[], None]] = None
    sensor._auto_switch_watchdog_unsub: Optional[Callable[[], None]] = None
    sensor._auto_switch_watchdog_interval = timedelta(seconds=30)
    sensor._forecast_retry_unsub: Optional[Callable[[], None]] = None

    # Log throttling to prevent HA "logging too frequently" warnings.
    sensor._log_last_ts = sensor._GLOBAL_LOG_LAST_TS

    # Planner result snapshot (legacy attribute schema name: mode_optimization).
    sensor._mode_optimization_result: Optional[Dict[str, Any]] = None

    # Mode recommendations (today + tomorrow).
    sensor._mode_recommendations: List[Dict[str, Any]] = []

    # Daily plans archive (yesterday, earlier).
    sensor._daily_plans_archive: Dict[str, Dict[str, Any]] = {}

    # Current daily plan state (restored from storage).
    sensor._daily_plan_state: Optional[Dict[str, Any]] = None
    sensor._baseline_repair_attempts: set[str] = set()

    # Hash-based change detection.
    sensor._data_hash: Optional[str] = None

    # Unified charging planner.
    sensor._active_charging_plan: Optional[Dict[str, Any]] = None
    sensor._plan_status = "none"
    sensor._balancing_plan_snapshot: Optional[Dict[str, Any]] = None

    # Hourly history update tracking.
    sensor._last_history_update_hour: Optional[int] = None
    sensor._initial_history_update_done = False

    # Storage helper for persistent battery plans.
    sensor._plans_store: Optional[Store] = None
    if sensor._hass:
        sensor._plans_store = Store(
            sensor._hass,
            version=1,
            key=f"oig_cloud.battery_plans_{sensor._box_id}",
        )
        _LOGGER.debug(
            "Initialized storage helper: oig_cloud.battery_plans_%s", sensor._box_id
        )
    else:
        _LOGGER.warning(
            "Cannot initialize storage helper - hass not available yet. "
            "Will retry in async_added_to_hass()."
        )

    # Storage helper for precomputed UI data.
    sensor._precomputed_store: Optional[Store] = None
    sensor._precompute_interval = timedelta(minutes=15)
    sensor._last_precompute_at: Optional[datetime] = None
    sensor._last_precompute_hash: Optional[str] = None
    sensor._precompute_task = None
    if sensor._hass:
        sensor._precomputed_store = Store(
            sensor._hass,
            version=1,
            key=f"oig_cloud.precomputed_data_{sensor._box_id}",
        )
        _LOGGER.debug(
            "Initialized precomputed storage: oig_cloud.precomputed_data_%s",
            sensor._box_id,
        )
    else:
        _LOGGER.debug(
            "Precomputed storage will be initialized in async_added_to_hass()"
        )
