from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from typing import Dict
from homeassistant.helpers.entity import EntityCategory

SENSOR_TYPES_EXTENDED_GRID: Dict[
    str, Dict[str, str | SensorDeviceClass | SensorStateClass]
] = {
    "extended_grid_voltage": {
        "name": "Extended Grid Voltage",
        "name_cs": "Rozšířené napětí sítě",
        "unit_of_measurement": "V",
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_grid_power": {
        "name": "Extended Grid Power",
        "name_cs": "Rozšířený výkon sítě",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_grid_consumption": {
        "name": "Extended Grid Consumption",
        "name_cs": "Rozšířená spotřeba ze sítě",
        "unit_of_measurement": "Wh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "node_id": None,
        "node_key": None,
    },
    "extended_grid_delivery": {
        "name": "Extended Grid Delivery",
        "name_cs": "Rozšířená dodávka do sítě",
        "unit_of_measurement": "Wh",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
}
