"""Services for OIG Cloud integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Mapping, Optional, Union, Final

from opentelemetry import trace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .api.oig_cloud_api import OigCloudApi, OigCloudApiError

_LOGGER = logging.getLogger(__name__)

# Define mode constants
MODES: Final[Dict[str, str]] = {
    "Home 1": "0",
    "Home 2": "1",
    "Home 3": "2",
    "Home UPS": "3",
}

GRID_DELIVERY: Final[Dict[str, int]] = {
    "Vypnuto / Off": 0, 
    "Zapnuto / On": 1, 
    "S omezením / Limited": 2
}

BOILER_MODE: Final[Dict[str, int]] = {
    "CBB": 0, 
    "Manual": 1
}

FORMAT_BATTERY: Final[Dict[str, int]] = {
    "Nenabíjet": 0, 
    "Nabíjet": 1
}

# Service schemas
SCHEMA_BOX_MODE = vol.Schema({
    vol.Required("Mode"): vol.In([
        "Home 1",
        "Home 2",
        "Home 3",
        "Home UPS",
    ]),
    vol.Required("Acknowledgement"): vol.Boolean(True),
})

SCHEMA_GRID_DELIVERY = vol.Schema({
    vol.Exclusive("Mode", "mode_or_limit"): vol.In([
        "Vypnuto / Off",
        "Zapnuto / On",
        "S omezením / Limited",
    ]),
    vol.Exclusive("Limit", "mode_or_limit"): vol.All(
        vol.Coerce(int),
        vol.Range(min=1, max=9999)
    ),
    vol.Required("Acknowledgement"): vol.Boolean(True),
    vol.Required("Upozornění"): vol.Boolean(True),
})

SCHEMA_BOILER_MODE = vol.Schema({
    vol.Required("Mode"): vol.In([
        "CBB",
        "Manual",
    ]),
    vol.Required("Acknowledgement"): vol.Boolean(True),
})

SCHEMA_FORMATTING_MODE = vol.Schema({
    vol.Required("Mode"): vol.In([
        "Nenabíjet",
        "Nabíjet",
    ]),
    vol.Optional("Limit"): vol.All(
        vol.Coerce(int),
        vol.Range(min=20, max=100)
    ),
    vol.Required("Acknowledgement"): vol.Boolean(True),
})

BOILER_MODE = {"CBB": 0, "Manual": 1}

FORMAT_BATTERY = {"Nenabíjet": 0, "Nabíjet": 1}

SSR_MODE = {"OFF": 0, "ON": 1}

tracer = trace.get_tracer(__name__)


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up OIG Cloud services."""
    
    async def async_set_box_mode(call: ServiceCall) -> None:
        """Set OIG Cloud box mode."""
        acknowledged: bool = call.data.get("Acknowledgement", False)
        if not acknowledged:
            raise HomeAssistantError("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_box_mode"):
            try:
                entry_data = hass.data[DOMAIN][entry.entry_id]
                client: OigCloudApi = entry_data["api"]
                mode: str = call.data.get("Mode")
                mode_value: str = MODES.get(mode)
                
                _LOGGER.info(f"Setting box mode to {mode} (value: {mode_value})")
                success: bool = await client.set_box_mode(mode_value)
                
                if success:
                    _LOGGER.info(f"Successfully set box mode to {mode}")
                    # Refresh coordinator data
                    await entry_data["coordinator"].async_refresh()
                else:
                    raise HomeAssistantError(f"Failed to set box mode to {mode}")
            except OigCloudApiError as err:
                raise HomeAssistantError(f"API error: {err}") from err
            except Exception as err:
                raise HomeAssistantError(f"Unexpected error: {err}") from err

    async def async_set_grid_delivery(call: ServiceCall) -> None:
        """Set OIG Cloud grid delivery mode or limit."""
        acknowledged: bool = call.data.get("Acknowledgement", False)
        if not acknowledged:
            raise HomeAssistantError("Acknowledgement is required")

        accepted: bool = call.data.get("Upozornění", False)
        if not accepted:
            raise HomeAssistantError("Upozornění je třeba odsouhlasit")

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
            try:
                entry_data = hass.data[DOMAIN][entry.entry_id]
                client: OigCloudApi = entry_data["api"]
                
                if grid_mode is not None:
                    mode: int = GRID_DELIVERY.get(grid_mode)
                    _LOGGER.info(f"Setting grid delivery mode to {grid_mode} (value: {mode})")
                    success = await client.set_grid_delivery(mode)
                    if success:
                        _LOGGER.info(f"Successfully set grid delivery mode to {grid_mode}")
                    else:
                        raise HomeAssistantError(f"Failed to set grid delivery mode to {grid_mode}")

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
            mode_value = BOILER_MODE.get(mode)
            success = await client.set_boiler_mode(mode_value)

    async def async_set_ssr_rele_1(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_ssr_rele_1"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = SSR_MODE.get(mode)
            success = await client.set_ssr_rele_1(mode_value)

    async def async_set_ssr_rele_2(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_ssr_rele_2"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = SSR_MODE.get(mode)
            success = await client.set_ssr_rele_2(mode_value)

    async def async_set_ssr_rele_3(call):
        acknowledged = call.data.get("Acknowledgement")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        with tracer.start_as_current_span("async_set_ssr_rele_3"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = SSR_MODE.get(mode)
            success = await client.set_ssr_rele_3(mode_value)

    async def async_set_formating_mode(call):
        acknowledged = call.data.get("Acknowledgement")
        limit = call.data.get("Limit")
        if not acknowledged:
            raise vol.Invalid("Acknowledgement is required")

        if limit is not None and (limit > 100 or limit < 20):
            raise vol.Invalid("Limit musí být v rozmezí 20-100")

        with tracer.start_as_current_span("async_set_formating_mode"):
            client: OigCloudApi = hass.data[DOMAIN][entry.entry_id]
            mode = call.data.get("Mode")
            mode_value = FORMAT_BATTERY.get(mode)
            success = await client.set_formating_mode(limit)

    hass.services.async_register(
        DOMAIN,
        "set_box_mode",
        async_set_box_mode,
        schema=SCHEMA_BOX_MODE,
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
        "set_ssr_rele_1",
        async_set_ssr_rele_1,
        schema=vol.Schema(
            {
                "Mode": vol.In(
                    [
                        "OFF",
                        "ON",
                    ]
                ),
                "Acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_ssr_rele_2",
        async_set_ssr_rele_2,
        schema=vol.Schema(
            {
                "Mode": vol.In(
                    [
                        "OFF",
                        "ON",
                    ]
                ),
                "Acknowledgement": vol.Boolean(1),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "set_ssr_rele_3",
        async_set_ssr_rele_3,
        schema=vol.Schema(
            {
                "Mode": vol.In(
                    [
                        "OFF",
                        "ON",
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
