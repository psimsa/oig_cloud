from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory


from typing import Dict


SENSOR_TYPES_MISC: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {
     "device_lastcall": {
        "name": "Last Call",
        "name_cs": "Poslední komunikace",
        "device_class": SensorDeviceClass.TIMESTAMP,
        "unit_of_measurement": None,
        "node_id": "device",
        "node_key": "lastcall",
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "invertor_prm1_p_max_feed_grid": {
        "name": "Max Feed to Grid",
        "name_cs": "Maximální přetoky",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "invertor_prm1",
        "node_key": "p_max_feed_grid",
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "invertor_prms_to_grid": {
        "name": "Grid Delivery",
        "name_cs": "Přetoky do sítě",
        "device_class": SensorDeviceClass.ENUM,
        "unit_of_measurement": None,
        "node_id": "invertor_prms",
        "node_key": "to_grid",
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"],
    },
}