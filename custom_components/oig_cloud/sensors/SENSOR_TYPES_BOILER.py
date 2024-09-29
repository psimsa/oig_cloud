from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory


from typing import Dict


SENSOR_TYPES_BOILER: Dict[
    str, Dict[str, str | SensorDeviceClass | SensorStateClass]
] = {
    "boiler_current_cbb_w": {
        "name": "Boiler - Current Energy (CBB)",
        "name_cs": "Bojler - Aktuální výkon (CBB)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "boiler",
        "node_key": "p",
        "state_class": SensorStateClass.MEASUREMENT,
        "requires": ["boiler"],
    },
    "boiler_current_w": {
        "name": "Boiler - Current Energy (Computed)",
        "name_cs": "Bojler - Aktuální výkon (Vypočítaná)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "requires": ["boiler"],
    },
    "boiler_day_w": {
        "name": "Boiler - Today Energy",
        "name_cs": "Bojler - Dnešní uložení",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "boiler",
        "node_key": "w",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "requires": ["boiler"],
    },
    "boiler_manual_mode": {
        "name": "Boiler - Manual mode",
        "name_cs": "Bojler - Manuální režim",
        "device_class": SensorDeviceClass.ENUM,
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "manual",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr1": {
        "name": "Boiler - SSR Rele 1",
        "name_cs": "Bojler - SSR Relé 1",
        "device_class": SensorDeviceClass.ENUM,
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr0",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr2": {
        "name": "Boiler - SSR Rele 2",
        "name_cs": "Bojler - SSR Relé 2",
        "device_class": SensorDeviceClass.ENUM,
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr1",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
    "boiler_ssr3": {
        "name": "Boiler - SSR Rele 3",
        "name_cs": "Bojler - SSR Relé 3",
        "device_class": SensorDeviceClass.ENUM,
        "unit_of_measurement": None,
        "node_id": "boiler_prms",
        "node_key": "ssr2",
        "entity_category": EntityCategory.DIAGNOSTIC,
        "state_class": None,
        "options": ["Vypnuto / Off", "Zapnuto / On"],
    },
}