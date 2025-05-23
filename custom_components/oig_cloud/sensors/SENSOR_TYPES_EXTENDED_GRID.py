from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_EXTENDED_GRID: Final[Dict[str, OigSensorTypeDescription]] = {
    "extended_grid_voltage": {
        "name": "Extended Grid Voltage",
        "name_cs": "Rozšířené napětí sítě",
        "unit_of_measurement": "V",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Extended sensors derive values differently
        "node_key": None,
    },
    "extended_grid_power": {
        "name": "Extended Grid Power",
        "name_cs": "Rozšířený výkon sítě",
        "unit_of_measurement": "W",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_grid_consumption": {
        "name": "Extended Grid Consumption",
        "name_cs": "Rozšířená spotřeba ze sítě",
        "unit_of_measurement": "Wh",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
        "node_id": None,
        "node_key": None,
    },
    "extended_grid_delivery": {
        "name": "Extended Grid Delivery",
        "name_cs": "Rozšířená dodávka do sítě",
        "unit_of_measurement": "Wh",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        # Original state_class was MEASUREMENT for delivery, this is unusual for energy.
        # Typically, delivered energy is also TOTAL_INCREASING or just TOTAL.
        # Keeping as "measurement" if that's the specific intent, but it's worth noting.
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT 
        "node_id": None,
        "node_key": None,
    },
}
