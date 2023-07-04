from opentelemetry.sdk.resources import Resource

from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN = "oig_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"

DEFAULT_NAME = "ČEZ Battery Box"

OT_RESOURCE = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": COMPONENT_VERSION,
        "service.namespace": "oig_cloud",
    }
)
OT_ENDPOINT = "https://otlp.eu01.nr-data.net"
OT_HEADERS = [
    (
        "api-key",
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]