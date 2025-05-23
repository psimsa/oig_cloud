from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_EXTENDED_FVE: Final[Dict[str, OigSensorTypeDescription]] = {
    "extended_fve_voltage_1": {
        "name": "Extended FVE Voltage 1",
        "name_cs": "Napětí FV1",
        "unit_of_measurement": "V",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Extended sensors derive values differently
        "node_key": None,
    },
    "extended_fve_voltage_2": {
        "name": "Extended FVE Voltage 2",
        "name_cs": "Napětí FV2",
        "unit_of_measurement": "V",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_current": {
        "name": "Extended FVE Current",
        "name_cs": "Proud FV",
        "unit_of_measurement": "A",
        "device_class": "current", # Was SensorDeviceClass.CURRENT
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_power_1": {
        "name": "Extended FVE Power 1",
        "name_cs": "Rozšířený výkon FV1",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_power_2": {
        "name": "Extended FVE Power 2",
        "name_cs": "Rozšířený výkon FV2",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
}
