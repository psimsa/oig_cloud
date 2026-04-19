from typing import Any

from ..oig_cloud_sensor import OigCloudSensor

__all__ = ["OigCloudSensor", "resolve_box_id", "_get_sensor_definition"]

SHIELD_SENSOR_TYPES: dict[str, dict[str, Any]] = {
    "service_shield_status": {
        "name": "Service Shield Status",
        "name_cs": "Stav Service Shield",
        "icon": "mdi:shield",
        "device_class": None,
        "state_class": None,
        "unit_of_measurement": None,
    },
    "service_shield_queue": {
        "name": "Service Shield Queue",
        "name_cs": "Fronta Service Shield",
        "icon": "mdi:format-list-numbered",
        "device_class": None,
        "state_class": None,
        "unit_of_measurement": None,
    },
    "mode_reaction_time": {
        "name": "Mode Reaction Time",
        "name_cs": "Reakční čas režimu",
        "icon": "mdi:timer",
        "device_class": None,
        "state_class": "measurement",
        "unit_of_measurement": "s",
    },
    "service_shield_activity": {
        "name": "Service Shield Activity",
        "name_cs": "Aktivita Service Shield",
        "icon": "mdi:shield-clock",
        "device_class": None,
        "state_class": None,
        "unit_of_measurement": None,
    },
}


def _get_sensor_definition(sensor_type: str) -> dict[str, Any]:
    """Get sensor definition for shield sensor types."""
    return SHIELD_SENSOR_TYPES.get(sensor_type, {})


def _as_numeric_string(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return str(int(value))
    if isinstance(value, str) and value.isdigit():
        return value
    return None


def resolve_box_id(coordinator: Any) -> str:
    forced = _as_numeric_string(getattr(coordinator, "forced_box_id", None))
    if forced:
        return forced

    entry = getattr(coordinator, "config_entry", None)
    if entry:
        for key in ("box_id", "inverter_sn"):
            for source in (getattr(entry, "options", None), getattr(entry, "data", None)):
                if isinstance(source, dict):
                    resolved = _as_numeric_string(source.get(key))
                    if resolved:
                        return resolved

    data = getattr(coordinator, "data", None)
    if isinstance(data, dict):
        for key in data:
            resolved = _as_numeric_string(key)
            if resolved:
                return resolved

    return "unknown"
