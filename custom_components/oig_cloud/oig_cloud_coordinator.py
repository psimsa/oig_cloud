import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo  # Nahradit pytz import

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .data_source import DATA_SOURCE_CLOUD_ONLY, get_data_source_state
from .lib.oig_cloud_client.api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

# Jitter configuration: ±5 seconds around base interval
JITTER_SECONDS = 5.0

# HA storage snapshot (retain last-known values across restart)
COORDINATOR_CACHE_VERSION = 1
COORDINATOR_CACHE_SAVE_COOLDOWN_S = 30.0
COORDINATOR_CACHE_MAX_LIST_ITEMS = 1500
COORDINATOR_CACHE_MAX_STR_LEN = 5000


class OigCloudCoordinator(DataUpdateCoordinator):
    @staticmethod
    def _utcnow() -> datetime:
        """Return utcnow compatible with HA test stubs."""
        utcnow = getattr(dt_util, "utcnow", None)
        if callable(utcnow):
            return utcnow()
        return datetime.now(timezone.utc)

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
        self._battery_forecast_task: Optional[asyncio.Task] = None

        # Spot price cache shared between scheduler/fallback and coordinator updates
        self._spot_prices_cache: Optional[Dict[str, Any]] = None

        # NOVÉ: OTE API inicializace - OPRAVA logiky
        pricing_enabled = self.config_entry and self.config_entry.options.get(
            "enable_pricing", False
        )

        if pricing_enabled:
            try:
                _LOGGER.debug("Pricing enabled - initializing OTE API")
                from .api.ote_api import OteApi

                # OPRAVA: Předat cache_path pro načtení uložených spotových cen
                cache_path = hass.config.path(".storage", "oig_ote_spot_prices.json")
                self.ote_api = OteApi(cache_path=cache_path)

                # Load cached spot prices asynchronously (avoid blocking file I/O in event loop)
                async def _async_load_ote_cache() -> None:
                    try:
                        await self.ote_api.async_load_cached_spot_prices()
                        if self.ote_api._last_data:
                            self._spot_prices_cache = self.ote_api._last_data
                            _LOGGER.info(
                                "Loaded %d hours of cached spot prices from disk",
                                self.ote_api._last_data.get("hours_count", 0),
                            )
                    except Exception as err:
                        _LOGGER.debug(
                            "Failed to load OTE cache asynchronously: %s", err
                        )

                self.hass.async_create_task(_async_load_ote_cache())

                # Naplánovat aktualizaci na příští den ve 13:05 (OTE zveřejňuje kolem 13:00)
                # OPRAVA: Použít zoneinfo místo pytz
                now = datetime.now(ZoneInfo("Europe/Prague"))
                next_update = now.replace(hour=13, minute=5, second=0, microsecond=0)
                if next_update <= now:
                    next_update += timedelta(days=1)

                _LOGGER.debug(f"Next spot price update scheduled for: {next_update}")

                # NOVÉ: Naplánovat fallback hodinové kontroly
                self._schedule_hourly_fallback()

                # NOVĚ: Aktivovat i hlavní plánovač a provést první fetch asynchronně
                self._schedule_spot_price_update()
                self.hass.async_create_task(self._update_spot_prices())

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

        # NOVÉ: ČHMÚ API inicializace
        chmu_enabled = self.config_entry and self.config_entry.options.get(
            "enable_chmu_warnings", False
        )

        if chmu_enabled:
            try:
                _LOGGER.debug("ČHMÚ warnings enabled - initializing ČHMÚ API")
                from .api.api_chmu import ChmuApi

                self.chmu_api = ChmuApi()
                self.chmu_warning_data: Optional[Dict[str, Any]] = None

                _LOGGER.debug("ČHMÚ API initialized successfully")

            except Exception as e:
                _LOGGER.error(f"Failed to initialize ČHMÚ API: {e}")
                self.chmu_api = None
                self.chmu_warning_data = None
        else:
            _LOGGER.debug("ČHMÚ warnings disabled - not initializing ČHMÚ API")
            self.chmu_api = None
            self.chmu_warning_data = None

        _LOGGER.info(
            f"Coordinator initialized with intervals: standard={standard_interval_seconds}s, extended={extended_interval_seconds}s, jitter=±{JITTER_SECONDS}s"
        )

        # Startup grace period to avoid loading-heavy work during HA bootstrap
        self._startup_ts: datetime = self._utcnow()
        self._startup_grace_seconds: int = (
            int(config_entry.options.get("startup_grace_seconds", 30))
            if config_entry and hasattr(config_entry, "options")
            else 30
        )

        # Retain last-known coordinator payload to avoid "unknown" after HA restart.
        self._cache_store: Optional[Store] = None
        self._last_cache_save_ts: Optional[datetime] = None
        try:
            if self.config_entry and getattr(self.config_entry, "entry_id", None):
                self._cache_store = Store(
                    hass,
                    COORDINATOR_CACHE_VERSION,
                    f"oig_cloud.coordinator_cache_{self.config_entry.entry_id}",
                )
        except Exception:
            self._cache_store = None

    async def async_config_entry_first_refresh(self) -> None:
        """Load cached payload before the first refresh.

        This makes entities render immediately with last-known values (retain-like behavior),
        while the coordinator is still doing the first network/local refresh.
        """
        if self._cache_store is not None:
            try:
                cached = await self._cache_store.async_load()
                cached_data = cached.get("data") if isinstance(cached, dict) else None
                if isinstance(cached_data, dict) and cached_data:
                    self.data = cached_data
                    self.last_update_success = True
                    _LOGGER.debug(
                        "Loaded cached coordinator data (%d keys) before first refresh",
                        len(cached_data),
                    )
            except Exception as err:
                _LOGGER.debug("Failed to load coordinator cache: %s", err)

        try:
            await super().async_config_entry_first_refresh()
        except Exception as err:
            # Keep cached values if refresh fails during startup (e.g. cloud unreachable).
            if self.data:
                self.last_update_success = True
                _LOGGER.warning(
                    "First refresh failed, continuing with cached coordinator data: %s",
                    err,
                )
                return
            raise

    def _prune_for_cache(self, value: Any, *, _depth: int = 0) -> Any:
        """Reduce payload size before saving to HA storage."""
        if _depth > 6:
            return None

        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            return (
                value
                if len(value) <= COORDINATOR_CACHE_MAX_STR_LEN
                else value[:COORDINATOR_CACHE_MAX_STR_LEN]
            )

        if isinstance(value, datetime):
            try:
                return value.isoformat()
            except Exception:
                return str(value)

        if isinstance(value, list):
            trimmed = value[:COORDINATOR_CACHE_MAX_LIST_ITEMS]
            return [self._prune_for_cache(v, _depth=_depth + 1) for v in trimmed]

        if isinstance(value, tuple):
            trimmed = list(value)[:COORDINATOR_CACHE_MAX_LIST_ITEMS]
            return [self._prune_for_cache(v, _depth=_depth + 1) for v in trimmed]

        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                # Drop very large/volatile raw blobs by key name
                key = str(k)
                if key in {"timeline_data", "timeline", "latest_timeline"}:
                    continue
                out[key] = self._prune_for_cache(v, _depth=_depth + 1)
            return out

        # Fallback: keep a readable representation
        try:
            return str(value)
        except Exception:
            return None

    def _maybe_schedule_cache_save(self, data: Dict[str, Any]) -> None:
        if self._cache_store is None:
            return
        now = self._utcnow()
        if self._last_cache_save_ts is not None:
            age = (now - self._last_cache_save_ts).total_seconds()
            if age < COORDINATOR_CACHE_SAVE_COOLDOWN_S:
                return

        self._last_cache_save_ts = now

        snapshot = {
            "saved_at": now.isoformat(),
            "data": self._prune_for_cache(data),
        }

        async def _save() -> None:
            try:
                await self._cache_store.async_save(snapshot)
            except Exception as err:
                _LOGGER.debug("Failed to save coordinator cache: %s", err)

        try:
            self.hass.async_create_task(_save())
        except Exception:
            pass

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
        now = dt_util.now()
        today_13 = now.replace(hour=13, minute=5, second=0, microsecond=0)

        # Pokud je už po 13:05 dnes, naplánujeme na zítra
        if now >= today_13:
            next_update = today_13 + timedelta(days=1)
        else:
            next_update = today_13

        _LOGGER.debug(f"Next spot price update scheduled for: {next_update}")

        # Naplánujeme callback
        async def spot_price_callback(now: datetime) -> None:
            await self._update_spot_prices()

        async_track_point_in_time(self.hass, spot_price_callback, next_update)

    def _schedule_hourly_fallback(self) -> None:
        """Naplánuje hodinové fallback stahování OTE dat."""

        # Spustit každou hodinu
        self.hass.loop.call_later(
            3600,  # 1 hodina
            lambda: self.hass.async_create_task(self._hourly_fallback_check()),
        )

    async def _hourly_fallback_check(self) -> None:
        """Hodinová kontrola a případné stahování OTE dat."""
        if not self.ote_api:
            return

        now = dt_util.now()

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
                    self._spot_prices_cache = spot_data
                    if hasattr(self, "data") and self.data:
                        self.data["spot_prices"] = spot_data
                        self.async_update_listeners()

                    _LOGGER.info(
                        f"Hourly fallback: Successfully updated spot prices: {spot_data.get('hours_count', 0)} hours"
                    )
                    self._last_spot_fetch = dt_util.now()
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
                "Attempting to update spot prices from OTE (scheduled 13:05 update)"
            )
            spot_data = await self.ote_api.get_spot_prices()

            if spot_data and spot_data.get("prices_czk_kwh"):
                _LOGGER.info(
                    f"Successfully updated spot prices: {spot_data.get('hours_count', 0)} hours"
                )
                self._spot_prices_cache = spot_data
                self._last_spot_fetch = dt_util.now()
                self._spot_retry_count = 0
                self._hourly_fallback_active = (
                    False  # NOVÉ: vypnout fallback po úspěšném stažení
                )

                # Uložíme data do coordinator dat
                if hasattr(self, "data") and self.data:
                    self.data["spot_prices"] = spot_data
                    self.async_update_listeners()

                # Naplánujeme další aktualizaci na zítra ve 13:05
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

        # Omezit retry pouze na důležité časy (kolem 13:05)
        now = dt_util.now()
        is_important_time = 12 <= now.hour <= 15  # Retry pouze 12-15h

        if self._spot_retry_count < 3 and is_important_time:  # Snížit max retries
            # Zkusíme znovu za 30 minut místo 15
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
                    "Failed to update spot prices after 3 attempts, giving up until tomorrow"
                )

            self._spot_retry_count = 0
            # Naplánujeme další pokus na zítra
            self._schedule_spot_price_update()

    async def _async_update_data(self) -> Dict[str, Any]:  # noqa: C901
        """Aktualizace základních dat."""
        _LOGGER.debug("🔄 _async_update_data called - starting update cycle")

        # Apply jitter - random delay at start of update
        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)

        # Only sleep for positive jitter (negative means update sooner, handled by next cycle)
        if jitter > 0:
            _LOGGER.debug(f"⏱️  Applying jitter: +{jitter:.1f}s delay before update")
            await asyncio.sleep(jitter)
        else:
            _LOGGER.debug(f"⏱️  Jitter: {jitter:.1f}s (no delay, update now)")

        try:
            # Standardní OIG data (cloud telemetry) – může být vypnuto v hybrid/local režimu,
            # pokud lokální proxy běží (viz DataSourceController).
            use_cloud = True
            try:
                if self.config_entry:
                    state = get_data_source_state(self.hass, self.config_entry.entry_id)
                    _LOGGER.debug(
                        "Data source state: configured=%s effective=%s local_ok=%s reason=%s",
                        state.configured_mode,
                        state.effective_mode,
                        state.local_available,
                        state.reason,
                    )
                    use_cloud = state.effective_mode == DATA_SOURCE_CLOUD_ONLY
            except Exception:
                use_cloud = True

            if use_cloud:
                stats = await self._try_get_stats()
            else:
                # Local mode: coordinator.data must already be cloud-shaped (filled by TelemetryStore).
                telemetry_store = getattr(self, "telemetry_store", None)
                if telemetry_store is not None:
                    try:
                        snap = telemetry_store.get_snapshot()
                        stats = snap.payload
                    except Exception:
                        stats = self.data or {}
                else:
                    stats = self.data or {}

                # Local mode: some configuration nodes can legitimately be missing/unknown.
                # Fetch those from cloud as a lightweight fallback (no other exceptions).
                try:
                    if isinstance(stats, dict):
                        await self._maybe_fill_config_nodes_from_cloud(stats)
                except Exception:
                    pass

            # Cloud notifications are optional and should never run in local/hybrid effective mode.
            cloud_notifications_enabled = bool(
                self.config_entry
                and self.config_entry.options.get("enable_cloud_notifications", True)
            )

            # NOVÉ: Inicializovat notification manager pokud ještě není
            if use_cloud and cloud_notifications_enabled:
                if (
                    not hasattr(self, "notification_manager")
                    or self.notification_manager is None
                ):
                    _LOGGER.debug("Initializing notification manager")
                    try:
                        from .oig_cloud_notification import OigNotificationManager

                        # NOVÉ: Použít get_session() z API pro sdílení autentifikace
                        self.notification_manager = OigNotificationManager(
                            self.hass, self.api, "https://portal.oigpower.cz"
                        )
                        _LOGGER.debug(
                            "Notification manager initialized with API session"
                        )
                    except Exception as e:
                        _LOGGER.error(f"Failed to initialize notification manager: {e}")
                        self.notification_manager = None
            else:
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
                _LOGGER.debug("Config entry found: True")
                # Do not log full options (may contain secrets)
                try:
                    _LOGGER.debug(
                        "Config entry option keys: %s",
                        sorted(list(getattr(config_entry, "options", {}).keys())),
                    )
                except Exception:
                    _LOGGER.debug("Config entry option keys: <unavailable>")
                _LOGGER.debug(
                    f"Extended sensors enabled from options: {extended_enabled}"
                )
            else:
                _LOGGER.warning("No config entry available for this coordinator")

            # Startup grace: během prvních X sekund po startu dělej jen lehké operace
            elapsed = (self._utcnow() - self._startup_ts).total_seconds()
            if elapsed < self._startup_grace_seconds:
                remaining = self._startup_grace_seconds - int(elapsed)
                _LOGGER.debug(
                    f"Startup grace active ({remaining}s left) – skipping extended stats, spot fetch, and forecast"
                )
                # Minimal return: základní stats + případné cached spot ceny
                result = stats.copy() if stats else {}
                if self._spot_prices_cache:
                    result["spot_prices"] = self._spot_prices_cache
                    _LOGGER.debug("Including cached spot prices during startup grace")
                return result

            should_update_extended = self._should_update_extended()
            _LOGGER.debug(f"Should update extended: {should_update_extended}")
            _LOGGER.debug(f"Last extended update: {self._last_extended_update}")
            _LOGGER.debug(f"Extended interval: {self.extended_interval}s")

            if use_cloud and extended_enabled and should_update_extended:
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
                    self._last_extended_update = dt_util.now()
                    _LOGGER.debug("Extended stats updated successfully")

                    # NOVÉ: Aktualizovat notifikace současně s extended daty
                    if cloud_notifications_enabled and (
                        hasattr(self, "notification_manager")
                        and self.notification_manager
                        and hasattr(self.notification_manager, "_device_id")
                        and self.notification_manager._device_id is not None
                    ):
                        try:
                            _LOGGER.debug(
                                "Refreshing notification data with extended stats"
                            )
                            # OPRAVA: Použít správnou metodu pro aktualizaci notifikací
                            await self.notification_manager.update_from_api()
                            _LOGGER.debug("Notification data updated successfully")
                        except Exception as e:
                            _LOGGER.debug(f"Notification data fetch failed: {e}")
                    elif cloud_notifications_enabled:
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
                if cloud_notifications_enabled and (
                    hasattr(self, "notification_manager")
                    and self.notification_manager
                    and hasattr(self.notification_manager, "_device_id")
                    and self.notification_manager._device_id is not None
                ):
                    # Aktualizovat notifikace každých 5 minut i bez extended dat
                    if not hasattr(self, "_last_notification_update"):
                        self._last_notification_update = None

                    now = dt_util.now()
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
                            # OPRAVA: Použít správnou metodu pro aktualizaci notifikací
                            await self.notification_manager.update_from_api()
                            self._last_notification_update = now
                            _LOGGER.debug(
                                "Standalone notification data updated successfully"
                            )
                        except Exception as e:
                            _LOGGER.debug(
                                f"Standalone notification data fetch failed: {e}"
                            )
                elif cloud_notifications_enabled:
                    _LOGGER.debug(
                        "Notification manager not available for standalone refresh - device_id not set yet"
                    )

            # Aktualizuj battery forecast pokud je povolen
            if self.config_entry and self.config_entry.options.get(
                "enable_battery_prediction", True
            ):
                # Do not block coordinator update/startup; run in background
                if (
                    not self._battery_forecast_task
                    or self._battery_forecast_task.done()
                ):
                    self._battery_forecast_task = self.hass.async_create_task(
                        self._update_battery_forecast()
                    )
                else:
                    _LOGGER.debug("Battery forecast task already running, skipping")

            # NOVÉ: Přidáme spotové ceny pokud jsou k dispozici
            if self._spot_prices_cache:
                stats["spot_prices"] = self._spot_prices_cache
                _LOGGER.debug("Including cached spot prices in coordinator data")
            elif self.ote_api and not hasattr(self, "_initial_spot_attempted"):
                # První pokus o získání spotových cen při startu
                self._initial_spot_attempted = True
                try:
                    _LOGGER.debug("Attempting initial spot price fetch")
                    spot_data = await self.ote_api.get_spot_prices()
                    if spot_data and spot_data.get("hours_count", 0) > 0:
                        stats["spot_prices"] = spot_data
                        self._spot_prices_cache = spot_data
                        _LOGGER.info("Initial spot price data loaded successfully")
                    else:
                        _LOGGER.warning("Initial spot price fetch returned empty data")
                except Exception as e:
                    _LOGGER.warning(f"Initial spot price fetch failed: {e}")
                    # Nebudeme dělat retry při inicializaci

            # Sloučíme standardní a extended data
            result = stats.copy() if stats else {}
            result.update(self.extended_data)

            # Přidáme battery forecast data pokud jsou k dispozici
            if self.battery_forecast_data:
                result["battery_forecast"] = self.battery_forecast_data
                _LOGGER.debug("🔋 Including battery forecast data in coordinator data")

            # Persist last-known payload for retain-like startup behavior.
            if isinstance(result, dict) and result:
                self._maybe_schedule_cache_save(result)

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

    async def _maybe_fill_config_nodes_from_cloud(self, stats: Dict[str, Any]) -> None:
        """In local effective mode, backfill missing configuration nodes from cloud (throttled)."""
        now = self._utcnow()
        last = getattr(self, "_last_cloud_config_fill_ts", None)
        if isinstance(last, datetime):
            if (now - last).total_seconds() < 900:
                return

        box_id: Optional[str] = None
        try:
            entry = self.config_entry
            if entry:
                opt = getattr(entry, "options", {}) or {}
                for key in ("box_id", "inverter_sn"):
                    val = opt.get(key)
                    if isinstance(val, str) and val.isdigit():
                        box_id = val
                        break
        except Exception:
            box_id = None
        if not (isinstance(box_id, str) and box_id.isdigit()):
            try:
                box_id = next((str(k) for k in stats.keys() if str(k).isdigit()), None)
            except Exception:
                box_id = None
        if not (isinstance(box_id, str) and box_id.isdigit()):
            return

        box = stats.get(box_id)
        if not isinstance(box, dict):
            return

        config_nodes = (
            "box_prms",
            "batt_prms",
            "invertor_prm1",
            "invertor_prms",
            "boiler_prms",
        )
        missing_nodes = [
            n
            for n in config_nodes
            if not isinstance(box.get(n), dict) or not box.get(n)
        ]
        if not missing_nodes:
            return

        cloud = None
        try:
            cloud = await self.api.get_stats()
        except Exception as err:
            _LOGGER.debug("Local mode: config backfill cloud fetch failed: %s", err)
            return
        if not isinstance(cloud, dict):
            return
        cloud_box = cloud.get(box_id)
        if not isinstance(cloud_box, dict):
            return

        did = False
        for node_id in missing_nodes:
            node = cloud_box.get(node_id)
            if isinstance(node, dict) and node:
                box[node_id] = node
                did = True

        if did:
            self._last_cloud_config_fill_ts = now
            _LOGGER.info(
                "Local mode: backfilled config nodes from cloud: %s",
                ",".join(missing_nodes),
            )

    def _today_range(self) -> Tuple[str, str]:
        """Vrátí dnešní datum jako string tuple pro API."""
        today = dt_util.now().date()
        today_str = today.strftime("%Y-%m-%d")
        return today_str, today_str

    def _should_update_extended(self) -> bool:
        """Určí, zda je čas aktualizovat extended data."""
        if self._last_extended_update is None:
            return True
        # OPRAVA: Používat lokální čas místo UTC pro konzistenci
        now = dt_util.now()
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
        """Aktualizuje battery forecast data přímo v coordinatoru."""
        try:
            _LOGGER.debug("🔋 Starting battery forecast calculation in coordinator")

            # KRITICKÁ KONTROLA: Coordinator MUSÍ mít data před vytvořením battery forecast sensoru
            if not self.data or not isinstance(self.data, dict) or not self.data:
                _LOGGER.debug(
                    "🔋 Coordinator has no data yet, skipping battery forecast calculation"
                )
                return

            # Importujeme battery forecast třídu
            from .oig_cloud_battery_forecast import OigCloudBatteryForecastSensor

            # Získat inverter_sn deterministicky (config entry → numerické klíče v self.data)
            inverter_sn: Optional[str] = None
            try:
                if self.config_entry:
                    opt_box = self.config_entry.options.get("box_id")
                    if isinstance(opt_box, str) and opt_box.isdigit():
                        inverter_sn = opt_box
            except Exception:
                inverter_sn = None

            if inverter_sn is None and isinstance(self.data, dict) and self.data:
                inverter_sn = next(
                    (str(k) for k in self.data.keys() if str(k).isdigit()),
                    None,
                )

            if not inverter_sn:
                _LOGGER.debug(
                    "🔋 No numeric inverter_sn available, skipping forecast update"
                )
                return

            _LOGGER.debug("🔍 Inverter SN resolved for forecast: %s", inverter_sn)

            # Vytvořit device_info pro Analytics Module
            from .const import DOMAIN

            device_info: Dict[str, Any] = {
                "identifiers": {(DOMAIN, f"{inverter_sn}_analytics")},
                "name": "Analytics & Predictions",
                "manufacturer": "ČEZ",
                "model": "Battery Box Analytics Module",
                "sw_version": "1.0.0",
            }

            # Vytvoříme dočasnou instanci pro výpočet (bez registrace)
            # DŮLEŽITÉ: Předáme hass PŘÍMO do __init__
            _LOGGER.debug(
                f"🔍 Creating temp sensor with config_entry: {self.config_entry is not None}"
            )
            temp_sensor = OigCloudBatteryForecastSensor(
                self,
                "battery_forecast",
                self.config_entry,
                device_info,
                self.hass,
                side_effects_enabled=False,
            )
            _LOGGER.debug(
                f"🔍 Temp sensor created, _hass set: {temp_sensor._hass is not None}"
            )

            # Spustíme výpočet - nová metoda async_update()
            await temp_sensor.async_update()

            # Získat data z timeline_data
            if temp_sensor._timeline_data:
                self.battery_forecast_data = {
                    "timeline_data": temp_sensor._timeline_data,
                    "calculation_time": (
                        temp_sensor._last_update.isoformat()
                        if temp_sensor._last_update
                        else None
                    ),
                    "data_source": "simplified_calculation",
                    "current_battery_kwh": (
                        temp_sensor._timeline_data[0].get("battery_capacity_kwh", 0)
                        if temp_sensor._timeline_data
                        else 0
                    ),
                    # Use consistent API key name and ensure default list when empty
                    "mode_recommendations": temp_sensor._mode_recommendations or [],
                }
                _LOGGER.debug(
                    f"🔋 Battery forecast data updated in coordinator: {len(temp_sensor._timeline_data)} points"
                )
            else:
                self.battery_forecast_data = None
                _LOGGER.warning("🔋 Battery forecast returned no timeline data")

        except Exception as e:
            _LOGGER.error(
                f"🔋 Failed to update battery forecast in coordinator: {e}",
                exc_info=True,
            )
            self.battery_forecast_data = None

    def _create_simple_battery_forecast(self) -> Dict[str, Any]:
        """Vytvoří jednoduchá forecast data když senzor není dostupný."""
        current_time = dt_util.now()

        # Základní data z koordinátoru
        if self.data:
            device_id = next(
                (str(k) for k in self.data.keys() if str(k).isdigit()), None
            )
            device_data = self.data.get(device_id, {}) if device_id else {}
            battery_level = device_data.get("batt_bat_c", 0)
        else:
            battery_level = 0

        return {
            "calculation_time": current_time.isoformat(),
            "current_battery_level": battery_level,
            "forecast_available": False,
            "simple_forecast": True,
        }
