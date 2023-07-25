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

BOILER_MODE = {"CBB": 0, "Manual": 1}

FORMAT_BATTERY = {"Nenabíjet": 0, "Nabíjet": 1}

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

        if (grid_mode is None and limit is None) or (
            grid_mode is not None and limit is not None
        ):
            raise vol.Invalid(
                "Musí být nastaven právě jeden parametr (Režim nebo Limit)"
            )

        if limit is not None and (limit > 9999 or limit < 1):
            raise vol.Invalid("Limit musí být v rozmezí 1-9999")

        with tracer.start_as_current_span("async_set_grid_delivery"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            if grid_mode is not None:
                mode = GRID_DELIVERY.get(grid_mode)
                await client.set_grid_delivery(mode)

            if limit is not None:
                success = await client.set_grid_delivery_limit(int(limit))
                if not success:
                    raise vol.Invalid("Limit se nepodařilo nastavit.")

    async def async_set_boiler_mode(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_boiler_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = MODES.get(mode)
            success = await client.set_boiler_mode(mode_value)

    async def async_set_formating_mode(call):
        acknowledged = call.data.get("Acknowledgement")
        limit = call.data.get("Limit")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_formating_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = MODES.get(mode)
            success = await client.set_formating_mode(mode_value)

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
                "Mode": vol.In(
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

    hass.services.async_register(
        DOMAIN,
        "set_boiler_mode",
        async_set_boiler_mode,
        schema=vol.Schema(
            {
                "Mode": vol.In(
                    [
                        "CBB",
                        "Manual",
                    ]
                ),
                "Acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_formating_mode",
        async_set_formating_mode,
        schema=vol.Schema(
            {
                "Mode": vol.In(
                    [
                        "Nenabíjet",
                        "Nabíjet",
                    ]
                ),
                "Limit": vol.Any(None, vol.Coerce(int)),
                "Acknowledgement": vol.Boolean(1),
            }
        ),
    )
