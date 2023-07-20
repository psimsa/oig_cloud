import logging
import hashlib

from opentelemetry import trace

from .api import oig_cloud_api

from homeassistant import config_entries, core
from homeassistant.exceptions import ConfigEntryNotReady

from .api.oig_cloud_api import OigCloudApi
from .const import CONF_NO_TELEMETRY, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .services import async_setup_entry_services
from .shared.tracing import setup_tracing
from .shared.logging import setup_otel_logging

tracer = trace.get_tracer(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
        hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
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
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error initializing OIG Cloud: {e}")
        raise ConfigEntryNotReady(f"Error initializing OIG Cloud. Will retry.") from e
