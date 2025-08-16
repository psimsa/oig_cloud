"""Constants for the OIG Cloud integration."""

from .release_const import COMPONENT_VERSION, SERVICE_NAME

DOMAIN = "oig_cloud"

# Configuration constants
CONF_ENABLE_STATISTICS = "enable_statistics"
CONF_ENABLE_PRICING = "enable_pricing"
CONF_ENABLE_SPOT_PRICES = "enable_spot_prices"  # NOVÉ
CONF_SPOT_PRICES_UPDATE_INTERVAL = "spot_prices_update_interval"  # NOVÉ
CONF_UPDATE_INTERVAL = "update_interval"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"
CONF_LOG_LEVEL = "log_level"
CONF_TIMEOUT = "timeout"

# Default values
DEFAULT_UPDATE_INTERVAL = 20
DEFAULT_NAME = "ČEZ Battery Box"
DEFAULT_STANDARD_SCAN_INTERVAL = 30
DEFAULT_EXTENDED_SCAN_INTERVAL = 300

# Performance settings - VYPNUTÍ STATISTICKÝCH SENSORŮ
DISABLE_STATISTICS_SENSORS = True  # Vypnout statistické senzory kvůli výkonu

# Platforms
PLATFORMS = ["sensor"]

# Device info
MANUFACTURER = "OIG"
MODEL = "Battery Box"

# Error messages
ERROR_AUTH_FAILED = "Authentication failed"
ERROR_CANNOT_CONNECT = "Cannot connect"
ERROR_UNKNOWN = "Unknown error"

# Service names
SERVICE_FORCE_UPDATE = "force_update"
SERVICE_RESET_STATISTICS = "reset_statistics"

# OpenTelemetry constants
OT_ENDPOINT = "https://log-api.eu.newrelic.com"
OT_HEADERS = [
    (
        "Api-Key",  # OPRAVA: Správný header pro New Relic
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]
OT_INSECURE = False
