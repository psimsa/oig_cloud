"""Profilovací engine - učení z historických dat."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util

from .const import MIN_CONFIDENCE, PROFILE_CATEGORIES, SEASON_MAP
from .models import BoilerProfile

_LOGGER = logging.getLogger(__name__)


def _get_profile_category(dt: datetime) -> str:
    """Určí kategorii profilu podle data."""
    is_weekend = dt.weekday() >= 5
    season = SEASON_MAP.get(dt.month, "spring")

    day_type = "weekend" if is_weekend else "workday"
    return f"{day_type}_{season}"


class BoilerProfiler:
    """Profilování spotřeby bojleru z SQL historie."""

    def __init__(
        self,
        hass: HomeAssistant,
        energy_sensor: str,
        lookback_days: int = 60,
    ) -> None:
        """
        Inicializace profileru.

        Args:
            hass: Home Assistant instance
            energy_sensor: entity_id senzoru celkové energie (sensor.oig_bojler_day_w → Wh)
            lookback_days: Počet dní historie k analýze
        """
        self.hass = hass
        self.energy_sensor = energy_sensor
        self.lookback_days = lookback_days
        self._profiles: dict[str, BoilerProfile] = {}

    async def async_update_profiles(self) -> dict[str, BoilerProfile]:
        """
        Aktualizuje všechny 8 profilů z SQL historie.

        Returns:
            Dictionary {kategorie: profil}
        """
        _LOGGER.info("Začíná profilování z SQL historie (%s dní)", self.lookback_days)

        # Inicializace prázdných profilů
        for category in PROFILE_CATEGORIES:
            self._profiles[category] = BoilerProfile(
                category=category,
                hourly_avg={},
                confidence={},
                sample_count={},
                last_updated=None,
            )

        # Získat historii z recorderu
        end_time = dt_util.now()
        start_time = end_time - timedelta(days=self.lookback_days)

        try:
            history_data = await self._fetch_history(start_time, end_time)
        except Exception as err:
            _LOGGER.error("Chyba při čtení historie: %s", err)
            return self._profiles

        # Zpracovat data
        self._process_history_data(history_data)

        _LOGGER.info("Profilování dokončeno. Celkem kategorií: %s", len(self._profiles))
        return self._profiles

    async def _fetch_history(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """
        Načte historii ze SQL pomocí recorder.

        Returns:
            List slovníků {timestamp, state}
        """
        instance = get_instance(self.hass)

        if instance is None:
            _LOGGER.error("Recorder není dostupný")
            return []

        # Recorder returns dict[entity_id, list[State]].
        history_states = await instance.async_add_executor_job(
            state_changes_during_period,
            self.hass,
            start_time,
            end_time,
            self.energy_sensor,
        )

        states = history_states.get(self.energy_sensor, [])
        _LOGGER.debug(
            "Načteno %s záznamů z SQL pro %s", len(states), self.energy_sensor
        )

        # Konverze na jednoduchou strukturu
        result = []
        for state in states:
            try:
                timestamp = state.last_updated
                value_wh = float(state.state)
                result.append({"timestamp": timestamp, "value_wh": value_wh})
            except (ValueError, AttributeError):
                continue

        return result

    def _process_history_data(self, history_data: list[dict]) -> None:
        """
        Zpracuje historická data a naplní profily.

        Args:
            history_data: List slovníků {timestamp, value_wh}
        """
        if len(history_data) < 2:
            _LOGGER.warning("Nedostatek dat pro profilování")
            return

        # Seskupit data po dnech
        daily_data: dict[str, list[dict]] = defaultdict(list)
        for entry in history_data:
            day_key = entry["timestamp"].strftime("%Y-%m-%d")
            daily_data[day_key].append(entry)

        # Kategorizované hodinové spotřeby
        # {kategorie: {hodina: [spotřeby_kWh]}}
        categorized_hourly: dict[str, dict[int, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Projít každý den
        for day_key, day_entries in daily_data.items():
            if len(day_entries) < 2:
                continue

            # Seřadit podle času
            day_entries.sort(key=lambda x: x["timestamp"])

            # Určit kategorii
            first_timestamp = day_entries[0]["timestamp"]
            category = _get_profile_category(first_timestamp)

            # Vypočítat hodinové spotřeby (delta mezi záznamy)
            for i in range(1, len(day_entries)):
                prev_entry = day_entries[i - 1]
                curr_entry = day_entries[i]

                time_diff_hours = (
                    curr_entry["timestamp"] - prev_entry["timestamp"]
                ).total_seconds() / 3600.0

                if time_diff_hours <= 0 or time_diff_hours > 2:
                    # Přeskočit neplatné intervaly
                    continue

                energy_diff_wh = curr_entry["value_wh"] - prev_entry["value_wh"]
                if energy_diff_wh < 0:
                    # Reset čítače (nový den)
                    energy_diff_wh = curr_entry["value_wh"]

                # Normalizovat na kWh/hod
                consumption_kwh = (energy_diff_wh / 1000.0) / time_diff_hours

                # Hodina záznamu
                hour = curr_entry["timestamp"].hour

                categorized_hourly[category][hour].append(consumption_kwh)

        # Vypočítat průměry a confidence
        for category, hourly_data in categorized_hourly.items():
            profile = self._profiles[category]

            for hour, consumptions in hourly_data.items():
                if not consumptions:
                    continue

                avg_kwh = sum(consumptions) / len(consumptions)
                count = len(consumptions)

                # Confidence: min(1.0, počet_vzorků / 10)
                confidence = min(1.0, count / 10.0)

                profile.hourly_avg[hour] = avg_kwh
                profile.confidence[hour] = confidence
                profile.sample_count[hour] = count

            profile.last_updated = dt_util.now()

            _LOGGER.debug(
                "Profil %s: %s hodin s daty, průměrná confidence %.2f",
                category,
                len(profile.hourly_avg),
                sum(profile.confidence.values()) / max(len(profile.confidence), 1),
            )

    def get_profile_for_datetime(self, dt: datetime) -> Optional[BoilerProfile]:
        """
        Vrátí profil pro daný čas.

        Args:
            dt: Časový okamžik

        Returns:
            Profil nebo None pokud není dostupný
        """
        category = _get_profile_category(dt)
        profile = self._profiles.get(category)

        if profile is None:
            _LOGGER.debug("Profil pro kategorii %s neexistuje", category)
            return None

        # Kontrola minimální confidence
        avg_confidence = (
            sum(profile.confidence.values()) / max(len(profile.confidence), 1)
            if profile.confidence
            else 0.0
        )

        if avg_confidence < MIN_CONFIDENCE:
            _LOGGER.debug(
                "Profil %s má nízkou confidence (%.2f < %.2f)",
                category,
                avg_confidence,
                MIN_CONFIDENCE,
            )
            return None

        return profile

    def get_all_profiles(self) -> dict[str, BoilerProfile]:
        """Vrátí všechny profily."""
        return self._profiles
