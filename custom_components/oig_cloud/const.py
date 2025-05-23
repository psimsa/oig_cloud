from typing import Final, List, Tuple

# Imports from .release_const are assumed to be Final in their source if needed.
# This refactoring focuses on constants defined directly in this file.
from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN: Final[str] = "oig_cloud"

CONF_USERNAME: Final[str] = "username"
CONF_PASSWORD: Final[str] = "password"
CONF_NO_TELEMETRY: Final[str] = "no_telemetry"
CONF_UPDATE_INTERVAL: Final[str] = "update_interval"
CONF_LOG_LEVEL: Final[str] = "log_level"

DEFAULT_NAME: Final[str] = "ČEZ Battery Box"
DEFAULT_UPDATE_INTERVAL: Final[int] = 60  # Update interval in seconds

# Nové konstanty pro scan intervaly (New constants for scan intervals)
CONF_STANDARD_SCAN_INTERVAL: Final[str] = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL: Final[str] = "extended_scan_interval"

OT_ENDPOINT: Final[str] = "https://otlp.eu01.nr-data.net"
OT_INSECURE: Final[bool] = False
# Explicitly typing the complex data structure for OT_HEADERS
OT_HEADERS: Final[List[Tuple[str, str]]] = [
    (
        "api-key",
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]