from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_DC_IN: Final[Dict[str, OigSensorTypeDescription]] = {
    "dc_in_fv_ad": {
        "name": "PV Output Today",
        "name_cs": "Dnešní výroba",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": "dc_in",
        "node_key": "fv_ad",
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
    },
    "dc_in_fv_p1": {
        "name": "Panels Output String 1",
        "name_cs": "Výkon panelů string 1",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p1",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "dc_in_fv_p2": {
        "name": "Panels Output String 2",
        "name_cs": "Výkon panelů string 2",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p2",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "dc_in_fv_proc": {
        "name": "Panels Output Percent",
        "name_cs": "Výkon panelů (procenta)",
        "device_class": "power_factor", # Was SensorDeviceClass.POWER_FACTOR
        "unit_of_measurement": "%",
        "node_id": "dc_in",
        "node_key": "fv_proc",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "dc_in_fv_total": {
        "name": "Panels Output Total",
        "name_cs": "Výkon panelů celkem",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
}
