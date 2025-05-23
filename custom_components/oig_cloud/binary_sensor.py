import logging
from datetime import timedelta
from typing import Any, Dict, Optional, Awaitable, Coroutine

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, DEFAULT_NAME # CONF_STANDARD_SCAN_INTERVAL is not used directly
from .binary_sensor_types import BINARY_SENSOR_TYPES
from .api.oig_cloud_api import OigCloudApi, OigCloudData # OigCloudData for coordinator typing

_LOGGER = logging.getLogger(__name__)

# Define the type for the coordinator's data. It's a dictionary of box_id to OigCloudData.
# However, OigCloudApi.get_stats() was typed as Optional[Dict[str, Any]]
# Let's assume the structure from OigCloudData if it's relevant or stick to Dict[str, Any]
CoordinatorDataType = Optional[Dict[str, Any]] # Or more specific if OigCloudData is suitable e.g. Optional[Dict[str, OigCloudData]]


class OigCloudBinarySensor(CoordinatorEntity[DataUpdateCoordinator[CoordinatorDataType]], BinarySensorEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator[CoordinatorDataType],
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_type: str = sensor_type
        # Assuming BINARY_SENSOR_TYPES structure is consistent and provides these keys
        self._node_id: str = BINARY_SENSOR_TYPES[self._sensor_type]["node_id"]
        self._node_key: str = BINARY_SENSOR_TYPES[self._sensor_type]["node_key"]
        self._box_id: Optional[str] = None  # Box ID will be fetched in async_added_to_hass

    async def async_added_to_hass(self) -> Awaitable[None]: # Or Coroutine[Any, Any, None]
        await super().async_added_to_hass()
        if self.coordinator.data and isinstance(self.coordinator.data, dict):
            # Assuming the first key in the data is the box_id
            # This might need a more robust way to get box_id if multiple boxes can exist
            if list(self.coordinator.data.keys()):
                self._box_id = list(self.coordinator.data.keys())[0]
                _LOGGER.debug(f"Created binary sensor {self.name} with box_id {self._box_id}")
            else:
                _LOGGER.warning(f"No box_id found in coordinator data for binary sensor {self.name}")
        else:
            _LOGGER.warning(f"Coordinator data not available or not a dict for binary sensor {self.name} on add to HASS.")
        # Explicitly return None or ensure no return path returns a value for Awaitable[None]
        return None


    @property
    def name(self) -> str:
        language: str = getattr(self.hass.config, "language", "en") if self.hass else "en"
        # Assuming BINARY_SENSOR_TYPES structure is consistent
        if language == "cs" and "name_cs" in BINARY_SENSOR_TYPES[self._sensor_type]:
            return str(BINARY_SENSOR_TYPES[self._sensor_type]["name_cs"])
        return str(BINARY_SENSOR_TYPES[self._sensor_type]["name"])

    @property
    def unique_id(self) -> Optional[str]:
        if self._box_id:
            return f"oig_cloud_{self._box_id}_{self._sensor_type}"
        return None

    @property
    def device_class(self) -> Optional[BinarySensorDeviceClass]:
        # Values in BINARY_SENSOR_TYPES should correspond to BinarySensorDeviceClass members
        device_class_str = BINARY_SENSOR_TYPES[self._sensor_type].get("device_class")
        if device_class_str:
            try:
                return BinarySensorDeviceClass(device_class_str)
            except ValueError:
                _LOGGER.warning(f"Invalid device_class '{device_class_str}' for sensor {self.name}")
                return None
        return None


    @property
    def is_on(self) -> Optional[bool]:
        if not self.coordinator.data or not self._box_id or not isinstance(self.coordinator.data, dict):
            return None
        try:
            # Ensure self._box_id is a valid key and coordinator.data is a dict
            box_data: Optional[Dict[str, Any]] = self.coordinator.data.get(self._box_id)
            if not box_data or not isinstance(box_data, dict):
                _LOGGER.debug(f"Box data for {self._box_id} not found or not a dict in coordinator data.")
                return None

            # Ensure _node_id is a key in box_data and its value is a dict
            node_data: Optional[Dict[str, Any]] = box_data.get(self._node_id)
            if not node_data or not isinstance(node_data, dict):
                _LOGGER.debug(f"Node data for {self._node_id} not found or not a dict in box_data for {self.name}.")
                return None
            
            value: Any = node_data.get(self._node_key)
            if value is None:
                _LOGGER.debug(f"Value for {self._node_key} not found in node_data for {self.name}.")
                return None
            return bool(value)
        except KeyError as e:
            _LOGGER.error(f"KeyError accessing data for {self.unique_id}: {e} in {self.coordinator.data}")
            return None
        except Exception as e:
            _LOGGER.error(f"Error reading state for {self.unique_id}: {e}")
            return None

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        if not self._box_id or not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return None
        try:
            # Ensure self._box_id is a valid key
            box_data: Optional[Dict[str, Any]] = self.coordinator.data.get(self._box_id)
            if not box_data:
                _LOGGER.debug(f"Box data for {self._box_id} not found in coordinator data for device_info.")
                return None

            model_name_base: str = f"{DEFAULT_NAME} Home"
            # Ensure 'queen' key exists or provide a default
            is_queen: bool = bool(box_data.get("queen", False))
            if is_queen:
                model_name_base = f"{DEFAULT_NAME} Queen"
            
            device_name: str = f"{model_name_base} {self._box_id}"

            return DeviceInfo(
                identifiers={(DOMAIN, self._box_id)},
                name=device_name,
                manufacturer="OIG",
                model=model_name_base,
            )
        except Exception as e:
            _LOGGER.error(f"Error constructing device_info for {self.unique_id}: {e}")
            return None

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> Awaitable[None]: # Or Coroutine[Any, Any, None]
    _LOGGER.debug("Setting up OIG Cloud Binary Sensors")

    # Assuming DOMAIN and config_entry.entry_id are valid keys
    oig_data_domain: Dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    oig_entry_data: Dict[str, Any] = oig_data_domain.get(config_entry.entry_id, {})
    
    api: Optional[OigCloudApi] = oig_entry_data.get("api")
    if not api:
        _LOGGER.error("OigCloudApi not found in hass.data. Cannot set up binary sensors.")
        return None # Must return if api is not available

    # Get standard_scan_interval, default to 30 if not found or not an int
    standard_scan_interval_any: Any = oig_entry_data.get("standard_scan_interval", 30)
    if not isinstance(standard_scan_interval_any, int):
        _LOGGER.warning(f"standard_scan_interval is not an int ({standard_scan_interval_any}), defaulting to 30s.")
        standard_scan_interval: int = 30
    else:
        standard_scan_interval: int = standard_scan_interval_any


    async def update_data() -> CoordinatorDataType: # Matches api.get_stats()
        if api: # Check api is not None before calling
            return await api.get_stats()
        return None # Should not happen if check above is done

    coordinator: DataUpdateCoordinator[CoordinatorDataType] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="OIG Cloud Binary Sensor Coordinator",
        update_method=update_data,
        update_interval=timedelta(seconds=standard_scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    # Ensure BINARY_SENSOR_TYPES is a dict or iterable
    if isinstance(BINARY_SENSOR_TYPES, dict):
        sensors_to_add = [
            OigCloudBinarySensor(coordinator, sensor_type)
            for sensor_type in BINARY_SENSOR_TYPES
            # Add a check to ensure sensor_type is valid if necessary
            if sensor_type in BINARY_SENSOR_TYPES 
        ]
        if sensors_to_add:
            async_add_entities(sensors_to_add)
    else:
        _LOGGER.error(f"BINARY_SENSOR_TYPES is not a dictionary: {BINARY_SENSOR_TYPES}")


    _LOGGER.debug("Finished setting up OIG Cloud Binary Sensors")
    return None # Explicitly return None