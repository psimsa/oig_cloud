from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass


from typing import Dict


SENSOR_TYPES_BATT: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {
    "batt_bat_c": {
        "name": "Battery Percent",
        "name_cs": "Nabití baterie (procenta, live)",
        "device_class": SensorDeviceClass.BATTERY,
        "unit_of_measurement": "%",
        "node_id": "actual",
        "node_key": "bat_c",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batt_batt_comp_p": {
        "name": "Battery Power",
        "name_cs": "Výkon baterie (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "bat_p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batt_batt_comp_p_charge": {
        "name": "Battery Charge Power",
        "name_cs": "Výkon baterie - nabíjení (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batt_batt_comp_p_discharge": {
        "name": "Battery Discharge Power",
        "name_cs": "Výkon baterie - vybíjení (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },    
}
