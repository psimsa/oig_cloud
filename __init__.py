from .oig_cloud import OigCloud
import asyncio

from homeassistant import config_entries, core

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD


async def async_setup(hass: core.HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    oig_cloud = OigCloud(username, password)

    # Run the authenticate() method to get the token
    await oig_cloud.authenticate()

    # Store the authenticated instance for other platforms to use
    hass.data[DOMAIN][entry.entry_id] = oig_cloud

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )

    return True
