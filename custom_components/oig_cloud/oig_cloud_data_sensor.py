"""Data sensor implementation for OIG Cloud integration."""
import logging
from typing import Any, Dict, Final, Optional, Union, cast

from .coordinator import OigCloudDataUpdateCoordinator
from .models import OigCloudDeviceData
from .oig_cloud_sensor import OigCloudSensor
from .shared.shared import GridMode

_LOGGER = logging.getLogger(__name__)

# Language translations for different states
_LANGS: Final[Dict[str, Dict[str, str]]] = {
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
    "Zapnuto/On": {
        "en": "On",
        "cs": "Zapnuto",
    },
    "Vypnuto/Off": {
        "en": "Off",
        "cs": "Vypnuto",
    },
}


class OigCloudDataSensor(OigCloudSensor):
    """Sensor that reads a value directly from the OIG Cloud API data."""

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Return the state of the sensor."""
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        
        # Use the helper method from the parent class to get the node value
        node_value = self.get_node_value()
        if node_value is None:
            return None
            
        language: str = self.hass.config.language
        
        # Process special cases
        if self._sensor_type == "box_prms_mode":
            return self._get_mode_name(node_value, language)

        if self._sensor_type == "invertor_prms_to_grid":
            try:
                box_id = list(self.coordinator.data.keys())[0]
                pv_data = self.coordinator.data[box_id]
                return self._grid_mode(pv_data, node_value, language)
            except (KeyError, IndexError) as e:
                _LOGGER.warning(f"Error processing grid mode: {e}")
                return _LANGS["unknown"][language]

        if self._sensor_type in ["boiler_ssr1", "boiler_ssr2", "boiler_ssr3", "boiler_manual_mode"]:
            return self._get_ssrmode_name(node_value, language)

        # Try to convert to float for numeric values
        try:
            return float(node_value)
        except (ValueError, TypeError):
            return node_value
        
    def _get_mode_name(self, node_value: int, language: str) -> str:
        """Convert box mode number to human-readable name."""
        if node_value == 0:
            return "Home 1"
        elif node_value == 1:
            return "Home 2"
        elif node_value == 2:
            return "Home 3"
        elif node_value == 3:
            return "Home UPS"
        return _LANGS["unknown"][language]
    
    def _grid_mode(self, pv_data: Dict[str, Any], node_value: Any, language: str) -> str:
        """Determine grid delivery mode based on multiple parameters."""
        try:
            # Get required parameters with safe fallbacks
            grid_enabled: int = pv_data.get("box_prms", {}).get("crcte", 0)
            to_grid: int = int(node_value) if node_value is not None else 0
            max_grid_feed: int = pv_data.get("invertor_prm1", {}).get("p_max_feed_grid", 0)
            
            # For typed data model (future usage)
            if isinstance(pv_data, OigCloudDeviceData):
                grid_enabled = pv_data.box_prms.crcte
                to_grid = pv_data.invertor_prms.to_grid
                max_grid_feed = pv_data.invertor_prm1.p_max_feed_grid

            # Different logic for queen/non-queen models
            if pv_data.get("queen", False):
                return self._grid_mode_queen(grid_enabled, to_grid, max_grid_feed, language)
            return self._grid_mode_king(grid_enabled, to_grid, max_grid_feed, language)
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            _LOGGER.warning(f"Error calculating grid mode: {e}")
            return _LANGS["unknown"][language]

    def _grid_mode_queen(self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str) -> str:
        """Determine grid mode for Queen models."""
        vypnuto = 0 == to_grid and 0 == max_grid_feed
        zapnuto = 1 == to_grid
        limited = 0 == to_grid and 0 < max_grid_feed

        if vypnuto:
            return GridMode.OFF.value
        elif limited:
            return GridMode.LIMITED.value
        elif zapnuto:
            return GridMode.ON.value
        return _LANGS["changing"][language]

    def _grid_mode_king(self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str) -> str:
        """Determine grid mode for King/regular models."""
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

    def _get_ssrmode_name(self, node_value: int, language: str) -> str:
        """Convert SSR mode number to human-readable name."""
        if node_value == 0:
            return "Vypnuto/Off"
        elif node_value == 1:
            return "Zapnuto/On"
        return _LANGS["unknown"][language]