import logging
from datetime import timedelta, datetime
from typing import List, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .oig_cloud_coordinator import OigCloudCoordinator
from .oig_cloud_data_sensor import OigCloudDataSensor
from .oig_cloud_computed_sensor import OigCloudComputedSensor
from .oig_cloud_statistics import OigCloudStatisticsSensor
from .oig_cloud_solar_forecast import OigCloudSolarForecastSensor
from .sensor_types import SENSOR_TYPES
from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS
from .const import DOMAIN
from .config_flow import (
    CONF_STANDARD_SCAN_INTERVAL,
    CONF_EXTENDED_SCAN_INTERVAL,
    CONF_SOLAR_FORECAST_ENABLED,
)

_LOGGER = logging.getLogger(__name__)


class OigShieldQueueSensor(SensorEntity):
    def __init__(self, hass, shield, config_entry_id):
        self._hass = hass
        self._shield = shield
        self._attr_name = "OIG Shield Service Queue"
        self._attr_icon = "mdi:shield-sync"
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = "oig_shield_service_queue"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"shield-{config_entry_id}")},
            "name": "OIG Cloud Shield",
            "manufacturer": "OIG",
            "model": "Shield",
        }

    @property
    def state(self):
        return len(self._shield.queue)

    @property
    def extra_state_attributes(self):
        now = datetime.now().isoformat()
        enriched = []
        for idx, q in enumerate(self._shield.queue):
            service, params, *_ = q
            added = self._shield.queue_metadata.get(
                (service, str(params)), "neznámý čas"
            )
            enriched.append(
                {
                    "position": idx + 1,
                    "service": service,
                    "params": params,
                    "added_at": added,
                }
            )
        return {
            "running_service": self._shield.running or "žádná",
            "queue_count": len(self._shield.queue),
            "last_checked": now,
            "queued_services": enriched,
        }


async def async_setup_entry(
    hass: Any, config_entry: Any, async_add_entities: Any
) -> None:
    _LOGGER.debug("Setting up OIG Cloud sensors")

    api_data = hass.data[DOMAIN][config_entry.entry_id]
    api = api_data["api"]

    standard_interval = config_entry.options.get(CONF_STANDARD_SCAN_INTERVAL, 30)
    extended_interval = config_entry.options.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

    coordinator = OigCloudCoordinator(
        hass,
        api,
        standard_interval_seconds=standard_interval,
        extended_interval_seconds=extended_interval,
    )

    await coordinator.async_config_entry_first_refresh()
    _register_entities(async_add_entities, coordinator, config_entry)

    # Add diagnostic queue sensor
    shield = hass.data[DOMAIN].get("shield")
    if shield:
        async_add_entities([OigShieldQueueSensor(hass, shield, config_entry.entry_id)])
    else:
        _LOGGER.warning(
            "OIG Shield není inicializován – senzor fronty nebude vytvořen."
        )


# Přidáme update listener pro celou entry
async def async_unload_entry(hass: Any, config_entry: Any) -> bool:
    """Unload a config entry."""
    return True


async def async_options_updated(hass: Any, config_entry: Any) -> None:
    """Handle options update."""
    _LOGGER.info("OIG Cloud options updated, reloading sensors if needed")
    # Solar forecast senzor má vlastní listener, ostatní senzory se restartují s coordinator


def _register_entities(
    async_add_entities: Any, coordinator: OigCloudCoordinator, config_entry: Any
) -> None:
    # Původní data senzory
    async_add_entities(
        OigCloudDataSensor(
            coordinator, sensor_type, extended=sensor_type.startswith("extended_")
        )
        for sensor_type in SENSOR_TYPES
        if (
            SENSOR_TYPES[sensor_type].get("node_id") is not None
            or sensor_type.startswith("extended_")
            or SENSOR_TYPES[sensor_type].get("entity_category") is not None
        )
    )

    # Původní computed senzory
    async_add_entities(
        OigCloudComputedSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if SENSOR_TYPES[sensor_type].get("node_id") is None
        and not sensor_type.startswith("extended_")
        and SENSOR_TYPES[sensor_type].get("entity_category") is None
    )

    # Nové statistické senzory
    _LOGGER.debug(f"Registering {len(SENSOR_TYPES_STATISTICS)} statistical sensors")
    async_add_entities(
        [
            OigCloudStatisticsSensor(coordinator, sensor_type)
            for sensor_type in SENSOR_TYPES_STATISTICS
            if sensor_type != "solar_forecast"  # Solar forecast má speciální handling
        ]
    )

    # Solar Forecast senzor (pokud je povolen)
    if config_entry.options.get(CONF_SOLAR_FORECAST_ENABLED, False):
        _LOGGER.debug("Registering Solar Forecast sensor")
        async_add_entities(
            [OigCloudSolarForecastSensor(coordinator, "solar_forecast", config_entry)]
        )
