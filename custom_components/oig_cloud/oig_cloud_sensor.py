"""Base sensor for OIG Cloud integration."""
import logging
from typing import Any, Dict, List, Optional, Union, cast

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import OigCloudDataUpdateCoordinator
from .models import OigCloudData
from .sensor_types import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


class OigCloudSensor(CoordinatorEntity, SensorEntity):
    """Base implementation of OIG Cloud sensor."""

    def __init__(self, coordinator: OigCloudDataUpdateCoordinator, sensor_type: str) -> None:
        """Initialize the sensor."""
        if not isinstance(sensor_type, str):
            raise TypeError("sensor_type must be a string")

        super().__init__(coordinator)
        self.coordinator: OigCloudDataUpdateCoordinator = coordinator
        self._sensor_type: str = sensor_type
        self._attr_state_class = SENSOR_TYPES[sensor_type].get("state_class")
        self._node_id: Optional[str] = SENSOR_TYPES[sensor_type].get("node_id")
        self._node_key: Optional[str] = SENSOR_TYPES[sensor_type].get("node_key")
        self._box_id: str = list(self.coordinator.data.keys())[0]
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created sensor {self.entity_id}")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # First check if coordinator has data and last update was successful
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return False
            
        # For sensors that need to access nodes
        if self._node_id is not None:
            # Check if the node exists in the data
            box_id = list(self.coordinator.data.keys())[0]
            if self._node_id not in self.coordinator.data[box_id]:
                return False
                
        return True

    @property
    def entity_category(self) -> Optional[str]:
        """Return the entity category of the sensor."""
        return SENSOR_TYPES[self._sensor_type].get("entity_category")

    @property
    def unit_of_measurement(self) -> Optional[str]:
        """Return the unit of measurement."""
        return SENSOR_TYPES[self._sensor_type].get("unit_of_measurement")

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information about the device."""
        data: Dict[str, Any] = self.coordinator.data
        box_id = list(data.keys())[0]
        pv_data: Dict[str, Any] = data[box_id]
        
        # Check if this is a Queen model
        is_queen: bool = bool(pv_data.get("queen", False))
        model_name: str = f"{DEFAULT_NAME} {'Queen' if is_queen else 'Home'}"

        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{model_name} {self._box_id}",
            manufacturer="OIG",
            model=model_name,
            sw_version=pv_data.get("box_prms", {}).get("sw", None),
        )

    @property
    def should_poll(self) -> bool:
        """Return False as entity should not poll on its own."""
        return False

    @property
    def options(self) -> Optional[List[str]]:
        """Return the options for this sensor if applicable."""
        return SENSOR_TYPES[self._sensor_type].get("options")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return SENSOR_TYPES[self._sensor_type].get("name_cs", SENSOR_TYPES[self._sensor_type]["name"])
        return SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return SENSOR_TYPES[self._sensor_type].get("device_class")

    @property
    def state_class(self) -> Optional[str]:
        """Return the state class of the sensor."""
        return SENSOR_TYPES[self._sensor_type].get("state_class")
        
    def get_node_value(self) -> Any:
        """Safely extract node value from coordinator data."""
        if not self.coordinator.data or not self._node_id or not self._node_key:
            return None
            
        box_id = list(self.coordinator.data.keys())[0]
        try:
            return self.coordinator.data[box_id][self._node_id][self._node_key]
        except (KeyError, TypeError):
            _LOGGER.debug(
                f"Could not find {self._node_id}.{self._node_key} in data for sensor {self.entity_id}"
            )
            return None
