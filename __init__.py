import logging
from opentelemetry import trace

from .sensor import OigCloudSensor
from .binary_sensor import OigCloudBinarySensor
from .api import oig_cloud_api

from homeassistant import config_entries, core
from .api.oig_cloud_api import OigCloudApi
from .const import CONF_NO_TELEMETRY, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .services import async_setup_entry_services
from .shared.tracing import trace_provider, trace_processor
from .shared.logging import LOGGING_HANDLER

tracer = trace.get_tracer(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    if entry.data.get(CONF_NO_TELEMETRY) is None:
        no_telemetry = False
    else:
        no_telemetry = entry.data[CONF_NO_TELEMETRY]

    if no_telemetry is False:
        trace_provider.add_span_processor(trace_processor)
        logging.getLogger(oig_cloud_api.__name__).addHandler(LOGGING_HANDLER)
        # logging.getLogger(binary_sensor.__name__).addHandler(LOGGING_HANDLER)
        # logging.getLogger(sensor.__name__).addHandler(LOGGING_HANDLER)

    oig_api = OigCloudApi(username, password, no_telemetry, hass)

    # Run the authenticate() method to get the token
    await oig_api.authenticate()

    # Store the authenticated instance for other platforms to use
    hass.data[DOMAIN][entry.entry_id] = oig_api

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "binary_sensor")
    )

    hass.async_create_task(async_setup_entry_services(hass, entry))

    return True
