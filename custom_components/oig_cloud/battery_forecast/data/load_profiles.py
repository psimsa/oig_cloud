"""Load profile helpers for battery forecast."""

from __future__ import annotations

import logging
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def get_load_avg_sensors(sensor: Any) -> Dict[str, Any]:
    """Collect load_avg sensors mapped with time ranges and day types."""
    if not sensor._hass:
        _LOGGER.warning("get_load_avg_sensors: hass not available")
        return {}

    from ...sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

    load_sensors: Dict[str, Any] = {}

    for sensor_type, config in SENSOR_TYPES_STATISTICS.items():
        if not sensor_type.startswith("load_avg_"):
            continue
        if "time_range" not in config or "day_type" not in config:
            continue

        entity_id = f"sensor.oig_{sensor._box_id}_{sensor_type}"
        state = sensor._hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Sensor %s not found in HA", entity_id)
            continue

        if state.state in ["unknown", "unavailable"]:
            _LOGGER.debug("Sensor %s is %s", entity_id, state.state)
            continue

        try:
            value = float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Failed to parse %s value '%s': %s", entity_id, state.state, err
            )
            continue

        load_sensors[entity_id] = {
            "value": value,
            "time_range": config["time_range"],
            "day_type": config["day_type"],
        }

    _LOGGER.info("Found %s valid load_avg sensors", len(load_sensors))
    if load_sensors:
        first_id = next(iter(load_sensors))
        first = load_sensors[first_id]
        _LOGGER.info(
            "Example: %s, value=%sW, range=%s, day=%s",
            first_id,
            first["value"],
            first["time_range"],
            first["day_type"],
        )

    return load_sensors
