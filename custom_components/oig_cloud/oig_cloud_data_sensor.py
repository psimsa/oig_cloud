import logging

from .oig_cloud_sensor import OigCloudSensor
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
                return self._get_mode_name(node_value, language)

            if self._sensor_type == "invertor_prms_to_grid":
                return self._grid_mode(pv_data, node_value, language)

            if self._sensor_type == "boiler_ssr1" or self._sensor_type == "boiler_ssr2" or self._sensor_type == "boiler_ssr3" or self._sensor_type == "boiler_manual_mode" :
                return self._get_ssrmode_name(node_value, language)

            try:
                return float(node_value)
            except ValueError:
                return node_value
        except KeyError:
            return None
        
    def _get_mode_name(self, node_value, language):
        if node_value == 0:
            return "Home 1"
        elif node_value == 1:
            return "Home 2"
        elif node_value == 2:
            return "Home 3"
        elif node_value == 3:
            return "Home UPS"
        return _LANGS["unknown"][language]
    
    def _grid_mode(self, pv_data, node_value, language):
        grid_enabled = int(pv_data["box_prms"]["crcte"])
        to_grid = int(node_value)
        max_grid_feed = int(pv_data["invertor_prm1"]["p_max_feed_grid"])

        if bool(pv_data["queen"]):
            return self._grid_mode_queen(grid_enabled, to_grid, max_grid_feed, language)
        return self._grid_mode_king(grid_enabled, to_grid, max_grid_feed, language)

    def _grid_mode_queen(self, grid_enabled, to_grid, max_grid_feed, language):
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

    def _grid_mode_king(self, grid_enabled, to_grid, max_grid_feed, language):
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

    def _get_ssrmode_name(self, node_value, language):
        if node_value == 0:
            return "Vypnuto/Off"
        elif node_value == 1:
            return "Zapnuto/On"
        return _LANGS["unknown"][language]