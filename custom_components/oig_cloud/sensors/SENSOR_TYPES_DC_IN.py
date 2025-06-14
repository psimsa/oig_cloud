from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory


from typing import Dict


SENSOR_TYPES_DC_IN: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {
    "dc_in_fv_ad": {
        "name": "PV Output Today",
        "name_cs": "Dnešní výroba",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "dc_in",
        "node_key": "fv_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "dc_in_fv_p1": {
        "name": "Panels Output String 1",
        "name_cs": "Výkon panelů string 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p1",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_p2": {
        "name": "Panels Output String 2",
        "name_cs": "Výkon panelů string 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p2",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_proc": {
        "name": "Panels Output Percent",
        "name_cs": "Výkon panelů (procenta)",
        "device_class": SensorDeviceClass.POWER_FACTOR,
        "unit_of_measurement": "%",
        "node_id": "dc_in",
        "node_key": "fv_proc",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_total": {
        "name": "Panels Output Total",
        "name_cs": "Výkon panelů celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}
