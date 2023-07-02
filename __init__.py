from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from homeassistant import config_entries, core
from .api.oig_cloud import OigCloud
from .const import CONF_NO_TELEMETRY, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .release_const import COMPONENT_VERSION, SERVICE_NAME
from .services import async_setup_entry_services

resource = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": COMPONENT_VERSION,
        "service.namespace": "oig_cloud",
    }
)

provider = TracerProvider(resource=resource)

# processor = BatchSpanProcessor(
#     OTLPSpanExporter(
#         endpoint="https://otlp.eu01.nr-data.net",
#         insecure=False,
#         headers=[
#             (
#                 "api-key",
#                 "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
#             )
#         ],
#     )
# )

processor = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint="https://api.honeycomb.io",
        insecure=False,
        headers=[
            ("x-honeycomb-team", "hTnPGhWUrkAleVhDHsBZ7G")
        ],
    )
)

# processor = BatchSpanProcessor(
#     OTLPSpanExporter(
#         endpoint="https://otlp.telemetryhub.com:4317",
#         insecure=False,
#         headers={
#             "x-telemetryhub-key": "d3421efb-6e9a-40bf-9b01-fe8ac3c947d6:8722b4ba-d435-4dee-8987-c67d6636211a:3131394"
#         },
#     )
# )

trace.set_tracer_provider(provider)
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
        provider.add_span_processor(processor)

    oig_cloud = OigCloud(username, password, no_telemetry, hass)

    # Run the authenticate() method to get the token
    await oig_cloud.authenticate()

    # Store the authenticated instance for other platforms to use
    hass.data[DOMAIN][entry.entry_id] = oig_cloud

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "binary_sensor")
    )

    hass.async_create_task(async_setup_entry_services(hass, entry))

    return True
