"""Solar Forecast API senzor pro OIG Cloud integraci."""

import logging
import aiohttp
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.dt import now as dt_now, utcnow as dt_utcnow
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)


class OigCloudSolarForecastSensor(OigCloudSensor, RestoreEntity):
    """Senzor pro Solar Forecast API data."""

    def __init__(self, coordinator: Any, sensor_type: str, config_entry: Any) -> None:
        super().__init__(coordinator, sensor_type)

        self._config_entry = config_entry
        self._forecast_data: Dict[str, Any] = {}
        self._last_forecast_update: Optional[datetime] = None
        self._rate_limit_info: Dict[str, Any] = {}
        self._track_time_interval_remove = None

        # Načteme konfiguraci
        self._load_config()

    def _load_config(self) -> None:
        """Načtení konfigurace z config_entry options."""
        self._api_key = self._config_entry.options.get("solar_forecast_api_key", "")
        self._latitude = self._config_entry.options.get(
            "solar_forecast_latitude", self.coordinator.hass.config.latitude
        )
        self._longitude = self._config_entry.options.get(
            "solar_forecast_longitude", self.coordinator.hass.config.longitude
        )
        self._declination = self._config_entry.options.get(
            "solar_forecast_declination", 30
        )
        self._azimuth = self._config_entry.options.get("solar_forecast_azimuth", 180)
        self._kwp = self._config_entry.options.get(
            "solar_forecast_kwp", self._get_estimated_kwp()
        )
        self._update_interval = self._config_entry.options.get(
            "solar_forecast_interval", 60
        )

    def _get_estimated_kwp(self) -> float:
        """Odhad instalovaného výkonu z coordinator dat."""
        try:
            if self.coordinator.data:
                data = self.coordinator.data
                pv_data = list(data.values())[0]

                # Zkusíme najít max výkon
                possible_values = [
                    pv_data.get("dc_in", {}).get("fv_p_max", 0),
                    pv_data.get("box_prms", {}).get("fv_p_max", 0),
                    pv_data.get("invertor_prms", {}).get("p_max", 0),
                ]

                for value in possible_values:
                    if value and float(value) > 1000:  # Rozumná hodnota v W
                        return float(value) / 1000.0  # W -> kWp

                # Odhad z aktuálního výkonu
                fv1 = float(pv_data.get("actual", {}).get("fv_p1", 0))
                fv2 = float(pv_data.get("actual", {}).get("fv_p2", 0))
                if fv1 > 0 or fv2 > 0:
                    # Hrubý odhad: aktuální * 3
                    return ((fv1 + fv2) * 3) / 1000.0

        except Exception as e:
            _LOGGER.debug(f"Error estimating kWp: {e}")

        return 10.0  # Fallback

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - obnovit stav a nastavit tracking."""
        await super().async_added_to_hass()

        # Obnovit forecast data ze stavu
        await self._restore_forecast_data()

        # Nastavit pravidelné stahování dat
        self._setup_time_tracking()

        # Nastavit listener pro změny konfigurace
        self._config_entry.add_update_listener(self._update_listener)

        # První volání ihned (pokud nemáme čerstvá data)
        if self._should_fetch_data():
            await self._fetch_forecast_data()

    async def _restore_forecast_data(self) -> None:
        """Obnovení forecast dat z uloženého stavu."""
        old_state = await self.async_get_last_state()
        if old_state and old_state.attributes:
            try:
                if "forecast_data" in old_state.attributes:
                    self._forecast_data = old_state.attributes["forecast_data"]

                if "last_forecast_update" in old_state.attributes:
                    try:
                        self._last_forecast_update = datetime.fromisoformat(
                            old_state.attributes["last_forecast_update"]
                        )
                        # Ujistíme se, že je naive
                        if self._last_forecast_update.tzinfo is not None:
                            self._last_forecast_update = (
                                self._last_forecast_update.replace(tzinfo=None)
                            )
                    except (ValueError, TypeError):
                        pass

                if "rate_limit_info" in old_state.attributes:
                    self._rate_limit_info = old_state.attributes["rate_limit_info"]

                _LOGGER.info(f"[{self.entity_id}] Restored solar forecast data")

            except Exception as e:
                _LOGGER.error(f"[{self.entity_id}] Error restoring forecast data: {e}")

    async def _update_listener(self, hass: Any, config_entry: Any) -> None:
        """Callback při změně konfigurace."""
        _LOGGER.info(
            f"[{self.entity_id}] Configuration updated, reloading solar forecast parameters"
        )

        # Načteme novou konfiguraci
        self._load_config()

        # Zrušíme starý tracking
        if self._track_time_interval_remove:
            self._track_time_interval_remove()

        # Nastavíme nový tracking s novým intervalem
        self._setup_time_tracking()

        # Ihned stáhneme nová data s novou konfigurací
        await self._fetch_forecast_data()

        # Aktualizujeme stav
        self.async_write_ha_state()

    def _setup_time_tracking(self) -> None:
        """Nastavení time tracking s aktuálním intervalem."""
        update_interval = timedelta(minutes=self._update_interval)
        self._track_time_interval_remove = async_track_time_interval(
            self.hass, self._fetch_forecast_data, update_interval
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup při odstranění senzoru."""
        await super().async_will_remove_from_hass()

        # Zrušíme tracking
        if self._track_time_interval_remove:
            self._track_time_interval_remove()

    def _should_fetch_data(self) -> bool:
        """Kontrola, zda je třeba stáhnout nová data."""
        if not self._last_forecast_update:
            return True

        # Stahujeme pouze během dne (6:00 - 21:00)
        now = dt_now()
        # Ujistíme se, že pracujeme s naive datetime
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        if not (6 <= now.hour <= 21):
            return False

        # Kontrola času posledního update - oba musí být naive
        last_update = self._last_forecast_update
        if last_update.tzinfo is not None:
            last_update = last_update.replace(tzinfo=None)

        time_since_update = now - last_update

        # S API key: každých 30 minut, bez API key: každou hodinu
        required_interval = timedelta(minutes=self._update_interval)

        return time_since_update >= required_interval

    async def _fetch_forecast_data(self, *_: Any) -> None:
        """Stažení dat z Solar Forecast API."""
        if not self._should_fetch_data():
            return

        try:
            url = self._build_api_url()

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        self._forecast_data = data.get("result", {})
                        self._rate_limit_info = data.get("message", {}).get(
                            "ratelimit", {}
                        )
                        # Ujistíme se, že čas je naive
                        self._last_forecast_update = dt_now().replace(tzinfo=None)

                        _LOGGER.info(
                            f"[{self.entity_id}] Solar forecast data updated successfully"
                        )

                        # Aktualizuj stav senzoru
                        self.async_write_ha_state()

                    elif response.status == 429:
                        _LOGGER.warning(
                            f"[{self.entity_id}] Rate limit exceeded for Solar Forecast API"
                        )
                    else:
                        _LOGGER.error(
                            f"[{self.entity_id}] Error fetching solar forecast: {response.status}"
                        )

        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Exception fetching solar forecast: {e}",
                exc_info=True,
            )

    def _build_api_url(self) -> str:
        """Sestavení URL pro API volání."""
        base_url = "https://api.forecast.solar"

        if self._api_key:
            url = f"{base_url}/{self._api_key}/estimate/{self._latitude}/{self._longitude}/{self._declination}/{self._azimuth}/{self._kwp}"
        else:
            url = f"{base_url}/estimate/{self._latitude}/{self._longitude}/{self._declination}/{self._azimuth}/{self._kwp}"

        return url

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Hlavní stav senzoru - aktuální forecast výkon."""
        if not self._forecast_data or "watts" not in self._forecast_data:
            return None

        try:
            now = dt_now()
            # Ujistíme se, že now je naive (bez timezone)
            if now.tzinfo is not None:
                now = now.replace(tzinfo=None)

            watts_data = self._forecast_data["watts"]

            # Najdi nejbližší čas v datech
            closest_time = None
            closest_value = None
            min_diff = float("inf")

            for time_str, value in watts_data.items():
                try:
                    # Parsování času a převod na naive datetime
                    forecast_time = datetime.fromisoformat(
                        time_str.replace("Z", "+00:00")
                    )
                    if forecast_time.tzinfo is not None:
                        forecast_time = forecast_time.replace(tzinfo=None)

                    diff = abs((now - forecast_time).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        closest_time = forecast_time
                        closest_value = value

                except (ValueError, TypeError) as e:
                    _LOGGER.debug(f"Error parsing forecast time {time_str}: {e}")
                    continue

            return closest_value if closest_value is not None else 0

        except Exception as e:
            _LOGGER.error(f"Error calculating current solar forecast: {e}")
            return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy senzoru."""
        attrs = {}

        # Kompletní forecast data jako atributy
        if self._forecast_data:
            attrs["forecast_data"] = self._forecast_data

        # Rate limit informace
        if self._rate_limit_info:
            attrs["rate_limit_info"] = self._rate_limit_info

        # Metadata
        attrs["last_forecast_update"] = (
            self._last_forecast_update.isoformat()
            if self._last_forecast_update
            else None
        )
        attrs["api_key_used"] = bool(self._api_key)
        attrs["update_interval_minutes"] = self._update_interval
        attrs["forecast_config"] = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "declination": self._declination,
            "azimuth": self._azimuth,
            "kwp": self._kwp,
        }

        # Dnešní předpověď energie
        if self._forecast_data and "watt_hours_day" in self._forecast_data:
            today = dt_now().strftime("%Y-%m-%d")
            attrs["today_forecast_kwh"] = (
                self._forecast_data["watt_hours_day"].get(today, 0) / 1000
            )

        # Přidáme info o použitých hodnotách
        attrs["ha_gps_used"] = {
            "latitude": self.coordinator.hass.config.latitude,
            "longitude": self.coordinator.hass.config.longitude,
        }
        attrs["estimated_kwp_from_sensors"] = self._get_estimated_kwp()

        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o zařízení - Solar Forecast jako součást Statistics."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return {
                "identifiers": {("oig_cloud", f"{box_id}_statistics")},
                "name": f"OIG {box_id} Statistics",
                "manufacturer": "OIG",
                "model": "Analytics & Predictions",
                "via_device": ("oig_cloud", box_id),
            }
        return {
            "identifiers": {("oig_cloud", "statistics")},
            "name": "OIG Statistics",
            "manufacturer": "OIG",
            "model": "Analytics & Predictions",
        }

    @property
    def unique_id(self) -> str:
        """Jedinečné ID pro solar forecast senzor."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return f"{box_id}_statistics_solar_forecast"
        return "statistics_solar_forecast"

    @property
    def should_poll(self) -> bool:
        """Solar forecast se neaktualizuje polling - má vlastní scheduler."""
        return False

    async def async_update(self) -> None:
        """Update senzoru - pouze při explicitním volání."""
        self.async_write_ha_state()
