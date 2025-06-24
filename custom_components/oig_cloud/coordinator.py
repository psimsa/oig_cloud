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

_LOGGER = logging.getLogger(__name__)


class OigCloudDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching OIG Cloud data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OigCloudApi,
        config_entry: ConfigEntry,
        update_interval: Optional[timedelta] = None,
    ) -> None:
        """Initialize the coordinator."""
        # Get update interval from config entry data or use provided interval or default
        configured_interval = config_entry.data.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL
        )
        effective_interval = update_interval or timedelta(seconds=configured_interval)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=effective_interval,
            config_entry=config_entry,
        )
        self.api = api

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            _LOGGER.debug("Fetching OIG Cloud data")
            data = await self.api.get_data()
            if not data:
                _LOGGER.warning("No data received from OIG Cloud API")
                raise UpdateFailed("No data received from OIG Cloud API")

            # Log detailed information about received data
            _LOGGER.debug(
                "Successfully fetched OIG Cloud data with %d entries", len(data)
            )

            # Log key data values for debugging
            for key, value in data.items():
                if isinstance(value, (int, float)):
                    _LOGGER.debug("Data received: %s = %s", key, value)
                elif isinstance(value, dict):
                    _LOGGER.debug(
                        "Data received: %s = %s (dict with %d keys)",
                        key,
                        str(value)[:100],
                        len(value),
                    )
                else:
                    _LOGGER.debug("Data received: %s = %s", key, str(value)[:100])

            return data
        except OigCloudApiError as err:
            _LOGGER.error("Error fetching OIG Cloud data: %s", err)
            raise UpdateFailed(f"Error fetching OIG Cloud data: {err}")
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout error fetching OIG Cloud data")
            raise UpdateFailed("Timeout error fetching OIG Cloud data")
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error fetching OIG Cloud data: %s", err)
            raise UpdateFailed(f"Unexpected error fetching OIG Cloud data: {err}")
