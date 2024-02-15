import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.oig_cloud.const import DEFAULT_NAME, DOMAIN
from custom_components.oig_cloud.sensor_types import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


class OigCloudSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sensor_type):
        if not isinstance(sensor_type, str):
            raise TypeError("sensor_type must be a string")

        self.coordinator = coordinator
        self._sensor_type = sensor_type
        self._attr_state_class = SENSOR_TYPES[sensor_type]["state_class"]
        self._node_id = SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key = SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id = list(self.coordinator.data.keys())[0]
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created sensor {self.entity_id}")

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    async def async_update(self):
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()

    @property
    def entity_category(self):
        return SENSOR_TYPES[self._sensor_type].get("entity_category")

    @property
    def unit_of_measurement(self):
        return SENSOR_TYPES[self._sensor_type]["unit_of_measurement"]

    @property
    def unique_id(self):
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self):
        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]
        is_queen = pv_data["queen"]
        if is_queen:
            model_name = f"{DEFAULT_NAME} Queen"
        else:
            model_name = f"{DEFAULT_NAME} Home"

        return {
            "identifiers": {(DOMAIN, self._box_id)},
            "name": f"{model_name} {self._box_id}",
            "manufacturer": "OIG",
            "model": model_name,
        }

    @property
    def should_poll(self):
        # DataUpdateCoordinator handles polling
        return False

    @property
    def options(self) -> list[str] | None:
        return SENSOR_TYPES[self._sensor_type].get("options")

    @property
    def name(self):
        """Return the name of the sensor."""
        language = self.hass.config.language
        if language == "cs":
            return SENSOR_TYPES[self._sensor_type]["name_cs"]
        return SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self):
        return SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def state_class(self):
        """Return the state class of the sensor."""
        return SENSOR_TYPES[self._sensor_type]["state_class"]
