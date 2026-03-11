"""Base sensor for OIG Cloud integration."""

import logging
from typing import Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..core.coordinator import OigCloudCoordinator
from .sensor_runtime import OigCloudSensorRuntimeMixin
from .sensor_setup import get_sensor_definition, resolve_box_id

# Backwards-compatible alias for modules that still import _get_sensor_definition.
_get_sensor_definition = get_sensor_definition

_LOGGER = logging.getLogger(__name__)


class OigCloudSensor(OigCloudSensorRuntimeMixin, CoordinatorEntity, SensorEntity):
    """Base implementation of OIG Cloud sensor."""

    def __init__(self, coordinator: OigCloudCoordinator, sensor_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._sensor_type = sensor_type

        try:
            from ..sensor_types import SENSOR_TYPES

            self._sensor_config = SENSOR_TYPES.get(sensor_type, {})
        except ImportError:
            _LOGGER.warning("Could not import SENSOR_TYPES for %s", sensor_type)
            self._sensor_config = {}

        self._box_id = resolve_box_id(coordinator)
        if self._box_id == "unknown":
            _LOGGER.warning(
                "No valid box_id found for %s, using fallback 'unknown'", sensor_type
            )

        _LOGGER.debug(
            "Initialized sensor %s with box_id: %s", sensor_type, self._box_id
        )

        sensor_def = get_sensor_definition(sensor_type)

        if sensor_type.startswith("service_shield"):
            _LOGGER.warning(
                "🔍 ServiceShield %s definition: %s", sensor_type, sensor_def
            )

        self._attr_name = sensor_def.get("name", sensor_type)
        self._attr_native_unit_of_measurement = sensor_def.get(
            "unit"
        ) or sensor_def.get("unit_of_measurement")
        self._attr_icon = sensor_def.get("icon")
        self._attr_device_class = sensor_def.get("device_class")
        self._attr_state_class = sensor_def.get("state_class")
        self._node_id: Optional[str] = sensor_def.get("node_id")
        self._node_key: Optional[str] = sensor_def.get("node_key")

        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug("Created sensor %s", self.entity_id)
