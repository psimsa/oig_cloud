import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from .const import DOMAIN, DEFAULT_NAME, CONF_STANDARD_SCAN_INTERVAL
from .binary_sensor_types import BINARY_SENSOR_TYPES
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

class OigCloudBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, sensor_type):
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._node_id = BINARY_SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key = BINARY_SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id = None  # Box ID načteme později bezpečně

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.coordinator.data:
            self._box_id = list(self.coordinator.data.keys())[0]
            _LOGGER.debug(f"Created binary sensor {self.name} with box_id {self._box_id}")

    @property
    def name(self):
        language = getattr(self.hass.config, "language", "en")
        if language == "cs":
            return BINARY_SENSOR_TYPES[self._sensor_type]["name_cs"]
        return BINARY_SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def unique_id(self):
        if self._box_id:
            return f"oig_cloud_{self._box_id}_{self._sensor_type}"
        return None

    @property
    def device_class(self):
        return BINARY_SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def is_on(self):
        if not self.coordinator.data or not self._box_id:
            return None
        try:
            pv_data = self.coordinator.data[self._box_id]
            value = pv_data[self._node_id][self._node_key]
            return bool(value)
        except Exception as e:
            _LOGGER.error(f"Error reading state for {self.unique_id}: {e}")
            return None

    @property
    def should_poll(self):
        return False

    @property
    def device_info(self):
        if not self._box_id:
            return None
        try:
            model_name = f"{DEFAULT_NAME} Home"
            is_queen = self.coordinator.data[self._box_id].get("queen", False)
            if is_queen:
                model_name = f"{DEFAULT_NAME} Queen"
            return {
                "identifiers": {(DOMAIN, self._box_id)},
                "name": f"{model_name} {self._box_id}",
                "manufacturer": "OIG",
                "model": model_name,
            }
        except Exception:
            return None

async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.debug("Setting up OIG Cloud Binary Sensors")

    oig_data = hass.data[DOMAIN][config_entry.entry_id]
    api: OigCloudApi = oig_data["api"]
    standard_scan_interval = oig_data.get("standard_scan_interval", 30)

    async def update_data():
        return await api.get_stats()

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="OIG Cloud Binary Sensor Coordinator",
        update_method=update_data,
        update_interval=timedelta(seconds=standard_scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    async_add_entities(
        OigCloudBinarySensor(coordinator, sensor_type)
        for sensor_type in BINARY_SENSOR_TYPES
    )

    _LOGGER.debug("Finished setting up OIG Cloud Binary Sensors")
