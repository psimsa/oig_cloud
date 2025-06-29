"""OIG Cloud Data Update Coordinator."""

import asyncio
import logging
import time
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

        # Initialize extended data attributes
        self._extended_enabled: bool = config_entry.data.get(
            "extended_data_enabled", False
        )
        self._extended_update_interval: int = config_entry.data.get(
            "extended_update_interval", 300
        )  # 5 minutes default
        self._last_extended_update: Optional[float] = None

        # NOVÉ: Debug logování extended nastavení
        _LOGGER.info(
            f"Extended data configuration: enabled={self._extended_enabled}, interval={self._extended_update_interval}s"
        )

        # Initialize notification manager reference
        self.notification_manager: Optional[Any] = None

    async def _fetch_basic_data(self) -> Dict[str, Any]:
        """Fetch basic data from API."""
        try:
            data = await self.api.get_basic_data()
            return {"basic": data}
        except OigCloudApiError as e:
            _LOGGER.error(f"Error fetching basic data: {e}")
            raise UpdateFailed(f"Failed to fetch basic data: {e}")

    async def _fetch_extended_data(self) -> Dict[str, Any]:
        """Fetch extended data from API."""
        try:
            data = await self.api.get_extended_data()
            return {"extended": data}
        except OigCloudApiError as e:
            _LOGGER.error(f"Error fetching extended data: {e}")
            raise UpdateFailed(f"Failed to fetch extended data: {e}")

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            combined_data = {}

            # 1. Základní data - vždy načíst
            basic_data = await self._fetch_basic_data()
            combined_data.update(basic_data)

            # 2. Extended data - načíst jen pokud je povoleno a je čas
            current_time = time.time()

            if self._extended_enabled:
                time_since_last = None
                if self._last_extended_update is not None:
                    time_since_last = current_time - self._last_extended_update

                if (
                    self._last_extended_update is None
                    or time_since_last >= self._extended_update_interval
                ):
                    _LOGGER.info(f"Fetching extended data")
                    try:
                        extended_data = await self._fetch_extended_data()
                        combined_data.update(extended_data)
                        self._last_extended_update = current_time
                        _LOGGER.debug("Extended data updated successfully")
                    except Exception as e:
                        _LOGGER.error(f"Extended data fetch failed: {e}")

            # 3. Aktualizace notifikací - pokud existuje notification manager
            if hasattr(self, "notification_manager") and self.notification_manager:
                try:
                    # KONTROLA: Možná se API objekt dostal do špatného stavu
                    _LOGGER.debug(
                        f"Notification manager API type: {type(self.notification_manager._api)}"
                    )
                    _LOGGER.debug(f"Coordinator API type: {type(self.api)}")

                    # MOŽNÁ OPRAVA: Pokud API objekt chybí, použij coordinator API
                    if not hasattr(self.notification_manager._api, "get_notifications"):
                        _LOGGER.warning(
                            "Notification manager API object doesn't have get_notifications, updating reference"
                        )
                        self.notification_manager._api = self.api

                    await self.notification_manager.update_from_api()
                    _LOGGER.debug("Notification data updated successfully")
                except Exception as e:
                    _LOGGER.warning(
                        f"Notification data fetch failed (non-critical): {e}"
                    )
                    # Neházeme chybu - notifikace nejsou kritické pro fungování integrace

            return combined_data

        except Exception as e:
            _LOGGER.error(f"Error in _async_update_data: {e}", exc_info=True)
            raise UpdateFailed(f"Error communicating with API: {e}")
