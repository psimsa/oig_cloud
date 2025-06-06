from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass


from typing import Dict


SENSOR_TYPES_ACTUAL: Dict[
    str, Dict[str, str | SensorDeviceClass | SensorStateClass]
] = {
    "actual_aci_wr": {
        "name": "Grid Load Line 1 (live)",
        "name_cs": "Síť - zátěž fáze 1 (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_wr",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_aci_ws": {
        "name": "Grid Load Line 2 (live)",
        "name_cs": "Síť - zátěž fáze 2 (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_ws",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_aci_wt": {
        "name": "Grid Load Line 3 (live)",
        "name_cs": "Síť - zátěž fáze 3 (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aci_wt",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_aci_wtotal": {
        "name": "Grid Load Total (live)",
        "name_cs": "Síť - Zátěž celkem (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_aco_p": {
        "name": "Load Total (live)",
        "name_cs": "Zátěž celkem (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "aco_p",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_fv_p1": {
        "name": "Panels Output String 1 (live)",
        "name_cs": "Výkon panelů string 1 (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "fv_p1",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_fv_p2": {
        "name": "Panels Output String 2 (live)",
        "name_cs": "Výkon panelů string 2 (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": "actual",
        "node_key": "fv_p2",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "actual_fv_total": {
        "name": "Panels Output Total (live)",
        "name_cs": "Výkon panelů celkem (live)",
        "device_class": SensorDeviceClass.POWER,
        "unit_of_measurement": "W",
        "node_id": None,
        "node_key": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}