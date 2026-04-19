"""Services for OIG Cloud integration."""

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Coroutine, Dict, Iterable, List, Mapping, Optional, Union

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.exceptions import HomeAssistantError
from opentelemetry import trace

from .const import DOMAIN
from .api.oig_cloud_api import OigCloudApi, OigCloudApiError
from .core.box_mode_composite import build_app_value


_LOGGER = logging.getLogger(__name__)

OigResponse = dict[str, Any]
OigResponseHandler = Callable[[ServiceCall], Coroutine[Any, Any, OigResponse | None]]


def _noop_setup_boiler_services(*_args: Any, **_kwargs: Any) -> None:
    return None


boiler = SimpleNamespace(setup_boiler_services=_noop_setup_boiler_services)

HOME_1 = "Home 1"
HOME_2 = "Home 2"
HOME_3 = "Home 3"
HOME_UPS = "Home UPS"
HOME_MODE_LABELS = (HOME_1, HOME_2, HOME_3, HOME_UPS)
HOME_MODE_ALL_KEYS = (
    HOME_1, HOME_2, HOME_3, HOME_UPS,
    "home_1", "home_2", "home_3", "home_ups",
    "home1", "home2", "home3", "homeups",
)

LEGACY_HOME_5_6_ALIASES = frozenset({
    "home_5", "home_6", "Home 5", "Home 6", "home5", "home6",
})


def _validate_box_mode(value):
    if value in LEGACY_HOME_5_6_ALIASES:
        raise vol.Invalid(
            "Home 5/6 are now supplementary toggles. "
            "Use home_grid_v/home_grid_vi boolean fields instead of mode."
        )
    if value not in HOME_MODE_ALL_KEYS:
        raise vol.Invalid(f"Invalid box mode: {value}")
    return value


def _validate_set_box_mode_schema(data):
    has_mode = data.get("mode") is not None
    has_toggles = data.get("home_grid_v") is not None or data.get("home_grid_vi") is not None
    if not has_mode and not has_toggles:
        raise vol.Invalid("At least one of mode, home_grid_v, or home_grid_vi must be provided.")
    return data

GRID_OFF_LABEL = "Vypnuto / Off"
GRID_ON_LABEL = "Zapnuto / On"
GRID_LIMITED_LABEL = "S omezením / Limited"
GRID_DELIVERY_LABELS = (GRID_OFF_LABEL, GRID_ON_LABEL, GRID_LIMITED_LABEL)
# Canonical machine values for grid delivery (as sent by services.yaml/frontend)
GRID_DELIVERY_CANONICAL = ("off", "on", "limited")
# All accepted values (canonical + backward-compatible labels)
GRID_DELIVERY_ALL_KEYS = GRID_DELIVERY_CANONICAL + GRID_DELIVERY_LABELS

BOILER_CBB_LABEL = "CBB"
BOILER_MANUAL_LABEL = "Manual"
BOILER_MODE_LABELS = (BOILER_CBB_LABEL, BOILER_MANUAL_LABEL)
# Canonical machine values for boiler mode (as sent by services.yaml/frontend)
BOILER_MODE_CANONICAL = ("cbb", "manual")
# All accepted values (canonical + backward-compatible labels)
BOILER_MODE_ALL_KEYS = BOILER_MODE_CANONICAL + BOILER_MODE_LABELS

FORMAT_NO_CHARGE_LABEL = "Nenabíjet"
FORMAT_CHARGE_LABEL = "Nabíjet"
FORMAT_BATTERY_LABELS = (FORMAT_NO_CHARGE_LABEL, FORMAT_CHARGE_LABEL)
# Canonical machine values for formating mode (as sent by services.yaml/frontend)
FORMAT_BATTERY_CANONICAL = ("no_charge", "charge")
# All accepted values (canonical + backward-compatible labels)
FORMAT_BATTERY_ALL_KEYS = FORMAT_BATTERY_CANONICAL + FORMAT_BATTERY_LABELS
SHIELD_LOG_PREFIX = "[SHIELD]"

SET_BOX_MODE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("device_id"): cv.string,
            vol.Optional("mode"): _validate_box_mode,
            vol.Optional("home_grid_v"): cv.boolean,
            vol.Optional("home_grid_vi"): cv.boolean,
            vol.Required("acknowledgement"): vol.In([True]),
        }
    ),
    _validate_set_box_mode_schema,
)
SET_GRID_DELIVERY_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("mode"): vol.In(GRID_DELIVERY_ALL_KEYS),
        vol.Required("limit"): vol.Coerce(int),
        vol.Required("acknowledgement"): vol.In([True]),
        vol.Required("warning"): vol.In([True]),
    }
)
SET_BOILER_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("mode"): vol.In(BOILER_MODE_ALL_KEYS),
        vol.Required("acknowledgement"): vol.In([True]),
    }
)
SET_FORMATING_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("mode"): vol.In(FORMAT_BATTERY_ALL_KEYS),
        vol.Required("acknowledgement"): vol.In([True]),
        "limit": vol.Any(None, vol.Coerce(int)),
    }
)


def _box_id_from_entry(
    hass: HomeAssistant, coordinator: Any, entry_id: str
) -> Optional[str]:
    try:
        entry = getattr(coordinator, "config_entry", None) or hass.config_entries.async_get_entry(
            entry_id
        )
        if not entry:
            return None
        val = (
            entry.options.get("box_id")
            or entry.data.get("box_id")
            or entry.data.get("inverter_sn")
        )
        if isinstance(val, str) and val.isdigit():
            return val
    except Exception:
        return None
    return None


def _box_id_from_coordinator(coordinator: Any) -> Optional[str]:
    try:
        data = getattr(coordinator, "data", None)
        if isinstance(data, dict) and data:
            return next((str(k) for k in data.keys() if str(k).isdigit()), None)
    except Exception:
        return None
    return None


def _strip_identifier_suffix(identifier_value: str) -> str:
    return identifier_value.replace("_shield", "").replace("_analytics", "")


def _extract_box_id_from_device(device: dr.DeviceEntry, device_id: str) -> Optional[str]:
    for identifier in device.identifiers:
        if identifier[0] != DOMAIN:
            continue
        identifier_value = identifier[1]
        box_id = _strip_identifier_suffix(identifier_value)
        if isinstance(box_id, str) and box_id.isdigit():
            _LOGGER.debug(
                "Found box_id %s from device %s (identifier: %s)",
                box_id,
                device_id,
                identifier_value,
            )
            return box_id
    return None


def _register_service_if_missing(
    hass: HomeAssistant,
    name: str,
    handler: OigResponseHandler,
    schema: vol.Schema,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> bool:
    if hass.services.has_service(DOMAIN, name):
        return False
    hass.services.async_register(
        DOMAIN, name, handler, schema=schema, supports_response=supports_response
    )
    return True


def _get_entry_client(hass: HomeAssistant, entry: ConfigEntry) -> OigCloudApi:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    return coordinator.api


def _resolve_box_id_from_service(
    hass: HomeAssistant,
    entry: ConfigEntry,
    service_data: Dict[str, Any],
    service_name: str,
) -> Optional[str]:
    device_id: Optional[str] = service_data.get("device_id")
    box_id = get_box_id_from_device(hass, device_id, entry.entry_id)
    if not box_id:
        _LOGGER.error("Cannot determine box_id for %s", service_name)
        return None
    return box_id


def _validate_grid_delivery_inputs(grid_mode: Optional[str], limit: Optional[int]) -> None:
    if (grid_mode is None and limit is None) or (
        grid_mode is not None and limit is not None
    ):
        raise vol.Invalid("Musí být nastaven právě jeden parametr (Režim nebo Limit)")
    if limit is not None and (limit > 9999 or limit < 1):
        raise vol.Invalid("Limit musí být v rozmezí 1–9999")


def _acknowledged(service_data: Dict[str, Any], service_name: str) -> bool:
    if service_data.get("acknowledgement", False):
        return True
    _LOGGER.error("Služba %s vyžaduje potvrzení (acknowledgement)", service_name)
    return False


def get_box_id_from_device(
    hass: HomeAssistant, device_id: Optional[str], entry_id: str
) -> Optional[str]:
    """
    Extrahuje box_id z device_id nebo vrátí první dostupný box_id.

    Args:
        hass: HomeAssistant instance
        device_id: ID zařízení z service call (může být None)
        entry_id: Config entry ID

    Returns:
        box_id (str) nebo None pokud nenalezen
    """
    coordinator = hass.data[DOMAIN][entry_id]["coordinator"]

    # Pokud není device_id, použij první dostupný box_id
    if not device_id:
        # Preferovat persistované box_id z config entry (funguje i v local_only režimu)
        if entry_box_id := _box_id_from_entry(hass, coordinator, entry_id):
            return entry_box_id

        # Fallback: numerický klíč v coordinator.data (cloud režim)
        if coord_box_id := _box_id_from_coordinator(coordinator):
            return coord_box_id

        _LOGGER.warning("No device_id provided and no box_id could be resolved")
        return None

    # Máme device_id, najdi odpovídající box_id
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)

    if not device:
        _LOGGER.warning("Device %s not found in registry", device_id)
        return _box_id_from_entry(hass, coordinator, entry_id) or _box_id_from_coordinator(
            coordinator
        )

    # Extrahuj box_id z device identifiers
    # Identifiers mají formát: {(DOMAIN, identifier_value), ...}
    # identifier_value může být:
    #   - "2206237016" (hlavní zařízení)
    #   - "2206237016_shield" (shield)
    #   - "2206237016_analytics" (analytics)
    if device_box_id := _extract_box_id_from_device(device, device_id):
        return device_box_id

    _LOGGER.warning("Could not extract box_id from device %s", device_id)
    return _box_id_from_entry(hass, coordinator, entry_id) or _box_id_from_coordinator(
        coordinator
    )


# Schema pro update solární předpovědi
SOLAR_FORECAST_UPDATE_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
    }
)
CHECK_BALANCING_SCHEMA = vol.Schema(
    {
        vol.Optional("box_id"): cv.string,
        vol.Optional("force"): cv.boolean,
    }
)

# Konstanty pro služby
MODES: Dict[str, str] = {
    "home_1": "0",
    "home_2": "1",
    "home_3": "2",
    "home_ups": "3",
    # Alternate slug variants (legacy docs)
    "home1": "0",
    "home2": "1",
    "home3": "2",
    "homeups": "3",
    # Backward-compatible labels (legacy automations)
    HOME_1: "0",
    HOME_2: "1",
    HOME_3: "2",
    HOME_UPS: "3",
}

GRID_DELIVERY = {
    "off": 0,
    "on": 1,
    "limited": 1,
    # Backward-compatible labels
    GRID_OFF_LABEL: 0,
    GRID_ON_LABEL: 1,
    GRID_LIMITED_LABEL: 1,
}
BOILER_MODE = {
    "cbb": 0,
    "manual": 1,
    # Backward-compatible labels
    BOILER_CBB_LABEL: 0,
    BOILER_MANUAL_LABEL: 1,
}
FORMAT_BATTERY = {
    "no_charge": 0,
    "charge": 1,
    # Backward-compatible labels
    FORMAT_NO_CHARGE_LABEL: 0,
    FORMAT_CHARGE_LABEL: 1,
}

tracer = trace.get_tracer(__name__)

# Storage key pro dashboard tiles
STORAGE_KEY_DASHBOARD_TILES = "oig_dashboard_tiles"


def _iter_entry_data(hass: HomeAssistant) -> Iterable[tuple[str, dict[str, Any]]]:
    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if isinstance(entry_data, dict):
            yield entry_id, entry_data


def _get_entry_solar_sensors(entry_data: dict[str, Any]) -> list[Any]:
    sensors = entry_data.get("solar_forecast_sensors")
    if isinstance(sensors, list) and sensors:
        return sensors
    fallback = entry_data.get("solar_forecast")
    if fallback is not None and hasattr(fallback, "async_update"):
        return [fallback]
    coordinator = entry_data.get("coordinator")
    if coordinator is not None:
        coordinator_sensor = getattr(coordinator, "solar_forecast", None)
        if coordinator_sensor is not None:
            return [coordinator_sensor]
    return []


def _get_primary_solar_sensor(entry_data: dict[str, Any]) -> Optional[Any]:
    for sensor in _get_entry_solar_sensors(entry_data):
        if getattr(sensor, "_sensor_type", None) == "solar_forecast":
            return sensor
    sensors = _get_entry_solar_sensors(entry_data)
    return sensors[0] if sensors else None


async def _update_solar_forecast_for_entry(
    entry_id: str,
    entry_data: dict[str, Any],
    entity_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    sensors = _get_entry_solar_sensors(entry_data)
    if not sensors:
        _LOGGER.debug("Config entry %s nemá solar forecast senzory", entry_id)
        return {"entry_id": entry_id, "status": "no_sensors"}

    if entity_ids:
        sensor_entity_ids = {
            sensor.entity_id
            for sensor in sensors
            if hasattr(sensor, "entity_id")
        }
        if not sensor_entity_ids.intersection(entity_ids):
            return {"entry_id": entry_id, "status": "skipped"}

    solar_forecast = _get_primary_solar_sensor(entry_data)
    if not solar_forecast:
        return {"entry_id": entry_id, "status": "no_primary"}
    try:
        if hasattr(solar_forecast, "async_manual_update"):
            success = await solar_forecast.async_manual_update()
            if not success:
                return {
                    "entry_id": entry_id,
                    "status": "error",
                    "error": "manual_update_failed",
                }
        else:
            await solar_forecast.async_update()
        _LOGGER.info("Manuálně aktualizována solární předpověď pro %s", entry_id)
        return {
            "entry_id": entry_id,
            "status": "updated",
            "entity_id": getattr(solar_forecast, "entity_id", None),
        }
    except Exception as exc:
        _LOGGER.error("Chyba při aktualizaci solární předpovědi: %s", exc, exc_info=True)
        return {"entry_id": entry_id, "status": "error", "error": str(exc)}


def _register_service_definitions(
    hass: HomeAssistant,
    service_definitions: Iterable[
        tuple[str, OigResponseHandler, vol.Schema, SupportsResponse, str]
    ],
) -> None:
    for name, handler, schema, supports_response, log_message in service_definitions:
        if _register_service_if_missing(
            hass, name, handler, schema, supports_response=supports_response
        ):
            _LOGGER.debug(log_message)


def _log_prefix(prefix: str) -> str:
    return f"{prefix} " if prefix else ""


async def _action_set_box_mode(
    hass: HomeAssistant,
    entry: ConfigEntry,
    service_data: Dict[str, Any],
    log_prefix: str,
) -> None:
    client = _get_entry_client(hass, entry)
    box_id = _resolve_box_id_from_service(hass, entry, service_data, "set_box_mode")
    if not box_id:
        return

    mode: Optional[str] = service_data.get("mode")
    home_grid_v: Optional[bool] = service_data.get("home_grid_v")
    home_grid_vi: Optional[bool] = service_data.get("home_grid_vi")

    if mode is not None:
        mode_value: Optional[str] = MODES.get(mode)
        if mode_value is None:
            raise vol.Invalid("Neplatný režim boxu.")
        _LOGGER.info(
            "%sSetting box mode for device %s to %s (value: %s)",
            log_prefix,
            box_id,
            mode,
            mode_value,
        )
        await client.set_box_mode(mode_value)

    if home_grid_v is not None or home_grid_vi is not None:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        current_raw = None
        try:
            current_raw = coordinator.data["box_prm2"]["app"]
        except (TypeError, KeyError):
            pass
        if current_raw is None:
            try:
                for value in coordinator.data.values():
                    if isinstance(value, dict) and isinstance(value.get("box_prm2"), dict):
                        current_raw = value["box_prm2"].get("app")
                        if current_raw is not None:
                            break
            except Exception:
                pass

        if current_raw is None:
            raise vol.Invalid(
                "Current box_prm2.app state unknown — cannot perform read-modify-write for supplementary toggles."
            )

        if current_raw == 4:
            raise vol.Invalid(
                "Flexibilita mode is active (box_prm2.app=4). "
                "Cannot modify supplementary toggles while Flexibilita is enabled."
            )

        new_value = build_app_value(
            home_grid_v=home_grid_v,
            home_grid_vi=home_grid_vi,
            current_raw=current_raw,
        )
        _LOGGER.info(
            "%sSetting box_prm2.app for device %s to %s (current: %s)",
            log_prefix,
            box_id,
            new_value,
            current_raw,
        )
        await client.set_box_prm2_app(new_value)


async def _action_set_boiler_mode(
    hass: HomeAssistant,
    entry: ConfigEntry,
    service_data: Dict[str, Any],
    log_prefix: str,
) -> None:
    client = _get_entry_client(hass, entry)
    box_id = _resolve_box_id_from_service(hass, entry, service_data, "set_boiler_mode")
    if not box_id:
        return

    mode: Optional[str] = service_data.get("mode")
    mode_value: Optional[int] = BOILER_MODE.get(mode) if mode else None
    _LOGGER.info(
        "%sSetting boiler mode for device %s to %s (value: %s)",
        log_prefix,
        box_id,
        mode,
        mode_value,
    )
    if mode_value is None:
        raise vol.Invalid("Neplatný režim bojleru.")
    await client.set_boiler_mode(str(mode_value))


async def _action_set_grid_delivery(
    hass: HomeAssistant,
    entry: ConfigEntry,
    service_data: Dict[str, Any],
    log_prefix: str,
    enforce_limit_success: bool,
) -> None:
    grid_mode: Optional[str] = service_data.get("mode")
    limit: Optional[int] = service_data.get("limit")
    _validate_grid_delivery_inputs(grid_mode, limit)

    client = _get_entry_client(hass, entry)
    box_id = _resolve_box_id_from_service(hass, entry, service_data, "set_grid_delivery")
    if not box_id:
        return

    _LOGGER.info(
        "%sSetting grid delivery for device %s: mode=%s, limit=%s",
        log_prefix,
        box_id,
        grid_mode,
        limit,
    )

    if grid_mode is not None:
        mode_value: Optional[int] = GRID_DELIVERY.get(grid_mode)
        if mode_value is None:
            raise vol.Invalid("Neplatný režim přetoků.")
        await client.set_grid_delivery(mode_value)
    if limit is not None:
        success = await client.set_grid_delivery_limit(int(limit))
        if enforce_limit_success and not success:
            raise vol.Invalid("Limit se nepodařilo nastavit.")


async def _action_set_formating_mode(
    hass: HomeAssistant,
    entry: ConfigEntry,
    service_data: Dict[str, Any],
    log_prefix: str,
) -> None:
    client = _get_entry_client(hass, entry)
    box_id = _resolve_box_id_from_service(hass, entry, service_data, "set_formating_mode")
    if not box_id:
        return

    mode: Optional[str] = service_data.get("mode")
    limit: Optional[int] = service_data.get("limit")
    _LOGGER.info(
        "%sSetting formating mode for device %s: mode=%s, limit=%s",
        log_prefix,
        box_id,
        mode,
        limit,
    )

    if not _acknowledged(service_data, "set_formating_mode"):
        return

    if limit is not None:
        await client.set_formating_mode(str(limit))
    else:
        mode_value: Optional[int] = FORMAT_BATTERY.get(mode) if mode else None
        if mode_value is not None:
            await client.set_formating_mode(str(mode_value))


async def _shield_set_box_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    with tracer.start_as_current_span("async_set_box_mode"):
        await _action_set_box_mode(
            hass, entry, service_data, _log_prefix(SHIELD_LOG_PREFIX)
        )


async def _shield_set_grid_delivery(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    with tracer.start_as_current_span("async_set_grid_delivery"):
        await _action_set_grid_delivery(
            hass, entry, service_data, _log_prefix(SHIELD_LOG_PREFIX), True
        )


async def _shield_set_boiler_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    with tracer.start_as_current_span("async_set_boiler_mode"):
        await _action_set_boiler_mode(
            hass, entry, service_data, _log_prefix(SHIELD_LOG_PREFIX)
        )


async def _shield_set_formating_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    with tracer.start_as_current_span("async_set_formating_mode"):
        await _action_set_formating_mode(
            hass, entry, service_data, _log_prefix(SHIELD_LOG_PREFIX)
        )


async def _fallback_set_box_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    await _action_set_box_mode(hass, entry, service_data, "")


async def _fallback_set_grid_delivery(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    await _action_set_grid_delivery(hass, entry, service_data, "", False)


async def _fallback_set_boiler_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    await _action_set_boiler_mode(hass, entry, service_data, "")


async def _fallback_set_formating_mode(
    hass: HomeAssistant, entry: ConfigEntry, service_data: Dict[str, Any]
) -> None:
    await _action_set_formating_mode(hass, entry, service_data, "")


def _make_shield_action(
    hass: HomeAssistant,
    entry: ConfigEntry,
    action: Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]],
) -> Callable[[str, str, Dict[str, Any], bool, Optional[Context]], Coroutine[Any, Any, None]]:
    @callback
    async def handler(
        domain: str,
        service: str,
        service_data: Dict[str, Any],
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        _ = domain, service, blocking, context
        await action(hass, entry, service_data)

    return handler


def _wrap_with_shield(
    hass: HomeAssistant,
    entry: ConfigEntry,
    shield: Any,
    service_name: str,
    action: Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]],
) -> Callable[[ServiceCall], Coroutine[Any, Any, None]]:
    shield_handler = _make_shield_action(hass, entry, action)

    async def wrapper(call: ServiceCall) -> None:
        data: Dict[str, Any] = dict(call.data)
        await shield.intercept_service_call(
            DOMAIN,
            service_name,
            {"params": data},
            shield_handler,
            blocking=False,
            context=call.context,
        )

    return wrapper


def _make_fallback_handler(
    hass: HomeAssistant,
    entry: ConfigEntry,
    action: Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]],
) -> Callable[[ServiceCall], Coroutine[Any, Any, None]]:
    async def handler(call: ServiceCall) -> None:
        data: Dict[str, Any] = dict(call.data)
        await action(hass, entry, data)

    return handler


async def async_setup_services(hass: HomeAssistant) -> None:
    """Nastavení základních služeb pro OIG Cloud."""
    await asyncio.sleep(0)

    async def handle_update_solar_forecast(call: ServiceCall) -> OigResponse:
        """Zpracování služby pro manuální aktualizaci solární předpovědi."""
        entity_ids: Optional[list[str]] = call.data.get("entity_id")
        results: list[dict[str, Any]] = []
        for entry_id, entry_data in _iter_entry_data(hass):
            results.append(
                await _update_solar_forecast_for_entry(
                    entry_id, entry_data, entity_ids
                )
            )
        updated = [item for item in results if item["status"] == "updated"]
        skipped = [item for item in results if item["status"] == "skipped"]
        errors = [item for item in results if item["status"] == "error"]
        return {
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "results": results,
        }

    async def handle_save_dashboard_tiles(call: ServiceCall) -> None:
        """Zpracování služby pro uložení konfigurace dashboard tiles."""
        await _save_dashboard_tiles_config(hass, call.data.get("config"))

    async def handle_get_dashboard_tiles(call: ServiceCall) -> OigResponse:
        """Služba pro načtení konfigurace dashboard tiles."""
        return await _load_dashboard_tiles_config(hass)

    async def handle_check_balancing(call: ServiceCall) -> OigResponse:
        """Manuálně spustí balancing kontrolu přes BalancingManager."""
        return await _run_manual_balancing_checks(hass, call)

    service_definitions = [
        (
            "update_solar_forecast",
            handle_update_solar_forecast,
            SOLAR_FORECAST_UPDATE_SCHEMA,
            SupportsResponse.OPTIONAL,
            f"Zaregistrovány základní služby pro {DOMAIN}",
        ),
        (
            "save_dashboard_tiles",
            handle_save_dashboard_tiles,
            vol.Schema({vol.Required("config"): cv.string}),
            SupportsResponse.NONE,
            "Registered save_dashboard_tiles service",
        ),
        (
            "get_dashboard_tiles",
            handle_get_dashboard_tiles,
            vol.Schema({}),
            SupportsResponse.OPTIONAL,
            "Registered get_dashboard_tiles service",
        ),
        (
            "check_balancing",
            handle_check_balancing,
            CHECK_BALANCING_SCHEMA,
            SupportsResponse.OPTIONAL,
            "Registered check_balancing service",
        ),
    ]
    _register_service_definitions(hass, service_definitions)


async def async_setup_entry_services_with_shield(
    hass: HomeAssistant, entry: ConfigEntry, shield: Any
) -> None:
    """Setup entry-specific services with shield protection - direct shield parameter."""
    _LOGGER.debug("Setting up entry services for %s with shield", entry.entry_id)
    _LOGGER.debug("Shield object: %s", shield)
    _LOGGER.debug("Shield type: %s", type(shield))

    if not shield:
        _LOGGER.debug("ServiceShield not provided, falling back to regular setup")
        await async_setup_entry_services_fallback(hass, entry)
        return

    if hass.services.has_service(DOMAIN, "set_box_mode"):
        _LOGGER.debug("Entry services already registered, skipping")
        return

    _LOGGER.debug("Registering all entry services with shield protection")
    service_actions = _entry_service_actions(shielded=True)
    _register_entry_services(
        hass,
        entry,
        service_actions,
        lambda service_name, action: _wrap_with_shield(
            hass, entry, shield, service_name, action
        ),
    )
    _register_boiler_services(hass, entry)

    _LOGGER.info("All entry services registered with shield protection")


async def async_setup_entry_services_fallback(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Setup entry-specific services WITHOUT shield protection as fallback."""
    await asyncio.sleep(0)
    _LOGGER.info("Registering fallback services for entry %s", entry.entry_id)
    if hass.services.has_service(DOMAIN, "set_box_mode"):
        _LOGGER.info("Services already registered, skipping fallback registration")
        return

    _LOGGER.info("No existing services found, registering all fallback services")
    services_to_register = _entry_service_actions(shielded=False)
    _register_entry_services(
        hass,
        entry,
        services_to_register,
        lambda _service_name, action: _make_fallback_handler(hass, entry, action),
    )

    _LOGGER.info("All fallback services registration completed")


def _entry_service_actions(
    *, shielded: bool
) -> list[tuple[str, Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]], vol.Schema]]:
    if shielded:
        return [
            ("set_box_mode", _shield_set_box_mode, SET_BOX_MODE_SCHEMA),
            ("set_grid_delivery", _shield_set_grid_delivery, SET_GRID_DELIVERY_SCHEMA),
            ("set_boiler_mode", _shield_set_boiler_mode, SET_BOILER_MODE_SCHEMA),
            ("set_formating_mode", _shield_set_formating_mode, SET_FORMATING_MODE_SCHEMA),
        ]
    return [
        ("set_box_mode", _fallback_set_box_mode, SET_BOX_MODE_SCHEMA),
        ("set_boiler_mode", _fallback_set_boiler_mode, SET_BOILER_MODE_SCHEMA),
        ("set_grid_delivery", _fallback_set_grid_delivery, SET_GRID_DELIVERY_SCHEMA),
        ("set_formating_mode", _fallback_set_formating_mode, SET_FORMATING_MODE_SCHEMA),
    ]


def _register_entry_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    services: Iterable[
        tuple[str, Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]], vol.Schema]
    ],
    handler_factory: Callable[
        [str, Callable[[HomeAssistant, ConfigEntry, Dict[str, Any]], Awaitable[None]]],
        Callable[[ServiceCall], Coroutine[Any, Any, None]],
    ],
) -> None:
    for service_name, action, schema in services:
        handler = handler_factory(service_name, action)
        try:
            hass.services.async_register(DOMAIN, service_name, handler, schema=schema)
            _LOGGER.info("Successfully registered %s service: %s", entry.entry_id, service_name)
        except Exception as exc:
            _LOGGER.error("Failed to register service %s: %s", service_name, exc)


def _register_boiler_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    boiler_coordinator = hass.data[DOMAIN].get(entry.entry_id, {}).get("boiler_coordinator")
    if not boiler_coordinator:
        return
    try:
        boiler.setup_boiler_services(hass, entry.entry_id, boiler_coordinator)
        _LOGGER.info("Boiler services registered")
    except Exception as exc:
        _LOGGER.error("Failed to register boiler services: %s", exc, exc_info=True)


async def _save_dashboard_tiles_config(
    hass: HomeAssistant, config_str: Optional[str]
) -> None:
    import json

    if not config_str:
        _LOGGER.error("Dashboard tiles config is empty")
        return

    try:
        config = json.loads(config_str)
        _validate_dashboard_tiles_config(config)

        from homeassistant.helpers.storage import Store

        store: Store[dict[str, Any]] = Store(
            hass, version=1, key=STORAGE_KEY_DASHBOARD_TILES
        )
        await store.async_save(config)

        _LOGGER.info(
            "Dashboard tiles config saved successfully: %s left, %s right",
            len(config.get("tiles_left", [])),
            len(config.get("tiles_right", [])),
        )

    except json.JSONDecodeError as e:
        _LOGGER.error("Invalid JSON in dashboard tiles config: %s", e)
    except ValueError as e:
        _LOGGER.error("Invalid dashboard tiles config structure: %s", e)
    except Exception as e:
        _LOGGER.error("Failed to save dashboard tiles config: %s", e)


async def _load_dashboard_tiles_config(hass: HomeAssistant) -> dict:
    try:
        from homeassistant.helpers.storage import Store

        store: Store[dict[str, Any]] = Store(
            hass, version=1, key=STORAGE_KEY_DASHBOARD_TILES
        )
        config = await store.async_load()
        if config:
            _LOGGER.info("Dashboard tiles config loaded from storage")
            return {"config": config}
        _LOGGER.info("No dashboard tiles config found in storage")
        return {"config": None}

    except Exception as e:
        _LOGGER.error("Failed to load dashboard tiles config: %s", e)
        return {"config": None}


def _validate_dashboard_tiles_config(config: Any) -> None:
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    required_keys = ["tiles_left", "tiles_right", "version"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required key: {key}")


def _serialize_dt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _iter_balancing_managers(
    hass: HomeAssistant, requested_box: Optional[str]
) -> List[tuple[str, Any, Optional[str]]]:
    managers: List[tuple[str, Any, Optional[str]]] = []
    domain_data = hass.data.get(DOMAIN, {})

    for entry_id, entry_data in domain_data.items():
        if not isinstance(entry_data, dict) or entry_id == "shield":
            continue
        balancing_manager = entry_data.get("balancing_manager")
        if not balancing_manager:
            continue
        manager_box_id = getattr(balancing_manager, "box_id", None)
        if requested_box and manager_box_id != requested_box:
            continue
        managers.append((entry_id, balancing_manager, manager_box_id))
    return managers


def _build_balancing_plan_result(
    entry_id: str, manager_box_id: Optional[str], plan: Any
) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "box_id": manager_box_id,
        "plan_mode": plan.mode.value,
        "reason": plan.reason,
        "holding_start": _serialize_dt(plan.holding_start),
        "holding_end": _serialize_dt(plan.holding_end),
        "priority": plan.priority.value,
    }


def _build_no_plan_result(entry_id: str, manager_box_id: Optional[str]) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "box_id": manager_box_id,
        "plan_mode": None,
        "reason": "no_plan_needed",
    }


def _build_error_result(
    entry_id: str, manager_box_id: Optional[str], err: Exception
) -> Dict[str, Any]:
    return {
        "entry_id": entry_id,
        "box_id": manager_box_id,
        "error": str(err),
    }


async def _run_manual_balancing_checks(
    hass: HomeAssistant, call: ServiceCall
) -> dict:
    requested_box = call.data.get("box_id")
    force_balancing = call.data.get("force", False)
    results: List[Dict[str, Any]] = []

    for entry_id, balancing_manager, manager_box_id in _iter_balancing_managers(
        hass, requested_box
    ):
        try:
            plan = await balancing_manager.check_balancing(force=force_balancing)
            if plan:
                results.append(_build_balancing_plan_result(entry_id, manager_box_id, plan))
                _LOGGER.info(
                    "Manual balancing check created %s plan for box %s (%s)",
                    plan.mode.value,
                    manager_box_id,
                    plan.reason,
                )
            else:
                results.append(_build_no_plan_result(entry_id, manager_box_id))
                _LOGGER.info(
                    "Manual balancing check executed for box %s - no plan needed",
                    manager_box_id,
                )
        except Exception as err:
            _LOGGER.error(
                "Manual balancing check failed for box %s: %s",
                manager_box_id or "unknown",
                err,
                exc_info=True,
            )
            results.append(_build_error_result(entry_id, manager_box_id, err))

    if not results:
        _LOGGER.warning(
            "Manual balancing check: no BalancingManager instances matched box_id=%s",
            requested_box or "any",
        )

    return {
        "requested_box_id": requested_box,
        "processed_entries": len(results),
        "results": results,
    }


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Setup entry-specific services with optional shield protection."""
    _LOGGER.debug("Setting up entry services for %s", entry.entry_id)
    shield = hass.data[DOMAIN].get("shield")

    if shield:
        _LOGGER.debug("Using shield protection for services")
        await async_setup_entry_services_with_shield(hass, entry, shield)
    else:
        _LOGGER.debug("Shield not available, using fallback services")
        await async_setup_entry_services_fallback(hass, entry)




async def async_unload_services(hass: HomeAssistant) -> None:
    """Odregistrace služeb při unload integrace."""
    await asyncio.sleep(0)
    services_to_remove = [
        "update_solar_forecast",
        "save_dashboard_tiles",
        "set_box_mode",
        "set_grid_delivery",
        "set_boiler_mode",
        "set_formating_mode",
    ]

    for service in services_to_remove:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("All services unloaded")
