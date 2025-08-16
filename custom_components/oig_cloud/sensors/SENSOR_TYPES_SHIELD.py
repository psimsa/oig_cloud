"""Definice typů senzorů pro ServiceShield."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from typing import Dict, Any

# Typy senzorů pro ServiceShield monitoring
SENSOR_TYPES_SHIELD: Dict[str, Dict[str, Any]] = {
    "service_shield_status": {
        "name": "ServiceShield Status",
        "name_cs": "Stav ServiceShield",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:shield-check",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "shield",
    },
    "service_shield_queue": {
        "name": "ServiceShield Queue",
        "name_cs": "Fronta ServiceShield",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:format-list-numbered",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "shield",
    },
    "service_shield_activity": {
        "name": "ServiceShield Activity",
        "name_cs": "Aktivita ServiceShield",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": None,
        "icon": "mdi:cog",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "shield",
    },
}
