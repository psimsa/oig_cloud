from typing import Dict, Final, List # Added List for options
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_MISC: Final[Dict[str, OigSensorTypeDescription]] = {
    "device_lastcall": {
        "name": "Last Call",
        "name_cs": "Poslední komunikace",
        "device_class": "timestamp", # Was SensorDeviceClass.TIMESTAMP
        "unit_of_measurement": None,
        "node_id": "device",
        "node_key": "lastcall",
        "state_class": None, # No direct string equivalent
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "invertor_prm1_p_max_feed_grid": {
        "name": "Max Feed to Grid",
        "name_cs": "Maximální přetoky",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "invertor_prm1",
        "node_key": "p_max_feed_grid",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "invertor_prms_to_grid": {
        "name": "Grid Delivery",
        "name_cs": "Přetoky do sítě",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "invertor_prms",
        "node_key": "to_grid",
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"],
        "entity_category": "diagnostic", # Added based on common pattern for such sensors
    },
    "installed_battery_capacity_kwh": {
        "name": "Installed Battery Capacity",
        "name_cs": "Baterie - instalovaná kapacita",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh", # Note: name implies kWh, unit is Wh. Data is likely in Wh.
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT (TOTAL could also fit for capacity)
        "node_id": "box_prms",
        "node_key": "p_bat",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "installed_fve_power_wp": {
        "name": "Installed FVE Power",
        "name_cs": "FVE - Instalovaný výkon",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "Wp",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": "box_prms",
        "node_key": "p_fve",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "box_prms_crct": {
        "name": "Distribution Emergency Control",
        "name_cs": "Krizové ovládání distribuce",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "state_class": None,
        "node_id": "box_prms",
        "node_key": "crct",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
}
