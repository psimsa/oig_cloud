from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_EXTENDED_LOAD: Final[Dict[str, OigSensorTypeDescription]] = {
    "extended_load_l1_power": {
        "name": "Extended Load L1 Power",
        "name_cs": "Rozšířený odběr fáze L1",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Extended sensors derive values differently
        "node_key": None,
    },
    "extended_load_l2_power": {
        "name": "Extended Load L2 Power",
        "name_cs": "Rozšířený odběr fáze L2",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_load_l3_power": {
        "name": "Extended Load L3 Power",
        "name_cs": "Rozšířený odběr fáze L3",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
}
