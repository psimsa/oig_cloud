import voluptuous as vol

from opentelemetry import trace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .api.oig_cloud import OigCloud

MODES = {
    "Home 1": "0",
    "Home 2": "1",
    "Home 3": "2",
    "Home UPS": "3",
}

tracer = trace.get_tracer(__name__)


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    async def async_set_box_mode(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        client: OigCloud = hass.data[DOMAIN][entry.entry_id]
        mode = call.data.get("Mode")
        mode_value = MODES.get(mode)
        success = await client.set_box_mode(mode_value)

    async def async_set_grid_delivery(call):
        client: OigCloud = hass.data[DOMAIN][entry.entry_id]
        if client.box_id != "2205232120" or client.box_id != "2111232079":
            raise vol.Invalid("Tato funkce není momentálně dostupná.")

        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        accepted = call.data.get("Upozornění")
        if not accepted:
            raise vol.Invalid("Upozornění je třeba odsouhlasit")

        enabled = call.data.get("Enabled")
        await client.set_grid_delivery(enabled)

    hass.services.async_register(
        DOMAIN,
        "set_box_mode",
        async_set_box_mode,
        schema=vol.Schema(
            {
                vol.Required("Mode"): vol.In(
                    [
                        "Home 1",
                        "Home 2",
                        "Home 3",
                        "Home UPS",
                    ]
                ),
                "Acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_grid_delivery",
        async_set_grid_delivery,
        schema=vol.Schema(
            {
                vol.Required("Enabled"): bool,
                "Acknowledgement": vol.Boolean(1),
                "Upozornění": vol.Boolean(1),
            }
        ),
    )
