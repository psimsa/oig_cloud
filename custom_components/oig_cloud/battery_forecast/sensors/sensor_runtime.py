"""Runtime helpers for battery forecast sensor."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Union

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..planning import auto_switch as auto_switch_module


def log_rate_limited(
    sensor,
    logger,
    key: str,
    level: str,
    message: str,
    *args: Any,
    cooldown_s: float = 300.0,
) -> None:
    """Log at most once per cooldown_s for a given key."""
    now_ts = time.time()
    log_cache = getattr(sensor, "_log_last_ts", None)
    if log_cache is None:
        log_cache = {}
        setattr(sensor, "_log_last_ts", log_cache)
    last = log_cache.get(key, 0.0)
    if now_ts - last < cooldown_s:
        return
    log_cache[key] = now_ts
    log_fn = getattr(logger, level, None)
    if callable(log_fn):
        log_fn(message, *args)


def get_config(sensor) -> Dict[str, Any]:
    """Return config dict from config entry (options preferred, then data)."""
    if not getattr(sensor, "_config_entry", None):
        return {}
    options = getattr(sensor._config_entry, "options", None)
    if options:
        return options
    return sensor._config_entry.data or {}


def handle_coordinator_update(sensor) -> None:
    """Delegate coordinator update handling."""
    CoordinatorEntity._handle_coordinator_update(sensor)


def get_state(sensor) -> Optional[Union[float, str]]:
    """Return battery capacity value for sensor state."""
    timeline = getattr(sensor, "_timeline_data", None)
    if timeline:
        capacity = timeline[0].get("battery_soc")
        if capacity is None:
            capacity = timeline[0].get("battery_capacity_kwh", 0)
        return round(capacity, 2)
    return 0


def is_available(sensor) -> bool:
    """Return if the sensor is available."""
    timeline = getattr(sensor, "_timeline_data", None)
    if timeline:
        return True
    available_prop = getattr(CoordinatorEntity, "available", None)
    if available_prop and getattr(available_prop, "fget", None):
        return available_prop.fget(sensor)
    return True


def handle_will_remove(sensor) -> None:
    """Cleanup auto switch resources before removal."""
    auto_switch_module.cancel_auto_switch_schedule(sensor)
    auto_switch_module.stop_auto_switch_watchdog(sensor)
