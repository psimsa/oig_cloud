from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory


BINARY_SENSOR_TYPES = {
    "oig_cloud_call_pending": {
        "name": "OIG Service Call in progress",
        "name_cs": "Probíhá zpracování servisního volání",
        "device_class": BinarySensorDeviceClass.LOCK,
        "node_id": None,
        "node_key": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    }
}
