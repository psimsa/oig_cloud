import logging
from datetime import timedelta
from homeassistant.util.dt import now as dt_now, utcnow as dt_utcnow

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

class OigCloudCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api: OigCloudApi, standard_interval_seconds=30, extended_interval_seconds=300):
        super().__init__(
            hass,
            _LOGGER,
            name="OIG Cloud Coordinator",
            update_interval=timedelta(seconds=standard_interval_seconds),
        )

        self.api = api
        self.standard_interval = standard_interval_seconds
        self.extended_interval = extended_interval_seconds

        self.extended_data = {}
        self._last_extended_update = None

    async def _async_update_data(self):
        """Fetch standard and extended stats and update sensors."""
        _LOGGER.debug("Fetching standard stats")

        stats = await self._try_get_stats()

        if self._should_update_extended():
            _LOGGER.debug("Fetching extended stats (FVE, LOAD, BATT, GRID)")
            try:
                extended_batt = await self.api.get_extended_stats("batt", *self._today_range())
                extended_fve = await self.api.get_extended_stats("fve", *self._today_range())
                extended_grid = await self.api.get_extended_stats("grid", *self._today_range())
                extended_load = await self.api.get_extended_stats("load", *self._today_range())

                self.extended_data = {
                    "extended_batt": extended_batt,
                    "extended_fve": extended_fve,
                    "extended_grid": extended_grid,
                    "extended_load": extended_load,
                }

                self._last_extended_update = self.hass.helpers.event.dt_util.utcnow()
                _LOGGER.debug("Extended stats updated successfully")
            except Exception as e:
                _LOGGER.warning(f"Failed to update extended stats: {e}")

        # Sloučíme standardní a extended data
        result = stats.copy()
        result.update(self.extended_data)

        # TADY je klíčové – pošleme aktualizovaná data entitám
        self.async_set_updated_data(result)

        return result

    async def _try_get_stats(self):
        """Wrapper na načítání standardních statistik s ošetřením chyb."""
        try:
            return await self.api.get_stats()
        except Exception as e:
            _LOGGER.error(f"Error fetching standard stats: {e}", exc_info=True)
            raise e

    def _today_range(self):
        today = dt_now().date()
        today_str = today.strftime("%Y-%m-%d")
        return today_str, today_str
    
    def _should_update_extended(self):
        if self._last_extended_update is None:
            return True
        now = dt_utcnow()
        delta = now - self._last_extended_update
        return delta.total_seconds() > self.extended_interval
    