import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .sensor_types import SENSOR_TYPES
from .shared.shared import GridMode

_LOGGER = logging.getLogger(__name__)

_LANGS = {
    "on": {
        "en": "On",
        "cs": "Zapnuto",
    },
    "off": {
        "en": "Off",
        "cs": "Vypnuto",
    },
    "unknown": {
        "en": "Unknown",
        "cs": "Neznámý",
    },
    "changing": {
        "en": "Changing in progress",
        "cs": "Probíhá změna",
    },
}


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
    def state(self):
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None
        language = self.hass.config.language
        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]

        
        try:
            node_value = pv_data[self._node_id][self._node_key]

            # special cases
            if self._sensor_type == "box_prms_mode":
                if node_value == 0:
                    return "Home 1"
                elif node_value == 1:
                    return "Home 2"
                elif node_value == 2:
                    return "Home 3"
                elif node_value == 3:
                    return "Home UPS"
                return _LANGS["unknown"][language]

            if self._sensor_type == "invertor_prms_to_grid":
                grid_enabled = int(pv_data["box_prms"]["crcte"])
                to_grid = int(node_value)
                max_grid_feed = int(pv_data["invertor_prm1"]["p_max_feed_grid"])

                if bool(pv_data["queen"]):
                    vypnuto = 0 == to_grid and 0 == max_grid_feed
                    zapnuto = 1 == to_grid
                    limited = 0 == to_grid and 0 < max_grid_feed
                else:
                    vypnuto = 0 == grid_enabled and 0 == to_grid
                    zapnuto = 1 == grid_enabled and 1 == to_grid and 10000 == max_grid_feed
                    limited = 1 == grid_enabled and 1 == to_grid and 9999 >= max_grid_feed

                if vypnuto:
                    return GridMode.OFF.value
                elif limited:
                    return GridMode.LIMITED.value
                elif zapnuto:
                    return GridMode.ON.value
                return _LANGS["changing"][language]
            try:
                return float(node_value)
            except ValueError:
                return node_value
        except KeyError:
            return None

    @property
    def unit_of_measurement(self):
        return SENSOR_TYPES[self._sensor_type]["unit_of_measurement"]

    @property
    def unique_id(self):
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def entity_category(self):
        return SENSOR_TYPES[self._sensor_type].get("entity_category")

    @property
    def should_poll(self):
        # DataUpdateCoordinator handles polling
        return False

    @property
    def state_class(self):
        """Return the state class of the sensor."""
        return SENSOR_TYPES[self._sensor_type]["state_class"]

    @property
    def options(self) -> list[str] | None:
        return SENSOR_TYPES[self._sensor_type].get("options")

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

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    async def async_update(self):
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()
