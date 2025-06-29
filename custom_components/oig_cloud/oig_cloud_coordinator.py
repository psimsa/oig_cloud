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
        config_entry: Optional[Any] = None,
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
        self.config_entry = config_entry  # NOVÉ: Uložit config_entry

        self.extended_data: Dict[str, Any] = {}
        self._last_extended_update: Optional[datetime] = None

        # NOVÉ: Přidání notification manager support
        self.notification_manager: Optional[Any] = None

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            _LOGGER.debug("Fetching standard stats")
            stats = await self._try_get_stats()

            # NOVÉ: Inicializovat notification manager pokud ještě není
            if (
                not hasattr(self, "notification_manager")
                or self.notification_manager is None
            ):
                _LOGGER.debug("Initializing notification manager")
                try:
                    from .oig_cloud_notification import OigNotificationManager

                    # NOVÉ: Použít get_session() z API pro sdílení autentifikace
                    self.notification_manager = OigNotificationManager(
                        self.hass, self.api, "https://www.oigpower.cz"
                    )
                    _LOGGER.debug("Notification manager initialized with API session")
                except Exception as e:
                    _LOGGER.error(f"Failed to initialize notification manager: {e}")
                    self.notification_manager = None

            # NOVÉ: Debug notification manager status
            _LOGGER.debug(
                f"Notification manager status: {hasattr(self, 'notification_manager')}"
            )
            if hasattr(self, "notification_manager"):
                _LOGGER.debug(
                    f"Notification manager value: {self.notification_manager}"
                )
                _LOGGER.debug(
                    f"Notification manager is None: {self.notification_manager is None}"
                )
                if self.notification_manager is not None:
                    _LOGGER.debug(
                        f"Notification manager ready: device_id={getattr(self.notification_manager, '_device_id', None)}"
                    )
            else:
                _LOGGER.debug(
                    "Coordinator does not have notification_manager attribute"
                )

            # OPRAVA: Použít uložený config_entry místo hledání
            config_entry = self.config_entry
            extended_enabled = False

            if config_entry:
                extended_enabled = config_entry.options.get(
                    "enable_extended_sensors", False
                )
                _LOGGER.debug(f"Config entry found: True")
                _LOGGER.debug(f"Config entry options: {config_entry.options}")
                _LOGGER.debug(
                    f"Extended sensors enabled from options: {extended_enabled}"
                )
            else:
                _LOGGER.warning("No config entry available for this coordinator")

            should_update_extended = self._should_update_extended()
            _LOGGER.debug(f"Should update extended: {should_update_extended}")
            _LOGGER.debug(f"Last extended update: {self._last_extended_update}")
            _LOGGER.debug(f"Extended interval: {self.extended_interval}s")

            if extended_enabled and should_update_extended:
                _LOGGER.info("Fetching extended stats (FVE, LOAD, BATT, GRID)")
                try:
                    today_from, today_to = self._today_range()
                    _LOGGER.debug(
                        f"Date range for extended stats: {today_from} to {today_to}"
                    )

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

                    # OPRAVA: Používat lokální čas místo UTC
                    self._last_extended_update = dt_now()
                    _LOGGER.debug("Extended stats updated successfully")

                    # NOVÉ: Aktualizovat notifikace současně s extended daty
                    if (
                        hasattr(self, "notification_manager")
                        and self.notification_manager
                        and hasattr(self.notification_manager, "_device_id")
                        and self.notification_manager._device_id is not None
                    ):
                        try:
                            _LOGGER.debug(
                                "Refreshing notification data with extended stats"
                            )
                            await self.notification_manager.refresh_data()
                            _LOGGER.debug("Notification data updated successfully")
                        except Exception as e:
                            _LOGGER.debug(f"Notification data fetch failed: {e}")
                    else:
                        _LOGGER.debug(
                            "Notification manager not ready for extended data refresh - device_id not set yet"
                        )

                except Exception as e:
                    _LOGGER.warning(f"Failed to fetch extended stats: {e}")
                    # Pokračujeme s prázdnými extended daty
                    self.extended_data = {}
            elif not extended_enabled:
                _LOGGER.debug("Extended sensors disabled in configuration")

                # NOVÉ: I když extended nejsou povoleny, aktualizovat notifikace samostatně
                if (
                    hasattr(self, "notification_manager")
                    and self.notification_manager
                    and hasattr(self.notification_manager, "_device_id")
                    and self.notification_manager._device_id is not None
                ):
                    # Aktualizovat notifikace každých 5 minut i bez extended dat
                    if not hasattr(self, "_last_notification_update"):
                        self._last_notification_update = None

                    now = dt_now()
                    should_refresh_notifications = False

                    if self._last_notification_update is None:
                        should_refresh_notifications = True
                    else:
                        time_since_notification = (
                            now - self._last_notification_update
                        ).total_seconds()
                        if time_since_notification >= 300:  # 5 minut
                            should_refresh_notifications = True

                    if should_refresh_notifications:
                        try:
                            _LOGGER.debug("Refreshing notification data (standalone)")
                            await self.notification_manager.refresh_data()
                            self._last_notification_update = now
                            _LOGGER.debug(
                                "Standalone notification data updated successfully"
                            )
                        except Exception as e:
                            _LOGGER.debug(
                                f"Standalone notification data fetch failed: {e}"
                            )
                else:
                    _LOGGER.debug(
                        "Notification manager not available for standalone refresh - device_id not set yet"
                    )

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
        # OPRAVA: Používat lokální čas místo UTC pro konzistenci
        now = dt_now()
        # Pokud _last_extended_update je v UTC, převést na lokální čas
        if self._last_extended_update.tzinfo is not None:
            # Převést UTC na lokální čas
            last_update_local = self._last_extended_update.astimezone(now.tzinfo)
            delta = now - last_update_local
        else:
            # Předpokládat že je už v lokálním čase
            delta = now - self._last_extended_update

        time_diff = delta.total_seconds()
        _LOGGER.debug(
            f"Extended time check: now={now.strftime('%H:%M:%S')}, last_update={self._last_extended_update.strftime('%H:%M:%S')}, diff={time_diff:.1f}s, interval={self.extended_interval}s"
        )

        return time_diff > self.extended_interval
