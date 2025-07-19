from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfElectricPotential, UnitOfPower, UnitOfEnergy
from typing import Dict, Any
from homeassistant.helpers.entity import EntityCategory

SENSOR_TYPES_EXTENDED_GRID: Dict[str, Dict[str, Any]] = {
    "extended_grid_voltage": {
        "name": "Extended Grid Voltage",
        "name_cs": "Rozšířené napětí sítě",
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_grid_power": {
        "name": "Extended Grid Power",
        "name_cs": "Rozšířený výkon sítě",
        "unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_grid_consumption": {
        "name": "Extended Grid Consumption",
        "name_cs": "Rozšířená spotřeba ze sítě",
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_grid_delivery": {
        "name": "Extended Grid Delivery",
        "name_cs": "Rozšířená dodávka do sítě",
        "unit_of_measurement": UnitOfEnergy.WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
}
