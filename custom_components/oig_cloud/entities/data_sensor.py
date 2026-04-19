import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple, TypedDict, Union

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from ..core.local_mapper import SUPPORTED_DOMAINS, normalize_proxy_entity_id


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

_STATE_NOT_HANDLED = object()


if TYPE_CHECKING:

    class _DataSensorBase:
        coordinator: Any
        hass: Any
        entity_id: str

        def __init__(self, coordinator: Any) -> None: ...
        @property
        def available(self) -> bool: ...
        async def async_added_to_hass(self) -> None: ...
        async def async_will_remove_from_hass(self) -> None: ...
        async def async_get_last_state(self) -> Any: ...
        def async_write_ha_state(self) -> None: ...

else:
    from homeassistant.helpers.restore_state import RestoreEntity
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    class _DataSensorBase(CoordinatorEntity, SensorEntity, RestoreEntity):
        pass


class OigCloudDataSensor(_DataSensorBase):
    """Representation of an OIG Cloud sensor."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        extended: bool = False,
        notification: bool = False,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._extended = extended
        self._notification = notification
        self._last_state: Optional[Union[float, str]] = None  # Uložíme si poslední stav
        self._local_state_unsub: Optional[Callable[[], None]] = None
        self._data_source_unsub: Optional[Callable[[], None]] = None
        self._entry_id: Optional[str] = None
        self._restored_state: Optional[Any] = None

        # Načteme sensor config
        try:
            import sys

            sensor_types_key = "custom_components.oig_cloud.sensor_types"
            # Check if package attribute exists but sys.modules entry is missing
            # (happens when earlier tests pop sys.modules but leave package attribute)
            if sensor_types_key not in sys.modules:
                import custom_components.oig_cloud

                if hasattr(custom_components.oig_cloud, "sensor_types"):
                    # Re-sync the stale module object back into sys.modules
                    sys.modules[sensor_types_key] = (
                        custom_components.oig_cloud.sensor_types
                    )
            sensor_types = __import__(
                sensor_types_key, globals(), locals(), ["SENSOR_TYPES"], 0
            )
            self._sensor_config = sensor_types.SENSOR_TYPES.get(sensor_type, {})
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

        # Entity ID - KLÍČOVÉ: Tady se vytváří entity ID z sensor_type!
        self._box_id = self._resolve_box_id(coordinator)
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

    async def async_added_to_hass(self) -> None:
        """Register per-entity listener for local telemetry."""
        await super().async_added_to_hass()

        # Retain last-known value across HA restarts (acts like "retain" for sensors).
        try:
            last_state = await self.async_get_last_state()
            if last_state and last_state.state not in (
                None,
                "",
                "unknown",
                "unavailable",
            ):
                self._restored_state = self._coerce_number(last_state.state)
        except Exception:
            self._restored_state = None

        # Local telemetry mapping is handled centrally by DataSourceController
        # which keeps coordinator.data in a cloud-shaped format even in local mode.
        # Data sensors therefore never subscribe to `sensor.oig_local_*` directly.

    async def async_will_remove_from_hass(self) -> None:
        if self._local_state_unsub:
            try:
                self._local_state_unsub()
            except Exception as err:
                _LOGGER.debug(
                    "[%s] Failed to unsubscribe local state listener: %s",
                    self.entity_id,
                    err,
                )
            self._local_state_unsub = None
        if self._data_source_unsub:
            try:
                self._data_source_unsub()
            except Exception as err:
                _LOGGER.debug(
                    "[%s] Failed to unsubscribe data source listener: %s",
                    self.entity_id,
                    err,
                )
            self._data_source_unsub = None
        await super().async_will_remove_from_hass()

    def _resolve_box_id(self, coordinator: Any) -> str:
        # Centralized resolution (config entry → proxy sensor → coordinator numeric keys)
        try:
            from .base_sensor import resolve_box_id

            return resolve_box_id(coordinator)
        except Exception:
            return "unknown"

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> Any:
        """Return device info."""
        from ..const import DEFAULT_NAME, DOMAIN

        box_id = self._box_id
        if not box_id or box_id == "unknown":
            return None

        return DeviceInfo(
            identifiers={(DOMAIN, box_id)},
            name=f"{DEFAULT_NAME} {box_id}",
            manufacturer="OIG",
            model=DEFAULT_NAME,
        )

    @property
    def available(self) -> bool:
        """Return whether entity is available."""
        return super().available

    @property
    def should_poll(self) -> bool:
        # Všechny senzory používají coordinator - NEPOTŘEBUJEME polling
        return False

    async def async_update(self) -> None:
        # ODSTRANÍME - coordinator se stará o všechny aktualizace
        # Extended i běžné senzory se aktualizují automaticky přes coordinator
        pass

    @property
    def state(self) -> Any:  # noqa: C901
        """Return the state of the sensor."""
        try:
            notification_state = self._get_notification_state()
            if notification_state is not _STATE_NOT_HANDLED:
                return notification_state

            if self.coordinator.data is None:
                return self._fallback_value()

            data = self.coordinator.data
            if not data:
                return self._fallback_value()

            pv_data = data.get(self._box_id, {})

            # Extended logika
            try:
                from ..sensor_types import SENSOR_TYPES

                sensor_config = SENSOR_TYPES.get(self._sensor_type, {})
                if sensor_config.get("sensor_type_category") == "extended":
                    return self._get_extended_value_for_sensor()
            except ImportError:
                pass

            # Získáme raw hodnotu z parent
            raw_value = self.get_node_value()
            if raw_value is None:
                return self._fallback_value()

            special_state = self._get_special_state(raw_value, pv_data)
            if special_state is not _STATE_NOT_HANDLED:
                return special_state

            # Pro ostatní senzory vrátíme raw hodnotu přímo
            return raw_value

        except Exception as e:
            _LOGGER.error(
                f"Error getting state for {self.entity_id}: {e}", exc_info=True
            )
            return self._fallback_value()

    def _get_notification_state(self) -> Any:
        notification_manager = getattr(self.coordinator, "notification_manager", None)
        if self._sensor_type == "latest_notification":
            return self._get_latest_notification_state(notification_manager)

        handler = self._notification_handler()
        if handler is None:
            return _STATE_NOT_HANDLED

        method_name, args, missing_value = handler
        if notification_manager is None:
            self._log_missing_notification_manager(method_name)
            return missing_value

        return getattr(notification_manager, method_name)(*args)

    def _get_latest_notification_state(self, notification_manager: Any) -> Any:
        if notification_manager is None:
            if not getattr(self, "_warned_notification_manager_missing", False):
                self._warned_notification_manager_missing = True
                _LOGGER.debug(
                    "[%s] Notification manager not initialized yet",
                    self.entity_id,
                )
            return None
        return notification_manager.get_latest_notification_message()

    def _notification_handler(
        self,
    ) -> Optional[Tuple[str, Tuple[Any, ...], Any]]:
        if self._sensor_type == "bypass_status":
            return ("get_bypass_status", (), self._fallback_value())
        if self._sensor_type == "notification_count_error":
            return ("get_notification_count", ("error",), None)
        if self._sensor_type == "notification_count_warning":
            return ("get_notification_count", ("warning",), None)
        if self._sensor_type == "notification_count_unread":
            return ("get_unread_count", (), None)
        return None

    def _log_missing_notification_manager(self, method_name: str) -> None:
        if method_name == "get_bypass_status":
            _LOGGER.debug(
                "[%s] Notification manager is None for bypass status",
                self.entity_id,
            )

    def _get_special_state(self, raw_value: Any, pv_data: Dict[str, Any]) -> Any:
        if self._sensor_type == "box_prms_mode":
            return self._get_mode_name(raw_value, "cs")
        if self._sensor_type == "invertor_prms_to_grid":
            if isinstance(raw_value, (int, float, str)):
                return self._grid_mode(pv_data, raw_value, "cs")
            _LOGGER.warning(
                "[%s] Invalid raw_value type for grid mode: %s",
                self.entity_id,
                type(raw_value),
            )
            return None
        if "ssr" in self._sensor_type:
            return self._get_ssrmode_name(raw_value, "cs")
        if self._sensor_type == "boiler_manual_mode":
            return self._get_boiler_mode_name(raw_value, "cs")
        if self._sensor_type in {"boiler_is_use", "box_prms_crct", "box_prms_crcte"}:
            return self._get_on_off_name(raw_value, "cs")
        return _STATE_NOT_HANDLED

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        attributes = {}

        # Notification sensors - OPRAVA: Kontrola existence notification_manager
        if self._sensor_type == "latest_notification":
            notification_manager = getattr(
                self.coordinator, "notification_manager", None
            )
            if notification_manager is not None:
                latest = notification_manager.get_latest_notification()
                if latest:
                    attributes.update(
                        {
                            "notification_id": latest.id,
                            "notification_type": latest.type,
                            "timestamp": latest.timestamp.isoformat(),
                            "device_id": latest.device_id,
                            "severity": latest.severity,
                            "read": latest.read,
                        }
                    )

        elif self._sensor_type == "bypass_status":
            notification_manager = getattr(
                self.coordinator, "notification_manager", None
            )
            if notification_manager is not None:
                attributes["last_check"] = datetime.now().isoformat()

        elif self._sensor_type.startswith("notification_count_"):
            notification_manager = getattr(
                self.coordinator, "notification_manager", None
            )
            if notification_manager is not None:
                attributes.update(
                    {
                        "total_notifications": len(notification_manager._notifications),
                        "last_update": datetime.now().isoformat(),
                    }
                )

        # Společné atributy pro notifikační senzory
        attributes.update(
            {
                "sensor_category": "notification",
                "integration": "oig_cloud",
            }
        )

        return attributes

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
                power_raw = last_values[3]
                voltage_raw = last_values[0]
                if power_raw is None or voltage_raw is None:
                    return None
                power = float(power_raw)
                voltage = float(voltage_raw)
            elif sensor_type == "extended_fve_current_2":
                power_raw = last_values[4]
                voltage_raw = last_values[1]
                if power_raw is None or voltage_raw is None:
                    return None
                power = float(power_raw)
                voltage = float(voltage_raw)
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

    def _get_mode_name(self, node_value: int, language: str) -> str:
        """Convert box mode number to human-readable name."""
        modes = {
            0: "Home 1",
            1: "Home 2",
            2: "Home 3",
            3: "Home UPS",
        }
        return modes.get(node_value, _LANGS["unknown"][language])

    def _grid_mode(
        self, pv_data: Dict[str, Any], node_value: Any, language: str
    ) -> str:
        try:
            canonical = resolve_grid_delivery_live_state(pv_data)
            if canonical["mode"] != "unknown":
                return _canonical_mode_to_label(canonical["mode"], language)

            local_mode = self._get_local_grid_mode(node_value, language)
            if local_mode != _LANGS["unknown"][language]:
                return local_mode

            grid_enabled_raw, max_grid_feed_raw = self._extract_grid_inputs(pv_data)
            self._log_missing_grid_inputs(grid_enabled_raw, max_grid_feed_raw)
            return _LANGS["unknown"][language]

        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(f"[{self.entity_id}] Error determining grid mode: {e}")
            return _LANGS["unknown"][language]

    def _extract_grid_inputs(
        self, pv_data: Dict[str, Any]
    ) -> Tuple[Optional[Any], Optional[Any]]:
        box_prms = pv_data.get("box_prms", {}) or {}
        grid_enabled_raw = (
            box_prms.get("crcte", box_prms.get("crct"))
            if isinstance(box_prms, dict)
            else None
        )
        invertor_prm1 = pv_data.get("invertor_prm1", {}) or {}
        max_grid_feed_raw = (
            invertor_prm1.get("p_max_feed_grid")
            if isinstance(invertor_prm1, dict)
            else None
        )
        return grid_enabled_raw, max_grid_feed_raw

    def _log_missing_grid_inputs(
        self, grid_enabled_raw: Optional[Any], max_grid_feed_raw: Optional[Any]
    ) -> None:
        if grid_enabled_raw is None:
            _LOGGER.debug(
                "[%s] Missing box_prms.crcte/crct in data",
                self.entity_id,
            )
        if max_grid_feed_raw is None:
            _LOGGER.debug(
                "[%s] Missing invertor_prm1.p_max_feed_grid in data",
                self.entity_id,
            )

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

    def _find_local_entity_candidate(
        self, suffix: str, domains: Tuple[str, ...]
    ) -> Optional[str]:
        for prefix_fmt in (
            "{domain}.oig_local_{box_id}_{suffix}",
            "{domain}.{box_id}_{suffix}",
        ):
            for domain in domains:
                candidate = prefix_fmt.format(
                    domain=domain, box_id=self._box_id, suffix=suffix
                )
                if normalize_proxy_entity_id(candidate, self._box_id):
                    state = self.hass.states.get(candidate)
                    if state is not None:
                        return candidate
        return None

    def _get_local_entity_id_for_config(
        self, sensor_config: Dict[str, Any]
    ) -> Optional[str]:
        entity_id = sensor_config.get("local_entity_id")
        if entity_id:
            return entity_id

        suffix = sensor_config.get("local_entity_suffix")
        if suffix and self._box_id and self._box_id != "unknown":
            domains = sensor_config.get("local_entity_domains")
            if isinstance(domains, str):
                primary_domains = [domains]
            elif isinstance(domains, (list, tuple, set)):
                primary_domains = [d for d in domains if isinstance(d, str)]
            else:
                primary_domains = []
            if not primary_domains:
                primary_domains = list(SUPPORTED_DOMAINS)

            candidate = self._find_local_entity_candidate(
                suffix, tuple(primary_domains)
            )
            if candidate:
                return candidate

            # Fallback: proxy control entities append _cfg to the suffix.
            cfg_candidate = self._find_local_entity_candidate(
                f"{suffix}_cfg", SUPPORTED_DOMAINS
            )
            if cfg_candidate:
                return cfg_candidate
        return None

    def _coerce_number(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return value

    def _apply_local_value_map(self, value: Any, sensor_config: Dict[str, Any]) -> Any:
        if value is None:
            return None
        value_map = sensor_config.get("local_value_map")
        if isinstance(value, str) and isinstance(value_map, dict):
            key = value.strip().lower()
            if key in value_map:
                return value_map[key]
        return self._coerce_number(value)

    def _fallback_value(self) -> Optional[Any]:
        if self._last_state is not None:
            return self._last_state
        if self._restored_state is not None:
            return self._restored_state
        if self._sensor_config:
            if self._sensor_config.get("device_class") == SensorDeviceClass.ENERGY:
                return 0.0
        return None

    def _get_local_value(self) -> Optional[Any]:
        local_entity_id = self._get_local_entity_id_for_config(self._sensor_config)
        if not local_entity_id:
            return None
        st = self.hass.states.get(local_entity_id)
        if not st or st.state in (None, "unknown", "unavailable"):
            return None
        return self._apply_local_value_map(st.state, self._sensor_config)

    def _get_local_value_for_sensor_type(self, sensor_type: str) -> Optional[Any]:
        try:
            from ..sensor_types import SENSOR_TYPES

            cfg = SENSOR_TYPES.get(sensor_type)
            if not cfg:
                return None
            local_entity_id = self._get_local_entity_id_for_config(cfg)
            if not local_entity_id:
                return None
            st = self.hass.states.get(local_entity_id)
            if not st or st.state in (None, "unknown", "unavailable"):
                return None
            return self._apply_local_value_map(st.state, cfg)
        except Exception:
            return None

    def _get_local_grid_mode(self, node_value: Any, language: str) -> str:
        try:
            grid_enabled_crcte = self._get_local_value_for_sensor_type("box_prms_crcte")
            grid_enabled_crct = self._get_local_value_for_sensor_type("box_prms_crct")
            max_grid_feed_raw = self._get_local_value_for_sensor_type(
                "invertor_prm1_p_max_feed_grid"
            )

            box_prms: dict = {}
            if grid_enabled_crcte is not None:
                box_prms["crcte"] = grid_enabled_crcte
            if grid_enabled_crct is not None:
                box_prms["crct"] = grid_enabled_crct

            raw_values = {
                "box_prms": box_prms,
                "invertor_prm1": {"p_max_feed_grid": max_grid_feed_raw},
                "invertor_prms": {"to_grid": node_value},
            }

            canonical = resolve_grid_delivery_live_state(raw_values)
            return _canonical_mode_to_label(canonical["mode"], language)
        except Exception:
            return _LANGS["unknown"][language]

    def get_node_value(self) -> Optional[Any]:
        """Get value from coordinator data using node_id and node_key."""
        try:
            if not self.coordinator.data:
                return None

            data = self.coordinator.data
            box_data = data.get(self._box_id) if isinstance(data, dict) else None

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


class GridDeliveryLiveState(TypedDict):
    """Canonical grid-delivery live state."""

    mode: str
    limit: Optional[int]


def resolve_grid_delivery_live_state(raw_values: dict) -> GridDeliveryLiveState:
    """Resolve canonical grid-delivery live state from raw telemetry fields.

    This helper is pure (no entity instance required) and handles both
    King and Queen inverter semantics.

    King semantics:
      - grid_enabled (box_prms.crcte/crct) must be 1.
      - to_grid == 0  →  off.
      - to_grid == 1 and p_max_feed_grid >= 10000  →  on.
      - to_grid == 1 and p_max_feed_grid <= 9999   →  limited.

    Queen semantics:
      - to_grid == 0 and p_max_feed_grid == 0  →  off.
      - to_grid == 0 and p_max_feed_grid > 0   →  limited.
      - to_grid == 1                           →  on.

    Required fields:
      - box_prms.crcte or box_prms.crct
      - invertor_prm1.p_max_feed_grid
      - invertor_prms.to_grid

    Returns explicit ``unknown`` when any required field is missing or
    non-numeric.  Never coerces missing telemetry to ``off``.
    """
    box_prms = raw_values.get("box_prms", {}) or {}
    invertor_prm1 = raw_values.get("invertor_prm1", {}) or {}
    invertor_prms = raw_values.get("invertor_prms", {}) or {}

    grid_enabled_raw = (
        box_prms.get("crcte", box_prms.get("crct"))
        if isinstance(box_prms, dict)
        else None
    )
    max_grid_feed_raw = (
        invertor_prm1.get("p_max_feed_grid")
        if isinstance(invertor_prm1, dict)
        else None
    )
    to_grid_raw = (
        invertor_prms.get("to_grid")
        if isinstance(invertor_prms, dict)
        else None
    )

    if grid_enabled_raw is None or max_grid_feed_raw is None or to_grid_raw is None:
        return GridDeliveryLiveState(mode="unknown", limit=None)

    try:
        grid_enabled = int(grid_enabled_raw)
        to_grid = int(to_grid_raw)
        max_grid_feed = int(max_grid_feed_raw)
    except (ValueError, TypeError):
        return GridDeliveryLiveState(mode="unknown", limit=None)

    is_queen = "queen" in raw_values and bool(raw_values["queen"])

    if is_queen:
        if to_grid == 0 and max_grid_feed == 0:
            return GridDeliveryLiveState(mode="off", limit=0)
        if to_grid == 0 and max_grid_feed > 0:
            return GridDeliveryLiveState(mode="limited", limit=max_grid_feed)
        if to_grid == 1:
            return GridDeliveryLiveState(mode="on", limit=max_grid_feed)
        return GridDeliveryLiveState(mode="unknown", limit=None)

    # King semantics
    if grid_enabled == 0:
        return GridDeliveryLiveState(mode="off", limit=0)
    if to_grid == 0:
        return GridDeliveryLiveState(mode="off", limit=0)
    if to_grid == 1 and max_grid_feed >= 10000:
        return GridDeliveryLiveState(mode="on", limit=max_grid_feed)
    if to_grid == 1 and max_grid_feed <= 9999:
        return GridDeliveryLiveState(mode="limited", limit=max_grid_feed)

    return GridDeliveryLiveState(mode="unknown", limit=None)


def _canonical_mode_to_label(mode: str, language: str) -> str:
    return {
        "off": GridMode.OFF,
        "on": GridMode.ON,
        "limited": GridMode.LIMITED,
    }.get(mode, _LANGS["unknown"][language])
