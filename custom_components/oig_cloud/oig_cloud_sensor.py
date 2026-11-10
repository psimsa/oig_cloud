"""Base sensor for OIG Cloud integration."""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .device_link import entity_config_entry_id, via_main_device
from .oig_cloud_coordinator import OigCloudCoordinator

_LOGGER = logging.getLogger(__name__)


def resolve_box_id(coordinator: Any) -> str:
    """Resolve the real box_id/inverter_sn and ignore helper keys.

    Prefer values persisted in the config entry, but keep backward-compatible
    autodetekci:
    1) forced_box_id (pokud jsme už jednou zjistili)
    2) options/data box_id nebo inverter_sn
    3) číslo v title
    4) hodnoty z lokálních entit (oig_local)
    5) numerické klíče v coordinator.data
    """

    def _extract_digits(text: Any) -> Optional[str]:
        if not isinstance(text, str):
            return None
        import re

        m = re.search(r"(\\d{6,})", text)
        return m.group(1) if m else None

    def _is_valid(val: Any) -> bool:
        return isinstance(val, str) and val.isdigit()

    try:
        forced = getattr(coordinator, "forced_box_id", None)
        if _is_valid(forced):
            return forced

        entry = getattr(coordinator, "config_entry", None)
        if entry:
            # Použij nejdřív hodnoty uložené v config entry
            for key in ("box_id", "inverter_sn"):
                if hasattr(entry, "options"):
                    val = entry.options.get(key)
                    if _is_valid(val):
                        return val
                if hasattr(entry, "data"):
                    val = entry.data.get(key)
                    if _is_valid(val):
                        return val
            # Další pokus: číslo vyčtené z title (např. "ČEZ Battery Box Home 2206237016")
            from_title = _extract_digits(getattr(entry, "title", ""))
            if _is_valid(from_title):
                return from_title

        # Pokus z lokálních entit (oig_local proxy)
        hass = getattr(coordinator, "hass", None)
        if hass:
            try:
                # Přímý senzor s box_id
                state = hass.states.get(
                    "sensor.oig_local_oig_proxy_proxy_status_box_device_id"
                )
                if state and _is_valid(state.state):
                    return state.state
            except Exception:
                pass
            try:
                import re

                from homeassistant.helpers import entity_registry as er

                reg = er.async_get(hass)
                ids: set[str] = set()
                pat = re.compile(r"^sensor\\.oig_local_(\\d+)_")
                for ent in reg.entities.values():
                    m = pat.match(ent.entity_id)
                    if m:
                        ids.add(m.group(1))
                if len(ids) == 1:
                    return next(iter(ids))
            except Exception:
                pass

        # Fallback – zkusíme zjistit box_id z klíčů dat koordinátoru
        data = getattr(coordinator, "data", None)
        if isinstance(data, dict) and data:
            # Preferujeme numerické klíče (reálné box ID)
            numeric = next((str(k) for k in data.keys() if str(k).isdigit()), None)
            if numeric:
                return numeric
    except Exception:
        pass

    return "unknown"


def _get_sensor_definition(sensor_type: str) -> Dict[str, Any]:
    """Získání definice senzoru ze správného zdroje."""
    # Pouze hlavní SENSOR_TYPES - žádné výjimky
    try:
        from .sensor_types import SENSOR_TYPES

        if sensor_type in SENSOR_TYPES:
            definition = SENSOR_TYPES[sensor_type]
            # Normalizujeme klíče pro konzistenci
            if "unit_of_measurement" in definition and "unit" not in definition:
                definition["unit"] = definition["unit_of_measurement"]
            return definition
    except ImportError:
        pass

    # Fallback pro neznámé senzory - prostě chyba
    _LOGGER.error(f"Sensor type '{sensor_type}' not found in SENSOR_TYPES!")
    return {
        "name": sensor_type,
        "unit": None,
        "icon": "mdi:help",
        "device_class": None,
        "state_class": None,
        "sensor_type_category": "unknown",
    }


class OigCloudSensor(CoordinatorEntity, SensorEntity):
    """Base implementation of OIG Cloud sensor."""

    def __init__(self, coordinator: OigCloudCoordinator, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._sensor_type = sensor_type

        # Načtení konfigurace senzoru
        try:
            from .sensor_types import SENSOR_TYPES

            self._sensor_config = SENSOR_TYPES.get(sensor_type, {})
        except ImportError:
            _LOGGER.warning(f"Could not import SENSOR_TYPES for {sensor_type}")
            self._sensor_config = {}

        # OPRAVA: Bezpečné získání box_id s fallback
        self._box_id: str = resolve_box_id(coordinator)
        if self._box_id == "unknown":
            _LOGGER.warning(
                f"No valid box_id found for {sensor_type}, using fallback 'unknown'"
            )

        _LOGGER.debug(f"Initialized sensor {sensor_type} with box_id: {self._box_id}")

        sensor_def = _get_sensor_definition(sensor_type)

        # Debug - ukažme definici
        if sensor_type.startswith("service_shield"):
            _LOGGER.warning(f"🔍 ServiceShield {sensor_type} definition: {sensor_def}")

        self._attr_name = sensor_def.get("name", sensor_type)
        # Oprava: používáme "unit" pro obě varianty
        self._attr_native_unit_of_measurement = sensor_def.get(
            "unit"
        ) or sensor_def.get("unit_of_measurement")
        self._attr_icon = sensor_def.get("icon")
        self._attr_device_class = sensor_def.get("device_class")
        self._attr_state_class = sensor_def.get("state_class")
        self._node_id: Optional[str] = sensor_def.get("node_id")
        self._node_key: Optional[str] = sensor_def.get("node_key")

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
            box_id = self._box_id
            if not box_id or box_id == "unknown":
                return False
            box_data = (
                self.coordinator.data.get(box_id, {})
                if isinstance(self.coordinator.data, dict)
                else {}
            )
            if self._node_id not in box_data:
                return False

        return True

    @property
    def entity_category(self) -> Optional[str]:
        """Return the entity category of the sensor."""
        return _get_sensor_definition(self._sensor_type).get("entity_category")

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information about the device."""
        box_id = self._box_id
        data: Dict[str, Any] = self.coordinator.data or {}
        pv_data: Dict[str, Any] = data.get(box_id, {}) if isinstance(data, dict) else {}

        # Check if this is a Queen model
        is_queen: bool = bool(pv_data.get("queen", False))
        model_name: str = f"{DEFAULT_NAME} {'Queen' if is_queen else 'Home'}"

        # Určíme kategorii senzoru pro rozhodnutí o zařízení
        sensor_def = _get_sensor_definition(self._sensor_type)
        sensor_category = sensor_def.get("sensor_type_category")

        # Propojení s hlavním zařízením (via_device_id od HA 2026.8)
        via_link = via_main_device(
            self.hass, entity_config_entry_id(self), self._box_id
        )

        # ServiceShield senzory budou v separátním Shield zařízení
        if sensor_category == "shield":
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._box_id}_shield")},
                name=f"ServiceShield {self._box_id}",
                manufacturer="OIG",
                model="Shield",
                **via_link,
            )

        # Analytics & Predictions senzory budou v samostatném propojeném zařízení
        if sensor_category in ["statistics", "solar_forecast", "pricing"]:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._box_id}_analytics")},
                name=f"Analytics & Predictions {self._box_id}",
                manufacturer="OIG",
                model="Analytics Module",
                **via_link,
            )

        # Hlavní zařízení pro data, computed a extended senzory
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
        return _get_sensor_definition(self._sensor_type).get("options")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return _get_sensor_definition(self._sensor_type).get(
                "name_cs", _get_sensor_definition(self._sensor_type)["name"]
            )
        return _get_sensor_definition(self._sensor_type)["name"]

    @property
    def icon(self) -> Optional[str]:
        """Return the icon for the sensor."""
        return _get_sensor_definition(self._sensor_type).get("icon")

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return _get_sensor_definition(self._sensor_type).get("device_class")

    @property
    def state_class(self) -> Optional[str]:
        """Return the state class of the sensor."""
        return _get_sensor_definition(self._sensor_type).get("state_class")

    def get_node_value(self) -> Any:
        """Safely extract node value from coordinator data."""
        if not self.coordinator.data or not self._node_id or not self._node_key:
            return None

        box_id = self._box_id
        if not box_id or box_id == "unknown":
            return None
        try:
            data: Dict[str, Any] = (
                self.coordinator.data if isinstance(self.coordinator.data, dict) else {}
            )
            return data[box_id][self._node_id][self._node_key]
        except (KeyError, TypeError):
            _LOGGER.debug(
                f"Could not find {self._node_id}.{self._node_key} in data for sensor {self.entity_id}"
            )
            return None

    async def async_update(self) -> None:
        """Update the sensor."""
        await super().async_update()
        # Additional update logic for the sensor if needed
