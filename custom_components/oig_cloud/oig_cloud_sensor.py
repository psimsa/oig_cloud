"""Base sensor for OIG Cloud integration."""
import logging
from typing import Any, Dict, List, Optional, Union, Awaitable # cast removed as unused

from homeassistant.core import HomeAssistant, callback # Added HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass # Added Sensor enums
from homeassistant.const import EntityCategory # Enum for entity_category
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.slugify import slugify # For unique_id generation

from .const import DEFAULT_NAME, DOMAIN
# Assuming OigCloudCoordinator is the correct name from previous refactor
from .oig_cloud_coordinator import OigCloudCoordinator 
# OigCloudData is not directly used here, but implies coordinator data structure
# from .models import OigCloudData 
from .sensor_types import SENSOR_TYPES # SENSOR_TYPES is Dict[str, Dict[str, Any]]

_LOGGER = logging.getLogger(__name__)

# Define a type alias for the sensor configuration dictionary for clarity
# Ideally, this would be a TypedDict if SENSOR_TYPES structure is strictly defined.
SensorConfigType = Dict[str, Any]


class OigCloudSensor(CoordinatorEntity[OigCloudCoordinator], SensorEntity):
    """Base implementation of OIG Cloud sensor."""

    _attr_has_entity_name = True # All sensors use the name from SENSOR_TYPES
    _attr_should_poll = False # Data is updated by the coordinator

    def __init__(self, coordinator: OigCloudCoordinator, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator) # Pass coordinator to CoordinatorEntity
        # self.coordinator is already set by CoordinatorEntity and typed
        
        if not isinstance(sensor_type, str): # Should not happen if setup is correct
            _LOGGER.error(f"Sensor type must be a string, got {type(sensor_type)}")
            # This situation should ideally be prevented by the setup logic.
            # Raising an error here might stop HA from starting other parts.
            # For now, log an error and try to proceed gracefully or raise specific error.
            raise TypeError(f"Sensor type must be a string, got {type(sensor_type)}")

        self._sensor_type: str = sensor_type
        self._sensor_config: SensorConfigType = SENSOR_TYPES.get(self._sensor_type, {})

        if not self._sensor_config:
            _LOGGER.error(f"Sensor type '{self._sensor_type}' not found in SENSOR_TYPES. Entity will not be created correctly.")
            # Handle missing sensor configuration, perhaps by raising an error
            # or allowing the entity to be created in a disabled/unavailable state.
            # For now, let it proceed but log error. Some attributes might be None.
        
        self._node_id: Optional[str] = self._sensor_config.get("node_id")
        self._node_key: Optional[str] = self._sensor_config.get("node_key")
        
        # _box_id will be set in async_added_to_hass to ensure coordinator.data is available
        self._box_id: Optional[str] = None 
        
        # Initialize common attributes from SENSOR_TYPES
        self._attr_name = self._get_localized_name() # Name is set using property for localization
        # Unique ID will be set after _box_id is known
        self._attr_icon = self._sensor_config.get("icon")
        
        # Set device class, state class, entity category using enum members if possible
        device_class_str = self._sensor_config.get("device_class")
        if device_class_str:
            try:
                self._attr_device_class = SensorDeviceClass(device_class_str)
            except ValueError:
                _LOGGER.warning(f"Invalid device_class '{device_class_str}' for sensor {self._sensor_type}")
                self._attr_device_class = None
        else:
            self._attr_device_class = None

        state_class_str = self._sensor_config.get("state_class")
        if state_class_str:
            try:
                self._attr_state_class = SensorStateClass(state_class_str)
            except ValueError:
                _LOGGER.warning(f"Invalid state_class '{state_class_str}' for sensor {self._sensor_type}")
                self._attr_state_class = None
        else:
            self._attr_state_class = None
            
        entity_category_str = self._sensor_config.get("entity_category")
        if entity_category_str:
            try:
                self._attr_entity_category = EntityCategory(entity_category_str)
            except ValueError:
                _LOGGER.warning(f"Invalid entity_category '{entity_category_str}' for sensor {self._sensor_type}")
                self._attr_entity_category = None
        else:
            self._attr_entity_category = None # Or a default like DIAGNOSTIC if appropriate

        self._attr_native_unit_of_measurement = self._sensor_config.get("unit_of_measurement")

        # self.hass is HomeAssistant, inherited from Entity
        # self.entity_id is set by Home Assistant Core, do not set it directly.
        _LOGGER.debug(f"Sensor {self._sensor_type} initialized (pending box_id and unique_id)")

    async def async_added_to_hass(self) -> Awaitable[None]:
        """Handle entity which will be added."""
        await super().async_added_to_hass() # Call super for CoordinatorEntity
        if self.coordinator.data and isinstance(self.coordinator.data, dict) and self.coordinator.data.keys():
            # Assuming the first key in coordinator.data is the box_id.
            # This might need adjustment if multiple boxes are handled or if box_id comes from elsewhere.
            # Or, if coordinator.data contains a specific key for the main device.
            # For now, using the first key as in original code, but with checks.
            potential_box_ids = list(self.coordinator.data.keys())
            if potential_box_ids:
                self._box_id = potential_box_ids[0]
                self._attr_unique_id = slugify(f"oig_cloud_{self._box_id}_{self._sensor_type}")
                self._attr_device_info = self._get_device_info() # Now that _box_id is set
                _LOGGER.debug(f"Sensor {self.entity_id} (type: {self._sensor_type}, box: {self._box_id}) added to HASS and unique_id set.")
            else:
                _LOGGER.error(f"Cannot determine box_id for sensor {self._sensor_type} as coordinator data keys are empty.")
        else:
            _LOGGER.error(f"Cannot determine box_id for sensor {self._sensor_type} as coordinator data is not available at async_added_to_hass.")
        # Ensure an initial state update after being added, if data is already available
        if self.coordinator.data:
            self._handle_coordinator_update()
        return None


    @callback # Ensure this method is a callback if it modifies HA state
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # This method is called by CoordinatorEntity when the coordinator has new data.
        # Update device info if it can change (e.g., SW version)
        if self._box_id: # Ensure box_id is set before trying to update device_info
             self._attr_device_info = self._get_device_info()
        # native_value will be re-evaluated by SensorEntity due to state write
        self.async_write_ha_state()
        _LOGGER.debug(f"Sensor {self.entity_id} (type: {self._sensor_type}) updated state via coordinator.")

    def _get_localized_name(self) -> str:
        """Get localized name from SENSOR_TYPES."""
        # self.hass might not be fully available during early __init__ for language.
        # Default to English name if hass or language config is not available.
        language: str = "en"
        if self.hass: # Check if hass object is available
            language = self.hass.config.language
        
        default_name = self._sensor_config.get("name", self._sensor_type) # Fallback to sensor_type if "name" is missing
        if language == "cs":
            return self._sensor_config.get("name_cs", default_name)
        return default_name
        
    def _get_device_info(self) -> Optional[DeviceInfo]:
        """Return information about the device, contingent on _box_id and coordinator data."""
        if not self._box_id or not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return None
        
        pv_data: Optional[Dict[str, Any]] = self.coordinator.data.get(self._box_id)
        if not pv_data or not isinstance(pv_data, dict):
            _LOGGER.debug(f"Device data for box_id {self._box_id} not found for device_info.")
            return None
        
        is_queen: bool = bool(pv_data.get("queen", False))
        model_name_suffix: str = "Queen" if is_queen else "Home"
        model_name: str = f"{DEFAULT_NAME} {model_name_suffix}"
        
        # Using .get() for sw_version for safety
        box_prms_data = pv_data.get("box_prms", {})
        sw_version_val = box_prms_data.get("sw") if isinstance(box_prms_data, dict) else None

        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{model_name} {self._box_id}", # Full name for the device
            manufacturer="OIG", # Assuming fixed manufacturer
            model=model_name,
            sw_version=str(sw_version_val) if sw_version_val is not None else None,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success or not self.coordinator.data or not self._box_id:
            return False
            
        pv_data = self.coordinator.data.get(self._box_id)
        if not pv_data:
            return False # No data for this sensor's box_id

        if self._node_id is not None:
            node = pv_data.get(self._node_id)
            if node is None:
                return False # Required node is missing
            if self._node_key is not None and isinstance(node, dict):
                 if node.get(self._node_key) is None:
                     return False # Required key in node is missing
            elif self._node_key is not None and not isinstance(node, dict):
                 return False # Node is not a dict but key is expected
                
        return True

    # Properties directly mapping to _attr_ are handled by SensorEntity
    # Overriding name to handle localization if not using has_entity_name=False pattern
    @property
    def name(self) -> str: # Overrides default _attr_name based name generation
        """Return the name of the sensor."""
        return self._get_localized_name()

    # unique_id is now _attr_unique_id, set in async_added_to_hass
    # device_info is now _attr_device_info, set in async_added_to_hass
    # unit_of_measurement is now _attr_native_unit_of_measurement
    # entity_category is now _attr_entity_category
    # device_class is now _attr_device_class
    # state_class is now _attr_state_class

    @property
    def options(self) -> Optional[List[str]]: # Kept as property if it's dynamic or from SENSOR_TYPES
        """Return the options for this sensor if applicable (e.g., for select entities)."""
        return self._sensor_config.get("options")
        
    @property
    def native_value(self) -> Any: # Renamed from get_node_value and made a property
        """Return the state of the sensor."""
        if not self._box_id or not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] No box_id or coordinator data.")
            return None # Or an appropriate default/unknown state
            
        pv_data = self.coordinator.data.get(self._box_id)
        if not pv_data or not isinstance(pv_data, dict):
            _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] No data for box_id {self._box_id}.")
            return None

        if not self._node_id or not self._node_key: # Should not happen if config is correct
            _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] Node ID or Key not configured.")
            return None
            
        try:
            # Navigate through the data structure pv_data -> node_id -> node_key
            node_data = pv_data.get(self._node_id)
            if node_data is None:
                _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] Node '{self._node_id}' not found.")
                return None
            
            # Handle if node_data itself is expected to be the value (e.g. simple sensor)
            # Or if it's a list, take the first element's relevant key (if applicable)
            # This part needs to be robust based on actual data structure from API for given node_id
            if isinstance(node_data, dict):
                value = node_data.get(self._node_key)
            elif isinstance(node_data, list) and node_data: # Example: if node_id points to a list of items
                # This specific handling for list might be too generic.
                # It depends on how SENSOR_TYPES defines access for list-based nodes.
                # For now, assuming if node_data is a list, the first item (if dict) is used.
                if isinstance(node_data[0], dict):
                    value = node_data[0].get(self._node_key)
                else: # Simple list of values, node_key might be an index (as string)
                    try:
                        idx = int(self._node_key)
                        if 0 <= idx < len(node_data):
                            value = node_data[idx]
                        else: value = None
                    except ValueError: value = None # node_key is not a valid index
            else: # node_data is a primitive value itself, node_key might be ignored or validated
                if self._node_key == "value": # Convention: if node_key is "value", use node_data directly
                    value = node_data
                else:
                    _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] Node '{self._node_id}' is not a dictionary or list, and node_key is '{self._node_key}'.")
                    value = None

            if value is None:
                _LOGGER.debug(f"[{self.unique_id or self._sensor_type}] Could not find value for {self._node_id}.{self._node_key}")
            return value # Return the raw value; HA will handle string conversion for state
        
        except (KeyError, TypeError, IndexError) as e: # Catch specific errors during data traversal
            _LOGGER.debug(
                f"[{self.unique_id or self._sensor_type}] Error accessing {self._node_id}.{self._node_key}: {e}"
            )
            return None
        except Exception as e: # Catch any other unexpected error
            _LOGGER.error(
                f"[{self.unique_id or self._sensor_type}] Unexpected error getting value for {self._node_id}.{self._node_key}: {e}",
                exc_info=True
            )
            return None
