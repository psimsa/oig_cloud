import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)
from custom_components.oig_cloud.oig_cloud_binary_sensor import OigCloudBinarySensor

from custom_components.oig_cloud.oig_cloud_computed_binary_sensor import (
    OigCloudComputedBinarySensor,
)
from custom_components.oig_cloud.const import (
    DOMAIN,
)
from custom_components.oig_cloud.binary_sensor_types import BINARY_SENSOR_TYPES
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.debug("async_setup_entry")

    oig_cloud: OigCloudApi = hass.data[DOMAIN][config_entry.entry_id]

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
        OigCloudBinarySensor(coordinator, sensor_type)
        for sensor_type in BINARY_SENSOR_TYPES
        if BINARY_SENSOR_TYPES[sensor_type]["node_id"] is not None
    )

    async_add_entities(
        OigCloudComputedBinarySensor(coordinator, sensor_type)
        for sensor_type in BINARY_SENSOR_TYPES
        if BINARY_SENSOR_TYPES[sensor_type]["node_id"] is None
    )
    _LOGGER.debug("async_setup_entry done")
