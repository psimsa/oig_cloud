"""Senzory pro spotové ceny elektřiny z OTE (spot 15min)."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.dt import now as dt_now

from ..api.ote_api import OteApi
from ..entities.base_sensor import OigCloudSensor
from ..sensors.SENSOR_TYPES_SPOT import SENSOR_TYPES_SPOT
from .spot_price_shared import (
    DAILY_FETCH_HOUR,
    DAILY_FETCH_MINUTE,
    HOURLY_RETRY_SECONDS,
    RETRY_DELAYS_SECONDS,
    _ote_cache_path,
    _resolve_box_id_from_coordinator,
)

_LOGGER = logging.getLogger(__name__)


class SpotPrice15MinSensor(OigCloudSensor, RestoreEntity):
    """Senzor pro aktuální spotovou cenu s 15minutovým intervalem včetně finální ceny."""

    def __init__(
        self,
        coordinator: Any,
        entry: ConfigEntry,
        sensor_type: str,
        device_info: Dict[str, Any],
    ) -> None:
        # OPRAVA: Volat super().__init__() pouze s coordinator a sensor_type
        super().__init__(coordinator, sensor_type)

        self._sensor_type = sensor_type
        self._sensor_config = SENSOR_TYPES_SPOT.get(sensor_type, {})
        self._entry = entry
        # OPRAVA: Uložit device_info pro použití v property (ne _attr_device_info!)
        self._analytics_device_info = device_info
        cache_path = _ote_cache_path(coordinator.hass)
        self._ote_api = OteApi(cache_path=cache_path)

        self._spot_data_15min: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None
        self._track_time_interval_remove = None
        self._track_15min_remove = None
        self._data_hash: Optional[str] = None  # Phase 1.5: Hash for change detection
        self._retry_remove: Optional[Any] = None
        self._retry_attempt: int = 0
        self._cached_state: Optional[float] = None
        self._cached_attributes: Dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - nastavit tracking a stáhnout data."""
        await super().async_added_to_hass()

        # Load cached OTE spot prices without blocking the event loop
        await self._ote_api.async_load_cached_spot_prices()

        _LOGGER.info(
            f"[{self.entity_id}] 15min spot price sensor added to HA - starting data fetch"
        )

        # Obnovit data ze stavu
        await self._restore_data()

        # Nastavit pravidelné stahování (denně v 13:00)
        self._setup_daily_tracking()

        # Nastavit aktualizaci každých 15 minut
        self._setup_15min_tracking()

        # Okamžitě stáhnout aktuální data, pokud daily_tracking už nespustil fetch
        now = dt_now()
        current_minutes = now.hour * 60 + now.minute
        daily_update_time = DAILY_FETCH_HOUR * 60 + DAILY_FETCH_MINUTE

        # Pokud je >= 13:00, daily_tracking už spustil fetch, nevoláme druhý
        if current_minutes < daily_update_time:
            try:
                await self._fetch_spot_data_with_retry()
            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Error in initial data fetch: {e}")

    async def _restore_data(self) -> None:
        """Obnovení dat z uloženého stavu."""
        old_state = await self.async_get_last_state()
        if old_state and old_state.attributes:
            try:
                if "last_update" in old_state.attributes:
                    self._last_update = datetime.fromisoformat(
                        old_state.attributes["last_update"]
                    )
                _LOGGER.info(f"[{self.entity_id}] Restored 15min spot price data")
            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Error restoring data: {e}")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Sync 15min spot data z coordinatoru."""
        try:
            if self.coordinator.data and "spot_prices" in self.coordinator.data:
                spot_data = self.coordinator.data["spot_prices"]
                if spot_data:
                    self._spot_data_15min = spot_data
                    self._last_update = dt_now()
                    self._refresh_cached_state_and_attributes()
                    intervals = len(spot_data.get("prices15m_czk_kwh", {}))
                    _LOGGER.debug(
                        f"[{self.entity_id}] Synced 15min spot prices from coordinator ({intervals} intervals)"
                    )
        except Exception as err:
            _LOGGER.debug(
                f"[{self.entity_id}] Failed to sync spot prices from coordinator: {err}"
            )

        super()._handle_coordinator_update()

    def _setup_daily_tracking(self) -> None:
        """Nastavení denního stahování dat ve 13:00 s retry."""
        now = dt_now()
        current_minutes = now.hour * 60 + now.minute
        daily_update_time = DAILY_FETCH_HOUR * 60 + DAILY_FETCH_MINUTE  # 13:00

        if current_minutes >= daily_update_time:
            # Data pro dnešek už jsou k dispozici
            self.hass.async_create_task(self._fetch_spot_data_with_retry())

        # Nastavit denní aktualizaci ve 13:00
        self._track_time_interval_remove = async_track_time_change(
            self.hass,
            self._fetch_spot_data_with_retry,
            hour=DAILY_FETCH_HOUR,
            minute=DAILY_FETCH_MINUTE,
            second=0,
        )

    def _setup_15min_tracking(self) -> None:
        """Nastavení aktualizace každých 15 minut (00, 15, 30, 45)."""
        # Aktualizace každých 15 minut pro změnu aktuálního intervalu
        self._track_15min_remove = async_track_time_change(
            self.hass,
            self._update_current_interval,
            minute=[0, 15, 30, 45],
            second=5,  # 5 sekund po začátku intervalu
        )

    async def _update_current_interval(self, *_: Any) -> None:
        """Aktualizace stavu senzoru při změně 15min intervalu."""
        _LOGGER.debug(f"[{self.entity_id}] Updating current 15min interval")
        self._refresh_cached_state_and_attributes()
        self.async_write_ha_state()
        # Trigger coordinator refresh in background to avoid blocking the event loop
        # and hitting HA warnings about slow state updates.
        if self.hass and self.coordinator:
            self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup při odstranění senzoru."""
        await super().async_will_remove_from_hass()

        if self._track_time_interval_remove:
            self._track_time_interval_remove()

        if self._track_15min_remove:
            self._track_15min_remove()

    async def _fetch_spot_data_with_retry(self, *_: Any) -> None:
        """Jednorázový fetch + plánování dalších pokusů až do úspěchu."""
        success = await self._do_fetch_15min_spot_data()
        if success:
            self._retry_attempt = 0
            self._cancel_retry_timer()
        else:
            self._schedule_retry(self._do_fetch_15min_spot_data)

    async def _do_fetch_15min_spot_data(self) -> bool:
        """Stáhne data, vrátí True při úspěchu, jinak False."""
        try:
            _LOGGER.info(
                f"[{self.entity_id}] Fetching 15min spot data - attempt {self._retry_attempt + 1}"
            )

            spot_data = await self._ote_api.get_spot_prices()

            if spot_data and "prices15m_czk_kwh" in spot_data:
                self._spot_data_15min = spot_data
                self._last_update = dt_now()
                self._refresh_cached_state_and_attributes()

                intervals_count = len(spot_data.get("prices15m_czk_kwh", {}))
                _LOGGER.info(
                    f"[{self.entity_id}] 15min spot data successful - {intervals_count} intervals"
                )

                # Aktualizovat stav tohoto senzoru
                self.async_write_ha_state()

                # Trigger coordinator refresh pro všechny závislé senzory
                await self.coordinator.async_request_refresh()

                # Úspěch jen pokud máme všechna potřebná data (cache je validní)
                if self._ote_api._is_cache_valid():
                    return True
                else:
                    _LOGGER.info(
                        f"[{self.entity_id}] Data received but incomplete (missing tomorrow after 13:00), will retry"
                    )
                    return False

            _LOGGER.warning(
                f"[{self.entity_id}] No 15min data on attempt {self._retry_attempt + 1}"
            )

        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error fetching 15min data on attempt {self._retry_attempt + 1}: {e}"
            )

        return False

    def _schedule_retry(self, fetch_coro) -> None:
        """Naplánuje další pokus podle retry schématu."""
        delay = (
            RETRY_DELAYS_SECONDS[self._retry_attempt]
            if self._retry_attempt < len(RETRY_DELAYS_SECONDS)
            else HOURLY_RETRY_SECONDS
        )
        self._retry_attempt += 1
        _LOGGER.info(
            f"[{self.entity_id}] Retrying spot data in {delay // 60} minutes (attempt {self._retry_attempt})"
        )

        self._cancel_retry_timer()

        async def _retry_after_delay():
            """Čeká a pak zavolá fetch."""
            _LOGGER.info(f"[{self.entity_id}] ⏰ Retry task waiting {delay}s...")
            await asyncio.sleep(delay)
            _LOGGER.info(f"[{self.entity_id}] 🔔 Retry timer fired!")
            await fetch_coro()

        self._retry_remove = self.hass.async_create_task(_retry_after_delay())

    def _cancel_retry_timer(self) -> None:
        """Zruší naplánovaný retry task, pokud existuje."""
        if self._retry_remove:
            if not self._retry_remove.done():
                self._retry_remove.cancel()
            self._retry_remove = None

    def _get_current_interval_index(self, now: datetime) -> int:
        """Vrátí index 15min intervalu (0-95) pro daný čas."""
        return OteApi.get_current_15min_interval(now)

    def _refresh_cached_state_and_attributes(self) -> None:
        """Recompute cached state/attributes to avoid heavy work in properties."""
        self._cached_state = self._calculate_current_state()
        self._cached_attributes = self._calculate_attributes()
        self._attr_native_value = self._cached_state
        self._attr_extra_state_attributes = self._cached_attributes

    def _calculate_current_state(self) -> Optional[float]:
        """Compute current spot price for the active 15min interval."""
        try:
            if not self._spot_data_15min:
                return None

            now = dt_now()
            interval_index = self._get_current_interval_index(now)

            spot_price_czk = OteApi.get_15min_price_for_interval(
                interval_index, self._spot_data_15min, now.date()
            )

            if spot_price_czk is None:
                return None

            return self._calculate_final_price_15min(spot_price_czk, now)

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error getting state: {e}")
            return None

    def _calculate_attributes(self) -> Dict[str, Any]:
        """Compute attributes summary for spot prices."""
        attrs: Dict[str, Any] = {}

        try:
            if (
                not self._spot_data_15min
                or "prices15m_czk_kwh" not in self._spot_data_15min
            ):
                return attrs

            now = dt_now()
            current_interval_index = self._get_current_interval_index(now)
            prices_15m = self._spot_data_15min["prices15m_czk_kwh"]

            future_prices = []
            current_price: Optional[float] = None
            next_price: Optional[float] = None

            for time_key, spot_price_czk in sorted(prices_15m.items()):
                try:
                    dt_naive = datetime.fromisoformat(time_key)
                    dt = (
                        dt_naive.replace(tzinfo=now.tzinfo)
                        if dt_naive.tzinfo is None
                        else dt_naive
                    )

                    interval_end = dt + timedelta(minutes=15)
                    if interval_end <= now:
                        continue

                    final_price = self._calculate_final_price_15min(spot_price_czk, dt)

                    future_prices.append(final_price)

                    if current_price is None:
                        current_price = final_price
                    elif next_price is None:
                        next_price = final_price

                except Exception as e:
                    _LOGGER.debug(f"Error processing interval {time_key}: {e}")
                    continue

            next_interval = (current_interval_index + 1) % 96
            next_hour = next_interval // 4
            next_minute = (next_interval % 4) * 15
            next_update = now.replace(
                hour=next_hour, minute=next_minute, second=0, microsecond=0
            )
            if next_interval == 0:
                next_update += timedelta(days=1)

            attrs = {
                "current_datetime": now.strftime("%Y-%m-%d %H:%M"),
                "source": "OTE_WSDL_API_QUARTER_HOUR",
                "interval_type": "QUARTER_HOUR",
                "current_interval": current_interval_index,
                "current_price": current_price,
                "next_price": next_price,
                "next_update": next_update.isoformat(),
                "current_tariff": self._get_tariff_for_datetime(now),
                "intervals_count": len(future_prices),
                "last_update": (
                    self._last_update.isoformat() if self._last_update else None
                ),
                "price_min": round(min(future_prices), 2) if future_prices else None,
                "price_max": round(max(future_prices), 2) if future_prices else None,
                "price_avg": (
                    round(sum(future_prices) / len(future_prices), 2)
                    if future_prices
                    else None
                ),
                "currency": "CZK/kWh",
                "api_endpoint": (
                    f"/api/oig_cloud/spot_prices/{_resolve_box_id_from_coordinator(self.coordinator)}/intervals?type=spot"
                ),
                "api_note": "Full intervals data available via API endpoint (reduces sensor size by 95%)",
            }

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error building attributes: {e}")

        return attrs

    def _get_tariff_for_datetime(self, target_datetime: datetime) -> str:
        """Získat tarif (VT/NT) pro daný datetime - kopie z analytics sensoru."""
        dual_tariff_enabled = self._entry.options.get("dual_tariff_enabled", True)
        if not dual_tariff_enabled:
            return "VT"

        is_weekend = target_datetime.weekday() >= 5
        options = self._entry.options

        if is_weekend:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekend", "0")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekend", "")
            )
        else:
            nt_times = self._parse_tariff_times(
                options.get("tariff_nt_start_weekday", "22,2")
            )
            vt_times = self._parse_tariff_times(
                options.get("tariff_vt_start_weekday", "6")
            )

        current_hour = target_datetime.hour
        last_tariff = "NT"
        last_hour = -1

        all_changes = []
        for hour in nt_times:
            all_changes.append((hour, "NT"))
        for hour in vt_times:
            all_changes.append((hour, "VT"))

        all_changes.sort(reverse=True)

        for hour, tariff in all_changes:
            if hour <= current_hour and hour > last_hour:
                last_tariff = tariff
                last_hour = hour

        return last_tariff

    def _parse_tariff_times(self, time_str: str) -> list[int]:
        """Parse tariff times string to list of hours."""
        if not time_str:
            return []
        try:
            return [int(x.strip()) for x in time_str.split(",") if x.strip()]
        except ValueError:
            return []

    def _calculate_final_price_15min(
        self, spot_price_czk: float, target_datetime: datetime
    ) -> float:
        """Vypočítat finální cenu včetně obchodních a distribučních poplatků a DPH."""
        options = self._entry.options

        # Parametry z konfigurace
        pricing_model = options.get("spot_pricing_model", "percentage")
        positive_fee_percent = options.get("spot_positive_fee_percent", 15.0)
        negative_fee_percent = options.get("spot_negative_fee_percent", 9.0)
        fixed_fee_mwh = options.get("spot_fixed_fee_mwh", 0.0)
        distribution_fee_vt_kwh = options.get("distribution_fee_vt_kwh", 1.50)
        distribution_fee_nt_kwh = options.get("distribution_fee_nt_kwh", 1.20)
        vat_rate = options.get("vat_rate", 21.0)

        # 1. Obchodní cena
        if pricing_model == "percentage":
            if spot_price_czk >= 0:
                commercial_price = spot_price_czk * (1 + positive_fee_percent / 100.0)
            else:
                commercial_price = spot_price_czk * (1 - negative_fee_percent / 100.0)
        elif pricing_model == "fixed_prices":
            fixed_price_vt = options.get("fixed_commercial_price_vt", 4.50)
            fixed_price_nt = options.get("fixed_commercial_price_nt", fixed_price_vt)
            current_tariff = self._get_tariff_for_datetime(target_datetime)
            commercial_price = (
                fixed_price_vt if current_tariff == "VT" else fixed_price_nt
            )
        else:  # fixed fee
            fixed_fee_kwh = fixed_fee_mwh / 1000.0
            commercial_price = spot_price_czk + fixed_fee_kwh

        # 2. Tarif pro distribuci
        current_tariff = self._get_tariff_for_datetime(target_datetime)

        # 3. Distribuční poplatek
        distribution_fee = (
            distribution_fee_vt_kwh
            if current_tariff == "VT"
            else distribution_fee_nt_kwh
        )

        # 4. Cena bez DPH
        price_without_vat = commercial_price + distribution_fee

        # 5. Finální cena s DPH
        return round(price_without_vat * (1 + vat_rate / 100.0), 2)

    @property
    def state(self) -> Optional[float]:
        """Aktuální finální cena pro 15min interval včetně distribuce a DPH."""
        if self._cached_state is not None or self._cached_attributes:
            return self._cached_state
        return self._calculate_current_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """
        Atributy se statistikami spot cen - LEAN VERSION (Phase 1.5).

        PŘED: ~40 KB (96+ intervals v attributes)
        PO: ~2 KB (summary only, intervals přes API)

        Full data: GET /api/oig_cloud/battery_forecast/{box_id}/timeline?type=active
        """
        if self._cached_attributes:
            return self._cached_attributes
        return self._calculate_attributes()

    @property
    def unique_id(self) -> str:
        """Jedinečné ID senzoru."""
        box_id = _resolve_box_id_from_coordinator(self.coordinator)
        return f"oig_cloud_{box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> Dict[str, Any]:
        """Vrátit analytics device info místo vytváření nového zařízení."""
        return self._analytics_device_info

    @property
    def should_poll(self) -> bool:
        """Nepoužívat polling - máme vlastní scheduler."""
        return False
