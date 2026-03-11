"""Definice typů senzorů pro ČHMÚ meteorologická varování."""

from typing import Any, Dict

from homeassistant.components.sensor import SensorStateClass

# Typy senzorů pro ČHMÚ varování
SENSOR_TYPES_CHMU: Dict[str, Dict[str, Any]] = {
    "chmu_warning_level": {
        "name": "ČHMÚ Warning Level (Local)",
        "name_cs": "Úroveň varování ČHMÚ (lokální)",
        "icon": "mdi:alert-octagon",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "chmu_warnings",
        "sensor_type_category": "chmu_warnings",
        "device_mapping": "analytics",
        "description": "Úroveň meteorologického varování pro vaši lokalitu (0=žádné, 1=Minor/žluté, 2=Moderate/oranžové, 3=Severe/červené, 4=Extreme/fialové)",
        "enabled_by_default": False,
    },
    "chmu_warning_level_global": {
        "name": "ČHMÚ Warning Level (Czech Republic)",
        "name_cs": "Úroveň varování ČHMÚ (celá ČR)",
        "icon": "mdi:alert-octagon-outline",
        "unit_of_measurement": None,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "category": "chmu_warnings",
        "sensor_type_category": "chmu_warnings",
        "device_mapping": "analytics",
        "description": "Nejvyšší úroveň meteorologického varování v celé České republice (0=žádné, 1=Minor/žluté, 2=Moderate/oranžové, 3=Severe/červené, 4=Extreme/fialové)",
        "enabled_by_default": False,
    },
}
