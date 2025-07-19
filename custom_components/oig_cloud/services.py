"""Služby pro integraci OIG Cloud."""

import logging
import voluptuous as vol
from typing import Dict, Any, Optional, Callable, Awaitable
from opentelemetry import trace

from homeassistant.core import HomeAssistant, ServiceCall, Context, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

# Schema pro update solární předpovědi
SOLAR_FORECAST_UPDATE_SCHEMA = vol.Schema({})

# Konstanty pro služby
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


async def async_setup_services(hass: HomeAssistant) -> None:
    """Nastavení základních služeb pro OIG Cloud."""

    async def handle_update_solar_forecast(call: ServiceCall) -> None:
        """Zpracování služby pro manuální aktualizaci solární předpovědi."""
        # Procházíme všechny config entries
        for entry_id in hass.data.get(DOMAIN, {}):
            entry_data = hass.data[DOMAIN][entry_id]

            # Kontrolujeme, zda má coordinator a solar_forecast
            if "coordinator" in entry_data and hasattr(
                entry_data["coordinator"], "solar_forecast"
            ):
                try:
                    solar_forecast = entry_data["coordinator"].solar_forecast
                    # Spustit update
                    await solar_forecast.async_update()
                    _LOGGER.info(
                        f"Manuálně aktualizována solární předpověď pro {entry_id}"
                    )
                except Exception as e:
                    _LOGGER.error(f"Chyba při aktualizaci solární předpovědi: {e}")
            else:
                _LOGGER.debug(f"Config entry {entry_id} nemá solární předpověď")

    # Registrace služby pouze pokud ještě není registrovaná
    if not hass.services.has_service(DOMAIN, "update_solar_forecast"):
        hass.services.async_register(
            DOMAIN,
            "update_solar_forecast",
            handle_update_solar_forecast,
            schema=SOLAR_FORECAST_UPDATE_SCHEMA,
        )
        _LOGGER.debug(f"Zaregistrovány základní služby pro {DOMAIN}")


async def async_setup_entry_services_with_shield(
    hass: HomeAssistant, entry: ConfigEntry, shield: Any
) -> None:
    """Setup entry-specific services with shield protection - direct shield parameter."""
    _LOGGER.debug(f"Setting up entry services for {entry.entry_id} with shield")
    _LOGGER.debug(f"Shield object: {shield}")
    _LOGGER.debug(f"Shield type: {type(shield)}")

    if not shield:
        _LOGGER.debug("ServiceShield not provided, falling back to regular setup")
        await async_setup_entry_services_fallback(hass, entry)
        return

    def wrap_with_shield(
        service_name: str,
        handler_func: Callable[
            [str, str, Dict[str, Any], bool, Optional[Context]], Awaitable[None]
        ],
    ) -> Callable[[ServiceCall], Awaitable[None]]:
        async def wrapper(call: ServiceCall) -> None:
            data: Dict[str, Any] = dict(call.data)
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
    async def real_call_set_box_mode(
        domain: str,
        service: str,
        service_data: Dict[str, Any],
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        with tracer.start_as_current_span("async_set_box_mode"):
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            client: OigCloudApi = coordinator.api
            mode: Optional[str] = service_data.get("mode")
            mode_value: Optional[str] = MODES.get(mode) if mode else None
            await client.set_box_mode(mode_value)

    @callback
    async def real_call_set_grid_delivery(
        domain: str,
        service: str,
        service_data: Dict[str, Any],
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        grid_mode: Optional[str] = service_data.get("mode")
        limit: Optional[int] = service_data.get("limit")

        if (grid_mode is None and limit is None) or (
            grid_mode is not None and limit is not None
        ):
            raise vol.Invalid(
                "Musí být nastaven právě jeden parametr (Režim nebo Limit)"
            )

        if limit is not None and (limit > 9999 or limit < 1):
            raise vol.Invalid("Limit musí být v rozmezí 1–9999")

        with tracer.start_as_current_span("async_set_grid_delivery"):
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            client: OigCloudApi = coordinator.api
            if grid_mode is not None:
                mode: Optional[int] = GRID_DELIVERY.get(grid_mode)
                await client.set_grid_delivery(mode)
            if limit is not None:
                success: bool = await client.set_grid_delivery_limit(int(limit))
                if not success:
                    raise vol.Invalid("Limit se nepodařilo nastavit.")

    @callback
    async def real_call_set_boiler_mode(
        domain: str,
        service: str,
        service_data: Dict[str, Any],
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        with tracer.start_as_current_span("async_set_boiler_mode"):
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            client: OigCloudApi = coordinator.api
            mode: Optional[str] = service_data.get("mode")
            mode_value: Optional[int] = BOILER_MODE.get(mode) if mode else None
            await client.set_boiler_mode(mode_value)

    @callback
    async def real_call_set_formating_mode(
        domain: str,
        service: str,
        service_data: Dict[str, Any],
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        limit: Optional[int] = service_data.get("limit")
        if limit is not None and (limit > 100 or limit < 20):
            raise vol.Invalid("Limit musí být v rozmezí 20–100")

        with tracer.start_as_current_span("async_set_formating_mode"):
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            client: OigCloudApi = coordinator.api
            mode: Optional[str] = service_data.get("mode")
            mode_value: Optional[int] = FORMAT_BATTERY.get(mode) if mode else None
            await client.set_formating_mode(limit)

    # Kontrola, zda služby již nejsou registrované (kvůli vícenásobným entries)
    if not hass.services.has_service(DOMAIN, "set_box_mode"):
        _LOGGER.debug("Registering all entry services with shield protection")

        # Registrace VŠECH služeb se shield ochranou
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
        _LOGGER.debug("Registered set_box_mode")

        hass.services.async_register(
            DOMAIN,
            "set_grid_delivery",
            wrap_with_shield("set_grid_delivery", real_call_set_grid_delivery),
            schema=vol.Schema(
                {
                    "mode": vol.Any(
                        None,
                        vol.In(
                            ["Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"]
                        ),
                    ),
                    "limit": vol.Any(None, vol.Coerce(int)),
                    vol.Required("acknowledgement"): vol.In([True]),
                    vol.Required("warning"): vol.In([True]),
                }
            ),
        )
        _LOGGER.debug("Registered set_grid_delivery")

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
        _LOGGER.debug("Registered set_boiler_mode")

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
        _LOGGER.debug("Registered set_formating_mode")
        _LOGGER.info("All entry services registered with shield protection")
    else:
        _LOGGER.debug("Entry services already registered, skipping")


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Setup entry-specific services with optional shield protection."""
    _LOGGER.debug(f"Setting up entry services for {entry.entry_id}")

    # Pokus o získání shield objektu
    shield = hass.data[DOMAIN].get("shield")

    if shield:
        _LOGGER.debug("Using shield protection for services")
        await async_setup_entry_services_with_shield(hass, entry, shield)
    else:
        _LOGGER.debug("Shield not available, using fallback services")
        await async_setup_entry_services_fallback(hass, entry)


async def async_setup_entry_services_fallback(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Setup entry-specific services WITHOUT shield protection as fallback."""
    _LOGGER.info(f"Registering fallback services for entry {entry.entry_id}")

    async def handle_set_box_mode(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        client: OigCloudApi = coordinator.api
        mode: Optional[str] = call.data.get("mode")
        mode_value: Optional[str] = MODES.get(mode) if mode else None
        await client.set_box_mode(mode_value)

    async def handle_set_boiler_mode(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        client: OigCloudApi = coordinator.api
        mode: Optional[str] = call.data.get("mode")
        mode_value: Optional[int] = BOILER_MODE.get(mode) if mode else None
        await client.set_boiler_mode(mode_value)

    async def handle_set_grid_delivery(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        client: OigCloudApi = coordinator.api
        grid_mode: Optional[str] = call.data.get("mode")
        limit: Optional[int] = call.data.get("limit")

        if grid_mode is not None:
            mode: Optional[int] = GRID_DELIVERY.get(grid_mode)
            await client.set_grid_delivery(mode)
        if limit is not None:
            await client.set_grid_delivery_limit(int(limit))

    async def handle_set_formating_mode(call: ServiceCall) -> None:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        client: OigCloudApi = coordinator.api
        limit: Optional[int] = call.data.get("limit")
        await client.set_formating_mode(limit)

    # Kontrola, zda služby již nejsou registrované
    if not hass.services.has_service(DOMAIN, "set_box_mode"):
        _LOGGER.info("No existing services found, registering all fallback services")

        # Registrace bez shield ochrany
        services_to_register = [
            (
                "set_box_mode",
                handle_set_box_mode,
                {
                    vol.Required("mode"): vol.In(
                        ["Home 1", "Home 2", "Home 3", "Home UPS"]
                    ),
                    vol.Required("acknowledgement"): vol.In([True]),
                },
            ),
            (
                "set_boiler_mode",
                handle_set_boiler_mode,
                {
                    vol.Required("mode"): vol.In(["CBB", "Manual"]),
                    vol.Required("acknowledgement"): vol.In([True]),
                },
            ),
            (
                "set_grid_delivery",
                handle_set_grid_delivery,
                {
                    "mode": vol.Any(
                        None,
                        vol.In(
                            ["Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"]
                        ),
                    ),
                    "limit": vol.Any(None, vol.Coerce(int)),
                    vol.Required("acknowledgement"): vol.In([True]),
                    vol.Required("warning"): vol.In([True]),
                },
            ),
            (
                "set_formating_mode",
                handle_set_formating_mode,
                {
                    vol.Required("mode"): vol.In(["Nenabíjet", "Nabíjet"]),
                    "limit": vol.Any(None, vol.Coerce(int)),
                    vol.Required("acknowledgement"): vol.In([True]),
                },
            ),
        ]

        for service_name, handler, schema in services_to_register:
            try:
                hass.services.async_register(
                    DOMAIN, service_name, handler, schema=vol.Schema(schema)
                )
                _LOGGER.info(
                    f"Successfully registered fallback service: {service_name}"
                )
            except Exception as e:
                _LOGGER.error(f"Failed to register service {service_name}: {e}")

        _LOGGER.info("All fallback services registration completed")
    else:
        _LOGGER.info("Services already registered, skipping fallback registration")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Odregistrace služeb při unload integrace."""
    services_to_remove = [
        "update_solar_forecast",
        "set_box_mode",
        "set_grid_delivery",
        "set_boiler_mode",
        "set_formating_mode",
    ]

    for service in services_to_remove:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    _LOGGER.debug("All services unloaded")
