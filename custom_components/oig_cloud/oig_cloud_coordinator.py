import logging
from datetime import timedelta, datetime
from typing import Dict, Any, Optional, Tuple
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import now as dt_now, utcnow as dt_utcnow
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)


class OigCloudCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        api: OigCloudApi,
        standard_interval_seconds: int = 30,
        extended_interval_seconds: int = 300,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="OIG Cloud Coordinator",
            update_interval=timedelta(seconds=standard_interval_seconds),
        )

        self.api = api
        self.standard_interval = standard_interval_seconds
        self.extended_interval = extended_interval_seconds

        self.extended_data: Dict[str, Any] = {}
        self._last_extended_update: Optional[datetime] = None

        _LOGGER.info(
            f"Coordinator initialized with intervals: standard={standard_interval_seconds}s, extended={extended_interval_seconds}s"
        )

    def update_intervals(self, standard_interval: int, extended_interval: int) -> None:
        """Dynamicky aktualizuje intervaly coordinatoru."""
        # Uložíme původní hodnoty pro logování
        old_standard = self.update_interval.total_seconds()
        old_extended = self.extended_interval

        self.standard_interval = standard_interval
        self.extended_interval = extended_interval

        # Aktualizujeme update_interval coordinatoru
        self.update_interval = timedelta(seconds=standard_interval)

        _LOGGER.info(
            f"Coordinator intervals updated: standard {old_standard}s→{standard_interval}s, "
            f"extended {old_extended}s→{extended_interval}s"
        )

        # Vynutíme okamžitou aktualizaci s novým intervalem
        self.hass.async_create_task(self.async_request_refresh())

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch standard and extended stats and update sensors."""
        try:
            _LOGGER.debug("Fetching standard stats")
            stats = await self._try_get_stats()

            # Kontrola, zda jsou extended senzory povolené
            config_entry = None
            for entry in self.hass.config_entries.async_entries("oig_cloud"):
                if entry.entry_id in self.hass.data.get("oig_cloud", {}):
                    if (
                        self.hass.data["oig_cloud"][entry.entry_id].get("coordinator")
                        == self
                    ):
                        config_entry = entry
                        break

            extended_enabled = (
                config_entry.options.get("enable_extended_sensors", False)
                if config_entry
                else False
            )

            if extended_enabled and self._should_update_extended():
                _LOGGER.debug("Fetching extended stats (FVE, LOAD, BATT, GRID)")
                try:
                    today_from, today_to = self._today_range()

                    extended_batt = await self.api.get_extended_stats(
                        "batt", today_from, today_to
                    )
                    extended_fve = await self.api.get_extended_stats(
                        "fve", today_from, today_to
                    )
                    extended_grid = await self.api.get_extended_stats(
                        "grid", today_from, today_to
                    )
                    extended_load = await self.api.get_extended_stats(
                        "load", today_from, today_to
                    )

                    self.extended_data = {
                        "extended_batt": extended_batt,
                        "extended_fve": extended_fve,
                        "extended_grid": extended_grid,
                        "extended_load": extended_load,
                    }

                    self._last_extended_update = dt_utcnow()
                    _LOGGER.debug("Extended stats updated successfully")

                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch extended stats: {e}")
                    # Pokračujeme s prázdnými extended daty
                    self.extended_data = {}
            else:
                _LOGGER.debug("Extended sensors disabled or not time for update")

            # Sloučíme standardní a extended data
            result = stats.copy() if stats else {}
            result.update(self.extended_data)

            return result

        except Exception as exception:
            _LOGGER.error(f"Error updating data: {exception}")
            raise UpdateFailed(
                f"Error communicating with OIG API: {exception}"
            ) from exception

    async def _try_get_stats(self) -> Optional[Dict[str, Any]]:
        """Wrapper na načítání standardních statistik s ošetřením chyb."""
        try:
            return await self.api.get_stats()
        except Exception as e:
            _LOGGER.error(f"Error fetching standard stats: {e}", exc_info=True)
            raise e

    def _today_range(self) -> Tuple[str, str]:
        """Vrátí dnešní datum jako string tuple pro API."""
        today = dt_now().date()
        today_str = today.strftime("%Y-%m-%d")
        return today_str, today_str

    def _should_update_extended(self) -> bool:
        """Určí, zda je čas aktualizovat extended data."""
        if self._last_extended_update is None:
            return True
        now = dt_utcnow()
        delta = now - self._last_extended_update
        return delta.total_seconds() > self.extended_interval
