"""Senzory pro spotové ceny elektřiny z OTE (spot hourly)."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

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


class SpotPriceSensor(OigCloudSensor, RestoreEntity):
    """Senzor pro spotové ceny elektřiny."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__(coordinator, sensor_type)

        self._sensor_type = sensor_type
        self._sensor_config = SENSOR_TYPES_SPOT.get(sensor_type, {})
        cache_path = _ote_cache_path(coordinator.hass)
        self._ote_api = OteApi(cache_path=cache_path)

        self._spot_data: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None
        self._track_time_interval_remove = None
        self._retry_remove: Optional[Any] = None
        self._retry_attempt: int = 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # OPRAVA: Číst spot price data z coordinatoru
        if self.coordinator.data and "spot_prices" in self.coordinator.data:
            self._spot_data = self.coordinator.data["spot_prices"]
            self._last_update = dt_now()
            _LOGGER.debug(
                f"[{self.entity_id}] Updated spot price data from coordinator: "
                f"{self._spot_data.get('hours_count', 0)} hours"
            )
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - nastavit tracking a stáhnout data."""
        await super().async_added_to_hass()

        # Load cached OTE spot prices without blocking the event loop
        await self._ote_api.async_load_cached_spot_prices()

        _LOGGER.info(
            f"[{self.entity_id}] Spot price sensor {self._sensor_type} added to HA - starting data fetch"
        )

        # Obnovit data ze stavu
        await self._restore_data()

        # Nastavit pravidelné stahování
        self._setup_time_tracking()

        # Okamžitě stáhnout aktuální data, pokud _setup_time_tracking už nespustil fetch
        now = dt_now()
        current_minutes = now.hour * 60 + now.minute
        daily_update_time = DAILY_FETCH_HOUR * 60 + DAILY_FETCH_MINUTE

        # Pokud je >= 13:00, _setup_time_tracking už spustil fetch, nevoláme druhý
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
                _LOGGER.info(f"[{self.entity_id}] Restored spot price data")
            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Error restoring data: {e}")

    def _setup_time_tracking(self) -> None:
        """Nastavení pravidelného stahování dat - jednou denně po 13:00 s retry logikou."""
        # Aktualizace jednou denně ve 13:00 (po publikaci dat)
        daily_update_time = (
            DAILY_FETCH_HOUR * 60 + DAILY_FETCH_MINUTE
        )  # 13:00 v minutách

        # Pokud je aktuální čas po 13:00, stáhneme data hned
        now = dt_now()
        current_minutes = now.hour * 60 + now.minute

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

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup při odstranění senzoru."""
        await super().async_will_remove_from_hass()

        if self._track_time_interval_remove:
            self._track_time_interval_remove()

        self._cancel_retry_timer()
        await self._ote_api.close()

    async def _fetch_spot_data_with_retry(self, *_: Any) -> None:
        """Jednorázový fetch + plánování dalších pokusů až do úspěchu."""
        success = await self._do_fetch_spot_data()
        if success:
            self._retry_attempt = 0
            self._cancel_retry_timer()
        else:
            self._schedule_retry(self._do_fetch_spot_data)

    async def _do_fetch_spot_data(self) -> bool:
        """Stáhne data, vrátí True při úspěchu, jinak False."""
        try:
            _LOGGER.info(
                f"[{self.entity_id}] Fetching spot data - attempt {self._retry_attempt + 1}"
            )

            spot_data = await self._ote_api.get_spot_prices()

            if spot_data and self._validate_spot_data(spot_data):
                self._spot_data = spot_data
                self._last_update = dt_now()

                hours_count = spot_data.get("hours_count", 0)
                tomorrow_available = bool(spot_data.get("tomorrow_stats"))
                _LOGGER.info(
                    f"[{self.entity_id}] Spot data successful - {hours_count} hours, tomorrow: {'yes' if tomorrow_available else 'no'}"
                )

                # Aktualizovat stav senzoru
                self.async_write_ha_state()

                # Úspěch jen pokud máme všechna potřebná data (cache je validní)
                if self._ote_api._is_cache_valid():
                    return True
                else:
                    _LOGGER.info(
                        f"[{self.entity_id}] Data received but incomplete (missing tomorrow after 13:00), will retry"
                    )
                    return False

            _LOGGER.warning(
                f"[{self.entity_id}] Incomplete spot data received on attempt {self._retry_attempt + 1}"
            )

        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error fetching spot data on attempt {self._retry_attempt + 1}: {e}"
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

    def _validate_spot_data(self, data: Dict[str, Any]) -> bool:
        """Validace že data jsou kompletní a použitelná."""
        if not data:
            return False

        prices = data.get("prices_czk_kwh", {})
        if not prices:
            return False

        # Kontrola že máme alespoň nějaká data pro dnes
        today = dt_now().date()
        today_str = today.strftime("%Y-%m-%d")

        today_hours = [k for k in prices.keys() if k.startswith(today_str)]

        # Měli bychom mít alespoň 12 hodin dat (polovina dne)
        if len(today_hours) < 12:
            _LOGGER.debug(
                f"[{self.entity_id}] Insufficient data - only {len(today_hours)} hours for today"
            )
            return False

        # Kontrola že ceny nejsou nulové
        valid_prices = [v for v in prices.values() if v is not None and v > 0]
        if len(valid_prices) < len(today_hours) * 0.8:  # 80% cen musí být validních
            _LOGGER.debug(f"[{self.entity_id}] Too many invalid prices")
            return False

        return True

    # Legacy metoda - přesměrování na novou retry logiku
    async def _fetch_spot_data(self, *_: Any) -> None:
        """Legacy metoda - přesměrování na novou retry logiku."""
        await self._fetch_spot_data_with_retry()

    @property
    def name(self) -> str:
        """Jméno senzoru."""
        box_id = _resolve_box_id_from_coordinator(self.coordinator)
        base = self._sensor_config.get("name", self._sensor_type)
        return f"OIG {box_id} {base}" if box_id != "unknown" else f"OIG {base}"

    @property
    def icon(self) -> str:
        """Ikona senzoru."""
        return self._sensor_config.get("icon", "mdi:flash")

    @property
    def unit_of_measurement(self) -> Optional[str]:
        """Jednotka měření."""
        return self._sensor_config.get("unit_of_measurement")

    @property
    def device_class(self) -> Optional[str]:
        """Třída zařízení."""
        return self._sensor_config.get("device_class")

    @property
    def state_class(self) -> Optional[str]:
        """Třída stavu."""
        return self._sensor_config.get("state_class")

    @property
    def state(self) -> Optional[Union[float, int]]:
        """Hlavní stav senzoru - aktuální spotová cena."""
        try:
            if self._sensor_type == "spot_price_current_czk_kwh":
                return self._get_current_price_czk_kwh()
            elif self._sensor_type == "spot_price_current_eur_mwh":
                return self._get_current_price_eur_mwh()
            elif self._sensor_type == "spot_price_tomorrow_avg":
                return self._get_tomorrow_average()
            elif self._sensor_type == "spot_price_today_min":
                return self._get_today_min()
            elif self._sensor_type == "spot_price_today_max":
                return self._get_today_max()
            elif self._sensor_type == "spot_price_today_avg":
                return self._get_today_average()
            elif self._sensor_type == "spot_price_hourly_all":
                return self._get_current_price_czk_kwh()
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error getting state: {e}")
            return None

        return None

    def _get_current_price_czk_kwh(self) -> Optional[float]:
        """Získání aktuální ceny v CZK/kWh."""
        if not self._spot_data or "prices_czk_kwh" not in self._spot_data:
            return None

        now = dt_now()
        current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"

        return self._spot_data["prices_czk_kwh"].get(current_hour_key)

    def _get_current_price_eur_mwh(self) -> Optional[float]:
        """Získání aktuální ceny v EUR/MWh."""
        if not self._spot_data or "prices_eur_mwh" not in self._spot_data:
            return None

        now = dt_now()
        current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"

        return self._spot_data["prices_eur_mwh"].get(current_hour_key)

    def _get_tomorrow_average(self) -> Optional[float]:
        """Získání průměrné ceny pro zítřek."""
        if (
            self._spot_data
            and "tomorrow_stats" in self._spot_data
            and self._spot_data["tomorrow_stats"]
        ):
            return self._spot_data["tomorrow_stats"].get("avg_czk")
        return None

    def _get_today_average(self) -> Optional[float]:
        """Průměrná cena dnes."""
        if self._spot_data and "today_stats" in self._spot_data:
            return self._spot_data["today_stats"].get("avg_czk")
        return None

    def _get_today_min(self) -> Optional[float]:
        """Minimální cena dnes."""
        if self._spot_data and "today_stats" in self._spot_data:
            return self._spot_data["today_stats"].get("min_czk")
        return None

    def _get_today_max(self) -> Optional[float]:
        """Maximální cena dnes."""
        if self._spot_data and "today_stats" in self._spot_data:
            return self._spot_data["today_stats"].get("max_czk")
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy senzoru."""
        attrs = {}

        if self._sensor_type == "spot_price_current_czk_kwh":
            # Aktuální cena + denní přehled
            if self._spot_data:
                attrs.update(
                    {
                        "today_avg_czk_kwh": self._get_today_average(),
                        "today_min_czk_kwh": self._get_today_min(),
                        "today_max_czk_kwh": self._get_today_max(),
                        "tomorrow_avg_czk_kwh": self._get_tomorrow_average(),
                    }
                )

                # Hodinové ceny pro dnes a zítřek
                attrs.update(self._get_hourly_prices())

        elif self._sensor_type == "spot_price_hourly_all":
            # Všechny dostupné hodinové ceny
            if self._spot_data:
                attrs.update(
                    {
                        "today_avg_czk_kwh": self._get_today_average(),
                        "today_min_czk_kwh": self._get_today_min(),
                        "today_max_czk_kwh": self._get_today_max(),
                        "tomorrow_avg_czk_kwh": self._get_tomorrow_average(),
                        "total_hours_available": len(
                            self._spot_data.get("prices_czk_kwh", {})
                        ),
                    }
                )

                # Všechny hodinové ceny zaokrouhlené na 2 desetinná místa
                attrs.update(self._get_all_hourly_prices())

        # Společné atributy
        attrs.update(
            {
                "last_update": (
                    self._last_update.isoformat() if self._last_update else None
                ),
                "source": "spotovaelektrina.cz",
            }
        )

        return attrs

    def _get_hourly_prices(self) -> Dict[str, Any]:
        """Hodinové ceny - jen dnes/zítřek pro UI."""
        if not self._spot_data or "prices_czk_kwh" not in self._spot_data:
            return {}

        # Jen základní data pro UI grafy
        now = dt_now()
        today_str = now.strftime("%Y-%m-%d")
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        today_prices = {}
        tomorrow_prices = {}

        for time_key, price in self._spot_data["prices_czk_kwh"].items():
            if time_key.startswith(today_str):
                hour = time_key[11:16]  # HH:MM
                today_prices[hour] = round(price, 3)
            elif time_key.startswith(tomorrow_str) and len(tomorrow_prices) < 24:
                hour = time_key[11:16]  # HH:MM
                tomorrow_prices[hour] = round(price, 3)

        return {
            "today_prices": today_prices,
            "tomorrow_prices": tomorrow_prices,
            "next_hour_price": self._get_next_hour_price(),
        }

    def _get_next_hour_price(self) -> Optional[float]:
        """Cena v příští hodině pro rychlé rozhodování."""
        if not self._spot_data or "prices_czk_kwh" not in self._spot_data:
            return None

        now = dt_now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        next_hour_key = next_hour.strftime("%Y-%m-%dT%H:00:00")

        return self._spot_data["prices_czk_kwh"].get(next_hour_key)

    def _get_all_hourly_prices(self) -> Dict[str, Any]:
        """Pouze základní statistiky - necháme historii na recorder."""
        if not self._spot_data or "prices_czk_kwh" not in self._spot_data:
            return {}

        prices = list(self._spot_data["prices_czk_kwh"].values())

        if not prices:
            return {}

        return {
            "price_summary": {
                "min": round(min(prices), 3),
                "max": round(max(prices), 3),
                "avg": round(sum(prices) / len(prices), 3),
                "current": self._get_current_price_czk_kwh(),
                "next": self._get_next_hour_price(),
            },
            "data_info": {
                "hours_available": len(prices),
                "last_update": (
                    self._last_update.isoformat() if self._last_update else None
                ),
                "coverage": "today + tomorrow" if len(prices) > 24 else "today only",
            },
        }

    @property
    def unique_id(self) -> str:
        """Jedinečné ID senzoru."""
        box_id = _resolve_box_id_from_coordinator(self.coordinator)
        return f"oig_cloud_{box_id}_{self._sensor_type}"

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o zařízení."""
        box_id = _resolve_box_id_from_coordinator(self.coordinator)
        return {
            "identifiers": {("oig_cloud", box_id)},
            "name": f"ČEZ Battery Box {box_id}",
            "manufacturer": "OIG",
            "model": "Spot Price Analytics",
        }

    @property
    def should_poll(self) -> bool:
        """Nepoužívat polling - máme vlastní scheduler."""
        return False

    async def async_update(self) -> None:
        """Update senzoru."""
        self.async_write_ha_state()
