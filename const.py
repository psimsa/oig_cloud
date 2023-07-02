from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorStateClass, SensorDeviceClass
from opentelemetry.sdk.resources import Resource
from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN = "oig_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"

DEFAULT_NAME = "Battery Box"

SENSOR_NAMES = {
    "en": {
        "dc_in_fv_p1": "Panels Output String 1",
        "dc_in_fv_p2": "Panels Output String 2",
        "dc_in_fv_total": "Panels Output Total",
        "dc_in_fv_proc": "Panels Output Percent",
        "batt_bat_c": "Battery Percent",
        "ac_out_aco_pr": "Load Line 1",
        "ac_out_aco_ps": "Load Line 2",
        "ac_out_aco_pt": "Load Line 3",
        "ac_out_aco_p": "Load Total",
        "ac_in_aci_wr": "Grid Load Line 1",
        "ac_in_aci_ws": "Grid Load Line 2",
        "ac_in_aci_wt": "Grid Load Line 3",
        "ac_in_aci_wtotal": "Grid Load Total",
        "dc_in_fv_ad": "PV Output Today",
        "ac_out_en_day": "Consumption Today",
        "ac_in_ac_ad": "Grid Consumption Today",
        "ac_in_ac_pd": "Grid Delivery Today",
        "batt_bat_apd": "Battery Charge Today",
        "batt_bat_and": "Battery Discharge Today",
        "device_lastcall": "Last Call",
        "box_prms_mode": "Operation Mode",
        "box_temp": "Box Temperature",
        "box_humid": "Box Humidity",
        "box_prms_sw": "Firmware Version",
        "invertor_prms_to_grid": "Grid Delivery",
    },
    "cs": {
        "dc_in_fv_p1": "Výkon panelů string 1",
        "dc_in_fv_p2": "Výkon panelů string 2",
        "dc_in_fv_total": "Výkon panelů celkem",
        "dc_in_fv_proc": "Výkon panelů (procenta)",
        "batt_bat_c": "Nabití baterie (procenta)",
        "ac_out_aco_pr": "Zátěž fáze 1",
        "ac_out_aco_ps": "Zátěž fáze 2",
        "ac_out_aco_pt": "Zátěž fáze 3",
        "ac_out_aco_p": "Zátěž celkem",
        "ac_in_aci_wr": "Síť - Zátěž fáze 1",
        "ac_in_aci_ws": "Síť - Zátěž fáze 2",
        "ac_in_aci_wt": "Síť - Zátěž fáze 3",
        "ac_in_aci_wtotal": "Síť - Zátěž celkem",
        "dc_in_fv_ad": "Dnešní výroba",
        "ac_out_en_day": "Dnešní spotřeba (FVE)",
        "ac_in_ac_ad": "Dnešní spotřeba (síť)",
        "ac_in_ac_pd": "Dnešní dodávka do sítě",
        "batt_bat_apd": "Dnešní nabíjení baterie",
        "batt_bat_and": "Dnešní vybíjení baterie",
        "device_lastcall": "Poslední komunikace",
        "box_prms_mode": "Režim provozu",
        "box_temp": "Teplota boxu",
        "box_humid": "Vlhkost v boxu",
        "box_prms_sw": "Verze firmware",
        "invertor_prms_to_grid": "Přetoky do sítě",
    },
}

SENSOR_TYPES = {
    "dc_in_fv_p1": {
        "name": "Panels Output String 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p1",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_p2": {
        "name": "Panels Output String 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "dc_in",
        "node_key": "fv_p2",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_total": {
        "name": "Panels Output Total",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_proc": {
        "name": "Panels Output Percent",
        "device_class": SensorDeviceClass.POWER_FACTOR,
        "unit_of_measurement": "%",
        "node_id": "dc_in",
        "node_key": "fv_proc",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batt_bat_c": {
        "name": "Battery Percent",
        "device_class": SensorDeviceClass.BATTERY,
        "unit_of_measurement": "%",
        "node_id": "batt",
        "node_key": "bat_c",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pr": {
        "name": "Load Line 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_ps": {
        "name": "Load Line 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_ps",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_pt": {
        "name": "Load Line 3",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_pt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_out_aco_p": {
        "name": "Load Total",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_out",
        "node_key": "aco_p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wr": {
        "name": "Grid Load Line 1",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_ws": {
        "name": "Grid Load Line 2",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_ws",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wt": {
        "name": "Grid Load Line 3",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "ac_in",
        "node_key": "aci_wt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ac_in_aci_wtotal": {
        "name": "Grid Load Total",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "",
        "node_key": "",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "dc_in_fv_ad": {
        "name": "PV Output Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "dc_in",
        "node_key": "fv_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_out_en_day": {
        "name": "Consumption Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_out",
        "node_key": "en_day",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_in_ac_ad": {
        "name": "Grid Consumption Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_ad",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "ac_in_ac_pd": {
        "name": "Grid Delivery Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "ac_in",
        "node_key": "ac_pd",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "batt_bat_apd": {
        "name": "Battery Charge Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "batt",
        "node_key": "bat_apd",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "batt_bat_and": {
        "name": "Battery Discharge Today",
        "device_class": SensorDeviceClass.ENERGY,
        "unit_of_measurement": "Wh",
        "node_id": "batt",
        "node_key": "bat_and",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "device_lastcall": {
        "name": "Last Call",
        "device_class": SensorDeviceClass.TIMESTAMP,
        "unit_of_measurement": None,
        "node_id": "device",
        "node_key": "lastcall",
        "state_class": None,
    },
    "box_prms_mode": {
        "name": "Operation Mode",
        "device_class": None,
        "unit_of_measurement": None,
        "node_id": "box_prms",
        "node_key": "mode",
        "state_class": None,
    },
    "box_temp": {
        "name": "Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit_of_measurement": "°C",
        "node_id": "box",
        "node_key": "temp",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "box_humid": {
        "name": "Humidity",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit_of_measurement": "%",
        "node_id": "box",
        "node_key": "humid",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "box_prms_sw": {
        "name": "Software Version",
        "device_class": None,
        "unit_of_measurement": None,
        "node_id": "box_prms",
        "node_key": "sw",
        "state_class": None,
    },
    
}

BINARY_SENSOR_TYPES= {
    "invertor_prms_to_grid":{
        "name": "Grid Delivery",
        "device_class": BinarySensorDeviceClass.POWER	,
        "node_id": "invertor_prms",
        "node_key": "to_grid"
    }
}

OT_RESOURCE = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": COMPONENT_VERSION,
        "service.namespace": "oig_cloud",
    }
)
OT_ENDPOINT = "https://otlp.eu01.nr-data.net"
OT_HEADERS = [
            (
                "api-key",
                "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
            )
        ]