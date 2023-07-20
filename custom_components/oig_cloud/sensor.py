import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)

from .oig_cloud_computed_sensor import OigCloudComputedSensor
from .oig_cloud_data_sensor import OigCloudDataSensor
from .const import (
    DOMAIN,
)
from .sensor_types import SENSOR_TYPES
from .api.oig_cloud_api import OigCloudApi

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
        name="sensor",
        update_method=update_data,
        update_interval=timedelta(seconds=60),
    )

    # Fetch initial data so we have data when entities subscribe.
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("First refresh done, will add entities")

    # Add common entities
    async_add_entities(
        OigCloudDataSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if not "requires" in SENSOR_TYPES[sensor_type].keys()
        and SENSOR_TYPES[sensor_type]["node_id"] is not None
    )
    async_add_entities(
        OigCloudComputedSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if not "requires" in SENSOR_TYPES[sensor_type].keys()
        and SENSOR_TYPES[sensor_type]["node_id"] is None
    )

    box_id = list(oig_cloud.last_state.keys())[0]
    # Add entities that require 'boiler'
    if len(oig_cloud.last_state[box_id]["boiler"]) > 0:
        async_add_entities(
            OigCloudDataSensor(coordinator, sensor_type)
            for sensor_type in SENSOR_TYPES
            if "requires" in SENSOR_TYPES[sensor_type].keys()
            and "boiler" in SENSOR_TYPES[sensor_type]["requires"]
            and SENSOR_TYPES[sensor_type]["node_id"] is not None

        )
        async_add_entities(
            OigCloudComputedSensor(coordinator, sensor_type)
            for sensor_type in SENSOR_TYPES
            if "requires" in SENSOR_TYPES[sensor_type].keys()
            and "boiler" in SENSOR_TYPES[sensor_type]["requires"]
            and SENSOR_TYPES[sensor_type]["node_id"] is None

        )

    _LOGGER.debug("async_setup_entry done")
