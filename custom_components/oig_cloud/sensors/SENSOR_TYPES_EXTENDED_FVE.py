from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from typing import Dict

SENSOR_TYPES_EXTENDED_FVE: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {
    "extended_fve_voltage_1": {
        "name": "Extended FVE Voltage 1",
        "name_cs": "Rozšířené napětí FV1",
        "unit_of_measurement": "V",
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_voltage_2": {
        "name": "Extended FVE Voltage 2",
        "name_cs": "Rozšířené napětí FV2",
        "unit_of_measurement": "V",
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_current": {
        "name": "Extended FVE Current",
        "name_cs": "Rozšířený proud FV",
        "unit_of_measurement": "A",
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_power_1": {
        "name": "Extended FVE Power 1",
        "name_cs": "Rozšířený výkon FV1",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
    "extended_fve_power_2": {
        "name": "Extended FVE Power 2",
        "name_cs": "Rozšířený výkon FV2",
        "unit_of_measurement": "W",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "node_id": None,
        "node_key": None,
    },
}