from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_AC_OUT: Final[Dict[str, OigSensorTypeDescription]] = {
    "ac_out_aco_p": {
        "name": "Load Total",
        "name_cs": "Zátěž celkem",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_p",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_out_aco_pr": {
        "name": "Load Line 1",
        "name_cs": "Zátěž fáze 1",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pr",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_out_aco_ps": {
        "name": "Load Line 2",
        "name_cs": "Zátěž fáze 2",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_ps",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_out_aco_pt": {
        "name": "Load Line 3",
        "name_cs": "Zátěž fáze 3",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pt",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_out_en_day": {
        "name": "Consumption Today",
        "name_cs": "Dnešní spotřeba",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": "ac_out",
        "node_key": "en_day",
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
    },
}
