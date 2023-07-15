import voluptuous as vol

from opentelemetry import trace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .api.oig_cloud_api import OigCloudApi

MODES = {
    "Home 1": "0",
    "Home 2": "1",
    "Home 3": "2",
    "Home UPS": "3",
}

GRID_DELIVERY = {"Vypnuto / Off": 0, "Zapnuto / On": 1, "S omezením / Limited": 2}

tracer = trace.get_tracer(__name__)


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    async def async_set_box_mode(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_box_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = MODES.get(mode)
            success = await client.set_box_mode(mode_value)

    async def async_set_grid_delivery(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        accepted = call.data.get("Upozornění")
        if not accepted:
            raise vol.Invalid("Upozornění je třeba odsouhlasit")

        grid_mode = call.data.get("Mode")
        limit = call.data.get("Limit")
        mode = GRID_DELIVERY.get(grid_mode)

        if mode == 2 and limit is None:
            raise vol.Invalid("Limit je třeba zadat")

        with tracer.start_as_current_span("async_set_grid_delivery"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            if mode == 2:
                limit = int(limit)
                success = await client.set_grid_delivery_limit(limit)
                if not success:
                    raise vol.Invalid("Limit se nepodařilo nastavit")
            await client.set_grid_delivery(mode)

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
                vol.Required("Mode"): vol.In(
                    [
                        "Vypnuto / Off",
                        "Zapnuto / On",
                        "S omezením / Limited",
                    ]
                ),
                "Limit": vol.Any(None, vol.Coerce(int)),
                "Acknowledgement": vol.Boolean(1),
                "Upozornění": vol.Boolean(1),
            }
        ),
    )
