import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .const import (
    DEFAULT_NAME,
    DOMAIN,
)
from .binary_sensor_types import BINARY_SENSOR_TYPES
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

class OigCloudBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, sensor_type: str) -> None:
        super().__init__(coordinator)
        self.coordinator: DataUpdateCoordinator = coordinator
        self._sensor_type: str = sensor_type
        self._node_id: str = BINARY_SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key: str = BINARY_SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id: str = list(self.coordinator.data.keys())[0]
        self.entity_id = f"binary_sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created binary sensor {self.entity_id}")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        language: str = self.hass.config.language
        if language == "cs":
            return BINARY_SENSOR_TYPES[self._sensor_type]["name_cs"]
        return BINARY_SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self) -> Optional[str]:
        return BINARY_SENSOR_TYPES[self._sensor_type]["device_class"]

    @property
    def state(self) -> Optional[bool]:
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None

        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]

        node_value: Any = pv_data[self._node_id][self._node_key]

        val: bool = bool(node_value)

        return val

    @property
    def unique_id(self) -> str:
        return f"oig_cloud_{self._sensor_type}"

    @property
    def should_poll(self) -> bool:
        # DataUpdateCoordinator handles polling
        return False

    @property
    def device_info(self) -> DeviceInfo:
        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]
        is_queen: bool = pv_data["queen"]
        if is_queen:
            model_name: str = f"{DEFAULT_NAME} Queen"
        else:
            model_name = f"{DEFAULT_NAME} Home"

        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{model_name} {self._box_id}",
            manufacturer="OIG",
            model=model_name,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_update(self) -> None:
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    _LOGGER.debug("async_setup_entry")

    oig_cloud: OigCloudApi = hass.data[DOMAIN][config_entry.entry_id]

    async def update_data() -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        return await oig_cloud.get_stats()

    # We create a new DataUpdateCoordinator.
    coordinator: DataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="binary_sensor",
        update_method=update_data,
        update_interval=timedelta(seconds=60),
    )

    # Fetch initial data so we have data when entities subscribe.
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("First refresh done, will add entities")

    async_add_entities(
        OigCloudBinarySensor(coordinator, sensor_type) for sensor_type in BINARY_SENSOR_TYPES
    )
    _LOGGER.debug("async_setup_entry done")
