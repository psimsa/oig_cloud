from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from typing import Dict
from homeassistant.helpers.entity import EntityCategory

SENSOR_TYPES_EXTENDED_LOAD: Dict[
    str, Dict[str, str | SensorDeviceClass | SensorStateClass]
] = {
    "extended_load_l1_power": {
        "name": "Extended Load L1 Power",
        "name_cs": "Rozšířený odběr fáze L1",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_load_l2_power": {
        "name": "Extended Load L2 Power",
        "name_cs": "Rozšířený odběr fáze L2",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_load_l3_power": {
        "name": "Extended Load L3 Power",
        "name_cs": "Rozšířený odběr fáze L3",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
}
