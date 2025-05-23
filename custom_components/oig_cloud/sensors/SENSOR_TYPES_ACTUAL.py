from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_ACTUAL: Final[Dict[str, OigSensorTypeDescription]] = {
    "actual_aci_wr": {
        "name": "Grid Load Line 1 (live)",
        "name_cs": "Síť - zátěž fáze 1 (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_wr",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_aci_ws": {
        "name": "Grid Load Line 2 (live)",
        "name_cs": "Síť - zátěž fáze 2 (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_ws",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_aci_wt": {
        "name": "Grid Load Line 3 (live)",
        "name_cs": "Síť - zátěž fáze 3 (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_wt",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_aci_wtotal": {
        "name": "Grid Load Total (live)",
        "name_cs": "Síť - Zátěž celkem (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # This indicates it's a computed sensor in some setups
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_aco_p": {
        "name": "Load Total (live)",
        "name_cs": "Zátěž celkem (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aco_p",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_fv_p1": {
        "name": "Panels Output String 1 (live)",
        "name_cs": "Výkon panelů string 1 (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "fv_p1",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_fv_p2": {
        "name": "Panels Output String 2 (live)",
        "name_cs": "Výkon panelů string 2 (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "fv_p2",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "actual_fv_total": {
        "name": "Panels Output Total (live)",
        "name_cs": "Výkon panelů celkem (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
}
