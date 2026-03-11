"""Runtime helpers for OIG Cloud sensors."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.helpers.entity import DeviceInfo

from ..const import DEFAULT_NAME, DOMAIN
from .sensor_setup import get_sensor_definition

_LOGGER = logging.getLogger(__name__)


class OigCloudSensorRuntimeMixin:
    """Runtime properties for OIG Cloud sensors."""

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return False

        if self._node_id is not None:
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
        return get_sensor_definition(self._sensor_type).get("entity_category")

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

        is_queen: bool = bool(pv_data.get("queen", False))
        model_name: str = f"{DEFAULT_NAME} {'Queen' if is_queen else 'Home'}"

        sensor_def = get_sensor_definition(self._sensor_type)
        sensor_category = sensor_def.get("sensor_type_category")

        if sensor_category == "shield":
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._box_id}_shield")},
                name=f"ServiceShield {self._box_id}",
                manufacturer="OIG",
                model="Shield",
                via_device=(DOMAIN, self._box_id),
            )

        if sensor_category in ["statistics", "solar_forecast", "pricing"]:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._box_id}_analytics")},
                name=f"Analytics & Predictions {self._box_id}",
                manufacturer="OIG",
                model="Analytics Module",
                via_device=(DOMAIN, self._box_id),
            )

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
        return get_sensor_definition(self._sensor_type).get("options")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return get_sensor_definition(self._sensor_type).get(
                "name_cs", get_sensor_definition(self._sensor_type)["name"]
            )
        return get_sensor_definition(self._sensor_type)["name"]

    @property
    def icon(self) -> Optional[str]:
        """Return the icon for the sensor."""
        return get_sensor_definition(self._sensor_type).get("icon")

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return get_sensor_definition(self._sensor_type).get("device_class")

    @property
    def state_class(self) -> Optional[str]:
        """Return the state class of the sensor."""
        return get_sensor_definition(self._sensor_type).get("state_class")

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
                "Could not find %s.%s in data for sensor %s",
                self._node_id,
                self._node_key,
                self.entity_id,
            )
            return None

    async def async_update(self) -> None:
        """Update the sensor."""
        await super().async_update()
