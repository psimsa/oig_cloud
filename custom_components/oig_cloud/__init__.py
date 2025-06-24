"""The OIG Cloud integration."""

from __future__ import annotations

import asyncio
import logging
import hashlib
from typing import Any, Dict

from homeassistant import config_entries, core
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .api.oig_cloud_api import OigCloudApi
from .const import (
    CONF_NO_TELEMETRY,
    CONF_USERNAME,
    CONF_PASSWORD,
    DOMAIN,
    DEFAULT_NAME,
    CONF_STANDARD_SCAN_INTERVAL,
    CONF_EXTENDED_SCAN_INTERVAL,
)
from .oig_cloud_coordinator import OigCloudCoordinator  # Přidáme správný import

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the OIG Cloud component."""
    hass.data.setdefault(DOMAIN, {})

    # 🛡️ Inicializace ServiceShieldu (ochrana volání služeb) - async import
    try:
        from .service_shield import ServiceShield

        shield = ServiceShield(hass)
        await shield.start()

        # Uložení pro použití ve services.py
        hass.data[DOMAIN]["shield"] = shield
    except ImportError:
        _LOGGER.warning("ServiceShield není dostupný")

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up OIG Cloud from a config entry."""
    _LOGGER.info(f"Setting up OIG Cloud entry: {entry.title}")

    try:
        # Async importy pro vyhnání se blokování event loopu
        from .services import async_setup_entry_services

        # Načtení konfigurace z entry.data nebo entry.options
        username = entry.data.get(CONF_USERNAME) or entry.options.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD) or entry.options.get(CONF_PASSWORD)

        # Debug log pro diagnostiku
        _LOGGER.debug(f"Config data keys: {list(entry.data.keys())}")
        _LOGGER.debug(f"Config options keys: {list(entry.options.keys())}")
        _LOGGER.debug(f"Username: {'***' if username else 'MISSING'}")
        _LOGGER.debug(f"Password: {'***' if password else 'MISSING'}")

        if not username or not password:
            _LOGGER.error("Username or password is missing from configuration")
            return False

        no_telemetry = entry.data.get(CONF_NO_TELEMETRY, False) or entry.options.get(
            CONF_NO_TELEMETRY, False
        )

        # OPRAVA: Preferuj options před data, jen pokud options neexistují, použij data nebo default
        standard_scan_interval = entry.options.get(
            "standard_scan_interval"
        ) or entry.data.get(CONF_STANDARD_SCAN_INTERVAL, 30)
        extended_scan_interval = entry.options.get(
            "extended_scan_interval"
        ) or entry.data.get(CONF_EXTENDED_SCAN_INTERVAL, 300)

        _LOGGER.debug(
            f"Using intervals: standard={standard_scan_interval}s, extended={extended_scan_interval}s"
        )

        # Dočasně vypnout telemetrii kvůli blokujícím voláním
        # await _setup_telemetry(hass, username)

        # Vytvoření OIG API instance
        oig_api = OigCloudApi(username, password, no_telemetry, hass)

        _LOGGER.debug("Authenticating with OIG Cloud")
        await oig_api.authenticate()

        # Inicializace koordinátoru
        coordinator = OigCloudCoordinator(
            hass, oig_api, standard_scan_interval, extended_scan_interval
        )

        # OPRAVA: Počkej na první data před vytvořením senzorů
        _LOGGER.debug("Waiting for initial coordinator data...")
        await coordinator.async_config_entry_first_refresh()

        if coordinator.data is None:
            _LOGGER.error("Failed to get initial data from coordinator")
            raise ConfigEntryNotReady("No data received from OIG Cloud API")

        _LOGGER.debug(f"Coordinator data received: {len(coordinator.data)} devices")

        # Inicializace solar forecast (pokud je povolená)
        solar_forecast = None
        if entry.options.get("enable_solar_forecast", False):
            try:
                _LOGGER.debug("Initializing solar forecast functionality")
                # Solar forecast se inicializuje přímo v sensorech, ne zde
                solar_forecast = {"enabled": True, "config": entry.options}
            except Exception as e:
                _LOGGER.error("Chyba při inicializaci solární předpovědi: %s", e)
                solar_forecast = {"enabled": False, "error": str(e)}

        # Uložení dat do hass.data
        hass.data[DOMAIN][entry.entry_id] = {
            "coordinator": coordinator,
            "solar_forecast": solar_forecast,
        }

        # Vyčištění starých/nepoužívaných zařízení před registrací nových
        await _cleanup_unused_devices(hass, entry)

        # Vždy registrovat sensor platform
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

        await async_setup_entry_services(hass, entry)

        # Přidáme listener pro změny konfigurace - OPRAVEN callback na async funkci
        entry.async_on_unload(entry.add_update_listener(async_update_options))

        _LOGGER.debug("OIG Cloud integration setup complete")
        return True

    except Exception as e:
        _LOGGER.error(f"Error initializing OIG Cloud: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Error initializing OIG Cloud: {e}") from e


async def _setup_telemetry(hass: core.HomeAssistant, username: str) -> None:
    """Setup telemetry if enabled."""
    try:
        email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
        hass_id = hashlib.sha256(hass.data["core.uuid"].encode("utf-8")).hexdigest()

        # Přesuneme import do async executor aby neblokoval event loop
        def _import_and_setup_telemetry() -> None:
            from .shared.tracing import setup_tracing

            setup_tracing(email_hash, hass_id)

        await hass.async_add_executor_job(_import_and_setup_telemetry)
    except Exception as e:
        _LOGGER.warning(f"Failed to setup telemetry: {e}")
        # Pokračujeme bez telemetrie


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Odstranění služeb
    from .services import async_unload_services

    await async_unload_services(hass)

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


async def async_update_options(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> None:
    """Update options."""
    # Pokud byla označena potřeba reload, proveď ho
    if config_entry.options.get("_needs_reload"):
        # Odstraň _needs_reload flag a reload
        new_options = dict(config_entry.options)
        new_options.pop("_needs_reload", None)

        # Aktualizuj options bez _needs_reload
        hass.config_entries.async_update_entry(config_entry, options=new_options)

        # Naplánuj reload
        hass.async_create_task(hass.config_entries.async_reload(config_entry.entry_id))


async def _cleanup_unused_devices(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Vyčištění nepoužívaných zařízení."""
    try:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Najdeme všechna zařízení pro tuto integraci
        devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)

        devices_to_remove = []

        for device in devices:
            device_name = device.name or ""
            should_keep = True

            # Definujeme pravidla pro zachování zařízení
            keep_patterns = [
                "ČEZ Battery Box",
                "OIG Cloud Home",
                "Analytics & Predictions",
                "ServiceShield",
            ]

            # Definujeme pravidla pro odstranění zařízení
            remove_patterns = [
                "OIG Cloud Shield",  # Staré duplicity
                "OIG.*Statistics",  # Staré statistiky (regex pattern)
            ]

            # Zkontrolujeme, jestli zařízení odpovídá keep patterns
            for pattern in keep_patterns:
                if pattern in device_name:
                    should_keep = True
                    break
            else:
                # Pokud neodpovídá keep patterns, zkontrolujeme remove patterns
                import re

                for pattern in remove_patterns:
                    if re.search(pattern, device_name):
                        should_keep = False
                        break

            if not should_keep:
                # Zkontrolujeme, jestli zařízení nemá žádné entity
                device_entities = er.async_entries_for_device(
                    entity_registry, device.id
                )
                if not device_entities:  # Žádné entity = můžeme smazat
                    devices_to_remove.append(device)
                    _LOGGER.info(
                        f"Marking device for removal: {device.name} (ID: {device.id})"
                    )
                else:
                    _LOGGER.debug(
                        f"Device {device.name} has {len(device_entities)} entities, keeping"
                    )
            else:
                _LOGGER.debug(f"Keeping device: {device.name} (ID: {device.id})")

        # Smažeme nepoužívaná zařízení
        for device in devices_to_remove:
            try:
                _LOGGER.info(f"Removing unused device: {device.name} (ID: {device.id})")
                device_registry.async_remove_device(device.id)
            except Exception as e:
                _LOGGER.warning(f"Error removing device {device.id}: {e}")

        if devices_to_remove:
            _LOGGER.info(f"Removed {len(devices_to_remove)} unused devices")
        else:
            _LOGGER.debug("No unused devices found to remove")

    except Exception as e:
        _LOGGER.warning(f"Error cleaning up devices: {e}")


async def _register_services(hass: HomeAssistant) -> None:
    """Registrace služeb pro OIG Cloud."""
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv

    async def handle_update_solar_forecast(call: ServiceCall) -> None:
        """Handle update solar forecast service call."""
        entity_id = call.data.get("entity_id")

        updated_count = 0

        try:
            if entity_id:
                # Update specific sensor
                entity = hass.states.get(entity_id)
                if entity and entity.attributes.get("integration") == DOMAIN:
                    # Najdeme odpovídající senzor a spustíme manuální update
                    for entry_id, entry_data in hass.data[DOMAIN].items():
                        if entry_id == "shield":  # Skip shield data
                            continue
                        # Najdeme solar forecast senzory pro tento entry
                        solar_sensors = entry_data.get("solar_forecast_sensors", [])
                        for sensor in solar_sensors:
                            if (
                                hasattr(sensor, "entity_id")
                                and sensor.entity_id == entity_id
                            ):
                                if hasattr(sensor, "async_manual_update"):
                                    success = await sensor.async_manual_update()
                                    if success:
                                        updated_count += 1
                                        _LOGGER.info(
                                            f"🌞 Manual update completed for {entity_id}"
                                        )
                                    else:
                                        _LOGGER.error(
                                            f"🌞 Manual update failed for {entity_id}"
                                        )
                                else:
                                    # Fallback - zavolej fetch_forecast_data přímo
                                    await sensor.async_fetch_forecast_data()
                                    updated_count += 1
                                    _LOGGER.info(
                                        f"🌞 Manual update completed for {entity_id}"
                                    )
                                break
                else:
                    _LOGGER.warning(
                        f"Entity {entity_id} not found or not from OIG Cloud"
                    )
            else:
                # Update all solar forecast sensors across all entries
                for entry_id, entry_data in hass.data[DOMAIN].items():
                    if entry_id == "shield":  # Skip shield data
                        continue
                    solar_sensors = entry_data.get("solar_forecast_sensors", [])
                    for sensor in solar_sensors:
                        try:
                            if hasattr(sensor, "async_manual_update"):
                                success = await sensor.async_manual_update()
                                if success:
                                    updated_count += 1
                            elif hasattr(sensor, "async_fetch_forecast_data"):
                                await sensor.async_fetch_forecast_data()
                                updated_count += 1
                        except Exception as e:
                            _LOGGER.error(
                                f"Error updating solar forecast sensor {getattr(sensor, 'entity_id', 'unknown')}: {e}"
                            )

                _LOGGER.info(
                    f"🌞 Manual update completed for {updated_count} solar forecast sensors"
                )

        except Exception as e:
            _LOGGER.error(f"Error in solar forecast service: {e}")

    # Registrace služby
    hass.services.async_register(
        DOMAIN,
        "update_solar_forecast",
        handle_update_solar_forecast,
        schema=vol.Schema(
            {
                vol.Optional("entity_id"): cv.entity_id,
            }
        ),
    )

    _LOGGER.debug("OIG Cloud services registered")
