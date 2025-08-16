from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfEnergy, UnitOfPower, PERCENTAGE
from typing import Dict, Any

SENSOR_TYPES_DC_IN: Dict[str, Dict[str, Any]] = {
    "dc_in_fv_ad": {
        "name": "PV Output Today",
        "name_cs": "Dnešní výroba",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "node_id": "dc_in",
        "node_key": "fv_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "sensor_type_category": "data",
    },
    "dc_in_fv_p1": {
        "name": "Panels Output String 1",
        "name_cs": "Výkon panelů string 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": UnitOfPower.WATT,
        "node_id": "dc_in",
        "node_key": "fv_p1",
        "state_class": SensorStateClass.MEASUREMENT,
        "sensor_type_category": "data",
    },
    "dc_in_fv_p2": {
        "name": "Panels Output String 2",
        "name_cs": "Výkon panelů string 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": UnitOfPower.WATT,
        "node_id": "dc_in",
        "node_key": "fv_p2",
        "state_class": SensorStateClass.MEASUREMENT,
        "sensor_type_category": "data",
    },
    "dc_in_fv_proc": {
        "name": "Panels Output Percent",
        "name_cs": "Výkon panelů (procenta)",
        "device_class": SensorDeviceClass.POWER_FACTOR,
        "unit_of_measurement": PERCENTAGE,
        "node_id": "dc_in",
        "node_key": "fv_proc",
        "state_class": SensorStateClass.MEASUREMENT,
        "sensor_type_category": "data",
    },
    "dc_in_fv_total": {
        "name": "Panels Output Total",
        "name_cs": "Výkon panelů celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": UnitOfPower.WATT,
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "sensor_type_category": "computed",
    },
}
