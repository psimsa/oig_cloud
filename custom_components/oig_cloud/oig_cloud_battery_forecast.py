"""Senzor pro predikci nabití baterie v průběhu dne."""

import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta
import statistics
import asyncio

from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)


class OigCloudBatteryForecastSensor(OigCloudSensor):
    """Senzor pro predikci nabití baterie."""

    def __init__(
        self, coordinator: Any, sensor_type: str, config_entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, sensor_type)
        self._config_entry = config_entry
        self._hass: Optional[HomeAssistant] = None

        # Získáme inverter_sn ze správného místa
        inverter_sn = "unknown"

        # Zkusíme získat z coordinator.config_entry.data
        if hasattr(coordinator, "config_entry") and coordinator.config_entry.data:
            inverter_sn = coordinator.config_entry.data.get("inverter_sn", "unknown")
            _LOGGER.debug(
                f"Battery forecast: Got inverter_sn from coordinator.config_entry: {inverter_sn}"
            )

        # Pokud stále unknown, zkusíme z coordinator.data
        if inverter_sn == "unknown" and coordinator.data:
            first_device_key = list(coordinator.data.keys())[0]
            inverter_sn = first_device_key
            _LOGGER.debug(
                f"Battery forecast: Got inverter_sn from coordinator.data keys: {inverter_sn}"
            )

        # Pokud stále unknown, něco je špatně - nebudeme vytvářet senzor
        if inverter_sn == "unknown":
            _LOGGER.error(
                "Battery forecast: Cannot determine inverter_sn - skipping sensor creation"
            )
            raise ValueError("Cannot determine inverter_sn for battery forecast sensor")

        _LOGGER.debug(f"Battery forecast: Final inverter_sn: {inverter_sn}")

        # Nastavíme Analytics Module device_info - stejné jako statistics
        self._device_info = {
            "identifiers": {("oig_cloud_analytics", inverter_sn)},
            "name": f"Analytics & Predictions {inverter_sn}",
            "manufacturer": "OIG",
            "model": "Analytics Module",
            "via_device": ("oig_cloud", inverter_sn),
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA."""
        await super().async_added_to_hass()
        self._hass = self.hass

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        await super().async_will_remove_from_hass()

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info - Analytics Module."""
        return self._device_info

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Stav senzoru - aktuální predikovaná kapacita baterie."""
        # Čteme data z koordinátoru
        forecast_data = getattr(self.coordinator, "battery_forecast_data", None)

        if not forecast_data or not forecast_data.get("forecast"):
            return None

        forecast = forecast_data["forecast"]
        if forecast:
            return round(forecast[0]["y"], 2)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy s celou predikcí."""
        # Čteme data z koordinátoru
        forecast_data = getattr(self.coordinator, "battery_forecast_data", None)

        if not forecast_data:
            return {}

        return {
            "forecast": forecast_data.get("forecast", []),
            "charging_hours": forecast_data.get("home_charging_hours", []),
            "last_update": datetime.now().isoformat(),
        }

    async def async_update(self) -> None:
        """Aktualizace - nepotřebná, data se aktualizují v koordinátoru."""
        pass

    async def _calculate_battery_forecast(self) -> Dict[str, Any]:
        """Výpočet predikce nabití baterie."""
        _LOGGER.debug("🔋 Starting battery forecast calculation")

        # Načtení konfiguračních hodnot z naší integrace
        home_battery_capacity_max = self._get_state_float(
            "sensor.usable_battery_capacity", 0
        )
        if home_battery_capacity_max <= 0:
            _LOGGER.warning("🔋 Usable battery capacity not available or zero")
            return {"forecast": [], "home_charging_hours": []}

        min_capacity_percent = self._config_entry.options.get(
            "min_capacity_percent", 20.0
        )
        min_home_battery_capacity = (
            min_capacity_percent / 100.0
        ) * home_battery_capacity_max
        home_charge_rate = (
            self._config_entry.options.get("home_charge_rate", 2800) / 1000.0
        )  # převod na kWh
        current_home_battery_capacity = self._get_state_float(
            "sensor.remaining_usable_capacity", 0
        )

        _LOGGER.debug(
            f"🔋 Battery capacity: {current_home_battery_capacity}/{home_battery_capacity_max} kWh"
        )
        _LOGGER.debug(
            f"🔋 Min capacity: {min_home_battery_capacity} kWh ({min_capacity_percent}%)"
        )
        _LOGGER.debug(f"🔋 Charge rate: {home_charge_rate} kW")

        percentile_conf = self._config_entry.options.get("percentile_conf", 80.0)
        max_price_conf = self._config_entry.options.get("max_price_conf", 4.0)
        total_hours = self._config_entry.options.get("total_hours", 24)

        current_time = datetime.now().replace(minute=0, second=0, microsecond=0)

        # Získání spotových cen
        spot_prices = self._get_spot_prices()
        _LOGGER.debug(f"🔋 Found {len(spot_prices)} spot prices")

        # Získání solar forecast dat
        solar_forecast = self._get_solar_forecast()
        _LOGGER.debug(f"🔋 Found {len(solar_forecast)} solar forecast data points")

        # Vytvoření times_to_simulate
        times_to_simulate = self._create_simulation_times(
            current_time, total_hours, spot_prices, solar_forecast
        )

        # Výpočet percentilu cen
        median_price = self._calculate_percentile_price(
            times_to_simulate, percentile_conf, max_price_conf
        )

        # Přidání is_peak atributu
        times_to_simulate = self._add_peak_attribute(times_to_simulate, median_price)

        # Simulace a optimalizace nabíjení
        forecast, charging_hours = self._simulate_charging(
            times_to_simulate,
            current_home_battery_capacity,
            home_battery_capacity_max,
            min_home_battery_capacity,
            home_charge_rate,
            median_price,
        )

        return {"forecast": forecast, "home_charging_hours": charging_hours}

    def _get_state_float(self, entity_id: str, default: float) -> float:
        """Získání float hodnoty ze stavu entity."""
        if not self._hass:
            return default

        state = self._hass.states.get(entity_id)
        if state is None:
            return default

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _get_spot_prices(self) -> List[Dict[str, Any]]:
        """Získání spotových cen ze senzoru."""
        if not self._hass:
            return []

        spot_sensor = self._hass.states.get("sensor.adjusted_spot_electricity_prices")
        if not spot_sensor:
            return []

        spot_prices = spot_sensor.attributes.get("data", [])
        if not spot_prices:
            return []

        # Vyfiltrování pouze budoucích cen
        current_time = datetime.now().replace(minute=0, second=0, microsecond=0)
        future_prices = [
            price
            for price in spot_prices
            if price.get("timestamp")
            and datetime.fromisoformat(price["timestamp"]) >= current_time
        ]

        return sorted(future_prices, key=lambda x: x["timestamp"])

    def _get_solar_forecast(self) -> Dict[str, float]:
        """Získání solar forecast dat z našeho senzoru."""
        if not self._hass:
            return {}

        # Pokusíme se najít solar forecast senzor podle inverter_sn
        inverter_sn = "unknown"
        if (
            hasattr(self.coordinator, "config_entry")
            and self.coordinator.config_entry.data
        ):
            inverter_sn = self.coordinator.config_entry.data.get(
                "inverter_sn", "unknown"
            )
        elif self.coordinator.data:
            first_device_key = list(self.coordinator.data.keys())[0]
            inverter_sn = first_device_key

        # Zkusíme najít senzor podle entity_id formátu
        solar_sensor_id = f"sensor.{inverter_sn}_solar_forecast"
        solar_sensor = self._hass.states.get(solar_sensor_id)

        if not solar_sensor:
            # Fallback na generický název
            solar_sensor = self._hass.states.get("sensor.solar_forecast")

        if not solar_sensor:
            _LOGGER.warning(f"Solar forecast sensor not found: {solar_sensor_id}")
            return {}

        # Získáme hodinová data z atributů
        today_hourly = solar_sensor.attributes.get("today_hourly_total_kw", {})
        tomorrow_hourly = solar_sensor.attributes.get("tomorrow_hourly_total_kw", {})

        # Sloučíme data a převedeme na watts
        solar_forecast = {}
        for timestamp, power_kw in today_hourly.items():
            solar_forecast[timestamp] = power_kw * 1000  # převod na watts

        for timestamp, power_kw in tomorrow_hourly.items():
            solar_forecast[timestamp] = power_kw * 1000  # převod na watts

        return solar_forecast

    def _create_simulation_times(
        self,
        current_time: datetime,
        total_hours: int,
        spot_prices: List[Dict[str, Any]],
        solar_forecast: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Vytvoření seznamu časů pro simulaci."""
        times_to_simulate = []

        for i in range(total_hours + 1):
            time = current_time + timedelta(hours=i)
            hour = time.hour
            is_weekend = time.weekday() >= 5

            # Určení senzoru spotřeby na základě hodiny
            load = self._get_load_for_hour(hour, is_weekend)
            load_kwh = -1 * load / 1000
            if load_kwh >= 0:
                load_kwh = -0.5

            # Vyhledání ceny
            time_iso = time.isoformat()
            price = None
            for price_entry in spot_prices:
                if price_entry.get("timestamp") == time_iso:
                    price = price_entry.get("price")
                    break

            # Získání solar výkonu
            solar_power = solar_forecast.get(time_iso, 0)

            times_to_simulate.append(
                {
                    "time": time,
                    "hour": hour,
                    "price": price,
                    "load": load_kwh,
                    "solar_power": solar_power,
                }
            )

        return times_to_simulate

    def _get_load_for_hour(self, hour: int, is_weekend: bool) -> float:
        """Získání spotřeby pro danou hodinu."""
        if not self._hass:
            return 500.0  # default hodnota

        # Pokusíme se najít statistics senzory podle inverter_sn
        inverter_sn = "unknown"
        if (
            hasattr(self.coordinator, "config_entry")
            and self.coordinator.config_entry.data
        ):
            inverter_sn = self.coordinator.config_entry.data.get(
                "inverter_sn", "unknown"
            )
        elif self.coordinator.data:
            first_device_key = list(self.coordinator.data.keys())[0]
            inverter_sn = first_device_key

        # Určení senzoru na základě hodiny a víkendu
        if 6 <= hour < 8:
            sensor_name = (
                f"sensor.{inverter_sn}_load_avg_6_8_weekend"
                if is_weekend
                else f"sensor.{inverter_sn}_load_avg_6_8_weekday"
            )
        elif 8 <= hour < 12:
            sensor_name = (
                f"sensor.{inverter_sn}_load_avg_8_12_weekend"
                if is_weekend
                else f"sensor.{inverter_sn}_load_avg_8_12_weekday"
            )
        elif 12 <= hour < 16:
            sensor_name = (
                f"sensor.{inverter_sn}_load_avg_12_16_weekend"
                if is_weekend
                else f"sensor.{inverter_sn}_load_avg_12_16_weekday"
            )
        elif 16 <= hour < 22:
            sensor_name = (
                f"sensor.{inverter_sn}_load_avg_16_22_weekend"
                if is_weekend
                else f"sensor.{inverter_sn}_load_avg_16_22_weekday"
            )
        else:
            sensor_name = (
                f"sensor.{inverter_sn}_load_avg_22_6_weekend"
                if is_weekend
                else f"sensor.{inverter_sn}_load_avg_22_6_weekday"
            )

        load_value = self._get_state_float(
            sensor_name, 500.0
        )  # default 500W pokud senzor neexistuje
        return abs(load_value)  # zajistíme že hodnota je pozitivní

    def _calculate_percentile_price(
        self,
        times_to_simulate: List[Dict[str, Any]],
        percentile_conf: float,
        max_price_conf: float,
    ) -> float:
        """Výpočet percentilu cen."""
        prices = [
            entry["price"] for entry in times_to_simulate if entry["price"] is not None
        ]

        if not prices:
            return 0

        # Výpočet percentilu
        try:
            percentile_value = statistics.quantiles(prices, n=100)[
                int(percentile_conf) - 1
            ]
        except (IndexError, ValueError):
            percentile_value = statistics.median(prices)

        # Omezení maximální cenou
        if percentile_value > max_price_conf:
            percentile_value = max_price_conf

        return round(percentile_value, 2)

    def _add_peak_attribute(
        self, times_to_simulate: List[Dict[str, Any]], median_price: float
    ) -> List[Dict[str, Any]]:
        """Přidání atributu is_peak."""
        for entry in times_to_simulate:
            is_peak = False
            if entry["price"] is not None and entry["price"] > median_price:
                is_peak = True
            entry["is_peak"] = is_peak

        return times_to_simulate

    def _simulate_charging(
        self,
        times_to_simulate: List[Dict[str, Any]],
        current_home_battery_capacity: float,
        home_battery_capacity_max: float,
        min_home_battery_capacity: float,
        home_charge_rate: float,
        median_price: float,
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        """Simulace nabíjení baterie s optimalizací."""
        home_charging_hours: List[str] = []

        max_iterations = 100

        for _ in range(max_iterations):
            # Vytvoření forecastu
            forecast = self._create_forecast(
                times_to_simulate,
                current_home_battery_capacity,
                home_battery_capacity_max,
                home_charge_rate,
                home_charging_hours,
                median_price,
            )

            # Kontrola, zda je potřeba další nabíjení
            charging_needed = False
            deficient_time = None

            for forecast_entry in forecast:
                if (
                    forecast_entry["y"] < min_home_battery_capacity
                    and forecast_entry["price"] is not None
                ):
                    charging_needed = True
                    deficient_time = forecast_entry["x"]
                    break

            if not charging_needed:
                break

            # Najít nejlepší hodinu pro nabíjení
            selected_time = self._find_best_charging_hour(
                times_to_simulate, home_charging_hours, deficient_time
            )

            if selected_time and selected_time not in home_charging_hours:
                home_charging_hours.append(selected_time)
            else:
                break  # Nemůžeme najít další vhodnou hodinu

        # Finální forecast
        final_forecast = self._create_forecast(
            times_to_simulate,
            current_home_battery_capacity,
            home_battery_capacity_max,
            home_charge_rate,
            home_charging_hours,
            median_price,
        )

        return final_forecast, home_charging_hours

    def _create_forecast(
        self,
        times_to_simulate: List[Dict[str, Any]],
        current_capacity: float,
        max_capacity: float,
        charge_rate: float,
        charging_hours: List[str],
        median_price: float,
    ) -> List[Dict[str, Any]]:
        """Vytvoření forecastu kapacity baterie."""
        forecast = []
        projected_capacity = current_capacity

        for entry in times_to_simulate:
            time_str = entry["time"].isoformat()
            load = entry["load"]
            price = entry["price"]
            solar_power = entry["solar_power"]

            # Aktualizace kapacity
            projected_capacity += load + (solar_power / 1000)

            # Přidání nabíjecí kapacity pokud je hodina v nabíjecích hodinách
            if time_str in charging_hours:
                projected_capacity += charge_rate - load + (solar_power / 1000)

            # Kontrola limitů
            if projected_capacity > max_capacity:
                projected_capacity = max_capacity
            elif projected_capacity < 0:
                projected_capacity = 0

            forecast.append(
                {
                    "x": time_str,
                    "y": round(projected_capacity, 2),
                    "price": price,
                    "home_is_charging": time_str in charging_hours,
                    "is_peak": entry["is_peak"],
                    "estimated_consumption": load,
                    "percentile": median_price,
                    "solar_power": entry["solar_power"],
                    "load": entry["load"],
                }
            )

        return forecast

    def _find_best_charging_hour(
        self,
        times_to_simulate: List[Dict[str, Any]],
        current_charging_hours: List[str],
        deficient_time: Optional[str],
    ) -> Optional[str]:
        """Najít nejlepší hodinu pro nabíjení."""
        current_time = datetime.now().replace(minute=0, second=0, microsecond=0)
        current_time_str = current_time.isoformat()

        # Filtrování dostupných hodin (mimo špičku, s cenou)
        off_peak_hours = [
            entry
            for entry in times_to_simulate
            if not entry["is_peak"]
            and entry["price"] is not None
            and entry["time"].isoformat() not in current_charging_hours
        ]

        # Seřazení podle ceny
        off_peak_hours.sort(key=lambda x: x["price"])

        # Preferuj aktuální hodinu pokud je dostupná
        for hour_entry in off_peak_hours:
            if hour_entry["time"].isoformat() == current_time_str:
                return hour_entry["time"].isoformat()

        # Jinak vezmi nejlevnější dostupnou hodinu
        if off_peak_hours:
            return off_peak_hours[0]["time"].isoformat()

        # Pokud není žádná hodina mimo špičku, vezmi nejlevnější obecně
        all_hours = [
            entry
            for entry in times_to_simulate
            if entry["price"] is not None
            and entry["time"].isoformat() not in current_charging_hours
        ]

        if all_hours:
            all_hours.sort(key=lambda x: x["price"])
            return all_hours[0]["time"].isoformat()

        return None
