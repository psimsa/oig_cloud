import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DEFAULT_NAME, DOMAIN
from .sensor_types import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


class OigCloudSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, sensor_type: str) -> None:
        if not isinstance(sensor_type, str):
            raise TypeError("sensor_type must be a string")

        super().__init__(coordinator)
        self.coordinator: DataUpdateCoordinator = coordinator
        self._sensor_type: str = sensor_type
        self._attr_state_class = SENSOR_TYPES[sensor_type]["state_class"]
        self._node_id: str = SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key: str = SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id: str = list(self.coordinator.data.keys())[0]
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created sensor {self.entity_id}")

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    async def async_update(self) -> None:
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()

    @property
    def entity_category(self) -> Optional[EntityCategory]:
        return SENSOR_TYPES[self._sensor_type].get("entity_category")

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return SENSOR_TYPES[self._sensor_type]["unit_of_measurement"]

    @property
    def unique_id(self) -> str:
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> DeviceInfo:
        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]
        model_name: str = f"{DEFAULT_NAME} Home"
 #       is_queen = pv_data["queen"]
 #       if is_queen:
 #           model_name = f"{DEFAULT_NAME} Queen"
 #       else:
 #           model_name = f"{DEFAULT_NAME} Home"

        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{model_name} {self._box_id}",
            manufacturer="OIG",
            model=model_name,
        )

    @property
    def should_poll(self) -> bool:
        # DataUpdateCoordinator handles polling
        return False

    @property
    def options(self) -> Optional[List[str]]:
        return SENSOR_TYPES[self._sensor_type].get("options")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return SENSOR_TYPES[self._sensor_type]["name_cs"]
        return SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self) -> Optional[str]:
        return SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def state_class(self) -> Optional[str]:
        """Return the state class of the sensor."""
        return SENSOR_TYPES[self._sensor_type]["state_class"]
