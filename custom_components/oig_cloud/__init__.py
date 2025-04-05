"""OIG Cloud integration for Home Assistant."""
import asyncio
import logging
import hashlib
from datetime import timedelta
from typing import Any, Dict, Optional

from opentelemetry import trace

from .api import oig_cloud_api

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .api.oig_cloud_api import OigCloudApi, OigCloudApiError, OigCloudAuthError
from .const import (
    CONF_NO_TELEMETRY,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    DEFAULT_UPDATE_INTERVAL,
)
from .coordinator import OigCloudDataUpdateCoordinator
from .services import async_setup_entry_services
from .shared.tracing import setup_tracing
from .shared.logging import setup_otel_logging

PLATFORMS = ["sensor", "binary_sensor"]

tracer = trace.get_tracer(__name__)
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the OIG Cloud integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up OIG Cloud from a config entry."""
    try:
        username: str = entry.data[CONF_USERNAME]
        password: str = entry.data[CONF_PASSWORD]

        # Get settings from options or data with fallbacks
        no_telemetry: bool = entry.options.get(
            CONF_NO_TELEMETRY,
            entry.data.get(CONF_NO_TELEMETRY, False)
        )
        
        update_interval: int = entry.options.get(
            CONF_UPDATE_INTERVAL,
            DEFAULT_UPDATE_INTERVAL
        )

        # Setup telemetry if enabled
        if not no_telemetry:
            email_hash: str = hashlib.sha256(username.encode("utf-8")).hexdigest()
            hass_id: str = hashlib.sha256(hass.data["core.uuid"].encode("utf-8")).hexdigest()

            # Set up tracing and logging in a non-blocking way
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, setup_tracing, email_hash, hass_id)

            api_logger: logging.Logger = logging.getLogger(oig_cloud_api.__name__)
            otel_logging_handler = await loop.run_in_executor(None, setup_otel_logging, email_hash, hass_id)
            api_logger.addHandler(otel_logging_handler)

            _LOGGER.info(f"Telemetry enabled with account hash {email_hash}")
            _LOGGER.info(f"Home Assistant ID hash is {hass_id}")
        else:
            _LOGGER.info("Telemetry disabled by user configuration")

        # Create the API client
        _LOGGER.debug("Creating OIG Cloud API client")
        oig_api: OigCloudApi = OigCloudApi(username, password, no_telemetry, hass)

        try:
            # Try authentication
            _LOGGER.debug("Authenticating with OIG Cloud API")
            await oig_api.authenticate()
        except OigCloudAuthError as err:
            _LOGGER.error("Authentication failed with OIG Cloud API")
            raise ConfigEntryNotReady("Authentication failed with OIG Cloud API") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error during authentication")
            raise ConfigEntryNotReady("Unexpected error during OIG Cloud setup") from err

        # Create the coordinator
        _LOGGER.debug(f"Creating OIG Cloud data coordinator with update interval of {update_interval} seconds")
        coordinator = OigCloudDataUpdateCoordinator(
            hass,
            oig_api,
            config_entry=entry,
            update_interval=timedelta(seconds=update_interval),
        )

        # Fetch initial data
        _LOGGER.debug("Fetching initial data from OIG Cloud API")
        await coordinator.async_config_entry_first_refresh()

        if not coordinator.last_update_success:
            _LOGGER.error("Failed to retrieve initial data from OIG Cloud API")
            raise ConfigEntryNotReady("Initial data fetch failed")

        _LOGGER.debug("Successfully fetched initial data from OIG Cloud API")

        # Store coordinator and API client in hass.data
        hass.data[DOMAIN][entry.entry_id] = {
            "coordinator": coordinator,
            "api": oig_api,
        }

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Setup services
        _LOGGER.debug("Setting up OIG Cloud services")
        await async_setup_entry_services(hass, entry)
        
        # Register update listener for option changes
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        _LOGGER.info("OIG Cloud setup completed successfully")
        return True
    except OigCloudAuthError as err:
        _LOGGER.error(f"Authentication error with OIG Cloud: {err}")
        raise ConfigEntryNotReady("Authentication failed with OIG Cloud API") from err
    except OigCloudApiError as err:
        _LOGGER.error(f"API error with OIG Cloud: {err}")
        raise ConfigEntryNotReady(f"Error communicating with OIG Cloud API: {err}") from err
    except Exception as err:
        _LOGGER.exception(f"Unexpected error setting up OIG Cloud: {err}")
        raise ConfigEntryNotReady(f"Unexpected error during OIG Cloud setup: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the OIG Cloud config entry."""
    _LOGGER.debug(f"Unloading OIG Cloud integration for {entry.entry_id}")
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        _LOGGER.debug(f"Successfully unloaded platforms for {entry.entry_id}")
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload OIG Cloud config entry."""
    _LOGGER.debug(f"Reloading OIG Cloud integration for {entry.entry_id}")
    
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
