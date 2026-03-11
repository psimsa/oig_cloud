"""Constants for the OIG Cloud integration."""

DOMAIN = "oig_cloud"

# Configuration constants
CONF_ENABLE_STATISTICS = "enable_statistics"
CONF_ENABLE_PRICING = "enable_pricing"  # Sjednoceno: pricing + spotové ceny
CONF_ENABLE_CHMU_WARNINGS = "enable_chmu_warnings"  # ČHMÚ meteorologická varování
CONF_SPOT_PRICES_UPDATE_INTERVAL = "spot_prices_update_interval"
OTE_SPOT_PRICE_CACHE_FILE = "oig_ote_spot_prices.json"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"
CONF_LOG_LEVEL = "log_level"
CONF_TIMEOUT = "timeout"

# Boiler Module constants
CONF_ENABLE_BOILER = "enable_boiler"
CONF_BOILER_VOLUME_L = "boiler_volume_l"
CONF_BOILER_TARGET_TEMP_C = "boiler_target_temp_c"
CONF_BOILER_COLD_INLET_TEMP_C = "boiler_cold_inlet_temp_c"
CONF_BOILER_TEMP_SENSOR_TOP = "boiler_temp_sensor_top"
CONF_BOILER_TEMP_SENSOR_BOTTOM = "boiler_temp_sensor_bottom"
CONF_BOILER_TEMP_SENSOR_POSITION = (
    "boiler_temp_sensor_position"  # NEW: Pozice při 1 teploměru
)
CONF_BOILER_STRATIFICATION_MODE = "boiler_stratification_mode"
CONF_BOILER_TWO_ZONE_SPLIT_RATIO = "boiler_two_zone_split_ratio"
CONF_BOILER_HEATER_POWER_KW_ENTITY = "boiler_heater_power_kw_entity"
CONF_BOILER_HEATER_SWITCH_ENTITY = "boiler_heater_switch_entity"
CONF_BOILER_ALT_HEATER_SWITCH_ENTITY = "boiler_alt_heater_switch_entity"
CONF_BOILER_HAS_ALTERNATIVE_HEATING = "boiler_has_alternative_heating"
CONF_BOILER_ALT_COST_KWH = "boiler_alt_cost_kwh"
CONF_BOILER_ALT_ENERGY_SENSOR = "boiler_alt_energy_sensor"  # NEW: Měřič alternativy
CONF_BOILER_SPOT_PRICE_SENSOR = "boiler_spot_price_sensor"
CONF_BOILER_DEADLINE_TIME = "boiler_deadline_time"
CONF_BOILER_PLANNING_HORIZON_HOURS = "boiler_planning_horizon_hours"
CONF_BOILER_PLAN_SLOT_MINUTES = "boiler_plan_slot_minutes"

# Auto Module constants
CONF_ENABLE_AUTO = "enable_auto"
CONF_AUTO_MODE_SWITCH = "auto_mode_switch_enabled"
# Backward-compatible option key used by older config flows/tests.
CONF_AUTO_MODE_PLAN = "auto_mode_plan"

# Battery Planning constants (BR-0.2)
CONF_THRESHOLD_CHEAP_CZK = "threshold_cheap_czk"  # Threshold for "cheap" electricity

# Default values
DEFAULT_UPDATE_INTERVAL = 20
DEFAULT_NAME = "ČEZ Battery Box"
DEFAULT_STANDARD_SCAN_INTERVAL = 30
DEFAULT_EXTENDED_SCAN_INTERVAL = 300
DEFAULT_THRESHOLD_CHEAP_CZK = 1.5  # Default 1.5 CZK/kWh

# Boiler defaults
DEFAULT_BOILER_TARGET_TEMP_C = 60.0
DEFAULT_BOILER_COLD_INLET_TEMP_C = 10.0
DEFAULT_BOILER_TEMP_SENSOR_POSITION = (
    "top"  # top | upper_quarter | middle | lower_quarter
)
DEFAULT_BOILER_STRATIFICATION_MODE = "two_zone"  # Changed from simple_avg
DEFAULT_BOILER_TWO_ZONE_SPLIT_RATIO = 0.5
DEFAULT_BOILER_HEATER_POWER_KW_ENTITY = "sensor.oig_2206237016_boiler_install_power"
DEFAULT_BOILER_DEADLINE_TIME = "20:00"
DEFAULT_BOILER_PLANNING_HORIZON_HOURS = 36
DEFAULT_BOILER_PLAN_SLOT_MINUTES = 15  # Changed from 30 to 15min intervals

# Energetic constant for water heating (kWh per liter per °C)
BOILER_ENERGY_CONSTANT_KWH_L_C = 0.001163  # ≈ 4.186 kJ/kg/°C / 3600

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
SERVICE_PLAN_BOILER_HEATING = "plan_boiler_heating"
SERVICE_APPLY_BOILER_PLAN = "apply_boiler_plan"
SERVICE_CANCEL_BOILER_PLAN = "cancel_boiler_plan"

# OpenTelemetry constants
OT_ENDPOINT = "https://log-api.eu.newrelic.com"
OT_HEADERS = [
    (
        "Api-Key",  # OPRAVA: Správný header pro New Relic
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]
OT_INSECURE = False

# CBB Modes (Battery Box Control Modes) per BR-1
HOME_I = 0  # Grid priority (normal operation)
HOME_II = 1  # Battery savings (grid import, no battery discharge)
HOME_III = 2  # Solar priority (FVE to battery first)
HOME_UPS = 3  # UPS mode (grid charging enabled)

CBB_MODE_NAMES = {
    HOME_I: "HOME I",
    HOME_II: "HOME II",
    HOME_III: "HOME III",
    HOME_UPS: "UPS",
}
