from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_AC_IN: Final[Dict[str, OigSensorTypeDescription]] = {
    "ac_in_ac_ad": {
        "name": "Grid Consumption Today",
        "name_cs": "Dnešní odběr ze sítě",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_ad",
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
    },
    "ac_in_ac_pd": {
        "name": "Grid Delivery Today",
        "name_cs": "Dnešní dodávka do sítě",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_pd",
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
    },
    "ac_in_aci_f": {
        "name": "Frequency",
        "name_cs": "Frekvence sítě",
        "device_class": "frequency", # Was SensorDeviceClass.FREQUENCY
        "unit_of_measurement": "Hz",
        "node_id": "ac_in",
        "node_key": "aci_f",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_vr": {
        "name": "Grid Voltage Line 1",
        "name_cs": "Síť - Napětí fáze 1",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vr",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_vs": {
        "name": "Grid Voltage Line 2",
        "name_cs": "Síť - Napětí fáze 2",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vs",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_vt": {
        "name": "Grid Voltage Line 3",
        "name_cs": "Síť - Napětí fáze 3",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vt",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_wr": {
        "name": "Grid Load Line 1",
        "name_cs": "Síť - zátěž fáze 1",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wr",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_ws": {
        "name": "Grid Load Line 2",
        "name_cs": "Síť - zátěž fáze 2",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_ws",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_wt": {
        "name": "Grid Load Line 3",
        "name_cs": "Síť - zátěž fáze 3",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wt",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "ac_in_aci_wtotal": {
        "name": "Grid Load Total",
        "name_cs": "Síť - Zátěž celkem",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
}
