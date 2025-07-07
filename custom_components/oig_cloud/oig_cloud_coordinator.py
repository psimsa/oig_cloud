import logging
import asyncio
from datetime import timedelta, datetime, time
from typing import Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo  # Nahradit pytz import
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

        # Battery forecast data
        self.battery_forecast_data: Optional[Dict[str, Any]] = None

        # NOVÉ: OTE API inicializace - OPRAVA logiky
        spot_prices_enabled = self.config_entry and self.config_entry.options.get(
            "enable_spot_prices", False
        )

        if spot_prices_enabled:
            try:
                _LOGGER.debug("Spot prices enabled - initializing OTE API")
                from .api.ote_api import OteApi

                self.ote_api = OteApi()

                # Naplánovat aktualizaci na příští den ve 13:00
                # OPRAVA: Použít zoneinfo místo pytz
                now = datetime.now(ZoneInfo("Europe/Prague"))
                next_update = now.replace(hour=13, minute=0, second=0, microsecond=0)
                if next_update <= now:
                    next_update += timedelta(days=1)

                _LOGGER.debug(f"Next spot price update scheduled for: {next_update}")

                # NOVÉ: Naplánovat fallback hodinové kontroly
                self._schedule_hourly_fallback()

            except Exception as e:
                _LOGGER.error(f"Failed to initialize OTE API: {e}")
                self.ote_api = None
        else:
            _LOGGER.debug("Spot prices disabled - not initializing OTE API")
            self.ote_api = None

        # NOVÉ: Sledování posledního stažení spotových cen
        self._last_spot_fetch: Optional[datetime] = None
        self._spot_retry_count: int = 0
        self._max_spot_retries: int = 20  # 20 * 15min = 5 hodin retry
        self._hourly_fallback_active: bool = False  # NOVÉ: flag pro hodinový fallback

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

    def _schedule_spot_price_update(self) -> None:
        """Naplánuje aktualizaci spotových cen."""
        now = dt_now()
        today_13 = now.replace(hour=13, minute=0, second=0, microsecond=0)

        # Pokud je už po 13:00 dnes, naplánujeme na zítra
        if now >= today_13:
            next_update = today_13 + timedelta(days=1)
        else:
            next_update = today_13

        _LOGGER.debug(f"Next spot price update scheduled for: {next_update}")

        # Naplánujeme callback
        async def spot_price_callback(now: datetime) -> None:
            await self._update_spot_prices()

        self.hass.helpers.event.async_track_point_in_time(
            spot_price_callback, next_update
        )

    def _schedule_hourly_fallback(self) -> None:
        """Naplánuje hodinové fallback stahování OTE dat."""
        from homeassistant.helpers.event import async_track_time_interval

        # Spustit každou hodinu
        self.hass.loop.call_later(
            3600,  # 1 hodina
            lambda: self.hass.async_create_task(self._hourly_fallback_check()),
        )

    async def _hourly_fallback_check(self) -> None:
        """Hodinová kontrola a případné stahování OTE dat."""
        if not self.ote_api:
            return

        now = dt_now()

        # Kontrola, jestli máme aktuální data
        needs_data = False

        if hasattr(self, "data") and self.data and "spot_prices" in self.data:
            spot_data = self.data["spot_prices"]

            # Před 13:00 - kontrolujeme jestli máme dnešní data
            if now.hour < 13:
                today_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
                if today_key not in spot_data.get("prices_czk_kwh", {}):
                    needs_data = True
                    _LOGGER.debug(
                        f"Missing today's data for hour {now.hour}, triggering fallback"
                    )

            # Po 13:00 - kontrolujeme jestli máme zítřejší data
            else:
                tomorrow = now + timedelta(days=1)
                tomorrow_key = f"{tomorrow.strftime('%Y-%m-%d')}T00:00:00"
                if tomorrow_key not in spot_data.get("prices_czk_kwh", {}):
                    needs_data = True
                    _LOGGER.debug(
                        "Missing tomorrow's data after 13:00, triggering fallback"
                    )
        else:
            # Žádná data vůbec
            needs_data = True
            _LOGGER.debug("No spot price data available, triggering fallback")

        if needs_data:
            self._hourly_fallback_active = True
            try:
                _LOGGER.info(
                    "Hourly fallback: Attempting to fetch spot prices from OTE"
                )

                # Upravit OTE API call podle času
                if now.hour < 13:
                    # Před 13:00 - stahujeme pouze dnešek
                    _LOGGER.debug("Before 13:00 - fetching today's data only")
                    spot_data = await self.ote_api.get_spot_prices()
                else:
                    # Po 13:00 - stahujeme dnes + zítra
                    _LOGGER.debug("After 13:00 - fetching today + tomorrow data")
                    spot_data = await self.ote_api.get_spot_prices()

                if spot_data and spot_data.get("prices_czk_kwh"):
                    # Aktualizujeme data v koordinátoru
                    if hasattr(self, "data") and self.data:
                        self.data["spot_prices"] = spot_data
                        self.async_update_listeners()

                    _LOGGER.info(
                        f"Hourly fallback: Successfully updated spot prices: {spot_data.get('hours_count', 0)} hours"
                    )
                    self._last_spot_fetch = dt_now()
                    self._hourly_fallback_active = False
                else:
                    _LOGGER.warning(
                        "Hourly fallback: No valid spot price data received"
                    )

            except Exception as e:
                _LOGGER.warning(f"Hourly fallback: Failed to update spot prices: {e}")
            finally:
                self._hourly_fallback_active = False

        # Naplánuj další hodinovou kontrolu
        self._schedule_hourly_fallback()

    async def _update_spot_prices(self) -> None:
        """Aktualizace spotových cen s lepším error handling."""
        if not self.ote_api:
            return

        try:
            _LOGGER.info(
                "Attempting to update spot prices from OTE (scheduled 13:00 update)"
            )
            spot_data = await self.ote_api.get_spot_prices()

            if spot_data and spot_data.get("prices_czk_kwh"):
                _LOGGER.info(
                    f"Successfully updated spot prices: {spot_data.get('hours_count', 0)} hours"
                )
                self._last_spot_fetch = dt_now()
                self._spot_retry_count = 0
                self._hourly_fallback_active = (
                    False  # NOVÉ: vypnout fallback po úspěšném stažení
                )

                # Uložíme data do coordinator dat
                if hasattr(self, "data") and self.data:
                    self.data["spot_prices"] = spot_data
                    self.async_update_listeners()

                # Naplánujeme další aktualizaci na zítra ve 13:00
                self._schedule_spot_price_update()

            else:
                _LOGGER.warning("No valid spot price data received from OTE API")
                self._handle_spot_retry()

        except Exception as e:
            _LOGGER.warning(f"Failed to update spot prices: {e}")
            self._handle_spot_retry()

    def _handle_spot_retry(self) -> None:
        """Handle spot price retry logic - pouze pro scheduled updates."""
        self._spot_retry_count += 1

        # Omezit retry pouze na důležité časy (kolem 13:00)
        now = dt_now()
        is_important_time = 12 <= now.hour <= 15  # Retry pouze 12-15h

        if self._spot_retry_count < 3 and is_important_time:  # Snížit max retries
            # Zkusíme znovu za 30 minut místo 15
            retry_time = dt_now() + timedelta(minutes=30)
            _LOGGER.info(
                f"Retrying spot price update in 30 minutes (attempt {self._spot_retry_count + 1}/3)"
            )

            async def retry_callback() -> None:
                await asyncio.sleep(30 * 60)  # 30 minutes
                await self._update_spot_prices()

            asyncio.create_task(retry_callback())
        else:
            if not is_important_time:
                _LOGGER.info(
                    "OTE API error outside important hours (12-15h), skipping retries until tomorrow"
                )
            else:
                _LOGGER.error(
                    f"Failed to update spot prices after 3 attempts, giving up until tomorrow"
                )

            self._spot_retry_count = 0
            # Naplánujeme další pokus na zítra
            self._schedule_spot_price_update()

    async def _async_update_data(self) -> Dict[str, Any]:
        """Aktualizace základních dat."""
        try:
            # Standardní OIG data
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

            # Aktualizuj battery forecast pokud je povolen
            if self.config_entry and self.config_entry.options.get(
                "enable_battery_prediction", True
            ):
                await self._update_battery_forecast()

            # NOVÉ: Přidáme spotové ceny pokud jsou k dispozici
            if (
                self.ote_api
                and hasattr(self, "data")
                and self.data
                and "spot_prices" in self.data
            ):
                stats["spot_prices"] = self.data["spot_prices"]
                _LOGGER.debug("Including cached spot prices in coordinator data")
            elif self.ote_api and not hasattr(self, "_initial_spot_attempted"):
                # První pokus o získání spotových cen při startu
                self._initial_spot_attempted = True
                try:
                    _LOGGER.debug("Attempting initial spot price fetch")
                    spot_data = await self.ote_api.get_spot_prices()
                    if spot_data and spot_data.get("hours_count", 0) > 0:
                        stats["spot_prices"] = spot_data
                        _LOGGER.info("Initial spot price data loaded successfully")
                    else:
                        _LOGGER.warning("Initial spot price fetch returned empty data")
                except Exception as e:
                    _LOGGER.warning(f"Initial spot price fetch failed: {e}")
                    # Nebudeme dělat retry při inicializaci

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

    async def _update_battery_forecast(self) -> None:
        """Aktualizuje battery forecast data."""
        try:
            # Najdeme battery forecast senzor a použijeme jeho logiku
            from homeassistant.helpers import entity_registry as er

            entity_reg = er.async_get(self.hass)

            # Najdeme battery forecast entity
            entries = er.async_entries_for_config_entry(
                entity_reg, self.config_entry.entry_id
            )
            battery_forecast_entity = None

            for entry in entries:
                if "battery_forecast" in entry.entity_id:
                    battery_forecast_entity = self.hass.states.get(entry.entity_id)
                    break

            if battery_forecast_entity:
                # Získáme senzor object a spustíme výpočet
                from .oig_cloud_battery_forecast import OigCloudBatteryForecastSensor

                # Vytvoříme dočasnou instanci pro výpočet
                temp_sensor = OigCloudBatteryForecastSensor(
                    self, "battery_forecast", self.config_entry
                )
                temp_sensor._hass = self.hass

                # Spustíme výpočet
                self.battery_forecast_data = (
                    await temp_sensor._calculate_battery_forecast()
                )
                _LOGGER.debug("🔋 Battery forecast data updated in coordinator")
            else:
                _LOGGER.debug("🔋 Battery forecast entity not found")

        except Exception as e:
            _LOGGER.error(f"🔋 Failed to update battery forecast in coordinator: {e}")
            self.battery_forecast_data = None
