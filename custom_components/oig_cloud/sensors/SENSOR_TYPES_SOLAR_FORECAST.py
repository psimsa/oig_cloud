"""Definice typů senzorů pro solar forecast."""

from typing import Dict, Any
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy

SENSOR_TYPES_SOLAR_FORECAST: Dict[str, Dict[str, Any]] = {
    "solar_forecast": {
        "name": "Solar Forecast Total",
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:solar-power",
        "entity_category": None,
        "suggested_display_precision": 2,
        "sensor_type_category": "solar_forecast",
    },
    "solar_forecast_string1": {
        "name": "Solar Forecast String 1",
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:solar-panel",
        "entity_category": None,
        "suggested_display_precision": 2,
        "sensor_type_category": "solar_forecast",
    },
    "solar_forecast_string2": {
        "name": "Solar Forecast String 2",
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL,
        "icon": "mdi:solar-panel",
        "entity_category": None,
        "suggested_display_precision": 2,
        "sensor_type_category": "solar_forecast",
    },
}
