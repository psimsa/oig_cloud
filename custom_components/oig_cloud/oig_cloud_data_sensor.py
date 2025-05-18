import logging

from .oig_cloud_sensor import OigCloudSensor
from .shared.shared import GridMode

_LOGGER = logging.getLogger(__name__)

_LANGS = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Off", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
    "Zapnuto/On": {"en": "On", "cs": "Zapnuto"},
    "Vypnuto/Off": {"en": "Off", "cs": "Vypnuto"},
}


class OigCloudDataSensor(OigCloudSensor):
    def __init__(self, coordinator, sensor_type: str, extended: bool = False):
        super().__init__(coordinator, sensor_type)
        self._extended = extended

    @property
    def should_poll(self) -> bool:
        return self._extended  # extended senzory budou pravidelně dotazovány

    async def async_update(self):
        # Extended senzory budou při update kontrolovat změnu dat
        if self._extended:
            self.async_write_ha_state()

    @property
    def state(self):
        _LOGGER.debug(f"Getting state for {self.entity_id}")

        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None

        language = self.hass.config.language

        if getattr(self, "_extended", False):
            if self._sensor_type.startswith("extended_battery_"):
                return self._get_extended_value("extended_batt", self._sensor_type)
            elif self._sensor_type.startswith("extended_fve_"):
                return self._get_extended_value("extended_fve", self._sensor_type)
            elif self._sensor_type.startswith("extended_grid_"):
                return self._get_extended_value("extended_grid", self._sensor_type)
            elif self._sensor_type.startswith("extended_load_"):
                return self._get_extended_value("extended_load", self._sensor_type)
            else:
                _LOGGER.warning(f"Unknown extended sensor type: {self._sensor_type}")
                return None

        # fallback - standardní senzory
        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]

        try:
            node = pv_data.get(self._node_id)

            if node is None:
                _LOGGER.debug(f"[{self.entity_id}] Node '{self._node_id}' neexistuje")
                return None

            if isinstance(node, list):
                if not node:
                    _LOGGER.debug(
                        f"[{self.entity_id}] Node list '{self._node_id}' je prázdný"
                    )
                    return None
                node = node[0]

            if not isinstance(node, dict):
                _LOGGER.warning(f"[{self.entity_id}] Node '{self._node_id}' není dict")
                return None

            node_value = node.get(self._node_key)
            if node_value is None:
                _LOGGER.debug(
                    f"[{self.entity_id}] Klíč '{self._node_key}' nebyl nalezen v '{self._node_id}'"
                )
                return None

            if self._sensor_type == "box_prms_mode":
                return self._get_mode_name(node_value, language)

            if self._sensor_type == "invertor_prms_to_grid":
                return self._grid_mode(pv_data, node_value, language)

            if self._sensor_type in [
                "boiler_ssr1",
                "boiler_ssr2",
                "boiler_ssr3",
                "boiler_manual_mode",
                "box_prms_crct",
                "boiler_is_use",
            ]:
                return self._get_ssrmode_name(node_value, language)

            try:
                return float(node_value)
            except ValueError:
                return node_value
        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Chyba při získávání hodnoty: {e}", exc_info=True
            )
            return None

    def _get_extended_value(self, extended_key: str, sensor_type: str):
        extended_data = self.coordinator.data.get(extended_key)
        if not extended_data:
            return None

        items = extended_data.get("items", [])
        if not items:
            return None

        last_values = items[-1]["values"]

        mapping = {
            # battery
            "extended_battery_voltage": 0,
            "extended_battery_current": 1,
            "extended_battery_capacity": 2,
            "extended_battery_temperature": 3,
            # fve
            "extended_fve_voltage_1": 0,
            "extended_fve_voltage_2": 1,
            "extended_fve_current": 2,
            "extended_fve_power_1": 3,
            "extended_fve_power_2": 4,
            # grid
            "extended_grid_voltage": 0,
            "extended_grid_power": 1,
            "extended_grid_consumption": 2,
            "extended_grid_delivery": 3,
            # load
            "extended_load_l1_power": 0,
            "extended_load_l2_power": 1,
            "extended_load_l3_power": 2,
        }

        index = mapping.get(sensor_type)
        if index is None:
            _LOGGER.warning(f"Unknown extended sensor mapping for {sensor_type}")
            return None

        if index >= len(last_values):
            _LOGGER.warning(f"Index {index} out of range for extended values")
            return None

        return last_values[index]

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

    def _grid_mode(self, pv_data: dict, node_value, language):
        grid_enabled = int(pv_data["box_prms"]["crcte"])
        to_grid = int(node_value)
        max_grid_feed = int(pv_data["invertor_prm1"]["p_max_feed_grid"])

        if "queen" in pv_data and bool(pv_data["queen"]):
            return self._grid_mode_queen(grid_enabled, to_grid, max_grid_feed, language)
        return self._grid_mode_king(grid_enabled, to_grid, max_grid_feed, language)

    def _grid_mode_queen(self, grid_enabled, to_grid, max_grid_feed, language):
        if 0 == to_grid and 0 == max_grid_feed:
            return GridMode.OFF.value
        elif 0 == to_grid and 0 < max_grid_feed:
            return GridMode.LIMITED.value
        elif 1 == to_grid:
            return GridMode.ON.value
        return _LANGS["changing"][language]

    def _grid_mode_king(self, grid_enabled, to_grid, max_grid_feed, language):
        if 0 == grid_enabled and 0 == to_grid:
            return GridMode.OFF.value
        elif 1 == grid_enabled and 1 == to_grid and 10000 == max_grid_feed:
            return GridMode.ON.value
        elif 1 == grid_enabled and 1 == to_grid and 9999 >= max_grid_feed:
            return GridMode.LIMITED.value
        return _LANGS["changing"][language]

    def _get_ssrmode_name(self, node_value, language):
        if node_value == 0:
            return "Vypnuto/Off"
        elif node_value == 1:
            return "Zapnuto/On"
        return _LANGS["unknown"][language]
