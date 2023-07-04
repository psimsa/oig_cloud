from homeassistant.components.binary_sensor import BinarySensorDeviceClass

BINARY_SENSOR_TYPES = {
    "invertor_prms_to_grid": {
        "name": "Grid Delivery",
        "name_cs": "Přetoky povoleny",
        "device_class": BinarySensorDeviceClass.POWER,
        "node_id": "invertor_prms",
        "node_key": "to_grid",
    }
}
