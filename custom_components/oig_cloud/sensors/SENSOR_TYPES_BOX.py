from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_BOX: Final[Dict[str, OigSensorTypeDescription]] = {
    "box_humid": {
        "name": "Humidity",
        "name_cs": "Vlhkost v boxu",
        "device_class": "humidity", # Was SensorDeviceClass.HUMIDITY
        "unit_of_measurement": "%",
        "node_id": "box",
        "node_key": "humid",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "box_prms_mode": {
        "name": "Operation Mode",
        "name_cs": "Režim",
        "device_class": None, # Explicitly None if no device class applies
        "unit_of_measurement": None, # Explicitly None if no unit
        "node_id": "box_prms",
        "node_key": "mode",
        "state_class": None, # Explicitly None if no state class applies
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "box_temp": {
        "name": "Temperature",
        "name_cs": "Teplota v boxu",
        "device_class": "temperature", # Was SensorDeviceClass.TEMPERATURE
        "unit_of_measurement": "°C",
        "node_id": "box",
        "node_key": "temp",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
}
