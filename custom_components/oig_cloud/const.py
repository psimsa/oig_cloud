"""Constants for the OIG Cloud integration."""

DOMAIN = "oig_cloud"

# Configuration constants
# CONF_API_URL = "api_url"  # Odebráno - zbytečné, API URL je hardcoded
CONF_UPDATE_INTERVAL = "update_interval"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"

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
OT_ENDPOINT = "https://otel.oigpower.cz:4317"
OT_HEADERS = {"x-api-key": "oig-cloud-telemetry"}
OT_INSECURE = False

# Základní definice pro sensor types - pokud není definována jinde
SENSOR_TYPES = {
    # Základní senzory pro ověření funkčnosti
    "battery_level": {
        "name": "Battery Level",
        "icon": "mdi:battery",
        "unit": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "value_template": lambda data: data.get("battery_level"),
    },
    "power_consumption": {
        "name": "Power Consumption",
        "icon": "mdi:lightning-bolt",
        "unit": "W",
        "device_class": "power",
        "state_class": "measurement",
        "value_template": lambda data: data.get("power_consumption"),
    },
    "energy_today": {
        "name": "Energy Today",
        "icon": "mdi:lightning-bolt-circle",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "value_template": lambda data: data.get("energy_today"),
    },
}

# Pokud existuje jiná definice, použij tu
try:
    from .sensor_definitions import SENSOR_TYPES as IMPORTED_SENSOR_TYPES

    SENSOR_TYPES.update(IMPORTED_SENSOR_TYPES)
except ImportError:
    pass
