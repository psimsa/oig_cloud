from typing import Dict
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

SENSOR_TYPES_EXTENDED_BATT: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {
   "extended_battery_voltage": {
        "name": "Extended Battery Voltage",
        "name_cs": "Rozšířené napětí baterie",
        "unit_of_measurement": "V",
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_battery_current": {
        "name": "Extended Battery Current",
        "name_cs": "Rozšířený proud baterie",
        "unit_of_measurement": "A",
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_battery_capacity": {
        "name": "Extended Battery Capacity",
        "name_cs": "Rozšířená kapacita baterie",
        "unit_of_measurement": "%",
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_battery_temperature": {
        "name": "Extended Battery Temperature",
        "name_cs": "Rozšířená teplota baterie",
        "unit_of_measurement": "°C",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
}