import logging
from typing import Any, Dict, Optional, Union

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback


# Importujeme pouze GridMode bez zbytku shared modulu
class GridMode:
    """Grid mode constants to avoid import issues."""

    ON = "Zapnuto"
    OFF = "Vypnuto"
    LIMITED = "Omezeno"


_LOGGER = logging.getLogger(__name__)

_LANGS: Dict[str, Dict[str, str]] = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Off", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
    "Zapnuto/On": {"en": "On", "cs": "Zapnuto"},
    "Vypnuto/Off": {"en": "Off", "cs": "Vypnuto"},
}


class OigCloudDataSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self, coordinator: Any, sensor_type: str, extended: bool = False
    ) -> None:
        super().__init__(coordinator)
        self._extended = extended
        self._sensor_type = sensor_type
        self._last_state: Optional[Union[float, str]] = None  # Uložíme si poslední stav

        # Načteme sensor config
        try:
            from .sensor_types import SENSOR_TYPES

            self._sensor_config = SENSOR_TYPES.get(sensor_type, {})
        except ImportError:
            self._sensor_config = {}

        # Správná lokalizace názvů - preferujeme český název
        name_cs = self._sensor_config.get("name_cs")
        name_en = self._sensor_config.get("name")

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        self._attr_name = name_cs or name_en or sensor_type

        # Základní atributy
        self._attr_native_unit_of_measurement = self._sensor_config.get(
            "unit_of_measurement"
        )
        self._attr_icon = self._sensor_config.get("icon")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")

        # Přidání entity_category z konfigurace
        self._attr_entity_category = self._sensor_config.get("entity_category")

        # Entity ID - OPRAVA: bez _ext suffixu pro extended senzory
        if coordinator.data:
            self._box_id = list(coordinator.data.keys())[0]
            # Používáme sensor_type bez dalších úprav
            self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> Any:
        """Return device info."""
        from homeassistant.helpers.entity import DeviceInfo
        from .const import DOMAIN, DEFAULT_NAME

        if not self.coordinator.data:
            return None

        data = self.coordinator.data
        box_id = list(data.keys())[0]

        return DeviceInfo(
            identifiers={(DOMAIN, box_id)},
            name=f"{DEFAULT_NAME} {box_id}",
            manufacturer="OIG",
            model=DEFAULT_NAME,
        )

    @property
    def should_poll(self) -> bool:
        # Všechny senzory používají coordinator - NEPOTŘEBUJEME polling
        return False

    async def async_update(self) -> None:
        # ODSTRANÍME - coordinator se stará o všechny aktualizace
        # Extended i běžné senzory se aktualizují automaticky přes coordinator
        pass

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data is None:
                return None

            data = self.coordinator.data
            if not data:
                return None

            box_id = list(data.keys())[0]
            pv_data = data[box_id]

            # Extended logika
            try:
                from .sensor_types import SENSOR_TYPES

                sensor_config = SENSOR_TYPES.get(self._sensor_type, {})
                if sensor_config.get("sensor_type_category") == "extended":
                    return self._get_extended_value_for_sensor()
            except ImportError:
                pass

            # Získáme raw hodnotu z parent
            raw_value = self.get_node_value()
            if raw_value is None:
                return None

            # SPECIÁLNÍ ZPRACOVÁNÍ pro určité typy senzorů
            if self._sensor_type == "box_prms_mode":
                return self._get_mode_name(raw_value, "cs")
            elif self._sensor_type == "invertor_prms_to_grid":
                if isinstance(raw_value, (int, float, str)):
                    return self._grid_mode(pv_data, raw_value, "cs")
                else:
                    _LOGGER.warning(
                        f"[{self.entity_id}] Invalid raw_value type for grid mode: {type(raw_value)}"
                    )
                    return None
            elif "ssr" in self._sensor_type:
                return self._get_ssrmode_name(raw_value, "cs")
            elif self._sensor_type == "boiler_manual_mode":
                return self._get_boiler_mode_name(raw_value, "cs")
            elif self._sensor_type == "boiler_is_use":
                return self._get_on_off_name(raw_value, "cs")
            elif self._sensor_type == "box_prms_crct":
                return self._get_on_off_name(raw_value, "cs")

            # Pro ostatní senzory vrátíme raw hodnotu přímo
            return raw_value

        except Exception as e:
            _LOGGER.error(
                f"Error getting state for {self.entity_id}: {e}", exc_info=True
            )
            return None

    def _get_extended_value_for_sensor(self) -> Optional[float]:
        """Získá hodnotu pro extended senzor podle typu."""
        sensor_type = self._sensor_type

        # Mapování sensor_type na extended_key
        if "battery" in sensor_type:
            return self._get_extended_value("extended_batt", sensor_type)
        elif "fve" in sensor_type:
            if "current" in sensor_type:
                return self._compute_fve_current(sensor_type)
            else:
                return self._get_extended_value("extended_fve", sensor_type)
        elif "grid" in sensor_type:
            return self._get_extended_value("extended_grid", sensor_type)
        elif "load" in sensor_type:
            return self._get_extended_value("extended_load", sensor_type)

        return None

    def _get_extended_value(
        self, extended_key: str, sensor_type: str
    ) -> Optional[float]:
        """Extended data jsou na top level coordinator.data."""
        try:
            if not self.coordinator.data:
                return None

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

        except (KeyError, IndexError, TypeError) as e:
            _LOGGER.error(f"Error getting extended value for {sensor_type}: {e}")
            return None

    def _compute_fve_current(self, sensor_type: str) -> Optional[float]:
        """Extended data jsou na top level coordinator.data."""
        try:
            if not self.coordinator.data:
                return None

            extended_fve = self.coordinator.data.get("extended_fve")
            if not extended_fve or not extended_fve.get("items"):
                return 0.0

            last_values = extended_fve["items"][-1]["values"]

            if sensor_type == "extended_fve_current_1":
                # Index 3 = power_1, Index 0 = voltage_1
                power = float(last_values[3])  # extended_fve_power_1
                voltage = float(last_values[0])  # extended_fve_voltage_1
            elif sensor_type == "extended_fve_current_2":
                # Index 4 = power_2, Index 1 = voltage_2
                power = float(last_values[4])  # extended_fve_power_2
                voltage = float(last_values[1])  # extended_fve_voltage_2
            else:
                return None

            if voltage != 0:
                current = power / voltage
                _LOGGER.debug(
                    f"{sensor_type}: {current:.3f}A (P={power}W, U={voltage}V)"
                )
                return round(current, 3)
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError, IndexError) as e:
            _LOGGER.error(f"Error computing {sensor_type}: {e}", exc_info=True)
            return None

    def _get_mode_name(self, node_value: Any, language: str) -> str:
        if node_value == 0:
            return "Home 1"
        elif node_value == 1:
            return "Home 2"
        elif node_value == 2:
            return "Home 3"
        elif node_value == 3:
            return "Home UPS"
        return _LANGS["unknown"][language]

    def _grid_mode(
        self, pv_data: Dict[str, Any], node_value: Any, language: str
    ) -> str:
        try:
            # Bezpečné získání hodnot s proper error handling
            if "box_prms" not in pv_data or "crcte" not in pv_data["box_prms"]:
                _LOGGER.warning(f"[{self.entity_id}] Missing box_prms.crcte in data")
                return _LANGS["unknown"][language]

            if (
                "invertor_prm1" not in pv_data
                or "p_max_feed_grid" not in pv_data["invertor_prm1"]
            ):
                _LOGGER.warning(
                    f"[{self.entity_id}] Missing invertor_prm1.p_max_feed_grid in data"
                )
                return _LANGS["unknown"][language]

            grid_enabled = int(pv_data["box_prms"]["crcte"])
            to_grid = int(node_value) if node_value is not None else 0
            max_grid_feed = int(pv_data["invertor_prm1"]["p_max_feed_grid"])

            if "queen" in pv_data and bool(pv_data["queen"]):
                return self._grid_mode_queen(
                    grid_enabled, to_grid, max_grid_feed, language
                )
            return self._grid_mode_king(grid_enabled, to_grid, max_grid_feed, language)

        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(f"[{self.entity_id}] Error determining grid mode: {e}")
            return _LANGS["unknown"][language]

    def _grid_mode_queen(
        self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str
    ) -> str:
        if 0 == to_grid and 0 == max_grid_feed:
            return GridMode.OFF
        elif 0 == to_grid and 0 < max_grid_feed:
            return GridMode.LIMITED
        elif 1 == to_grid:
            return GridMode.ON
        return _LANGS["changing"][language]

    def _grid_mode_king(
        self, grid_enabled: int, to_grid: int, max_grid_feed: int, language: str
    ) -> str:
        if 0 == grid_enabled and 0 == to_grid:
            return GridMode.OFF
        elif 1 == grid_enabled and 1 == to_grid and 10000 == max_grid_feed:
            return GridMode.ON
        elif 1 == grid_enabled and 1 == to_grid and 9999 >= max_grid_feed:
            return GridMode.LIMITED
        return _LANGS["changing"][language]

    def _get_ssrmode_name(self, node_value: Any, language: str) -> str:
        if node_value == 0:
            return "Vypnuto/Off"
        elif node_value == 1:
            return "Zapnuto/On"
        return _LANGS["unknown"][language]

    def _get_boiler_mode_name(self, node_value: Any, language: str) -> str:
        if node_value == 0:
            return "CBB"
        elif node_value == 1:
            return "Manuální"
        return _LANGS["unknown"][language]

    def _get_on_off_name(self, node_value: Any, language: str) -> str:
        if node_value == 0:
            return _LANGS["off"][language]
        elif node_value == 1:
            return _LANGS["on"][language]
        return _LANGS["unknown"][language]

    def get_node_value(self) -> Optional[Any]:
        """Get value from coordinator data using node_id and node_key."""
        try:
            if not self.coordinator.data:
                return None

            data = self.coordinator.data
            box_data = list(data.values())[0] if data else None

            if not box_data:
                return None

            node_id = self._sensor_config.get("node_id")
            node_key = self._sensor_config.get("node_key")

            if not node_id or not node_key:
                return None

            if node_id in box_data:
                node_data = box_data[node_id]
                if node_key in node_data:
                    value = node_data[node_key]
                    # ODSTRANIT zbytečný debug
                    return value

            return None

        except (KeyError, TypeError, IndexError):
            return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data:
            # Uložíme si starou hodnotu PŘED aktualizací
            old_value = self._last_state

            # Aktualizujeme available status
            self._attr_available = True

            # Získáme novou hodnotu pomocí state property
            new_value = self.state

            # Uložíme si novou hodnotu pro příští porovnání
            self._last_state = new_value

            # Log value updates for debugging - vždy vypisuj obě hodnoty
            if old_value != new_value:
                _LOGGER.debug(
                    "[%s] Data updated: %s -> %s (sensor_type: %s)",
                    self.entity_id,
                    old_value,
                    new_value,
                    self._sensor_type,
                )
            else:
                _LOGGER.debug(
                    "[%s] Data unchanged, previous: %s, current: %s (sensor_type: %s)",
                    self.entity_id,
                    old_value,
                    new_value,
                    self._sensor_type,
                )

        else:
            self._attr_available = False
            _LOGGER.debug("[%s] No coordinator data available", self.entity_id)

        self.async_write_ha_state()
