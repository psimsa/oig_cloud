from typing import Dict
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.oig_cloud.sensors.SENSOR_TYPES_ACTUAL import SENSOR_TYPES_ACTUAL
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_OUT import SENSOR_TYPES_AC_OUT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BATT import SENSOR_TYPES_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOILER import SENSOR_TYPES_BOILER
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOX import SENSOR_TYPES_BOX
from custom_components.oig_cloud.sensors.SENSOR_TYPES_MISC import SENSOR_TYPES_MISC
from custom_components.oig_cloud.sensors.SENSOR_TYPES_DC_IN import SENSOR_TYPES_DC_IN
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_IN import SENSOR_TYPES_AC_IN

SENSOR_TYPES: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {}
SENSOR_TYPES.update(SENSOR_TYPES_AC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_DC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_BOX)
SENSOR_TYPES.update(SENSOR_TYPES_BOILER)
SENSOR_TYPES.update(SENSOR_TYPES_BATT)
SENSOR_TYPES.update(SENSOR_TYPES_ACTUAL)
SENSOR_TYPES.update(SENSOR_TYPES_AC_OUT)
SENSOR_TYPES.update(SENSOR_TYPES_MISC)

# "ac_out_aco_vr": {
#     "name": "Voltage Line 1",
#     "name_cs": "Napětí fáze 1",
#     "device_class": SensorDeviceClass.VOLTAGE,
#     "unit_of_measurement": "V",
#     "node_id": "ac_out",
#     "node_key": "aco_vr",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "ac_out_aco_vs": {
#     "name": "Voltage Line 2",
#     "name_cs": "Napětí fáze 2",
#     "device_class": SensorDeviceClass.VOLTAGE,
#     "unit_of_measurement": "V",
#     "node_id": "ac_out",
#     "node_key": "aco_vs",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "ac_out_aco_vt": {
#     "name": "Voltage Line 3",
#     "name_cs": "Napětí fáze 3",
#     "device_class": SensorDeviceClass.VOLTAGE,
#     "unit_of_measurement": "V",
#     "node_id": "ac_out",
#     "node_key": "aco_vt",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "batt_bat_and": {
#     "name": "Battery Discharge Today",
#     "name_cs": "Dnešní vybíjení baterie",
#     "device_class": SensorDeviceClass.ENERGY,
#     "unit_of_measurement": "Wh",
#     "node_id": "batt",
#     "node_key": "bat_and",
#     "state_class": SensorStateClass.TOTAL_INCREASING,
# },
# "batt_bat_apd": {
#     "name": "Battery Charge Today",
#     "name_cs": "Dnešní nabíjení baterie",
#     "device_class": SensorDeviceClass.ENERGY,
#     "unit_of_measurement": "Wh",
#     "node_id": "batt",
#     "node_key": "bat_apd",
#     "state_class": SensorStateClass.TOTAL_INCREASING,
# },
# "battery_add_month": {
#     "name": "Battery - Month add",
#     "name_cs": "Nabíjení baterie za měsíc",
#     "device_class": SensorDeviceClass.ENERGY,
#     "unit_of_measurement": "kW",
#     "node_id": "batt",
#     "node_key": "bat_am",
#     "state_class": SensorStateClass.TOTAL_INCREASING,
# },
# "battery_add_year": {
#     "name": "Battery - Year add",
#     "name_cs": "Nabíjení baterie za rok",
#     "device_class": SensorDeviceClass.ENERGY,
#     "unit_of_measurement": "kW",
#     "node_id": "batt",
#     "node_key": "bat_ay",
#     "state_class": SensorStateClass.TOTAL_INCREASING,
# },
# "battery_current": {
#     "name": "Battery - current",
#     "name_cs": "Proud v baterii",
#     "device_class": SensorDeviceClass.POWER,
#     "unit_of_measurement": "A",
#     "node_id": "batt",
#     "node_key": "bat_i",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "battery_quality": {
#     "name": "Quality of battery",
#     "name_cs": "Kvalita baterie",
#     "device_class": SensorDeviceClass.POWER_FACTOR,
#     "unit_of_measurement": "%",
#     "node_id": "batt",
#     "node_key": "bat_q",
#     "state_class": SensorStateClass.MEASUREMENT,
#     "entity_category": EntityCategory.DIAGNOSTIC,
# },
# "battery_temp": {
#     "name": "Battery - temp",
#     "name_cs": "Teplota baterie",
#     "device_class": SensorDeviceClass.TEMPERATURE,
#     "unit_of_measurement": "°C",
#     "node_id": "batt",
#     "node_key": "bat_t",
#     "entity_category": EntityCategory.DIAGNOSTIC,
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "battery_volt": {
#     "name": "Battery - volt",
#     "name_cs": "Napětí v baterii",
#     "device_class": SensorDeviceClass.POWER,
#     "unit_of_measurement": "V",
#     "node_id": "batt",
#     "node_key": "bat_v",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "box_prms_sw": {
#     "name": "Software Version",
#     "name_cs": "Verze firmware",
#     "device_class": None,
#     "unit_of_measurement": None,
#     "node_id": "box_prms",
#     "node_key": "sw",
#     "state_class": None,
#     "entity_category": EntityCategory.DIAGNOSTIC,
# },
# "cbb_consumption_w": {
#     "name": "CBB - Consumption Energy (Computed)",
#     "name_cs": "CBB - Spotřeba (Vypočítaná)",
#     "device_class": SensorDeviceClass.POWER,
#     "unit_of_measurement": "W",
#     "node_id": None,
#     "node_key": None,
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "dc_in_fv_i1": {
#     "name": "Panels Current String 1",
#     "name_cs": "Proud panelů string 1",
#     "device_class": SensorDeviceClass.CURRENT,
#     "unit_of_measurement": "A",
#     "node_id": "dc_in",
#     "node_key": "fv_i1",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "dc_in_fv_i2": {
#     "name": "Panels Current String 2",
#     "name_cs": "Proud panelů string 2",
#     "device_class": SensorDeviceClass.CURRENT,
#     "unit_of_measurement": "A",
#     "node_id": "dc_in",
#     "node_key": "fv_i2",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "dc_in_fv_v1": {
#     "name": "Panels Voltage String 1",
#     "name_cs": "Napětí panelů string 1",
#     "device_class": SensorDeviceClass.VOLTAGE,
#     "unit_of_measurement": "V",
#     "node_id": "dc_in",
#     "node_key": "fv_v1",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
# "dc_in_fv_v2": {
#     "name": "Panels Voltage String 2",
#     "name_cs": "Napětí panelů string 2",
#     "device_class": SensorDeviceClass.VOLTAGE,
#     "unit_of_measurement": "V",
#     "node_id": "dc_in",
#     "node_key": "fv_v2",
#     "state_class": SensorStateClass.MEASUREMENT,
# },
