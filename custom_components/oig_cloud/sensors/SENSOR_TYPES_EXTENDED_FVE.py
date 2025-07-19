from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfElectricCurrent,
)
from typing import Dict, Any
from homeassistant.helpers.entity import EntityCategory

SENSOR_TYPES_EXTENDED_FVE: Dict[str, Dict[str, Any]] = {
    "extended_fve_voltage_1": {
        "name": "Extended FVE Voltage 1",
        "name_cs": "Napětí FV1",
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_fve_voltage_2": {
        "name": "Extended FVE Voltage 2",
        "name_cs": "Napětí FV2",
        "unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_fve_power_1": {
        "name": "Extended FVE Power 1",
        "name_cs": "Rozšířený výkon FV1",
        "unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_fve_power_2": {
        "name": "Extended FVE Power 2",
        "name_cs": "Rozšířený výkon FV2",
        "unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_fve_current_1": {
        "name": "Extended FVE Curren FV 1",
        "name_cs": "Proud String 1",
        "unit_of_measurement": UnitOfElectricCurrent.AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
    "extended_fve_current_2": {
        "name": "Extended FVE Curren FV 2",
        "name_cs": "Proud String 2",
        "unit_of_measurement": UnitOfElectricCurrent.AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
        "sensor_type_category": "extended",
    },
}
