import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .const import (
    DOMAIN,
    SENSOR_NAMES,
    BINARY_SENSOR_TYPES,
)
from .api.oig_cloud import OigCloud

_LOGGER = logging.getLogger(__name__)

class OigCloudBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, sensor_type):
        self.coordinator = coordinator
        self._sensor_type = sensor_type
        self._node_id = BINARY_SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key = BINARY_SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id = list(self.coordinator.data.keys())[0]
        self.entity_id = f"binary_sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created binary sensor {self.entity_id}")

    @property
    def name(self):
        """Return the name of the sensor."""
        language = self.hass.config.language
        return SENSOR_NAMES.get(language, SENSOR_NAMES["en"])[self._sensor_type]

    @property
    def device_class(self):
        return BINARY_SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def state(self):
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None

        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]

        node_value = pv_data[self._node_id][self._node_key]

        return bool(node_value)

    @property
    def unique_id(self):
        return f"oig_cloud_{self._sensor_type}"

    @property
    def should_poll(self):
        # DataUpdateCoordinator handles polling
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._box_id)},
            "name": f"Battery Box {self._box_id}",
            "manufacturer": "OIG",
            "model": "Unknown",
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


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.debug("async_setup_entry")

    oig_cloud: OigCloud = hass.data[DOMAIN][config_entry.entry_id]

    async def update_data():
        """Fetch data from API endpoint."""
        return await oig_cloud.get_stats()

    # We create a new DataUpdateCoordinator.
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="binary_sensor",
        update_method=update_data,
        update_interval=timedelta(seconds=60),
    )

    # Fetch initial data so we have data when entities subscribe.
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("First refresh done, will add entities")

    async_add_entities(
        OigCloudBinarySensor(coordinator, sensor_type) for sensor_type in BINARY_SENSOR_TYPES
    )
    _LOGGER.debug("async_setup_entry done")
