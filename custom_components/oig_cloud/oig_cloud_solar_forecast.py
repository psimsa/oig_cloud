"""Solar forecast senzory pro OIG Cloud integraci."""

import asyncio
import logging
from typing import Any, Dict, Optional, Union
from datetime import datetime, timedelta
import aiohttp
import time

from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr, entity_registry as er
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

# URL pro forecast.solar API
FORECAST_SOLAR_API_URL = (
    "https://api.forecast.solar/estimate/{lat}/{lon}/{declination}/{azimuth}/{kwp}"
)
FORECAST_SOLAR_API_URL_WITH_KEY = "https://api.forecast.solar/{api_key}/estimate/{lat}/{lon}/{declination}/{azimuth}/{kwp}"


class OigCloudSolarForecastSensor(OigCloudSensor):
    """Senzor pro solar forecast data."""

    def __init__(
        self, coordinator: Any, sensor_type: str, config_entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, sensor_type)
        self._config_entry = config_entry

        # Získáme inverter_sn ze správného místa
        inverter_sn = "unknown"

        # Zkusíme získat z coordinator.config_entry.data
        if hasattr(coordinator, "config_entry") and coordinator.config_entry.data:
            inverter_sn = coordinator.config_entry.data.get("inverter_sn", "unknown")

        # Pokud stále unknown, zkusíme z coordinator.data
        if inverter_sn == "unknown" and coordinator.data:
            first_device_key = list(coordinator.data.keys())[0]
            inverter_sn = first_device_key

        # Nastavíme Analytics Module device_info - stejné jako statistics
        self._device_info = {
            "identifiers": {("oig_cloud_analytics", inverter_sn)},
            "name": f"Analytics & Predictions {inverter_sn}",
            "manufacturer": "OIG",
            "model": "Analytics Module",
            "via_device": ("oig_cloud", inverter_sn),
            "entry_type": "service",
        }

        self._last_forecast_data: Optional[Dict[str, Any]] = None
        self._last_api_call: float = 0
        self._min_api_interval: float = 300  # 5 minut mezi voláními
        self._retry_count: int = 0
        self._max_retries: int = 3
        self._update_interval_remover: Optional[Any] = None

        # Storage key pro persistentní uložení posledního API volání a dat
        self._storage_key = f"oig_solar_forecast_{inverter_sn}"

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - nastavit periodické aktualizace podle konfigurace."""
        await super().async_added_to_hass()

        # Načtení posledního času API volání a dat z persistentního úložiště
        await self._load_persistent_data()

        forecast_mode = self._config_entry.options.get(
            "solar_forecast_mode", "daily_optimized"
        )

        if forecast_mode != "manual":
            interval = self._get_update_interval(forecast_mode)
            if interval:
                self._update_interval_remover = async_track_time_interval(
                    self.hass, self._periodic_update, interval
                )
                _LOGGER.info(
                    f"🌞 Solar forecast periodic updates enabled: {forecast_mode}"
                )

        # OKAMŽITÁ inicializace dat při startu - pouze pro hlavní senzor a pouze pokud jsou data zastaralá
        if self._sensor_type == "solar_forecast" and self._should_fetch_data():
            _LOGGER.info(
                f"🌞 Data is outdated (last call: {datetime.fromtimestamp(self._last_api_call).strftime('%Y-%m-%d %H:%M:%S') if self._last_api_call else 'never'}), triggering immediate fetch"
            )
            # Spustíme úlohu na pozadí s malým zpožděním
            self.hass.async_create_task(self._delayed_initial_fetch())
        else:
            # Pokud máme načtená data z úložiště, sdílíme je s koordinátorem
            if self._last_forecast_data:
                if hasattr(self.coordinator, "solar_forecast_data"):
                    self.coordinator.solar_forecast_data = self._last_forecast_data
                else:
                    setattr(
                        self.coordinator,
                        "solar_forecast_data",
                        self._last_forecast_data,
                    )
                _LOGGER.info(
                    f"🌞 Loaded forecast data from storage (last call: {datetime.fromtimestamp(self._last_api_call).strftime('%Y-%m-%d %H:%M:%S')}), skipping immediate fetch"
                )

    async def _load_persistent_data(self) -> None:
        """Načte čas posledního API volání a forecast data z persistentního úložiště."""
        try:
            store = Store(
                self.hass,
                version=1,
                key=self._storage_key,
            )
            data = await store.async_load()

            if data:
                # Načtení času posledního API volání
                if isinstance(data.get("last_api_call"), (int, float)):
                    self._last_api_call = float(data["last_api_call"])
                    _LOGGER.debug(
                        f"🌞 Loaded last API call time: {datetime.fromtimestamp(self._last_api_call).strftime('%Y-%m-%d %H:%M:%S')}"
                    )

                # Načtení forecast dat
                if isinstance(data.get("forecast_data"), dict):
                    self._last_forecast_data = data["forecast_data"]
                    _LOGGER.debug(
                        f"🌞 Loaded forecast data from storage with {len(self._last_forecast_data)} keys"
                    )
                else:
                    _LOGGER.debug("🌞 No forecast data found in storage")
            else:
                _LOGGER.debug("🌞 No previous data found in storage")

        except Exception as e:
            _LOGGER.warning(f"🌞 Failed to load persistent data: {e}")
            self._last_api_call = 0
            self._last_forecast_data = None

    async def _save_persistent_data(self) -> None:
        """Uloží čas posledního API volání a forecast data do persistentního úložiště."""
        try:
            store = Store(
                self.hass,
                version=1,
                key=self._storage_key,
            )

            save_data = {
                "last_api_call": self._last_api_call,
                "forecast_data": self._last_forecast_data,
                "saved_at": datetime.now().isoformat(),
            }

            await store.async_save(save_data)
            _LOGGER.debug(
                f"🌞 Saved persistent data: API call time {datetime.fromtimestamp(self._last_api_call).strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            _LOGGER.warning(f"🌞 Failed to save persistent data: {e}")

    async def _load_last_api_call(self) -> None:
        """Načte čas posledního API volání z persistentního úložiště."""
        # Tato metoda je teď nahrazena _load_persistent_data
        pass

    async def _save_last_api_call(self) -> None:
        """Uloží čas posledního API volání do persistentního úložiště."""
        # Tato metoda je teď nahrazena _save_persistent_data
        pass

    def _should_fetch_data(self) -> bool:
        """Rozhodne zda je potřeba načíst nová data na základě módu a posledního volání."""
        current_time = time.time()

        # Pokud nemáme žádná data
        if not self._last_api_call:
            return True

        forecast_mode = self._config_entry.options.get(
            "solar_forecast_mode", "daily_optimized"
        )

        time_since_last = current_time - self._last_api_call

        # Pro různé módy různé intervaly
        if forecast_mode == "daily_optimized":
            # Data starší než 4 hodiny vyžadují aktualizaci
            return time_since_last > 14400  # 4 hodiny
        elif forecast_mode == "daily":
            # Data starší než 20 hodin vyžadují aktualizaci
            return time_since_last > 72000  # 20 hodin
        elif forecast_mode == "every_4h":
            # Data starší než 4 hodiny
            return time_since_last > 14400  # 4 hodiny
        elif forecast_mode == "hourly":
            # Data starší než 1 hodinu
            return time_since_last > 3600  # 1 hodina

        # Pro manual mode nikdy neaktualizujeme automaticky
        return False

    def _get_update_interval(self, mode: str) -> Optional[timedelta]:
        """Získá interval aktualizace podle módu."""
        intervals = {
            "hourly": timedelta(hours=1),  # Pro testing - vysoká frekvence
            "every_4h": timedelta(hours=4),  # Klasický 4-hodinový
            "daily": timedelta(hours=24),  # Jednou denně
            "daily_optimized": timedelta(
                minutes=30
            ),  # Každých 30 minut, ale update jen 3x denně
            "manual": None,  # Pouze manuální
        }
        return intervals.get(mode)

    async def _delayed_initial_fetch(self) -> None:
        """Spustí okamžitou aktualizaci s malým zpožděním."""
        # Počkáme 5 sekund na dokončení inicializace
        await asyncio.sleep(5)

        try:
            _LOGGER.info("🌞 Starting immediate solar forecast data fetch")
            await self.async_fetch_forecast_data()
            _LOGGER.info("🌞 Initial solar forecast data fetch completed")
        except Exception as e:
            _LOGGER.error(f"🌞 Initial solar forecast fetch failed: {e}")

    async def _periodic_update(self, now: datetime) -> None:
        """Periodická aktualizace - optimalizovaná pro 3x denně."""
        forecast_mode = self._config_entry.options.get(
            "solar_forecast_mode", "daily_optimized"
        )

        current_time = time.time()

        # Kontrola rate limiting - nikdy neaktualizujeme častěji než každých 5 minut
        if current_time - self._last_api_call < self._min_api_interval:
            _LOGGER.debug(
                f"🌞 Rate limiting: {(current_time - self._last_api_call)/60:.1f} minutes since last call"
            )
            return

        # Pro optimalizovaný denní režim - kontrolujeme konkrétní hodiny
        if forecast_mode == "daily_optimized":
            # Aktualizace pouze v 6:00, 12:00 a 16:00 (±5 minut tolerance)
            target_hours = [6, 12, 16]
            current_hour = now.hour
            current_minute = now.minute

            # Kontrola zda jsme v požadované hodině a prvních 5 minutách
            if current_hour in target_hours and current_minute <= 5:
                # Dodatečná kontrola - neaktualizovali jsme už v posledních 3 hodinách?
                if self._last_api_call:
                    time_since_last = current_time - self._last_api_call
                    if time_since_last < 10800:  # 3 hodiny
                        _LOGGER.debug(
                            f"🌞 Skipping update - last call was {time_since_last/60:.1f} minutes ago"
                        )
                        return

                # Pouze hlavní sensor provádí API call
                if self._sensor_type == "solar_forecast":
                    _LOGGER.info(
                        f"🌞 Scheduled solar forecast update at {current_hour}:00"
                    )
                    await self.async_fetch_forecast_data()
            return

        # Pro denní režim kontrolujeme čas a datum posledního volání
        elif forecast_mode == "daily":
            if now.hour != 6:  # Pouze v 6:00
                return

            # Kontrola zda jsme už dnes neaktualizovali
            if self._last_api_call:
                last_call_date = datetime.fromtimestamp(self._last_api_call).date()
                if last_call_date == now.date():
                    _LOGGER.debug("🌞 Already updated today, skipping")
                    return

            # Pouze hlavní sensor provádí API call
            if self._sensor_type == "solar_forecast":
                await self.async_fetch_forecast_data()

        # Pro every_4h režim
        elif forecast_mode == "every_4h":
            if self._last_api_call:
                time_since_last = current_time - self._last_api_call
                if time_since_last < 14400:  # 4 hodiny
                    return

            if self._sensor_type == "solar_forecast":
                await self.async_fetch_forecast_data()

        # Pro hodinový režim
        elif forecast_mode == "hourly":
            if self._last_api_call:
                time_since_last = current_time - self._last_api_call
                if time_since_last < 3600:  # 1 hodina
                    return

            if self._sensor_type == "solar_forecast":
                await self.async_fetch_forecast_data()

    # Přidání metody pro okamžitou aktualizaci
    async def async_manual_update(self) -> bool:
        """Manuální aktualizace forecast dat - pro službu."""
        try:
            _LOGGER.info(
                f"🌞 Manual solar forecast update requested for {self.entity_id}"
            )
            await self.async_fetch_forecast_data()
            return True
        except Exception as e:
            _LOGGER.error(
                f"Manual solar forecast update failed for {self.entity_id}: {e}"
            )
            return False

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA - zrušit periodické aktualizace."""
        if self._update_interval_remover:
            self._update_interval_remover()
            self._update_interval_remover = None
        await super().async_will_remove_from_hass()

    async def async_fetch_forecast_data(self) -> None:
        """Získání forecast dat z API pro oba stringy."""
        try:
            _LOGGER.debug(f"[{self.entity_id}] Starting solar forecast API call")

            current_time = time.time()

            # Kontrola rate limiting
            if current_time - self._last_api_call < self._min_api_interval:
                remaining_time = self._min_api_interval - (
                    current_time - self._last_api_call
                )
                _LOGGER.warning(
                    f"🌞 Rate limiting: waiting {remaining_time:.1f} seconds before next API call"
                )
                return

            # Konfigurační parametry
            lat = self._config_entry.options.get("solar_forecast_latitude", 50.1219800)
            lon = self._config_entry.options.get("solar_forecast_longitude", 13.9373742)
            api_key = self._config_entry.options.get("solar_forecast_api_key", "")

            # String 1 - zapnutý podle checkboxu
            string1_enabled = self._config_entry.options.get(
                "solar_forecast_string1_enabled", True
            )

            # String 2 - zapnutý podle checkboxu
            string2_enabled = self._config_entry.options.get(
                "solar_forecast_string2_enabled", False
            )

            _LOGGER.debug(f"🌞 String 1: enabled={string1_enabled}")
            _LOGGER.debug(f"🌞 String 2: enabled={string2_enabled}")

            # Pro API key už nepotřebujeme headers, protože je v URL
            headers = {}
            data_string1 = None
            data_string2 = None

            # Získání dat pro String 1 (pokud je zapnutý)
            if string1_enabled:
                string1_declination = self._config_entry.options.get(
                    "solar_forecast_string1_declination", 10
                )
                string1_azimuth = self._config_entry.options.get(
                    "solar_forecast_string1_azimuth", 138
                )
                string1_kwp = self._config_entry.options.get(
                    "solar_forecast_string1_kwp", 5.4
                )

                # URL s nebo bez API key
                if api_key:
                    url_string1 = FORECAST_SOLAR_API_URL_WITH_KEY.format(
                        api_key=api_key,
                        lat=lat,
                        lon=lon,
                        declination=string1_declination,
                        azimuth=string1_azimuth,
                        kwp=string1_kwp,
                    )
                else:
                    url_string1 = FORECAST_SOLAR_API_URL.format(
                        lat=lat,
                        lon=lon,
                        declination=string1_declination,
                        azimuth=string1_azimuth,
                        kwp=string1_kwp,
                    )

                _LOGGER.info(
                    f"🌞 Calling forecast.solar API for string 1: {url_string1}"
                )

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url_string1, headers=headers, timeout=30
                    ) as response:
                        if response.status == 200:
                            data_string1 = await response.json()
                            _LOGGER.debug("🌞 String 1 data received successfully")
                        elif response.status == 422:
                            error_text = await response.text()
                            _LOGGER.warning(f"🌞 String 1 API error 422: {error_text}")
                            return
                        elif response.status == 429:
                            _LOGGER.warning("🌞 String 1 rate limited")
                            return
                        else:
                            error_text = await response.text()
                            _LOGGER.error(
                                f"🌞 String 1 API error {response.status}: {error_text}"
                            )
                            return
            else:
                _LOGGER.debug("🌞 String 1 disabled")

            # Získání dat pro String 2 (pokud je zapnutý)
            if string2_enabled:
                string2_declination = self._config_entry.options.get(
                    "solar_forecast_string2_declination", 10
                )
                string2_azimuth = self._config_entry.options.get(
                    "solar_forecast_string2_azimuth", 138
                )
                string2_kwp = self._config_entry.options.get(
                    "solar_forecast_string2_kwp", 0
                )

                # URL s nebo bez API key
                if api_key:
                    url_string2 = FORECAST_SOLAR_API_URL_WITH_KEY.format(
                        api_key=api_key,
                        lat=lat,
                        lon=lon,
                        declination=string2_declination,
                        azimuth=string2_azimuth,
                        kwp=string2_kwp,
                    )
                else:
                    url_string2 = FORECAST_SOLAR_API_URL.format(
                        lat=lat,
                        lon=lon,
                        declination=string2_declination,
                        azimuth=string2_azimuth,
                        kwp=string2_kwp,
                    )

                _LOGGER.info(
                    f"🌞 Calling forecast.solar API for string 2: {url_string2}"
                )

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url_string2, headers=headers, timeout=30
                    ) as response:
                        if response.status == 200:
                            data_string2 = await response.json()
                            _LOGGER.debug("🌞 String 2 data received successfully")
                        elif response.status == 422:
                            error_text = await response.text()
                            _LOGGER.warning(f"🌞 String 2 API error 422: {error_text}")
                            # Pro string 2 pokračujeme i s chybou
                        elif response.status == 429:
                            _LOGGER.warning("🌞 String 2 rate limited")
                        else:
                            error_text = await response.text()
                            _LOGGER.error(
                                f"🌞 String 2 API error {response.status}: {error_text}"
                            )
            else:
                _LOGGER.debug("🌞 String 2 disabled")

            # Kontrola, zda máme alespoň jeden string s daty
            if not data_string1 and not data_string2:
                _LOGGER.error(
                    "🌞 No data received - at least one string must be enabled"
                )
                return

            # Zpracování dat
            self._last_forecast_data = self._process_forecast_data(
                data_string1, data_string2
            )
            self._last_api_call = current_time

            # Uložení času posledního API volání a dat do persistentního úložiště
            await self._save_persistent_data()

            # Uložení dat do koordinátoru pro sdílení mezi senzory
            if hasattr(self.coordinator, "solar_forecast_data"):
                self.coordinator.solar_forecast_data = self._last_forecast_data
            else:
                setattr(
                    self.coordinator, "solar_forecast_data", self._last_forecast_data
                )

            _LOGGER.info(
                f"🌞 Solar forecast data updated successfully - last API call: {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Aktualizuj stav tohoto senzoru
            self.async_write_ha_state()

            # NOVÉ: Pošli signál ostatním solar forecast sensorům, že jsou dostupná nová data
            await self._broadcast_forecast_data()

        except asyncio.TimeoutError:
            _LOGGER.warning(f"[{self.entity_id}] Timeout fetching solar forecast data")
            self._last_forecast_data = {
                "error": "Timeout",
                "response_time": datetime.now().isoformat(),
            }
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error fetching solar forecast data: {e}")
            self._last_forecast_data = {
                "error": str(e),
                "response_time": datetime.now().isoformat(),
            }

    async def _broadcast_forecast_data(self) -> None:
        """Pošle signál ostatním solar forecast sensorům o nových datech."""
        try:
            # Získáme registry správným způsobem
            device_registry = dr.async_get(self.hass)
            entity_registry = er.async_get(self.hass)

            # Najdeme naše zařízení
            device_id = None
            entity_entry = entity_registry.async_get(self.entity_id)
            if entity_entry:
                device_id = entity_entry.device_id

            if device_id:
                # Najdeme všechny entity tohoto zařízení
                device_entities = er.async_entries_for_device(
                    entity_registry, device_id
                )

                # Aktualizujeme všechny solar forecast senzory
                for device_entity in device_entities:
                    if device_entity.entity_id.endswith(
                        "_solar_forecast_string1"
                    ) or device_entity.entity_id.endswith("_solar_forecast_string2"):

                        entity = self.hass.states.get(device_entity.entity_id)
                        if entity:
                            # Spustíme aktualizaci entity
                            self.hass.async_create_task(
                                self.hass.services.async_call(
                                    "homeassistant",
                                    "update_entity",
                                    {"entity_id": device_entity.entity_id},
                                )
                            )
                            _LOGGER.debug(
                                f"🌞 Triggered update for {device_entity.entity_id}"
                            )
        except Exception as e:
            _LOGGER.error(f"Error broadcasting forecast data: {e}")

    def _process_forecast_data(
        self,
        data_string1: Optional[Dict[str, Any]],
        data_string2: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Zpracuje data z forecast.solar API."""
        result = {
            "response_time": datetime.now().isoformat(),
        }

        try:
            # Inicializace prázdných hodnot
            total_hourly: Dict[str, float] = {}
            total_daily: Dict[str, float] = {}

            # Zpracování String 1 dat (pouze pokud existují)
            if data_string1 and "result" in data_string1:
                string1_watts = data_string1.get("result", {}).get("watts", {})
                string1_wh_day = data_string1.get("result", {}).get(
                    "watt_hours_day", {}
                )

                # Převod na hodinová data pro String 1
                string1_hourly = self._convert_to_hourly(string1_watts)
                string1_daily = {
                    k: v / 1000 for k, v in string1_wh_day.items()
                }  # Převod na kWh

                result.update(
                    {
                        "string1_hourly": string1_hourly,
                        "string1_daily": string1_daily,
                        "string1_today_kwh": next(iter(string1_daily.values()), 0),
                        "string1_raw_data": data_string1,
                    }
                )

                # Inicializace celkových dat s String 1
                total_hourly = string1_hourly.copy()
                total_daily = string1_daily.copy()
            else:
                # String 1 není nakonfigurován - prázdné hodnoty
                result.update(
                    {
                        "string1_hourly": {},
                        "string1_daily": {},
                        "string1_today_kwh": 0,
                    }
                )

            # Zpracování String 2 dat (pokud existují)
            if data_string2 and "result" in data_string2:
                string2_watts = data_string2.get("result", {}).get("watts", {})
                string2_wh_day = data_string2.get("result", {}).get(
                    "watt_hours_day", {}
                )

                string2_hourly = self._convert_to_hourly(string2_watts)
                string2_daily = {k: v / 1000 for k, v in string2_wh_day.items()}

                result.update(
                    {
                        "string2_hourly": string2_hourly,
                        "string2_daily": string2_daily,
                        "string2_today_kwh": next(iter(string2_daily.values()), 0),
                        "string2_raw_data": data_string2,
                    }
                )

                # Pokud nemáme String 1 data, inicializujeme celkové hodnoty s String 2
                if not total_hourly:
                    total_hourly = string2_hourly.copy()
                    total_daily = string2_daily.copy()
                else:
                    # Sečtení obou stringů pro celkové hodnoty
                    for hour, power in string2_hourly.items():
                        total_hourly[hour] = total_hourly.get(hour, 0) + power

                    for day, energy in string2_daily.items():
                        total_daily[day] = total_daily.get(day, 0) + energy
            else:
                # String 2 není nakonfigurován - prázdné hodnoty
                result.update(
                    {
                        "string2_hourly": {},
                        "string2_daily": {},
                        "string2_today_kwh": 0,
                    }
                )

            # Celkové hodnoty
            result.update(
                {
                    "total_hourly": total_hourly,
                    "total_daily": total_daily,
                    "total_today_kwh": next(iter(total_daily.values()), 0),
                }
            )

            _LOGGER.debug(
                f"Processed forecast data: String1 today: {result['string1_today_kwh']:.1f}kWh, "
                f"String2 today: {result['string2_today_kwh']:.1f}kWh, "
                f"Total today: {result['total_today_kwh']:.1f}kWh"
            )

        except Exception as e:
            _LOGGER.error(f"Error processing forecast data: {e}", exc_info=True)
            result["error"] = str(e)

        return result

    def _convert_to_hourly(self, watts_data: Dict[str, float]) -> Dict[str, float]:
        """Převede forecast data na hodinová data."""
        hourly_data = {}

        for timestamp_str, power in watts_data.items():
            try:
                # Parsování timestamp (forecast.solar používá UTC čas)
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                # Zaokrouhlení na celou hodinu
                hour_key = dt.replace(minute=0, second=0, microsecond=0).isoformat()
                # Uchování nejvyšší hodnoty pro danou hodinu
                hourly_data[hour_key] = max(hourly_data.get(hour_key, 0), power)
            except Exception as e:
                _LOGGER.debug(f"Error parsing timestamp {timestamp_str}: {e}")

        return hourly_data

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info - Analytics Module."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # OPRAVA 3: Hlavní kontrola - je solar forecast zapnutý?
        solar_enabled = self._config_entry.options.get("enable_solar_forecast", False)

        if not solar_enabled:
            return False  # Modul je vypnutý - senzor není dostupný

        # Dodatečné kontroly pro stringy
        if self._sensor_type == "solar_forecast_string1":
            string1_enabled = self._config_entry.options.get(
                "solar_forecast_string1_enabled", False
            )
            return string1_enabled

        elif self._sensor_type == "solar_forecast_string2":
            string2_enabled = self._config_entry.options.get(
                "solar_forecast_string2_enabled", False
            )
            return string2_enabled

        # Pro hlavní senzor - dostupný pokud je alespoň jeden string zapnutý
        elif self._sensor_type == "solar_forecast":
            string1_enabled = self._config_entry.options.get(
                "solar_forecast_string1_enabled", False
            )
            string2_enabled = self._config_entry.options.get(
                "solar_forecast_string2_enabled", False
            )
            return string1_enabled or string2_enabled

        return True  # Default pro ostatní typy

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Stav senzoru - celková denní prognóza výroby v kWh."""
        # Pokud není dostupný, vrátit None
        if not self.available:
            return None

        # Zkusíme načíst data z koordinátoru pokud nemáme vlastní
        if not self._last_forecast_data and hasattr(
            self.coordinator, "solar_forecast_data"
        ):
            self._last_forecast_data = self.coordinator.solar_forecast_data
            _LOGGER.debug(
                f"🌞 {self._sensor_type}: loaded shared data from coordinator"
            )

        if not self._last_forecast_data:
            return None

        try:
            if self._sensor_type == "solar_forecast":
                # Celková denní výroba z obou stringů v kWh
                return round(self._last_forecast_data.get("total_today_kwh", 0), 2)

            elif self._sensor_type == "solar_forecast_string1":
                # Denní výroba jen z string1 v kWh
                return round(self._last_forecast_data.get("string1_today_kwh", 0), 2)

            elif self._sensor_type == "solar_forecast_string2":
                # Denní výroba jen z string2 v kWh
                return round(self._last_forecast_data.get("string2_today_kwh", 0), 2)

        except Exception as e:
            _LOGGER.error(f"Error getting solar forecast state: {e}")

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy s hodinovými výkony a aktuální hodinovou prognózou."""
        if not self._last_forecast_data:
            return {}

        attrs = {}

        try:
            # Základní informace
            attrs["response_time"] = self._last_forecast_data.get("response_time")

            # Aktuální hodinová prognóza jako atribut
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)

            if self._sensor_type == "solar_forecast":
                # Hlavní senzor - celkové hodnoty + detaily obou stringů
                attrs.update(
                    {
                        "today_total_kwh": self._last_forecast_data.get(
                            "total_today_kwh", 0
                        ),
                        "string1_today_kwh": self._last_forecast_data.get(
                            "string1_today_kwh", 0
                        ),
                        "string2_today_kwh": self._last_forecast_data.get(
                            "string2_today_kwh", 0
                        ),
                    }
                )

                # Aktuální hodinová prognóza
                total_hourly = self._last_forecast_data.get("total_hourly", {})
                current_hour_watts = total_hourly.get(current_hour.isoformat(), 0)
                attrs["current_hour_kw"] = round(current_hour_watts / 1000, 2)

                # Hodinové výkony pro dnes a zítra - s timestamp
                string1_hourly = self._last_forecast_data.get("string1_hourly", {})
                string2_hourly = self._last_forecast_data.get("string2_hourly", {})

                # Rozdělíme na dnes a zítra - ponecháme timestamp
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)

                today_total = {}
                tomorrow_total = {}
                today_string1 = {}
                tomorrow_string1 = {}
                today_string2 = {}
                tomorrow_string2 = {}

                # Sumy pro dnes a zítra
                today_total_sum = 0
                tomorrow_total_sum = 0
                today_string1_sum = 0
                tomorrow_string1_sum = 0
                today_string2_sum = 0
                tomorrow_string2_sum = 0

                for hour_str, power in total_hourly.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        power_kw = round(power / 1000, 2)

                        if hour_dt.date() == today:
                            today_total[hour_str] = power_kw
                            today_total_sum += power_kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_total[hour_str] = power_kw
                            tomorrow_total_sum += power_kw
                    except:
                        continue

                for hour_str, power in string1_hourly.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        power_kw = round(power / 1000, 2)

                        if hour_dt.date() == today:
                            today_string1[hour_str] = power_kw
                            today_string1_sum += power_kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_string1[hour_str] = power_kw
                            tomorrow_string1_sum += power_kw
                    except:
                        continue

                for hour_str, power in string2_hourly.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        power_kw = round(power / 1000, 2)

                        if hour_dt.date() == today:
                            today_string2[hour_str] = power_kw
                            today_string2_sum += power_kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_string2[hour_str] = power_kw
                            tomorrow_string2_sum += power_kw
                    except:
                        continue

                attrs.update(
                    {
                        "today_hourly_total_kw": today_total,
                        "tomorrow_hourly_total_kw": tomorrow_total,
                        "today_hourly_string1_kw": today_string1,
                        "tomorrow_hourly_string1_kw": tomorrow_string1,
                        "today_hourly_string2_kw": today_string2,
                        "tomorrow_hourly_string2_kw": tomorrow_string2,
                        # Sumy hodinových výkonů
                        "today_total_sum_kw": round(today_total_sum, 2),
                        "tomorrow_total_sum_kw": round(tomorrow_total_sum, 2),
                        "today_string1_sum_kw": round(today_string1_sum, 2),
                        "tomorrow_string1_sum_kw": round(tomorrow_string1_sum, 2),
                        "today_string2_sum_kw": round(today_string2_sum, 2),
                        "tomorrow_string2_sum_kw": round(tomorrow_string2_sum, 2),
                    }
                )

            elif self._sensor_type == "solar_forecast_string1":
                # String 1 senzor
                attrs["today_kwh"] = self._last_forecast_data.get(
                    "string1_today_kwh", 0
                )

                # Aktuální hodinová prognóza
                string1_hourly = self._last_forecast_data.get("string1_hourly", {})
                current_hour_watts = string1_hourly.get(current_hour.isoformat(), 0)
                attrs["current_hour_kw"] = round(current_hour_watts / 1000, 2)

                # Hodinové výkony jen pro string 1 - s timestamp
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)

                today_hours = {}
                tomorrow_hours = {}
                today_sum = 0
                tomorrow_sum = 0

                for hour_str, power in today_hours.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        power_kw = round(power / 1000, 2)

                        if hour_dt.date() == today:
                            today_hours[hour_str] = power_kw
                            today_sum += power_kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_hours[hour_str] = power_kw
                            tomorrow_sum += power_kw
                    except:
                        continue

                attrs.update(
                    {
                        "today_hourly_kw": today_hours,
                        "tomorrow_hourly_kw": tomorrow_hours,
                        "today_sum_kw": round(today_sum, 2),
                        "tomorrow_sum_kw": round(tomorrow_sum, 2),
                    }
                )

            elif self._sensor_type == "solar_forecast_string2":
                # String 2 senzor
                attrs["today_kwh"] = self._last_forecast_data.get(
                    "string2_today_kwh", 0
                )

                # Aktuální hodinová prognóza
                string2_hourly = self._last_forecast_data.get("string2_hourly", {})
                current_hour_watts = string2_hourly.get(current_hour.isoformat(), 0)
                attrs["current_hour_kw"] = round(current_hour_watts / 1000, 2)

                # Hodinové výkony jen pro string 2 - s timestamp
                today = datetime.now().date()
                tomorrow = today + timedelta(days=1)

                today_hours = {}
                tomorrow_hours = {}
                today_sum = 0
                tomorrow_sum = 0

                for hour_str, power in today_hours.items():
                    try:
                        hour_dt = datetime.fromisoformat(hour_str)
                        power_kw = round(power / 1000, 2)

                        if hour_dt.date() == today:
                            today_hours[hour_str] = power_kw
                            today_sum += power_kw
                        elif hour_dt.date() == tomorrow:
                            tomorrow_hours[hour_str] = power_kw
                            tomorrow_sum += power_kw
                    except:
                        continue

                attrs.update(
                    {
                        "today_hourly_kw": today_hours,
                        "tomorrow_hourly_kw": tomorrow_hours,
                        "today_sum_kw": round(today_sum, 2),
                        "tomorrow_sum_kw": round(tomorrow_sum, 2),
                    }
                )

        except Exception as e:
            _LOGGER.error(f"Error creating solar forecast attributes: {e}")
            attrs["error"] = str(e)

        return attrs
