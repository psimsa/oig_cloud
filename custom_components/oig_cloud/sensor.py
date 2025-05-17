import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .oig_cloud_coordinator import OigCloudCoordinator
from .oig_cloud_data_sensor import OigCloudDataSensor
from .oig_cloud_computed_sensor import OigCloudComputedSensor
from .sensor_types import SENSOR_TYPES
from .const import DOMAIN
from .config_flow import CONF_STANDARD_SCAN_INTERVAL, CONF_EXTENDED_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Nastavení senzorů OIG Cloud při načtení integrace."""
    _LOGGER.debug("Setting up OIG Cloud sensors")

    # 🛠 Správně rozbalíme, protože v hass.data je dict
    api_data = hass.data[DOMAIN][config_entry.entry_id]
    api = api_data["api"]

    # Vytáhnout intervaly z options (nebo defaulty)
    standard_interval = config_entry.options.get(CONF_STANDARD_SCAN_INTERVAL, 30)
    extended_interval = config_entry.options.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

    _LOGGER.debug(
        f"Using standard_interval={standard_interval}s and extended_interval={extended_interval}s"
    )

    # Vytvořit koordinátor
    coordinator = OigCloudCoordinator(
        hass,
        api,
        standard_interval_seconds=standard_interval,
        extended_interval_seconds=extended_interval,
    )

    # První refresh
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("First data refresh completed, now registering entities")

    # Registrace senzorů
    _register_entities(async_add_entities, coordinator)

    _LOGGER.debug("OIG Cloud sensors setup done")


def _register_entities(async_add_entities, coordinator: OigCloudCoordinator):
    """Registrace všech entit."""

    async_add_entities(
        OigCloudDataSensor(
            coordinator, sensor_type, extended=sensor_type.startswith("extended_")
        )
        for sensor_type in SENSOR_TYPES
        if (
            SENSOR_TYPES[sensor_type].get("node_id") is not None
            or sensor_type.startswith("extended_")
            or SENSOR_TYPES[sensor_type].get("entity_category")
            is not None  # nově: diagnostické senzory z HTML
        )
    )

    async_add_entities(
        OigCloudComputedSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if SENSOR_TYPES[sensor_type].get("node_id") is None
        and not sensor_type.startswith("extended_")
        and SENSOR_TYPES[sensor_type].get("entity_category")
        is None  # zůstává pouze pro computed-only
    )
