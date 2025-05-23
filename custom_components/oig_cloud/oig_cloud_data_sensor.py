import logging
from typing import Any, Dict, Optional, Union, Awaitable

from homeassistant.core import HomeAssistant # For self.hass
from homeassistant.components.sensor import SensorEntity # Base class for OigCloudSensor
# SensorDeviceClass and SensorStateClass might be used by base or SENSOR_TYPES
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass 
from homeassistant.helpers.entity import DeviceInfo, EntityCategory # For _attr_ definitions

# Import the specific coordinator
from .oig_cloud_coordinator import OigCloudCoordinator
from .oig_cloud_sensor import OigCloudSensor # This class inherits from OigCloudSensor
from .shared.shared import GridMode # Used in _grid_mode methods

# SENSOR_TYPES and its structure definition (e.g., OigSensorTypeDescription) would be imported here
# from .sensor_types import SENSOR_TYPES, OigSensorTypeDescription

_LOGGER = logging.getLogger(__name__)

# _LANGS definition is specific to this module for now, used for localizing some states
_LANGS: Dict[str, Dict[str, str]] = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Off", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
    "Zapnuto/On": {"en": "On", "cs": "Zapnuto"}, # Used by _get_ssrmode_name
    "Vypnuto/Off": {"en": "Off", "cs": "Vypnuto"}, # Used by _get_ssrmode_name
}

# Define CoordinatorDataType to match OigCloudCoordinator's data type
CoordinatorDataType = Dict[str, Any] # As per OigCloudCoordinator subtask

class OigCloudDataSensor(OigCloudSensor):
    """Sensor that retrieves its state from OIG Cloud coordinator data, possibly from extended data."""

    # _sensor_config, _node_id, _node_key, _box_id are assumed to be initialized
    # in the base class OigCloudSensor and correctly typed there.
    # Example types if they were to be declared here:
    # _sensor_config: Dict[str, Any] # Or OigSensorTypeDescription
    # _node_id: Optional[str]
    # _node_key: Optional[str]
    # _box_id: Optional[str]
    # _attr_name: Optional[str]
    # _attr_unique_id: Optional[str]
    # ... other _attr_ properties

    def __init__(
        self,
        coordinator: OigCloudCoordinator, # Use the specific coordinator
        sensor_type: str,
        extended: bool = False,
    ) -> None:
        """Initialize the data sensor."""
        super().__init__(coordinator, sensor_type)
        self._extended: bool = extended
        # self.hass is inherited from HomeAssistantEntity, typed as HomeAssistant

    @property
    def should_poll(self) -> bool:
        """Return True if the sensor requires polling, False otherwise."""
        # Extended sensors are updated by direct calls to async_write_ha_state
        # rather than relying on the coordinator's polling for all entities.
        # However, the coordinator itself polls. This property usually indicates
        # if HA should call async_update independently of coordinator.
        # If coordinator handles updates, this is typically False for CoordinatorEntity subclasses.
        # Given current async_update, this seems to be for a different update mechanism.
        return self._extended

    async def async_update(self) -> Awaitable[None]: # Type hint for async method
        """Update the sensor's state. Only called if should_poll is True."""
        # This method is called by HA if should_poll is True.
        # For extended sensors, this ensures their state is updated.
        # For non-extended (coordinator-driven) sensors, this method might not be strictly necessary
        # if OigCloudSensor (as a CoordinatorEntity subclass) handles updates.
        if self._extended:
            # This implies that extended sensors might not be CoordinatorEntity,
            # or they need an additional trigger for state writing.
            # If they are CoordinatorEntity, _handle_coordinator_update updates, then async_write_ha_state.
            _LOGGER.debug(f"[{self.entity_id}] Extended sensor async_update triggered, writing HA state.")
            self.async_write_ha_state()
        # For non-extended sensors, update is handled by the coordinator via _handle_coordinator_update
        return None # Explicitly return None

    @property
    def native_value(self) -> Optional[Any]: # Renamed from 'state'
        """Return the state of the sensor."""
        _LOGGER.debug(f"Getting native_value for {self.entity_id} (sensor_type: {self._sensor_type})")

        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None

        # Determine language for localized strings
        language: str = self.hass.config.language if self.hass else "en"

        # Handle extended sensors first
        if self._extended: # Direct attribute access is fine as it's set in __init__
            # Based on previous subtask, extended data is nested under keys like "extended_batt"
            # in the coordinator's main data dictionary.
            if self._sensor_type.startswith("extended_battery_"):
                return self._get_extended_value(self.coordinator.data.get("extended_batt"), self._sensor_type)
            elif self._sensor_type.startswith("extended_fve_"):
                return self._get_extended_value(self.coordinator.data.get("extended_fve"), self._sensor_type)
            elif self._sensor_type.startswith("extended_grid_"):
                return self._get_extended_value(self.coordinator.data.get("extended_grid"), self._sensor_type)
            elif self._sensor_type.startswith("extended_load_"):
                return self._get_extended_value(self.coordinator.data.get("extended_load"), self._sensor_type)
            else:
                _LOGGER.warning(f"[{self.entity_id}] Unknown extended sensor type: {self._sensor_type}")
                return None

        # Standard (non-extended) sensors
        # Use self._box_id (assumed to be set by OigCloudSensor base class) to get specific device data
        if not hasattr(self, "_box_id") or not self._box_id:
            _LOGGER.warning(f"[{self.entity_id}] _box_id is not set, cannot fetch standard sensor data.")
            return None
        
        pv_data: Optional[Dict[str, Any]] = self.coordinator.data.get(self._box_id)
        if not pv_data:
            _LOGGER.debug(f"[{self.entity_id}] No data for box_id {self._box_id} in coordinator data.")
            return None

        try:
            # _node_id and _node_key are assumed to be set by OigCloudSensor base class
            node_id: Optional[str] = getattr(self, "_node_id", None)
            node_key: Optional[str] = getattr(self, "_node_key", None)

            if node_id is None or node_key is None:
                _LOGGER.warning(f"[{self.entity_id}] Node ID or Key is not set for sensor type {self._sensor_type}.")
                return None

            node_data: Optional[Any] = pv_data.get(node_id)

            if node_data is None:
                _LOGGER.debug(f"[{self.entity_id}] Node '{node_id}' does not exist in pv_data.")
                return None

            # Handle cases where node_data might be a list (e.g., if API sometimes returns list for a node)
            if isinstance(node_data, list):
                if not node_data:
                    _LOGGER.debug(f"[{self.entity_id}] Node list '{node_id}' is empty.")
                    return None
                node_data = node_data[0] # Use the first item if it's a list

            if not isinstance(node_data, dict):
                _LOGGER.warning(f"[{self.entity_id}] Node data for '{node_id}' is not a dict: {type(node_data)}")
                return None

            node_value: Any = node_data.get(node_key)
            if node_value is None:
                _LOGGER.debug(f"[{self.entity_id}] Key '{node_key}' not found in node '{node_id}'.")
                return None

            # Sensor-specific value transformations
            if self._sensor_type == "box_prms_mode":
                return self._get_mode_name(node_value, language)
            if self._sensor_type == "invertor_prms_to_grid":
                return self._grid_mode(pv_data, node_value, language)
            if self._sensor_type in [
                "boiler_ssr1", "boiler_ssr2", "boiler_ssr3",
                "boiler_manual_mode", "box_prms_crct", "boiler_is_use",
            ]:
                return self._get_ssrmode_name(node_value, language)

            # Attempt to convert to float if possible, otherwise return as is
            try:
                return float(node_value)
            except (ValueError, TypeError):
                _LOGGER.debug(f"[{self.entity_id}] Value for {node_key} is not a float: {node_value}, returning as is.")
                return node_value # Return original value if not float (e.g., string)
        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error getting value for sensor {self._sensor_type}: {e}", exc_info=True
            )
            return None

    def _get_extended_value(self, extended_data_source: Optional[Dict[str, Any]], sensor_type: str) -> Optional[Any]:
        """Extract value from extended data source based on sensor type."""
        if not extended_data_source or not isinstance(extended_data_source, dict):
            _LOGGER.debug(f"[{self.entity_id}] Extended data source for {sensor_type} is missing or not a dict.")
            return None

        items: List[Dict[str, Any]] = extended_data_source.get("items", [])
        if not items:
            _LOGGER.debug(f"[{self.entity_id}] No 'items' in extended data for {sensor_type}.")
            return None

        # Assuming 'values' is a list within the last item
        last_item_values: Optional[List[Any]] = items[-1].get("values")
        if not isinstance(last_item_values, list):
            _LOGGER.debug(f"[{self.entity_id}] 'values' in last item is not a list for {sensor_type}.")
            return None
        
        # This mapping should ideally come from SENSOR_TYPES or a more structured config
        mapping: Dict[str, int] = {
            "extended_battery_voltage": 0, "extended_battery_current": 1,
            "extended_battery_capacity": 2, "extended_battery_temperature": 3,
            "extended_fve_voltage_1": 0, "extended_fve_voltage_2": 1,
            "extended_fve_current": 2, "extended_fve_power_1": 3, "extended_fve_power_2": 4,
            "extended_grid_voltage": 0, "extended_grid_power": 1,
            "extended_grid_consumption": 2, "extended_grid_delivery": 3,
            "extended_load_l1_power": 0, "extended_load_l2_power": 1, "extended_load_l3_power": 2,
        }

        index: Optional[int] = mapping.get(sensor_type)
        if index is None:
            _LOGGER.warning(f"[{self.entity_id}] Unknown extended sensor mapping for {sensor_type}")
            return None

        if index >= len(last_item_values):
            _LOGGER.warning(f"[{self.entity_id}] Index {index} out of range for extended values for {sensor_type} (len: {len(last_item_values)})")
            return None

        return last_item_values[index]

    def _get_mode_name(self, node_value: Any, language: str) -> str:
        """Convert mode numeric value to a human-readable name."""
        try:
            mode_val = int(node_value) # Ensure it's an int for comparison
            if mode_val == 0: return "Home 1"
            if mode_val == 1: return "Home 2"
            if mode_val == 2: return "Home 3"
            if mode_val == 3: return "Home UPS"
        except (ValueError, TypeError):
            _LOGGER.warning(f"[{self.entity_id}] Invalid mode value for _get_mode_name: {node_value}")
        return _LANGS.get("unknown", {}).get(language, "Unknown")


    def _grid_mode(self, pv_data: Dict[str, Any], node_value: Any, language: str) -> str:
        """Determine grid mode based on various parameters."""
        try:
            # Ensure all required sub-keys exist before trying to access them
            box_prms_data = pv_data.get("box_prms", {})
            invertor_prm1_data = pv_data.get("invertor_prm1", {})

            grid_enabled = int(box_prms_data.get("crcte", 0))
            to_grid = int(node_value) # node_value is invertor_prms_to_grid
            max_grid_feed = int(invertor_prm1_data.get("p_max_feed_grid", 0))
            
            is_queen = bool(pv_data.get("queen", False))

            if is_queen:
                return self._grid_mode_queen(grid_enabled, to_grid, max_grid_feed, language)
            return self._grid_mode_king(grid_enabled, to_grid, max_grid_feed, language)
        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.warning(f"[{self.entity_id}] Error determining grid mode: {e}", exc_info=True)
            return _LANGS.get("unknown", {}).get(language, "Unknown")


    def _grid_mode_queen(self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str) -> str:
        """Determine grid mode for 'Queen' type devices."""
        # grid_enabled seems unused for queen, based on original logic
        if to_grid == 0 and max_grid_feed == 0: return GridMode.OFF.value
        if to_grid == 0 and max_grid_feed > 0: return GridMode.LIMITED.value
        if to_grid == 1: return GridMode.ON.value
        return _LANGS.get("changing", {}).get(language, "Changing in progress")

    def _grid_mode_king(self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str) -> str:
        """Determine grid mode for 'King' type devices."""
        if grid_enabled == 0 and to_grid == 0: return GridMode.OFF.value
        if grid_enabled == 1 and to_grid == 1 and max_grid_feed == 10000: return GridMode.ON.value
        # Original logic: 9999 >= max_grid_feed. If max_grid_feed can be < 0, this needs care.
        # Assuming max_grid_feed is non-negative.
        if grid_enabled == 1 and to_grid == 1 and max_grid_feed <= 9999: return GridMode.LIMITED.value
        return _LANGS.get("changing", {}).get(language, "Changing in progress")

    def _get_ssrmode_name(self, node_value: Any, language: str) -> str:
        """Convert SSR mode numeric value to a human-readable name."""
        try:
            ssr_val = int(node_value)
            if ssr_val == 0: return _LANGS.get("Vypnuto/Off", {}).get(language, "Off")
            if ssr_val == 1: return _LANGS.get("Zapnuto/On", {}).get(language, "On")
        except (ValueError, TypeError):
             _LOGGER.warning(f"[{self.entity_id}] Invalid SSR mode value: {node_value}")
        return _LANGS.get("unknown", {}).get(language, "Unknown")
