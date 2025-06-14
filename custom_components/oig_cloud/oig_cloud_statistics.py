"""Statistické senzory a predikce pro OIG Cloud integraci."""

import logging
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from collections import deque

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.dt import now as dt_now, utcnow as dt_utcnow
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)


class OigCloudStatisticsSensor(OigCloudSensor, RestoreEntity):
    """Senzor pro statistiky a predikce spotřeby."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__(coordinator, sensor_type)

        # Úložiště pro naměřené hodnoty
        self._load_history: Dict[str, deque] = {}
        self._last_update: Optional[datetime] = None

        # Konfigurace podle typu senzoru
        self._config = self._get_sensor_config(sensor_type)

        # Inicializace historie pro každý časový úsek
        self._init_history_storage()

    def _get_sensor_config(self, sensor_type: str) -> Dict[str, Any]:
        """Získání konfigurace pro daný typ senzoru."""
        from .sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        return SENSOR_TYPES_STATISTICS.get(sensor_type, {})

    def _init_history_storage(self) -> None:
        """Inicializace úložiště historie dat."""
        max_size = self._config.get("sampling_size", 1000)

        if "time_range" in self._config:
            # Pro časové úseky - oddělené úložiště pro weekday/weekend
            self._load_history["weekday"] = deque(maxlen=max_size)
            self._load_history["weekend"] = deque(maxlen=max_size)
        else:
            # Pro obecné statistiky
            self._load_history["general"] = deque(maxlen=max_size)

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - obnovit stav a nastavit tracking."""
        await super().async_added_to_hass()

        # Obnovit historii ze stavu PŘED nastavením trackingu
        await self._restore_history()

        # Počkat na první data z coordinatoru
        if not self.coordinator.data:
            await self.coordinator.async_request_refresh()

        # Nastavit pravidelné ukládání dat
        async_track_time_interval(self.hass, self._collect_data, timedelta(minutes=1))

    async def _restore_history(self) -> None:
        """Obnovení historie z uloženého stavu."""
        old_state = await self.async_get_last_state()
        if old_state and old_state.attributes:
            try:
                # Obnovíme všechny historické klíče
                for key in ["general", "weekday", "weekend"]:
                    history_key = f"history_{key}"
                    if history_key in old_state.attributes:
                        restored_data = old_state.attributes[history_key]
                        if isinstance(restored_data, list) and restored_data:
                            # Ujistíme se, že máme správnou velikost deque
                            max_size = self._config.get("sampling_size", 1000)
                            if key not in self._load_history:
                                self._load_history[key] = deque(maxlen=max_size)

                            # Obnovíme všechna data
                            self._load_history[key].extend(restored_data)

                _LOGGER.info(
                    f"[{self.entity_id}] Restored {sum(len(h) for h in self._load_history.values())} historical values"
                )

                # Obnovíme i last_update
                if (
                    "last_update" in old_state.attributes
                    and old_state.attributes["last_update"]
                ):
                    try:
                        self._last_update = datetime.fromisoformat(
                            old_state.attributes["last_update"]
                        )
                    except ValueError:
                        pass

                # Ihned aktualizuj stav po obnovení dat
                self.async_write_ha_state()

            except Exception as e:
                _LOGGER.error(
                    f"[{self.entity_id}] Error restoring history: {e}", exc_info=True
                )

    async def _collect_data(self, *_: Any) -> None:
        """Pravidelné sbírání dat o spotřebě."""
        try:
            # Získání aktuální spotřeby
            current_load = self._get_current_load()
            if current_load is None:
                return

            now = dt_now()

            # Určení typu dne a časového úseku
            day_type = self._get_day_type(now)

            # Uložení dat podle konfigurace senzoru
            if "time_range" in self._config:
                time_range = self._config["time_range"]
                if self._is_in_time_range(now, time_range):
                    target_day_type = self._config.get("day_type", "any")
                    if target_day_type == "any" or target_day_type == day_type:
                        self._load_history[day_type].append(
                            {
                                "timestamp": now.isoformat(),
                                "value": current_load,
                                "hour": now.hour,
                            }
                        )
            else:
                # Pro obecné statistiky
                self._load_history["general"].append(
                    {
                        "timestamp": now.isoformat(),
                        "value": current_load,
                        "hour": now.hour,
                    }
                )

            self._last_update = now

        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error collecting data: {e}", exc_info=True
            )

    def _get_current_load(self) -> Optional[float]:
        """Získání aktuální spotřeby z coordinatoru."""
        if self.coordinator.data is None:
            return None

        try:
            data = self.coordinator.data
            pv_data = list(data.values())[0]
            # Spotřeba domácnosti
            load_power = float(pv_data["actual"]["aco_p"])
            return load_power
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.debug(f"[{self.entity_id}] Error getting current load: {e}")
            return None

    def _get_day_type(self, dt: datetime) -> str:
        """Určení typu dne (weekday/weekend)."""
        return "weekend" if dt.weekday() >= 5 else "weekday"

    def _is_in_time_range(self, dt: datetime, time_range: Tuple[int, int]) -> bool:
        """Kontrola, zda je čas v daném rozsahu."""
        start_hour, end_hour = time_range
        current_hour = dt.hour

        if start_hour < end_hour:
            # Normální rozsah (např. 8-12)
            return start_hour <= current_hour < end_hour
        else:
            # Rozsah přes půlnoc (např. 22-6)
            return current_hour >= start_hour or current_hour < end_hour

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Hlavní stav senzoru."""
        if self._sensor_type == "battery_load_median":
            return self._calculate_current_median()
        elif self._sensor_type.startswith("load_avg_"):
            return self._calculate_time_range_average()
        elif self._sensor_type.startswith("battery_prediction_"):
            return self._calculate_prediction()

        return None

    def _calculate_current_median(self) -> Optional[float]:
        """Výpočet mediánu aktuální spotřeby za posledních X minut."""
        sampling_minutes = self._config.get("sampling_minutes", 10)
        cutoff_time = dt_utcnow() - timedelta(minutes=sampling_minutes)

        recent_values = []
        for entry in self._load_history.get("general", []):
            try:
                entry_time = datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                )
                if entry_time >= cutoff_time:
                    recent_values.append(entry["value"])
            except (ValueError, KeyError):
                continue

        if len(recent_values) >= 3:  # Minimálně 3 hodnoty pro smysluplný medián
            return round(statistics.median(recent_values), 1)

        return None

    def _calculate_time_range_average(self) -> Optional[float]:
        """Výpočet průměru pro specifický časový úsek a typ dne."""
        day_type = self._config.get("day_type", "weekday")
        statistic_type = self._config.get("statistic", "median")
        max_age_days = self._config.get("max_age_days", 30)

        cutoff_time = dt_utcnow() - timedelta(days=max_age_days)

        values = []
        for entry in self._load_history.get(day_type, []):
            try:
                entry_time = datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                )
                if entry_time >= cutoff_time:
                    values.append(entry["value"])
            except (ValueError, KeyError):
                continue

        if len(values) >= 5:  # Minimálně 5 hodnot
            if statistic_type == "median":
                return round(statistics.median(values), 1)
            elif statistic_type == "mean":
                return round(statistics.mean(values), 1)

        return None

    def _calculate_prediction(self) -> Optional[Union[float, str]]:
        """Výpočet predikčních hodnot."""
        if self._sensor_type == "battery_prediction_discharge_time":
            return self._predict_discharge_time()
        elif self._sensor_type == "battery_prediction_needed_capacity":
            return self._predict_needed_capacity()
        elif self._sensor_type == "battery_prediction_morning_soc":
            return self._predict_morning_soc()

        return None

    def _predict_discharge_time(self) -> Optional[float]:
        """Predikce času vybití baterie na základě aktuální spotřeby."""
        try:
            # Získání aktuálního stavu baterie
            if self.coordinator.data is None:
                return None

            data = self.coordinator.data
            pv_data = list(data.values())[0]

            bat_capacity_wh = float(pv_data["box_prms"]["p_bat"])
            bat_soc = float(pv_data["actual"]["bat_c"]) / 100.0
            current_load = float(pv_data["actual"]["aco_p"])

            # Využitelná kapacita (80% z celkové)
            usable_capacity = bat_capacity_wh * 0.8
            current_energy = usable_capacity * bat_soc

            if current_load > 0:
                hours_remaining = current_energy / current_load
                return round(hours_remaining, 1)

        except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            _LOGGER.debug(f"Error predicting discharge time: {e}")

        return None

    def _predict_needed_capacity(self) -> Optional[float]:
        """Predikce potřebné kapacity baterie pro přenesení přes noc."""
        try:
            # Získání průměrné noční spotřeby
            night_consumption = self._get_night_average_consumption()
            if night_consumption is None:
                return None

            # Předpokládáme 8 hodin noční spotřeby
            needed_wh = night_consumption * 8
            needed_kwh = needed_wh / 1000

            return round(needed_kwh, 2)

        except Exception as e:
            _LOGGER.debug(f"Error predicting needed capacity: {e}")

        return None

    def _predict_morning_soc(self) -> Optional[float]:
        """Predikce stavu baterie ráno na základě aktuálního stavu a noční spotřeby."""
        try:
            if self.coordinator.data is None:
                return None

            data = self.coordinator.data
            pv_data = list(data.values())[0]

            bat_capacity_wh = float(pv_data["box_prms"]["p_bat"])
            current_soc = float(pv_data["actual"]["bat_c"])

            # Získání průměrné noční spotřeby
            night_consumption = self._get_night_average_consumption()
            if night_consumption is None:
                return None

            # Výpočet hodin do rána (6:00)
            now = dt_now()
            morning = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now.hour >= 6:
                morning += timedelta(days=1)

            hours_until_morning = (morning - now).total_seconds() / 3600

            # Predikovaná spotřeba do rána
            predicted_consumption_wh = night_consumption * hours_until_morning

            # Aktuální energie v baterii
            current_energy_wh = (bat_capacity_wh * current_soc) / 100

            # Predikovaná energie ráno
            morning_energy_wh = max(0, current_energy_wh - predicted_consumption_wh)
            morning_soc = (morning_energy_wh / bat_capacity_wh) * 100

            return round(morning_soc, 1)

        except Exception as e:
            _LOGGER.debug(f"Error predicting morning SoC: {e}")

        return None

    def _get_night_average_consumption(self) -> Optional[float]:
        """Získání průměrné noční spotřeby (22-6h)."""
        now = dt_now()
        day_type = self._get_day_type(now)

        # Použijeme data z noční spotřeby
        night_values = []
        max_age = dt_utcnow() - timedelta(days=30)

        for entry in self._load_history.get(day_type, []):
            try:
                entry_time = datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                )
                if entry_time >= max_age:
                    hour = entry["hour"]
                    if hour >= 22 or hour < 6:  # Noční hodiny
                        night_values.append(entry["value"])
            except (ValueError, KeyError):
                continue

        if len(night_values) >= 5:
            return statistics.median(night_values)

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy senzoru."""
        attrs = {}

        # Uložení KOMPLETNÍ historie pro restore (ne jen 50 hodnot)
        for key, history in self._load_history.items():
            # Uložíme všechna data, ale omezeně pro velikost stavu
            attrs[f"history_{key}"] = list(history)[
                -500:
            ]  # Posledních 500 hodnot místo 50

        # Statistiky
        total_samples = sum(len(h) for h in self._load_history.values())
        attrs["total_samples"] = total_samples
        attrs["last_update"] = (
            self._last_update.isoformat() if self._last_update else None
        )
        attrs["config"] = self._config

        # Přidáme verzi pro kompatibilitu
        attrs["data_version"] = "1.0"

        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o statistickém zařízení - bezpečnější verze."""
        if self.coordinator.data and self.coordinator.data:
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
        """Jedinečné ID pro statistický senzor - bezpečnější verze."""
        if self.coordinator.data and self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return f"{box_id}_statistics_{self._sensor_type}"
        # Fallback pokud data nejsou dostupná
        return f"statistics_{self._sensor_type}"

    async def async_update(self) -> None:
        """Update senzoru."""
        await self.coordinator.async_request_refresh()
