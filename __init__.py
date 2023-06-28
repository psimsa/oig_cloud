from homeassistant import config_entries, core
from .const import CONF_NO_TELEMETRY, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from .api.oig_cloud import OigCloud
from .services import async_setup_entry_services


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
