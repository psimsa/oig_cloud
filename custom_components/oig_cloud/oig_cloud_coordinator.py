import logging
from datetime import datetime, timedelta # Added datetime for type hints
from typing import Any, Dict, Optional, Tuple, Awaitable # Added necessary types

from homeassistant.core import HomeAssistant # For hass type hint
from homeassistant.util.dt import now as dt_now, utcnow as dt_utcnow
# from homeassistant.helpers import aiohttp_client # Unused import

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .api.oig_cloud_api import OigCloudApi, OigCloudApiError # Import OigCloudApiError for specific exceptions

_LOGGER = logging.getLogger(__name__)


class OigCloudCoordinator(DataUpdateCoordinator[Dict[str, Any]]): # Parameterized Coordinator
    def __init__(
        self,
        hass: HomeAssistant, # Typed hass
        api: OigCloudApi,
        standard_interval_seconds: int = 30, # Typed interval
        extended_interval_seconds: int = 300, # Typed interval
    ) -> None: # Return type for __init__
        super().__init__(
            hass,
            _LOGGER,
            name="OIG Cloud Coordinator", # Consider making this a constant or more dynamic if needed
            update_interval=timedelta(seconds=standard_interval_seconds),
        )

        self.api: OigCloudApi = api # Explicitly type attribute
        self.standard_interval: int = standard_interval_seconds # Explicitly type attribute
        self.extended_interval: int = extended_interval_seconds # Explicitly type attribute

        self.extended_data: Dict[str, Any] = {} # Typed attribute
        self._last_extended_update: Optional[datetime] = None # Typed attribute

    async def _async_update_data(self) -> Awaitable[Dict[str, Any]]:
        """Fetch standard and extended stats and update sensors."""
        _LOGGER.debug("Fetching standard stats")

        stats: Optional[Dict[str, Any]] = await self._try_get_stats()

        if stats is None:
            # If _try_get_stats failed and raised, it won't reach here.
            # If it returned None (e.g. auth error handled in API layer), then fail update.
            _LOGGER.warning("Failed to fetch standard stats, data is None.")
            raise UpdateFailed("Failed to fetch standard stats, data is None.")


        if self._should_update_extended():
            _LOGGER.debug("Fetching extended stats (FVE, LOAD, BATT, GRID)")
            try:
                # Types based on api.get_extended_stats return: Optional[Union[Dict[str, Any], list]]
                # Using Optional[Any] for simplicity here as structure might vary or be list.
                extended_batt: Optional[Any] = await self.api.get_extended_stats(
                    "batt", *self._today_range()
                )
                extended_fve: Optional[Any] = await self.api.get_extended_stats(
                    "fve", *self._today_range()
                )
                extended_grid: Optional[Any] = await self.api.get_extended_stats(
                    "grid", *self._today_range()
                )
                extended_load: Optional[Any] = await self.api.get_extended_stats(
                    "load", *self._today_range()
                )
                self.extended_data = { # Ensure keys match what entities expect
                    "extended_batt": extended_batt,
                    "extended_fve": extended_fve,
                    "extended_grid": extended_grid,
                    "extended_load": extended_load,
                }

                self._last_extended_update = dt_utcnow()
                _LOGGER.debug("Extended stats updated successfully")
            except OigCloudApiError as e: # Catch specific API errors
                _LOGGER.warning(f"Failed to update extended stats due to API error: {e}")
            except Exception as e: # Catch other unexpected errors
                _LOGGER.warning(f"Failed to update extended stats due to unexpected error: {e}", exc_info=True)
        
        # Merge standard and extended data
        # Ensure stats is not None before copying, already handled by check above.
        result: Dict[str, Any] = stats.copy() 
        result.update(self.extended_data)

        # The DataUpdateCoordinator base class handles self.async_set_updated_data(result)
        # if the update method returns the data. So, no explicit call needed here.
        return result

    async def _try_get_stats(self) -> Awaitable[Optional[Dict[str, Any]]]:
        """Wrapper for fetching standard statistics with error handling."""
        try:
            # Assuming self.api.get_stats() returns Optional[Dict[str, Any]]
            return await self.api.get_stats()
        except OigCloudApiError as e: # More specific error catching
            _LOGGER.error(f"API error fetching standard stats: {e}", exc_info=True)
            # Optionally, re-raise as UpdateFailed or return None if handled by caller
            # For this structure, re-raising specific UpdateFailed or letting caller handle None is better.
            # raise UpdateFailed(f"API error: {e}") from e 
            return None # Or re-raise if _async_update_data should always fail hard
        except Exception as e:
            _LOGGER.error(f"Unexpected error fetching standard stats: {e}", exc_info=True)
            # raise UpdateFailed(f"Unexpected error: {e}") from e
            return None # Or re-raise

    def _today_range(self) -> Tuple[str, str]:
        """Get today's date range as formatted strings."""
        today: datetime.date = dt_now().date() # dt_now() returns datetime, .date() gets date part
        today_str: str = today.strftime("%Y-%m-%d")
        return today_str, today_str

    def _should_update_extended(self) -> bool:
        """Determine if extended data should be updated based on interval."""
        if self._last_extended_update is None:
            return True
        now: datetime = dt_utcnow()
        delta: timedelta = now - self._last_extended_update
        return delta.total_seconds() > self.extended_interval
