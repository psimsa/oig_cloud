from typing import Dict, Final, List # List may be needed for options
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_BOILER: Final[Dict[str, OigSensorTypeDescription]] = {
    "boiler_current_cbb_w": {
        "name": "Boiler - Current Energy (CBB)",
        "name_cs": "Bojler - Aktuální výkon (CBB)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "boiler",
        "node_key": "p",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        # "requires": ["boiler"], # 'requires' is not in OigSensorTypeDescription, remove or add to TypedDict
    },
    "boiler_current_w": {
        "name": "Boiler - Current Energy (Computed)",
        "name_cs": "Bojler - Aktuální výkon (Vypočítaná)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        # "requires": ["boiler"],
    },
    "boiler_day_w": {
        "name": "Boiler - Today Energy",
        "name_cs": "Bojler - Dnešní uložení",
        "device_class": "power", # Was SensorDeviceClass.POWER - unit is Wh, should be ENERGY
        "unit_of_measurement": "Wh",
        "node_id": "boiler",
        "node_key": "w",
        "state_class": "total_increasing", # Was SensorStateClass.TOTAL_INCREASING
        # "requires": ["boiler"],
    },
    "boiler_manual_mode": {
        "name": "Boiler - Manual mode",
        "name_cs": "Bojler - Manuální režim",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "manual",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "state_class": None, # No direct string equivalent for None state_class
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr1": {
        "name": "Boiler - SSR Rele 1",
        "name_cs": "Bojler - SSR Relé 1",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr0",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr2": {
        "name": "Boiler - SSR Rele 2",
        "name_cs": "Bojler - SSR Relé 2",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr1",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr3": {
        "name": "Boiler - SSR Rele 3",
        "name_cs": "Bojler - SSR Relé 3",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr2",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_is_use": {
        "name": "Boiler - is use",
        "name_cs": "Bojler - K dispozici",
        "device_class": "enum", # Was SensorDeviceClass.ENUM
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ison",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_install_power": {
        "name": "Boiler - install power",
        "name_cs": "Bojler - instalovaný výkon",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": "boiler_prms",
        "node_key": "p_set",
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
}
