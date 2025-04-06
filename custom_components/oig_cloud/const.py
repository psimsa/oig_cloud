from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN = "oig_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_LOG_LEVEL = "log_level"

DEFAULT_NAME = "ČEZ Battery Box"
DEFAULT_UPDATE_INTERVAL = 60  # Update interval in seconds


OT_ENDPOINT = "https://otlp.eu01.nr-data.net"
OT_INSECURE = False
OT_HEADERS = [
    (
        "api-key",
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]
