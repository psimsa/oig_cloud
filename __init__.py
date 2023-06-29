import hashlib

from .release_const import COMPONENT_VERSION, SERVICE_NAME
from homeassistant import config_entries, core
from .const import CONF_NO_TELEMETRY, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .api.oig_cloud import OigCloud
from .services import async_setup_entry_services

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint="https://otlp.eu01.nr-data.net",
        insecure=False,
        headers=[
            (
                "api-key",
                "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
            )
        ],
    )
)

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    with tracer.start_as_current_span("async_setup_entry") as span:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]

        span.set_attributes(
            {
                "email_hash": hashlib.md5(username.encode("utf-8")).hexdigest(),
                "service.version": COMPONENT_VERSION,
            }
        )

        if entry.data.get(CONF_NO_TELEMETRY) is None:
            no_telemetry = False
        else:
            no_telemetry = entry.data[CONF_NO_TELEMETRY]

        if no_telemetry is False:
            provider.add_span_processor(processor)

        oig_cloud = OigCloud(username, password, no_telemetry, hass)

        # Run the authenticate() method to get the token
        await oig_cloud.authenticate()

        # Store the authenticated instance for other platforms to use
        hass.data[DOMAIN][entry.entry_id] = oig_cloud

        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, "sensor")
        )

        hass.async_create_task(async_setup_entry_services(hass, entry))

        return True
