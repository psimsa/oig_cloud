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
        acknowledged = call.data.get("acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_box_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = call.data.get("mode")
            mode_value = MODES.get(mode)
            success = await client.set_box_mode(mode_value)

    async def async_set_grid_delivery(call):
        acknowledged = call.data.get("acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        accepted = call.data.get("warning")
        if not accepted:
            raise vol.Invalid("Upozornění je třeba odsouhlasit")

        grid_mode = call.data.get("mode")
        limit = call.data.get("limit")

        if (grid_mode is None and limit is None) or (
            grid_mode is not None and limit is not None
        ):
            raise vol.Invalid(
                "Musí být nastaven právě jeden parametr (Režim nebo Limit)"
            )

        if limit is not None and (limit > 9999 or limit < 1):
            raise vol.Invalid("Limit musí být v rozmezí 1-9999")

        with tracer.start_as_current_span("async_set_grid_delivery"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            if grid_mode is not None:
                mode = GRID_DELIVERY.get(grid_mode)
                await client.set_grid_delivery(mode)

            if limit is not None:
                success = await client.set_grid_delivery_limit(int(limit))
                if not success:
                    raise vol.Invalid("Limit se nepodařilo nastavit.")

    async def async_set_boiler_mode(call):
        acknowledged = call.data.get("acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_boiler_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = call.data.get("mode")
            mode_value = BOILER_MODE.get(mode)
            success = await client.set_boiler_mode(mode_value)

    async def async_set_formating_mode(call):
        acknowledged = call.data.get("acknowledgement")
        limit = call.data.get("limit")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        if limit is not None and (limit > 100 or limit < 20):
            raise vol.Invalid("Limit musí být v rozmezí 20-100")

        with tracer.start_as_current_span("async_set_formating_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = call.data.get("mode")
            mode_value = FORMAT_BATTERY.get(mode)
            success = await client.set_formating_mode(limit)

    async def async_get_extended_stats(call):
        acknowledged = call.data.get("acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_get_extended_stats"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            name = call.data.get("name")
            from_date = call.data.get("from_date")
            to_date = call.data.get("to_date")
            result = await client.get_extended_stats(name, from_date, to_date)
            return result

    hass.services.async_register(
        DOMAIN,
        "set_box_mode",
        async_set_box_mode,
        schema=vol.Schema(
            {
                vol.Required("mode"): vol.In(
                    [
                        "Home 1",
                        "Home 2",
                        "Home 3",
                        "Home UPS",
                    ]
                ),
                "acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_grid_delivery",
        async_set_grid_delivery,
        schema=vol.Schema(
            {
                "mode": vol.In(
                    [
                        "Vypnuto / Off",
                        "Zapnuto / On",
                        "S omezením / Limited",
                    ]
                ),
                "limit": vol.Any(None, vol.Coerce(int)),
                "acknowledgement": vol.Boolean(1),
                "warning": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_boiler_mode",
        async_set_boiler_mode,
        schema=vol.Schema(
            {
                "mode": vol.In(
                    [
                        "CBB",
                        "Manual",
                    ]
                ),
                "acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_formating_mode",
        async_set_formating_mode,
        schema=vol.Schema(
            {
                "mode": vol.In(
                    [
                        "Nenabíjet",
                        "Nabíjet",
                    ]
                ),
                "limit": vol.Any(None, vol.Coerce(int)),
                "acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "get_extended_stats",
        async_get_extended_stats,
        schema=vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("from_date"): str,
                vol.Required("to_date"): str,
                "acknowledgement": vol.Boolean(1),
            }
        ),
    )
