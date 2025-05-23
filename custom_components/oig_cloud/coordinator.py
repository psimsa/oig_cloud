"""OIG Cloud Data Update Coordinator."""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.oig_cloud_api import OigCloudApi, OigCloudApiError
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .shared.tracing import setup_tracer

_LOGGER = logging.getLogger(__name__)
tracer = setup_tracer(__name__) # Assuming setup_tracer returns a compatible Tracer object


class OigCloudDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching OIG Cloud data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OigCloudApi,
        config_entry: ConfigEntry,
        update_interval: Optional[timedelta] = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval or timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        with tracer.start_as_current_span("_async_update_data"):
            try:
                _LOGGER.debug("Fetching OIG Cloud data")
                data = await self.api.get_data() # Assuming get_data() returns Dict[str, Any]
                if not data: # This check implies data could be None or empty.
                             # If api.get_data() can return None, the type hint for it should be Optional.
                             # However, since UpdateFailed is raised, the coordinator itself won't return None on success.
                    _LOGGER.warning("No data received from OIG Cloud API")
                    raise UpdateFailed("No data received from OIG Cloud API")
                return data # Type Dict[str, Any]
            except OigCloudApiError as err:
                _LOGGER.error(f"Error fetching OIG Cloud data: {err}")
                raise UpdateFailed(f"Error fetching OIG Cloud data: {err}") from err
            except asyncio.TimeoutError as err: # Add err for context if needed by logger
                _LOGGER.error("Timeout error fetching OIG Cloud data")
                raise UpdateFailed("Timeout error fetching OIG Cloud data") from err
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception(f"Unexpected error fetching OIG Cloud data: {err}")
                raise UpdateFailed(f"Unexpected error fetching OIG Cloud data: {err}") from err