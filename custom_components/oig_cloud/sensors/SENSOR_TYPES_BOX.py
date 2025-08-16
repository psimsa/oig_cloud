from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature

from typing import Dict, Any

SENSOR_TYPES_BOX: Dict[str, Dict[str, Any]] = {
    "box_humid": {
        "name": "Humidity",
        "name_cs": "Vlhkost v boxu",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit_of_measurement": PERCENTAGE,
        "node_id": "box",
        "node_key": "humid",
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "data",
    },
    "box_prms_mode": {
        "name": "Operation Mode",
        "name_cs": "Režim",
        "device_class": None,
        "unit_of_measurement": None,
        "node_id": "box_prms",
        "node_key": "mode",
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "data",
    },
    "box_temp": {
        "name": "Temperature",
        "name_cs": "Teplota v boxu",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit_of_measurement": UnitOfTemperature.CELSIUS,
        "node_id": "box",
        "node_key": "temp",
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "sensor_type_category": "data",
    },
}
