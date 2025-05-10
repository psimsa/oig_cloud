from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN = "oig_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"

DEFAULT_NAME = "ČEZ Battery Box"

# Nové konstanty pro scan intervaly
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"

OT_ENDPOINT = "https://otlp.eu01.nr-data.net"
OT_INSECURE = False
OT_HEADERS = [
    (
        "api-key",
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]
