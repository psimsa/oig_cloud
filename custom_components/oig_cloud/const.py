

DOMAIN = "oig_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NO_TELEMETRY = "no_telemetry"

DEFAULT_NAME = "ČEZ Battery Box"


OT_ENDPOINT = "https://otlp.eu01.nr-data.net"
OT_INSECURE = False
OT_HEADERS = [
    (
        "api-key",
        "eu01xxefc1a87820b35d1becb5efd5c5FFFFNRAL",
    )
]

OIG_BASE_URL = "https://www.oigpower.cz/cez/"
OIG_LOGIN_URL = "inc/php/scripts/Login.php"
OIG_GET_STATS_URL = "json.php"
OIG_SET_MODE_URL = "inc/php/scripts/Device.Set.Value.php"
OIG_SET_GRID_DELIVERY_URL = "inc/php/scripts/ToGrid.Toggle.php"
OIG_SET_BATT_FORMATTING_URL = "inc/php/scripts/Battery.Format.Save.php"
