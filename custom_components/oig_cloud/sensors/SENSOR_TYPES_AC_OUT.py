from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from typing import Dict


SENSOR_TYPES_AC_OUT: Dict[
    str, Dict[str, str | SensorDeviceClass | SensorStateClass]
] = {
    "ac_out_aco_p": {
        "name": "Load Total",
        "name_cs": "Zátěž celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pr": {
        "name": "Load Line 1",
        "name_cs": "Zátěž fáze 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_ps": {
        "name": "Load Line 2",
        "name_cs": "Zátěž fáze 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_ps",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pt": {
        "name": "Load Line 3",
        "name_cs": "Zátěž fáze 3",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_en_day": {
        "name": "Consumption Today",
        "name_cs": "Dnešní spotřeba",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_out",
        "node_key": "en_day",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
}
