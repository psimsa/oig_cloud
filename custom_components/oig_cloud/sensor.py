"""Sensor platform for OIG Cloud integration."""
import logging
from typing import Any, Callable, Dict, List, Optional, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import OigCloudDataUpdateCoordinator
from .oig_cloud_computed_sensor import OigCloudComputedSensor
from .oig_cloud_data_sensor import OigCloudDataSensor
from .sensor_types import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OIG Cloud sensors from a config entry."""
    _LOGGER.debug("Setting up OIG Cloud sensors")
    
    # Get coordinator from hass.data
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: OigCloudDataUpdateCoordinator = entry_data["coordinator"]
    
    # Check if we have data before proceeding
    if not coordinator.data:
        _LOGGER.error("No data available from coordinator")
        return
    
    _LOGGER.debug("First coordinator refresh successful, adding entities")

    # Add common entities
    _register_common_entities(async_add_entities, coordinator)

    # Get the box ID from the coordinator data
    box_id = list(coordinator.data.keys())[0]
    
    # Add entities that require 'boiler' if available
    if "boiler" in coordinator.data[box_id] and len(coordinator.data[box_id]["boiler"]) > 0:
        _LOGGER.debug("Registering boiler entities")
        _register_boiler_entities(async_add_entities, coordinator)
    else:
        _LOGGER.debug("No boiler data available, skipping boiler entities")

    _LOGGER.debug("Sensor setup completed")


def _register_boiler_entities(async_add_entities: AddEntitiesCallback, coordinator: DataUpdateCoordinator) -> None:
    """Register boiler-specific sensor entities."""
    # Add data sensors that require boiler data
    async_add_entities(
        OigCloudDataSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if "requires" in SENSOR_TYPES[sensor_type]
        and "boiler" in SENSOR_TYPES[sensor_type]["requires"]
        and SENSOR_TYPES[sensor_type]["node_id"] is not None
    )
    
    # Add computed sensors that require boiler data
    async_add_entities(
        OigCloudComputedSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if "requires" in SENSOR_TYPES[sensor_type]
        and "boiler" in SENSOR_TYPES[sensor_type]["requires"]
        and SENSOR_TYPES[sensor_type]["node_id"] is None
    )


def _register_common_entities(async_add_entities: AddEntitiesCallback, coordinator: DataUpdateCoordinator) -> None:
    """Register common sensor entities that don't require specific components."""
    # Add standard data sensors
    async_add_entities(
        OigCloudDataSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if "requires" not in SENSOR_TYPES[sensor_type]
        and SENSOR_TYPES[sensor_type]["node_id"] is not None
    )
    
    # Add computed sensors
    async_add_entities(
        OigCloudComputedSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if "requires" not in SENSOR_TYPES[sensor_type]
        and SENSOR_TYPES[sensor_type]["node_id"] is None
    )
