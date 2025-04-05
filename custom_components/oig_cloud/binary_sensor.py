"""Binary sensor platform for OIG Cloud integration."""
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .const import (
    DEFAULT_NAME,
    DOMAIN,
)
from .coordinator import OigCloudDataUpdateCoordinator
from .binary_sensor_types import BINARY_SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)

class OigCloudBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for OIG Cloud data."""
    
    def __init__(self, coordinator: DataUpdateCoordinator, sensor_type: str) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator)
        self.coordinator: DataUpdateCoordinator = coordinator
        self._sensor_type: str = sensor_type
        self._node_id: str = BINARY_SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key: str = BINARY_SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id: str = list(self.coordinator.data.keys())[0]
        self.entity_id = f"binary_sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created binary sensor {self.entity_id}")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return BINARY_SENSOR_TYPES[self._sensor_type]["name_cs"]
        return BINARY_SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return BINARY_SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def is_on(self) -> Optional[bool]:
        """Return true if the binary sensor is on."""
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if not self.coordinator.data:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None

        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]

        try:
            node_value: Any = pv_data[self._node_id][self._node_key]
            return bool(node_value)
        except (KeyError, TypeError):
            _LOGGER.warning(f"Could not find data for {self._node_id}.{self._node_key}")
            return None

    @property
    def unique_id(self) -> str:
        """Return unique ID for sensor."""
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]
        is_queen: bool = pv_data.get("queen", False)
        
        model_name: str = f"{DEFAULT_NAME} {'Queen' if is_queen else 'Home'}"

        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{model_name} {self._box_id}",
            manufacturer="OIG",
            model=model_name,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # First, check if coordinator is available at all
        if not self.coordinator.last_update_success:
            return False
            
        # Then check if we have the necessary data
        if not self.coordinator.data:
            return False
            
        # If we have data, check if we have the required node
        box_id = list(self.coordinator.data.keys())[0]
        if self._node_id not in self.coordinator.data[box_id]:
            return False
            
        return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up OIG Cloud binary sensors from a config entry."""
    _LOGGER.debug("Setting up OIG Cloud binary sensors")
    
    # Get coordinator from hass.data
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: OigCloudDataUpdateCoordinator = entry_data["coordinator"]
    
    if not coordinator.data:
        _LOGGER.error("No data available from coordinator")
        return
        
    if not BINARY_SENSOR_TYPES:
        _LOGGER.info("No binary sensor types defined, skipping binary sensor setup")
        return
    
    # Create sensor entities
    entities = [
        OigCloudBinarySensor(coordinator, sensor_type)
        for sensor_type in BINARY_SENSOR_TYPES
    ]
    
    if not entities:
        _LOGGER.debug("No binary sensor entities to add")
        return
        
    async_add_entities(entities)
    _LOGGER.debug("Binary sensor setup completed")
