from typing import Dict, Final
from ..sensor_types import OigSensorTypeDescription

# SensorDeviceClass, SensorStateClass, EntityCategory are not directly used as types here
# if their values are stored as strings, matching OigSensorTypeDescription.

SENSOR_TYPES_BATT: Final[Dict[str, OigSensorTypeDescription]] = {
    # Live hodnoty
    "batt_bat_c": {
        "name": "Battery Percent",
        "name_cs": "Nabití baterie (procenta, live)",
        "device_class": "battery", # Was SensorDeviceClass.BATTERY
        "unit_of_measurement": "%",
        "node_id": "actual", # Note: was 'batt' in some older versions, now 'actual' for live SoC
        "node_key": "bat_c",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "batt_batt_comp_p": {
        "name": "Battery Power",
        "name_cs": "Výkon baterie (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": "actual", # Note: was 'batt' in some older versions, now 'actual' for live power
        "node_key": "bat_p",
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    # Výkon oddělený na nabíjení a vybíjení
    "batt_batt_comp_p_charge": {
        "name": "Battery Charge Power",
        "name_cs": "Výkon baterie - nabíjení (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    "batt_batt_comp_p_discharge": {
        "name": "Battery Discharge Power",
        "name_cs": "Výkon baterie - vybíjení (live)",
        "device_class": "power", # Was SensorDeviceClass.POWER
        "unit_of_measurement": "W",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "measurement", # Was SensorStateClass.MEASUREMENT
    },
    # Energie nabíjení/vybíjení CELKEM
    "computed_batt_charge_energy_today": {
        "name": "Battery Charge Energy Today",
        "name_cs": "Energie nabíjení baterie dnes",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_discharge_energy_today": {
        "name": "Battery Discharge Energy Today",
        "name_cs": "Energie vybíjení baterie dnes",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_energy_month": {
        "name": "Battery Charge Energy This Month",
        "name_cs": "Energie nabíjení baterie tento měsíc",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_discharge_energy_month": {
        "name": "Battery Discharge Energy This Month",
        "name_cs": "Energie vybíjení baterie tento měsíc",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_energy_year": {
        "name": "Battery Charge Energy This Year",
        "name_cs": "Energie nabíjení baterie tento rok",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_discharge_energy_year": {
        "name": "Battery Discharge Energy This Year",
        "name_cs": "Energie vybíjení baterie tento rok",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    # Energie nabíjení Z FVE
    "computed_batt_charge_fve_energy_today": {
        "name": "Battery Charge Energy from Solar Today",
        "name_cs": "Energie nabíjení baterie ze slunce dnes",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_fve_energy_month": {
        "name": "Battery Charge Energy from Solar This Month",
        "name_cs": "Energie nabíjení baterie ze slunce tento měsíc",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_fve_energy_year": {
        "name": "Battery Charge Energy from Solar This Year",
        "name_cs": "Energie nabíjení baterie ze slunce tento rok",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    # Energie nabíjení ZE SÍTĚ
    "computed_batt_charge_grid_energy_today": {
        "name": "Battery Charge Energy from Grid Today",
        "name_cs": "Energie nabíjení baterie ze sítě dnes",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_grid_energy_month": {
        "name": "Battery Charge Energy from Grid This Month",
        "name_cs": "Energie nabíjení baterie ze sítě tento měsíc",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
    "computed_batt_charge_grid_energy_year": {
        "name": "Battery Charge Energy from Grid This Year",
        "name_cs": "Energie nabíjení baterie ze sítě tento rok",
        "device_class": "energy", # Was SensorDeviceClass.ENERGY
        "unit_of_measurement": "Wh",
        "node_id": None, # Computed
        "node_key": None,
        "state_class": "total", # Was SensorStateClass.TOTAL
    },
}
