"""Statistics sensor implementation for OIG Cloud integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union, List, Tuple
from statistics import median
import json

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class OigCloudStatisticsSensor(SensorEntity, RestoreEntity):
    """Statistics sensor for OIG Cloud data."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        device_info: Dict[str, Any],
    ) -> None:
        """Initialize the statistics sensor."""
        super().__init__()
        self._coordinator = coordinator
        self._sensor_type = sensor_type
        self._device_info = device_info

        # Získáme konfiguraci senzoru
        from .sensor_types import SENSOR_TYPES

        sensor_config = SENSOR_TYPES.get(sensor_type, {})
        self._sensor_config = sensor_config  # OPRAVA: Uložení reference

        # OPRAVA: Použití sensor_type pro entity_id místo friendly_name
        self._attr_name = sensor_config.get("name", sensor_type)
        self._attr_unique_id = f"oig_statistics_{sensor_type}"
        # OPRAVA: entity_id se odvozuje od sensor_type, ne od friendly_name
        self.entity_id = f"sensor.{sensor_type}"

        # Získání data_key z coordinator config
        self._data_key = "unknown"
        if hasattr(coordinator, "config_entry") and coordinator.config_entry:
            if (
                hasattr(coordinator.config_entry, "data")
                and coordinator.config_entry.data
            ):
                self._data_key = coordinator.config_entry.data.get(
                    "inverter_sn", "unknown"
                )

        # Fallback - zkusit získat z coordinator.data
        if self._data_key == "unknown" and coordinator.data:
            first_device_key = list(coordinator.data.keys())[0]
            self._data_key = first_device_key

        # Nastavení základních atributů
        sensor_name = sensor_config.get("name", sensor_type)
        # Lokalizace názvu podle konfigurace
        if hasattr(coordinator, "config_entry") and coordinator.config_entry.options:
            use_czech = coordinator.config_entry.options.get("use_czech_names", False)
            if use_czech and "name_cs" in sensor_config:
                sensor_name = sensor_config["name_cs"]

        self._attr_name = sensor_name
        self._attr_unique_id = f"{self._data_key}_{sensor_type}"
        self._attr_icon = sensor_config.get("icon")
        self._attr_native_unit_of_measurement = sensor_config.get("unit")

        # Správné nastavení device_class - buď enum nebo None
        device_class = sensor_config.get("device_class")
        if isinstance(device_class, str):
            try:
                self._attr_device_class = getattr(
                    SensorDeviceClass, device_class.upper()
                )
            except AttributeError:
                self._attr_device_class = device_class
        else:
            self._attr_device_class = device_class

        # Správné nastavení state_class - buď enum nebo None
        state_class = sensor_config.get("state_class")
        if isinstance(state_class, str):
            try:
                self._attr_state_class = getattr(SensorStateClass, state_class.upper())
            except AttributeError:
                self._attr_state_class = state_class
        else:
            self._attr_state_class = state_class

        # Správné nastavení entity_category - už je to enum z config
        self._attr_entity_category = sensor_config.get("entity_category")

        # Inicializace datových struktur pro hodinové senzory
        self._hourly_data: List[Dict[str, Any]] = []
        self._last_hour_reset: Optional[datetime] = None
        self._last_source_value: Optional[float] = None
        self._hourly_accumulated_energy: float = 0.0
        self._current_hourly_value: Optional[float] = None

        # Inicializace source_entity_id pro hodinové senzory
        self._source_entity_id: Optional[str] = None
        if self._sensor_type.startswith("hourly_"):
            source_sensor = sensor_config.get("source_sensor")
            if source_sensor:
                self._source_entity_id = f"sensor.oig_{self._data_key}_{source_sensor}"

        # Statistická data pro základní mediánový senzor
        self._sampling_data: List[Tuple[datetime, float]] = []
        self._max_sampling_size: int = 1000
        self._sampling_minutes: int = 10

        # Data pro intervalové statistiky
        self._interval_data: Dict[str, List[float]] = {}
        self._last_interval_check: Optional[datetime] = None
        self._current_interval_data: List[float] = []

        # Storage pro persistentní data
        self._storage_key = f"oig_stats_{self._data_key}_{sensor_type}"

        # Načtení konfigurace senzoru
        if hasattr(self, "_sensor_config"):
            config = self._sensor_config
            self._sampling_minutes = config.get("sampling_minutes", 10)
            self._max_sampling_size = config.get("sampling_size", 1000)
            self._time_range = config.get("time_range")
            self._day_type = config.get("day_type")
            self._statistic = config.get("statistic", "median")
            self._max_age_days = config.get("max_age_days", 30)

        _LOGGER.debug(
            f"[{self.entity_id}] Initialized statistics sensor: {sensor_type}"
        )

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        """Return device info - use same as other sensors."""
        return self._device_info

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        # Načtení persistentních dat
        await self._load_statistics_data()

        # Nastavení pravidelných aktualizací
        if self._sensor_type == "battery_load_median":
            # Základní mediánový senzor - aktualizace každou minutu
            async_track_time_interval(
                self.hass, self._update_sampling_data, timedelta(minutes=1)
            )
        elif self._sensor_type.startswith("hourly_"):
            # Hodinové senzory - kontrola konce hodiny každých 5 minut
            async_track_time_interval(
                self.hass, self._check_hourly_end, timedelta(minutes=5)
            )
            _LOGGER.debug(
                f"[{self.entity_id}] Set up hourly tracking for sensor: {self._sensor_type}"
            )
        elif hasattr(self, "_time_range") and self._time_range is not None:
            # Intervalové senzory - kontrola konce intervalů každých 15 minut
            async_track_time_interval(
                self.hass, self._check_interval_end, timedelta(minutes=15)
            )
            _LOGGER.debug(
                f"[{self.entity_id}] Set up interval tracking for time range: {self._time_range}"
            )

    async def _load_statistics_data(self) -> None:
        """Načte statistická data z persistentního úložiště."""
        try:
            store = Store(self.hass, version=1, key=self._storage_key)
            data = await store.async_load()

            if data:
                # Načtení základních sampling dat
                if "sampling_data" in data:
                    sampling_list = data["sampling_data"]
                    self._sampling_data = []
                    for item in sampling_list[-self._max_sampling_size :]:
                        try:
                            # Převod na naive datetime pro konzistenci
                            dt = datetime.fromisoformat(item[0])
                            if dt.tzinfo is not None:
                                dt = dt.replace(tzinfo=None)  # Odstranění timezone info
                            self._sampling_data.append((dt, item[1]))
                        except (ValueError, TypeError) as e:
                            _LOGGER.warning(
                                f"[{self.entity_id}] Skipping invalid sample: {item[0]} - {e}"
                            )
                            continue

                # Načtení intervalových dat
                if "interval_data" in data:
                    self._interval_data = data["interval_data"]

                # Načtení hodinových dat
                if "hourly_data" in data:
                    self._hourly_data = data["hourly_data"]

                # Načtení aktuální hodinové hodnoty
                if "current_hourly_value" in data:
                    self._current_hourly_value = data["current_hourly_value"]

                # Načtení posledních hodnot pro hodinové senzory
                if "last_source_value" in data:
                    self._last_source_value = data["last_source_value"]

                if "last_hour_reset" in data:
                    try:
                        self._last_hour_reset = datetime.fromisoformat(
                            data["last_hour_reset"]
                        )
                        if self._last_hour_reset.tzinfo is not None:
                            self._last_hour_reset = self._last_hour_reset.replace(
                                tzinfo=None
                            )
                    except (ValueError, TypeError):
                        self._last_hour_reset = None

                # Vyčištění starých dat
                await self._cleanup_old_data()

                _LOGGER.debug(
                    f"[{self.entity_id}] Loaded data - sampling: {len(self._sampling_data)}, "
                    f"hourly: {len(self._hourly_data)}, current_hourly: {self._current_hourly_value}"
                )

                # Okamžitý výpočet stavu po načtení dat
                if self._sampling_data and self._sensor_type == "battery_load_median":
                    initial_state = self._calculate_statistics_value()
                    if initial_state is not None:
                        _LOGGER.info(
                            f"[{self.entity_id}] Restored median state: {initial_state}W"
                        )
                        self.async_write_ha_state()

                elif (
                    self._sensor_type.startswith("hourly_")
                    and self._current_hourly_value is not None
                ):
                    _LOGGER.info(
                        f"[{self.entity_id}] Restored hourly state: {self._current_hourly_value} kWh"
                    )
                    self.async_write_ha_state()

        except Exception as e:
            _LOGGER.warning(f"[{self.entity_id}] Failed to load statistics data: {e}")

    async def _save_statistics_data(self) -> None:
        """Uloží statistická data do persistentního úložiště."""
        try:
            store = Store(self.hass, version=1, key=self._storage_key)

            # Příprava dat k uložení - zajistit naive datetime
            sampling_data_serializable = []
            for dt, value in self._sampling_data:
                # Ujistit se, že ukládáme naive datetime
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                sampling_data_serializable.append((dt.isoformat(), value))

            save_data = {
                "sampling_data": sampling_data_serializable,
                "interval_data": self._interval_data,
                "hourly_data": self._hourly_data,
                "current_hourly_value": self._current_hourly_value,
                "last_source_value": self._last_source_value,
                "last_hour_reset": (
                    self._last_hour_reset.isoformat() if self._last_hour_reset else None
                ),
                "last_update": datetime.now().isoformat(),
            }

            await store.async_save(save_data)
            _LOGGER.debug(f"[{self.entity_id}] Saved statistics data")

        except Exception as e:
            _LOGGER.warning(f"[{self.entity_id}] Failed to save statistics data: {e}")

    async def _cleanup_old_data(self) -> None:
        """Vyčistí stará data podle konfigurace."""
        now = datetime.now()

        # Vyčištění sampling dat - ponechat jen posledních N minut
        if self._sampling_data:
            cutoff_time = now - timedelta(
                minutes=self._sampling_minutes * 2
            )  # 2x buffer

            # Bezpečné porovnání - zajistit naive datetime pro všechny objekty
            cleaned_data = []
            for dt, value in self._sampling_data:
                # Převod na naive datetime pokud je timezone-aware
                dt_naive = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
                if dt_naive > cutoff_time:
                    cleaned_data.append((dt_naive, value))

            self._sampling_data = cleaned_data

        # Vyčištění intervalových dat - ponechat jen posledních N dní
        if hasattr(self, "_max_age_days") and self._interval_data:
            cutoff_date = (now - timedelta(days=self._max_age_days)).strftime(
                "%Y-%m-%d"
            )
            keys_to_remove = [
                key for key in self._interval_data.keys() if key < cutoff_date
            ]
            for key in keys_to_remove:
                del self._interval_data[key]

        # Vyčištění hodinových dat - ponechat jen posledních 48 hodin
        if self._hourly_data:
            cutoff_time = now - timedelta(hours=48)
            self._hourly_data = [
                record
                for record in self._hourly_data
                if datetime.fromisoformat(record["datetime"]) > cutoff_time
            ]

    async def _update_sampling_data(self, now: datetime) -> None:
        """Aktualizuje sampling data pro základní mediánový senzor."""
        if self._sensor_type != "battery_load_median":
            return

        try:
            # Získání aktuální hodnoty z source senzoru
            source_value = self._get_actual_load_value()
            if source_value is None:
                return

            # Použití aktuálního lokálního času místo parametru
            now_local = datetime.now()

            # Přidání nového vzorku
            self._sampling_data.append((now_local, source_value))

            # Omezení velikosti dat
            if len(self._sampling_data) > self._max_sampling_size:
                self._sampling_data = self._sampling_data[-self._max_sampling_size :]

            # Vyčištění starých dat - zajistit naive datetime pro porovnání
            cutoff_time = now_local - timedelta(minutes=self._sampling_minutes)
            cleaned_data = []
            for dt, value in self._sampling_data:
                # Převod na naive datetime pokud je timezone-aware
                dt_naive = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
                if dt_naive > cutoff_time:
                    cleaned_data.append((dt_naive, value))

            self._sampling_data = cleaned_data

            # Aktualizace stavu senzoru
            self.async_write_ha_state()

            # Uložení dat každých 10 vzorků
            if len(self._sampling_data) % 10 == 0:
                await self._save_statistics_data()

            _LOGGER.debug(
                f"[{self.entity_id}] Updated sampling data: {len(self._sampling_data)} points, "
                f"current value: {source_value}W, time: {now_local.strftime('%H:%M:%S')}"
            )

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error updating sampling data: {e}")

    async def _check_hourly_end(self, now: datetime) -> None:
        """Kontroluje konec hodiny a aktualizuje hodinové senzory."""
        if not self._sensor_type.startswith("hourly_"):
            return

        try:
            current_minute = now.minute

            # Aktualizace pouze v prvních 5 minutách nové hodiny (např. 09:00-09:05)
            if current_minute <= 5:
                current_hour = now.replace(minute=0, second=0, microsecond=0)

                # Kontrola zda jsme už v této hodině neaktualizovali
                if self._last_hour_reset != current_hour:
                    # Výpočet za uplynulou hodinu
                    hourly_value = await self._calculate_hourly_energy()

                    if hourly_value is not None:
                        # Uložení hodnoty pro současný stav
                        self._current_hourly_value = hourly_value

                        # Přidání do historických dat
                        previous_hour = current_hour - timedelta(hours=1)
                        hourly_record = {
                            "datetime": previous_hour.isoformat(),
                            "value": hourly_value,
                            "timestamp": previous_hour.timestamp(),
                        }

                        self._hourly_data.append(hourly_record)

                        # Omezení na posledních 48 hodin (včera + dnes)
                        cutoff_time = now - timedelta(hours=48)
                        self._hourly_data = [
                            record
                            for record in self._hourly_data
                            if datetime.fromisoformat(record["datetime"]) > cutoff_time
                        ]

                        # Uložení hodnoty do historie
                        self._last_hour_reset = current_hour

                        # Uložení dat
                        await self._save_statistics_data()

                        # Aktualizace stavu senzoru
                        self.async_write_ha_state()

                        _LOGGER.info(
                            f"[{self.entity_id}] Hourly update: {hourly_value:.3f} kWh for hour ending at {previous_hour.strftime('%H:%M')}"
                        )

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error in hourly check: {e}")

    async def _check_interval_end(self, now: datetime) -> None:
        """Kontroluje konec intervalů a ukládá statistiky."""
        if not hasattr(self, "_time_range") or not self._time_range:
            return

        try:
            start_hour, end_hour = self._time_range
            current_hour = now.hour

            # Kontrola konce intervalu
            is_interval_end = False
            if end_hour > start_hour:
                # Normální interval (např. 6-8)
                is_interval_end = current_hour == end_hour and now.minute < 15
            else:
                # Interval přes půlnoc (např. 22-6)
                is_interval_end = current_hour == end_hour and now.minute < 15

            # Kontrola typu dne
            if is_interval_end:
                is_correct_day_type = self._is_correct_day_type(now)
                if not is_correct_day_type:
                    return

                # Získání dat z základního mediánového senzoru
                median_values = await self._get_interval_median_data(
                    start_hour, end_hour, now
                )
                if median_values:
                    # Výpočet mediánu z intervalu
                    interval_median = median(median_values)

                    # Uložení do historických dat
                    date_key = now.strftime("%Y-%m-%d")
                    if date_key not in self._interval_data:
                        self._interval_data[date_key] = []

                    self._interval_data[date_key].append(interval_median)

                    # Omezení na posledních 30 hodnot
                    if len(self._interval_data[date_key]) > 30:
                        self._interval_data[date_key] = self._interval_data[date_key][
                            -30:
                        ]

                    # Uložení dat
                    await self._save_statistics_data()

                    # Aktualizace stavu senzoru
                    self.async_write_ha_state()

                    _LOGGER.info(
                        f"[{self.entity_id}] Saved interval median: {interval_median:.1f}W "
                        f"for {start_hour}-{end_hour}h on {date_key}"
                    )

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error checking interval end: {e}")

    def _is_correct_day_type(self, dt: datetime) -> bool:
        """Kontroluje zda je správný typ dne (weekday/weekend)."""
        is_weekend = dt.weekday() >= 5  # 5=Saturday, 6=Sunday

        if hasattr(self, "_day_type"):
            if self._day_type == "weekend":
                return is_weekend
            elif self._day_type == "weekday":
                return not is_weekend

        return True

    async def _get_interval_median_data(
        self, start_hour: int, end_hour: int, end_time: datetime
    ) -> List[float]:
        """Získá mediánová data z základního senzoru pro daný interval."""
        try:
            # Najdeme základní mediánový senzor
            median_entity_id = f"sensor.oig_{self._data_key}_battery_load_median"

            # Získáme jeho historická data (implementace závisí na dostupnosti historie)
            # Pro teď použijeme aktuální hodnotu jako aproximaci
            median_sensor = self.hass.states.get(median_entity_id)
            if median_sensor and median_sensor.state not in (
                "unavailable",
                "unknown",
                None,
            ):
                try:
                    current_median = float(median_sensor.state)
                    return [current_median]  # Zjednodušená implementace
                except (ValueError, TypeError):
                    pass

            # Fallback - přímé vzorkování ze source senzoru
            source_value = self._get_actual_load_value()
            if source_value is not None:
                return [source_value]

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error getting interval data: {e}")

        return []

    def _get_actual_load_value(self) -> Optional[float]:
        """Získá aktuální hodnotu odběru ze source senzoru."""
        try:
            # Source sensor pro odběr
            source_entity_id = f"sensor.oig_{self._data_key}_actual_aco_p"
            source_entity = self.hass.states.get(source_entity_id)

            if source_entity and source_entity.state not in (
                "unavailable",
                "unknown",
                None,
            ):
                return float(source_entity.state)

        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"[{self.entity_id}] Error getting load value: {e}")

        return None

    async def _calculate_hourly_energy(self) -> Optional[float]:
        """Vypočítá energii za uplynulou hodinu."""
        if not self._sensor_config or not self._source_entity_id:
            return None

        try:
            source_entity = self.hass.states.get(self._source_entity_id)
            if not source_entity or source_entity.state in (
                "unavailable",
                "unknown",
                None,
            ):
                return None

            current_value = float(source_entity.state)
            hourly_data_type = self._sensor_config.get(
                "hourly_data_type", "energy_diff"
            )

            if hourly_data_type == "energy_diff":
                # Rozdíl energie - počítáme rozdíl od začátku hodiny
                if self._last_source_value is None:
                    self._last_source_value = current_value
                    return None

                if current_value >= self._last_source_value:
                    # Normální růst
                    energy_diff = current_value - self._last_source_value
                else:
                    # Reset počítadla - použijeme aktuální hodnotu
                    energy_diff = current_value

                self._last_source_value = current_value

                # Kontrola jednotek podle source_sensor
                source_sensor = self._sensor_config.get("source_sensor", "")
                kwh_sensors = [
                    "computed_batt_charge_energy_today",
                    "computed_batt_discharge_energy_today",
                ]

                if source_sensor in kwh_sensors:
                    # Už je v kWh
                    return round(energy_diff, 3)
                else:
                    # Je v Wh, převést na kWh
                    return round(energy_diff / 1000, 3)

            elif hourly_data_type == "power_integral":
                # Průměrný výkon za hodinu * 1 hodina
                # Pro zjednodušení použijeme aktuální výkon jako reprezentativní
                # Výkon v W * 1h = Wh, pak / 1000 = kWh
                return round(current_value / 1000, 3)

            return None

        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"[{self.entity_id}] Error calculating hourly energy: {e}")
            return None

    def _calculate_hourly_value(self) -> Optional[float]:
        """Calculate hourly value - vrací uloženou hodnotu z posledního výpočtu."""
        # Pro hodinové senzory vracíme pouze uloženou hodnotu
        # Výpočet se provádí jen na konci hodiny v _calculate_hourly_energy
        return getattr(self, "_current_hourly_value", None)

    def _calculate_statistics_value(self) -> Optional[float]:
        """Calculate statistics value for non-hourly sensors."""
        try:
            if self._sensor_type == "battery_load_median":
                # Základní mediánový senzor - medián za posledních N minut
                if len(self._sampling_data) < 1:
                    return None

                # Filtrování dat za posledních N minut - použití lokálního času
                now = datetime.now()
                cutoff_time = now - timedelta(minutes=self._sampling_minutes)
                recent_data = [
                    value for dt, value in self._sampling_data if dt > cutoff_time
                ]

                _LOGGER.debug(
                    f"[{self.entity_id}] Time check: now={now.strftime('%H:%M:%S')}, "
                    f"cutoff={cutoff_time.strftime('%H:%M:%S')}, "
                    f"total_samples={len(self._sampling_data)}, recent_samples={len(recent_data)}"
                )

                if recent_data:
                    result = median(recent_data)
                    _LOGGER.debug(
                        f"[{self.entity_id}] Calculated median: {result:.1f}W "
                        f"from {len(recent_data)} recent samples"
                    )
                    return round(result, 1)
                else:
                    # Pokud nemáme žádná data v časovém okně, použijeme všechna dostupná
                    if self._sampling_data:
                        all_values = [value for _, value in self._sampling_data]
                        result = median(all_values)
                        _LOGGER.debug(
                            f"[{self.entity_id}] No recent data, using all {len(all_values)} samples: {result:.1f}W"
                        )
                        return round(result, 1)

            elif hasattr(self, "_time_range") and self._time_range:
                # Intervalové statistiky - medián z historických dat
                if not self._interval_data:
                    return None

                # Shromáždění všech hodnot ze všech dní
                all_values = []
                for date_values in self._interval_data.values():
                    all_values.extend(date_values)

                if all_values:
                    result = median(all_values)
                    _LOGGER.debug(
                        f"[{self.entity_id}] Calculated interval median: {result:.1f}W "
                        f"from {len(all_values)} historical values"
                    )
                    return round(result, 1)

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error calculating statistics: {e}")

        return None

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Return the state of the sensor."""
        # Odstraníme závislost na coordinator.data pro statistické senzory
        if self._sensor_type.startswith("hourly_") and self._coordinator.data is None:
            # Pro hodinové senzory zkusíme výpočet i bez coordinator dat
            return self._calculate_hourly_value()

        # Hodinové senzory
        if self._sensor_type.startswith("hourly_"):
            return self._calculate_hourly_value()

        # Ostatní statistické senzory (včetně mediánových)
        return self._calculate_statistics_value()

    @property
    def available(self) -> bool:
        """Return True if sensor is available."""
        # Senzor je dostupný pokud má data nebo koordinátor funguje
        if self._sensor_type == "battery_load_median":
            return len(self._sampling_data) > 0 or self._coordinator.data is not None
        elif self._sensor_type.startswith("hourly_"):
            # Hodinové senzory jsou dostupné pokud existuje source entity
            if self._source_entity_id:
                source_entity = self.hass.states.get(self._source_entity_id)
                return source_entity is not None and source_entity.state not in (
                    "unavailable",
                    "unknown",
                )
            return False
        return self._coordinator.data is not None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        attributes = {}

        try:
            if self._sensor_type == "battery_load_median":
                # Atributy pro základní mediánový senzor
                attributes.update(
                    {
                        "sampling_points": len(self._sampling_data),
                        "sampling_minutes": self._sampling_minutes,
                        "max_sampling_size": self._max_sampling_size,
                    }
                )

                if self._sampling_data:
                    last_update = max(dt for dt, _ in self._sampling_data)
                    attributes["last_sample"] = last_update.isoformat()

            elif self._sensor_type.startswith("hourly_"):
                # Atributy pro hodinové senzory
                attributes.update(
                    {
                        "hourly_data_points": len(self._hourly_data),
                        "source_sensor": self._sensor_config.get(
                            "source_sensor", "unknown"
                        ),
                        "hourly_data_type": self._sensor_config.get(
                            "hourly_data_type", "unknown"
                        ),
                    }
                )

                # Přidání historických hodinových dat
                if self._hourly_data:
                    # Rozdělení na včerejší a dnešní data
                    now = datetime.now()
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    yesterday_start = today_start - timedelta(days=1)

                    today_data = []
                    yesterday_data = []

                    for record in self._hourly_data:
                        record_time = datetime.fromisoformat(record["datetime"])
                        if record_time >= today_start:
                            today_data.append(record)
                        elif record_time >= yesterday_start:
                            yesterday_data.append(record)

                    if today_data:
                        attributes["today_hourly"] = today_data
                    if yesterday_data:
                        attributes["yesterday_hourly"] = yesterday_data

                    # Celkem za dnes a včera
                    today_total = sum(record["value"] for record in today_data)
                    yesterday_total = sum(record["value"] for record in yesterday_data)

                    attributes["today_total"] = round(today_total, 3)
                    attributes["yesterday_total"] = round(yesterday_total, 3)

            elif hasattr(self, "_time_range") and self._time_range:
                # Atributy pro intervalové senzory
                start_hour, end_hour = self._time_range
                attributes.update(
                    {
                        "time_range": f"{start_hour:02d}:00-{end_hour:02d}:00",
                        "day_type": getattr(self, "_day_type", "unknown"),
                        "statistic": getattr(self, "_statistic", "median"),
                        "max_age_days": getattr(self, "_max_age_days", 30),
                    }
                )

                # Statistiky o datech
                total_values = sum(
                    len(values) for values in self._interval_data.values()
                )
                attributes.update(
                    {
                        "total_days": len(self._interval_data),
                        "total_values": total_values,
                    }
                )

                if self._interval_data:
                    latest_date = max(self._interval_data.keys())
                    attributes["latest_data"] = latest_date

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error creating attributes: {e}")
            attributes["error"] = str(e)

        return attributes
