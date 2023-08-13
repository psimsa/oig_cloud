import logging
import hashlib

from opentelemetry import trace


from homeassistant import config_entries, core
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi
from custom_components.oig_cloud.const import (
    CONF_NO_TELEMETRY,
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
)
from custom_components.oig_cloud.services import async_setup_entry_services
from custom_components.oig_cloud.shared.tracing import setup_tracing
from custom_components.oig_cloud.shared.logging import setup_otel_logging

from .api import oig_cloud_api


tracer = trace.get_tracer(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    """
    Set up the OIG Cloud component for a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry representing the OIG Cloud account.

    Returns:
        True if the setup was successful, else False.

    Raises:
        ConfigEntryNotReady: If an error occurred while setting up the component.
    """
    try:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]

        if entry.data.get(CONF_NO_TELEMETRY) is None:
            no_telemetry = False
        else:
            no_telemetry = entry.data[CONF_NO_TELEMETRY]

        if no_telemetry is False:
            email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
            hass_id = hashlib.sha256(hass.data["core.uuid"].encode("utf-8")).hexdigest()

            setup_tracing(email_hash, hass_id)
            api_logger = logging.getLogger(oig_cloud_api.__name__)
            api_logger.addHandler(setup_otel_logging(email_hash, hass_id))

            logger = logging.getLogger(__name__)
            logger.info(f"Account hash is {email_hash}")
            logger.info(f"Home Assistant ID is {hass_id}")

            # logging.getLogger(binary_sensor.__name__).addHandler(LOGGING_HANDLER)
            # logging.getLogger(sensor.__name__).addHandler(LOGGING_HANDLER)

        oig_api = OigCloudApi(username, password, no_telemetry, hass)

        await oig_api.authenticate()

        hass.data[DOMAIN][entry.entry_id] = oig_api

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "sensor")
        )

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "binary_sensor")
        )

        hass.async_create_task(async_setup_entry_services(hass, entry))

        return True
    except Exception as exception:
        logger = logging.getLogger(__name__)
        logger.error("Error initializing OIG Cloud: %s", exception)
        raise ConfigEntryNotReady(
            "Error initializing OIG Cloud. Will retry."
        ) from exception
