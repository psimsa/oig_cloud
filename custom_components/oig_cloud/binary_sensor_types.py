from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

BINARY_SENSOR_TYPES: Dict[str, Dict[str, Any]] = {
    "chmu_warning_active": {
        "name": "ČHMÚ Warning Active",
        "name_cs": "Aktivní varování ČHMÚ",
        "icon": "mdi:alert",
        "device_class": BinarySensorDeviceClass.SAFETY,
        "sensor_type_category": "chmu_warnings",
        "device_mapping": "analytics",
        "description": "Indikátor aktivního meteorologického varování (ON pokud severity >= 2 / Moderate)",
        "enabled_by_default": False,
    },
}
