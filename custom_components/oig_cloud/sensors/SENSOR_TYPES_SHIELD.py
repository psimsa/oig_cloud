"""Definice typů senzorů pro ServiceShield."""

from typing import Any, Dict

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

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
        "device_mapping": "shield",
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
        "device_mapping": "shield",
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
        "device_mapping": "shield",
    },
    "mode_reaction_time": {
        "name": "Box Mode Reaction Time",
        "name_cs": "Doba reakce změny režimu",
        "unit_of_measurement": "s",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:timer-outline",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "shield",
        "device_mapping": "shield",
        "description": "Průměrná doba reakce střídače na změnu režimu",
        "description_cs": "Měří jak dlouho trvá změna režimu (např. Home 1 → Home UPS). Používá se pro dynamické offsety při plánovaném nabíjení.",
    },
}
