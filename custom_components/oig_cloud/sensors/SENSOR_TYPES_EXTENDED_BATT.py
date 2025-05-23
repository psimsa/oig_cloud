from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_EXTENDED_BATT: Final[Dict[str, OigSensorTypeDescription]] = {
    "extended_battery_voltage": {
        "name": "Extended Battery Voltage",
        "name_cs": "Napětí baterie",
        "unit_of_measurement": "V",
        "device_class": "voltage", # Was SensorDeviceClass.VOLTAGE
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Extended sensors derive values differently
        "node_key": None,
    },
    "extended_battery_current": {
        "name": "Extended Battery Current",
        "name_cs": "Proud baterie",
        "unit_of_measurement": "A",
        "device_class": "current", # Was SensorDeviceClass.CURRENT
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_battery_capacity": {
        "name": "Extended Battery Capacity",
        "name_cs": "Rozšířená kapacita baterie",
        "unit_of_measurement": "%",
        "device_class": "battery", # Was SensorDeviceClass.BATTERY
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
    },
    "extended_battery_temperature": {
        "name": "Extended Battery Temperature",
        "name_cs": "Teplota baterie",
        "unit_of_measurement": "°C",
        "device_class": "temperature", # Was SensorDeviceClass.TEMPERATURE
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None,
        "node_key": None,
        "entity_category": "diagnostic", # Was EntityCategory.DIAGNOSTIC
    },
    "usable_battery_capacity": {
        "name": "Usable Battery Capacity",
        "name_cs": "Baterie - využitelná kapacita",
        "unit_of_measurement": "kWh",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT (Energy can also be TOTAL)
        "node_id": None, # Computed
        "node_key": None,
    },
    "missing_battery_kwh": {
        "name": "Missing Energy to 100%",
        "name_cs": "Baterie - k nabití",
        "unit_of_measurement": "kWh",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Computed
        "node_key": None,
    },
    "remaining_usable_capacity": {
        "name": "Remaining Usable Capacity",
        "name_cs": "Baterie - zbývající kapacita",
        "unit_of_measurement": "kWh",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
        "node_id": None, # Computed
        "node_key": None,
    },
    "time_to_full": {
        "name": "Time to Full",
        "name_cs": "Baterie - plné nabití",
        "unit_of_measurement": None, # Unit might be 'hours' or 'minutes' if formatted by sensor
        "device_class": None, # No specific device class for duration unless using SensorDeviceClass.DURATION
        "state_class": None, # Typically measurement if it's a numeric duration
        "node_id": None, # Computed
        "node_key": None,
        "icon": "mdi:battery-clock", # Example icon
    },
    "time_to_empty": {
        "name": "Time to Empty",
        "name_cs": "Baterie - do vybití",
        "unit_of_measurement": None,
        "device_class": None, # SensorDeviceClass.DURATION could be applicable if value is in standard time units
        "state_class": None,
        "node_id": None, # Computed
        "node_key": None,
        "icon": "mdi:battery-clock-outline", # Example icon
    },
}
