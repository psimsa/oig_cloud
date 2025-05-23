import logging
from datetime import datetime # timedelta removed as unused
from typing import Any, Dict, List, Optional, Awaitable # Added List for enriched type

# from homeassistant.helpers.update_coordinator import DataUpdateCoordinator # Unused direct import
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo # Added DeviceInfo for typing
from homeassistant.core import HomeAssistant # For hass type
from homeassistant.config_entries import ConfigEntry # For config_entry type
from homeassistant.helpers.entity_platform import AddEntitiesCallback # For async_add_entities type

from .oig_cloud_coordinator import OigCloudCoordinator
from .oig_cloud_data_sensor import OigCloudDataSensor
from .oig_cloud_computed_sensor import OigCloudComputedSensor
from .sensor_types import SENSOR_TYPES # Assuming SENSOR_TYPES is Dict[str, Dict[str, Any]]
from .const import DOMAIN, CONF_STANDARD_SCAN_INTERVAL, CONF_EXTENDED_SCAN_INTERVAL
from .api.oig_cloud_api import OigCloudApi # For api type hint
# Assuming ServiceShield is the correct class name and location
from .service_shield import ServiceShield # For shield type hint

_LOGGER = logging.getLogger(__name__)


class OigShieldQueueSensor(SensorEntity):
    """Diagnostic sensor for OIG Shield service queue."""
    _attr_name = "OIG Shield Service Queue"
    _attr_icon = "mdi:shield-sync"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id = "oig_shield_service_queue" # Static unique ID for this singleton sensor

    def __init__(
        self, 
        hass: HomeAssistant, 
        shield: ServiceShield, 
        config_entry_id: str # Used to make device unique per config entry if needed
    ) -> None:
        """Initialize the OIG Shield Queue sensor."""
        self._hass: HomeAssistant = hass # Store hass instance if needed for other methods
        self._shield: ServiceShield = shield
        # Device info should use the DeviceInfo TypedDict
        self._attr_device_info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, f"shield-{config_entry_id}")}, # Unique per config entry
            name="OIG Cloud Shield",
            manufacturer="OIG",
            model="Shield",
        )

    @property
    def native_value(self) -> int: # Renamed from state
        """Return the current queue length."""
        return len(self._shield.queue)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes of the queue."""
        now_iso: str = datetime.now().isoformat()
        enriched_queue: List[Dict[str, Any]] = []
        for idx, q_item in enumerate(self._shield.queue):
            # Assuming q_item structure: (service_name, params_dict, maybe_other_elements...)
            service, params, *_ = q_item 
            added_at_str: str = self._shield.queue_metadata.get(
                (service, str(params)), "neznámý čas" # unknown time
            )
            enriched_queue.append(
                {
                    "position": idx + 1,
                    "service": service,
                    "params": params,
                    "added_at": added_at_str,
                }
            )
        return {
            "running_service": self._shield.running or "žádná", # none
            "queue_count": len(self._shield.queue),
            "last_checked": now_iso, # Use consistent naming if other places use last_updated
            "queued_services": enriched_queue,
        }


async def async_setup_entry(
    hass: HomeAssistant, 
    config_entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> Awaitable[None]: # Return type for async setup
    """Set up OIG Cloud sensors from a config entry."""
    _LOGGER.debug(f"Setting up OIG Cloud sensors for config entry {config_entry.entry_id}")

    # Assuming DOMAIN and config_entry.entry_id are valid and api_data exists
    # Add safety for data access
    domain_data: Optional[Dict[str, Any]] = hass.data.get(DOMAIN)
    if not domain_data:
        _LOGGER.error(f"Domain data for {DOMAIN} not found. Cannot set up sensors.")
        return None
        
    api_data: Optional[Dict[str, Any]] = domain_data.get(config_entry.entry_id)
    if not api_data or "api" not in api_data:
        _LOGGER.error(f"API data or API instance not found for entry {config_entry.entry_id}. Cannot set up sensors.")
        return None
        
    api: OigCloudApi = api_data["api"]

    standard_interval: int = config_entry.options.get(CONF_STANDARD_SCAN_INTERVAL, 30)
    extended_interval: int = config_entry.options.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

    coordinator: OigCloudCoordinator = OigCloudCoordinator(
        hass,
        api,
        standard_interval_seconds=standard_interval,
        extended_interval_seconds=extended_interval,
    )

    await coordinator.async_config_entry_first_refresh()
    _register_entities(async_add_entities, coordinator)

    # Add diagnostic queue sensor
    # Shield instance is expected to be in hass.data[DOMAIN]["shield"]
    shield: Optional[ServiceShield] = domain_data.get("shield")
    if shield:
        async_add_entities([OigShieldQueueSensor(hass, shield, config_entry.entry_id)])
    else:
        _LOGGER.warning(
            "OIG Shield (service_shield) instance not found in hass.data. "
            "OIG Shield Queue sensor will not be created."
        )
    return None # Explicitly return None


def _register_entities(
    async_add_entities: AddEntitiesCallback, 
    coordinator: OigCloudCoordinator
) -> None:
    """Register sensor entities based on SENSOR_TYPES."""
    data_sensors_to_add: List[OigCloudDataSensor] = []
    computed_sensors_to_add: List[OigCloudComputedSensor] = []

    # Assuming SENSOR_TYPES is Dict[str, Dict[str, Any]]
    for sensor_type, config in SENSOR_TYPES.items():
        # Ensure config is a dictionary
        if not isinstance(config, dict):
            _LOGGER.warning(f"Skipping sensor type {sensor_type} due to invalid config (not a dict).")
            continue

        is_extended_sensor = sensor_type.startswith("extended_")
        has_node_id = config.get("node_id") is not None
        # Condition from original code: entity_category is not None
        # This seems to imply that some sensors are defined only by having an entity_category
        # and no node_id, typically for computed sensors.
        has_entity_category_for_data_sensor = config.get("entity_category") is not None
        
        # Logic for OigCloudDataSensor (standard and extended data point sensors)
        if has_node_id or is_extended_sensor or (has_entity_category_for_data_sensor and not has_node_id and not is_extended_sensor):
             data_sensors_to_add.append(
                OigCloudDataSensor(coordinator, sensor_type, extended=is_extended_sensor)
            )
        # Logic for OigCloudComputedSensor (sensors that compute state without direct node_id)
        elif not has_node_id and not is_extended_sensor and not has_entity_category_for_data_sensor :
            computed_sensors_to_add.append(
                OigCloudComputedSensor(coordinator, sensor_type)
            )
        # else:
            # _LOGGER.debug(f"Sensor type {sensor_type} did not match criteria for Data or Computed sensor.")

    if data_sensors_to_add:
        async_add_entities(data_sensors_to_add)
    if computed_sensors_to_add:
        async_add_entities(computed_sensors_to_add)
    
    _LOGGER.debug(f"Registered {len(data_sensors_to_add)} data sensors and {len(computed_sensors_to_add)} computed sensors.")
