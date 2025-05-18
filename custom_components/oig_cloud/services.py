import voluptuous as vol
from opentelemetry import trace
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    shield = hass.data[DOMAIN].get("shield")

    def wrap_with_shield(service_name, handler_func):
        async def wrapper(call):
            data = dict(call.data)
            await shield.intercept_service_call(
                DOMAIN,
                service_name,
                {
                    "params": data,
                    "entities": shield.extract_expected_entities(
                        f"{DOMAIN}.{service_name}", data
                    ),
                },
                handler_func,
                blocking=False,
                context=call.context,
            )

        return wrapper

    @callback
    async def real_call_set_box_mode(domain, service, service_data, blocking, context):
        with tracer.start_as_current_span("async_set_box_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = service_data.get("mode")
            mode_value = MODES.get(mode)
            await client.set_box_mode(mode_value)

    @callback
    async def real_call_set_grid_delivery(
        domain, service, service_data, blocking, context
    ):
        grid_mode = service_data.get("mode")
        limit = service_data.get("limit")

        if (grid_mode is None and limit is None) or (
            grid_mode is not None and limit is not None
        ):
            raise vol.Invalid(
                "Musí být nastaven právě jeden parametr (Režim nebo Limit)"
            )

        if limit is not None and (limit > 9999 or limit < 1):
            raise vol.Invalid("Limit musí být v rozmezí 1–9999")

        with tracer.start_as_current_span("async_set_grid_delivery"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            if grid_mode is not None:
                mode = GRID_DELIVERY.get(grid_mode)
                await client.set_grid_delivery(mode)
            if limit is not None:
                success = await client.set_grid_delivery_limit(int(limit))
                if not success:
                    raise vol.Invalid("Limit se nepodařilo nastavit.")

    @callback
    async def real_call_set_boiler_mode(
        domain, service, service_data, blocking, context
    ):
        with tracer.start_as_current_span("async_set_boiler_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = service_data.get("mode")
            mode_value = BOILER_MODE.get(mode)
            await client.set_boiler_mode(mode_value)

    @callback
    async def real_call_set_formating_mode(
        domain, service, service_data, blocking, context
    ):
        limit = service_data.get("limit")
        if limit is not None and (limit > 100 or limit < 20):
            raise vol.Invalid("Limit musí být v rozmezí 20–100")

        with tracer.start_as_current_span("async_set_formating_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]["api"]
            mode = service_data.get("mode")
            mode_value = FORMAT_BATTERY.get(mode)
            await client.set_formating_mode(limit)

    # Registrace služeb se schématem, které striktně vyžaduje potvrzení
    hass.services.async_register(
        DOMAIN,
        "set_box_mode",
        wrap_with_shield("set_box_mode", real_call_set_box_mode),
        schema=vol.Schema(
            {
                vol.Required("mode"): vol.In(
                    ["Home 1", "Home 2", "Home 3", "Home UPS"]
                ),
                vol.Required("acknowledgement"): vol.In([True]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_grid_delivery",
        wrap_with_shield("set_grid_delivery", real_call_set_grid_delivery),
        schema=vol.Schema(
            {
                "mode": vol.Any(
                    None,
                    vol.In(["Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"]),
                ),
                "limit": vol.Any(None, vol.Coerce(int)),
                vol.Required("acknowledgement"): vol.In([True]),
                vol.Required("warning"): vol.In([True]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_boiler_mode",
        wrap_with_shield("set_boiler_mode", real_call_set_boiler_mode),
        schema=vol.Schema(
            {
                vol.Required("mode"): vol.In(["CBB", "Manual"]),
                vol.Required("acknowledgement"): vol.In([True]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_formating_mode",
        wrap_with_shield("set_formating_mode", real_call_set_formating_mode),
        schema=vol.Schema(
            {
                vol.Required("mode"): vol.In(["Nenabíjet", "Nabíjet"]),
                "limit": vol.Any(None, vol.Coerce(int)),
                vol.Required("acknowledgement"): vol.In([True]),
            }
        ),
    )
