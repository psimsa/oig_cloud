from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

SENSOR_TYPES = {
    "dc_in_fv_p1": {
        "name": "Panels Output String 1",
        "name_cs": "Výkon panelů string 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p1",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_p2": {
        "name": "Panels Output String 2",
        "name_cs": "Výkon panelů string 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p2",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_total": {
        "name": "Panels Output Total",
        "name_cs": "Výkon panelů celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_proc": {
        "name": "Panels Output Percent",
        "name_cs": "Výkon panelů (procenta)",
        "device_class": SensorDeviceClass.POWER_FACTOR,
        "unit_of_measurement": "%",
        "node_id": "dc_in",
        "node_key": "fv_proc",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batt_bat_c": {
        "name": "Battery Percent",
        "name_cs": "Nabití baterie (procenta)",
        "device_class": SensorDeviceClass.BATTERY,
        "unit_of_measurement": "%",
        "node_id": "batt",
        "node_key": "bat_c",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_vr": {
        "name": "Voltage Line 1",
        "name_cs": "Napětí fáze 1",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_out",
        "node_key": "aco_vr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_vs": {
        "name": "Voltage Line 2",
        "name_cs": "Napětí fáze 2",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_out",
        "node_key": "aco_vs",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_vt": {
        "name": "Voltage Line 3",
        "name_cs": "Napětí fáze 3",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_out",
        "node_key": "aco_vt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pr": {
        "name": "Load Line 1",
        "name_cs": "Zátěž fáze 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_ps": {
        "name": "Load Line 2",
        "name_cs": "Zátěž fáze 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_ps",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pt": {
        "name": "Load Line 3",
        "name_cs": "Zátěž fáze 3",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_p": {
        "name": "Load Total",
        "name_cs": "Zátěž celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wr": {
        "name": "Grid Load Line 1",
        "name_cs": "Síť - zátěž fáze 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_ws": {
        "name": "Grid Load Line 2",
        "name_cs": "Síť - zátěž fáze 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_ws",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wt": {
        "name": "Grid Load Line 3",
        "name_cs": "Síť - zátěž fáze 3",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_vr": {
        "name": "Grid Voltage Line 1",
        "name_cs": "Síť - Napětí fáze 1",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_vs": {
        "name": "Grid Voltage Line 2",
        "name_cs": "Síť - Napětí fáze 2",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vs",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_vt": {
        "name": "Grid Voltage Line 3",
        "name_cs": "Síť - Napětí fáze 3",
        "device_class": SensorDeviceClass.VOLTAGE,
        "unit_of_measurement": "V",
        "node_id": "ac_in",
        "node_key": "aci_vt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wtotal": {
        "name": "Grid Load Total",
        "name_cs": "Síť - Zátěž celkem",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_ad": {
        "name": "PV Output Today",
        "name_cs": "Dnešní výroba",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "dc_in",
        "node_key": "fv_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_out_en_day": {
        "name": "Consumption Today",
        "name_cs": "Dnešní spotřeba",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_out",
        "node_key": "en_day",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_in_ac_ad": {
        "name": "Grid Consumption Today",
        "name_cs": "Dnešní odběr ze sítě",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_in_ac_pd": {
        "name": "Grid Delivery Today",
        "name_cs": "Dnešní dodávka do sítě",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_pd",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "batt_bat_apd": {
        "name": "Battery Charge Today",
        "name_cs": "Dnešní nabíjení baterie",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "batt",
        "node_key": "bat_apd",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "batt_bat_and": {
        "name": "Battery Discharge Today",
        "name_cs": "Dnešní vybíjení baterie",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "batt",
        "node_key": "bat_and",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
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
    "box_prms_mode": {
        "name": "Operation Mode",
        "name_cs": "Režim",
        "device_class": None,
        "unit_of_measurement": None,
        "node_id": "box_prms",
        "node_key": "mode",
        "state_class": None,
    },
    "box_temp": {
        "name": "Temperature",
        "name_cs": "Teplota v boxu",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit_of_measurement": "°C",
        "node_id": "box",
        "node_key": "temp",
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "box_humid": {
        "name": "Humidity",
        "name_cs": "Vlhkost v boxu",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit_of_measurement": "%",
        "node_id": "box",
        "node_key": "humid",
        "state_class": SensorStateClass.MEASUREMENT,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "box_prms_sw": {
        "name": "Software Version",
        "name_cs": "Verze firmware",
        "device_class": None,
        "unit_of_measurement": None,
        "node_id": "box_prms",
        "node_key": "sw",
        "state_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "batt_batt_comp_p": {
        "name": "Battery Power",
        "name_cs": "Výkon baterie",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "boiler_day_w": {
        "name": "Boiler - Today Energy",
        "name_cs": "Bojler - Dnešní uložení",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "boiler",
        "node_key": "w",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "boiler_current_cbb_w": {
        "name": "Boiler - Current Energy(CBB)",
        "name_cs": "Bojler - Aktuální výkon(CBB)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "boiler",
        "node_key": "p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "boiler_current_w": {
        "name": "Boiler - Current Energy(Computed)",
        "name_cs": "Bojler - Aktuální výkon(Vypočítaná)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "cbb_consumption_w": {
        "name": "CBB - Consumption Energy(Computed)",
        "name_cs": "CBB - Spotřeba(Vypočítaná)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    }
    # these don't seem to work like this, disabling
    # "box_prms_fan1": {
    #     "name": "Fan 1",
    #     "name_cs": "Ventilátor 1",
    #     "device_class": SensorDeviceClass.SPEED,
    #     "unit_of_measurement": "%",
    #     "node_id": "box_prms",
    #     "node_key": "fan1",
    #     "state_class": SensorStateClass.MEASUREMENT,
    #     "entity_category": EntityCategory.DIAGNOSTIC,
    #
    },
    # "box_prms_fan2": {
    #     "name": "Fan 2",
    #     "name_cs": "Ventilátor 2",
    #     "device_class": SensorDeviceClass.SPEED,
    #     "unit_of_measurement": "%",
    #     "node_id": "box_prms",
    #     "node_key": "fan2",
    #     "state_class": SensorStateClass.MEASUREMENT,
    #     "entity_category": EntityCategory.DIAGNOSTIC,
    #
    },
}
