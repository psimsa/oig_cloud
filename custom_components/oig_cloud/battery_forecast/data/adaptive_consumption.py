"""Adaptive consumption helpers extracted from legacy battery forecast."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

UNKNOWN_PROFILE_LABEL = "Neznámý profil"
NO_PROFILE_LABEL = "Žádný profil"
SEASON_NAMES = {
    "winter": "zimní",
    "spring": "jarní",
    "summer": "letní",
    "autumn": "podzimní",
}
SIMILARITY_PARENS_RE = re.compile(r"\([^)]*(podobn|shoda)[^)]*\)", re.IGNORECASE)


class AdaptiveConsumptionHelper:
    """Helper for adaptive consumption profiling and summaries."""

    def __init__(
        self,
        hass: Optional[HomeAssistant],
        box_id: str,
        iso_tz_offset: str = "+00:00",
    ) -> None:
        self._hass = hass
        self._box_id = box_id
        self._iso_tz_offset = iso_tz_offset

    @staticmethod
    def _strip_similarity_parens(value: str) -> str:
        return SIMILARITY_PARENS_RE.sub("", value)

    @classmethod
    def _normalize_profile_name(cls, raw_name: Any) -> str:
        cleaned = cls._strip_similarity_parens(str(raw_name)).strip()
        if not cleaned:
            cleaned = str(raw_name).strip()
        return " ".join(cleaned.split())

    @staticmethod
    def _get_season_label(season: str) -> str:
        return SEASON_NAMES.get(season, season)

    @staticmethod
    def _sum_profile_hours(hourly: Any, start_hour: int, start: int, end: int) -> float:
        total = 0.0
        if isinstance(hourly, list):
            for hour in range(start, end):
                index = hour - start_hour
                if 0 <= index < len(hourly):
                    total += hourly[index]
        elif isinstance(hourly, dict):
            for hour in range(start, end):
                total += hourly.get(hour, 0.0)
        return total

    @classmethod
    def _build_profile_suffix(
        cls, profile: Dict[str, Any], ui: Dict[str, Any]
    ) -> List[str]:
        characteristics = profile.get("characteristics", {})
        season_cz = cls._get_season_label(characteristics.get("season", ""))

        day_count = ui.get("sample_count", profile.get("sample_count", 0))
        try:
            day_count_val = int(day_count) if day_count is not None else 0
        except (TypeError, ValueError):
            day_count_val = 0

        similarity_score = ui.get("similarity_score")
        try:
            similarity_val = (
                float(similarity_score) if similarity_score is not None else None
            )
        except (TypeError, ValueError):
            similarity_val = None

        suffix_parts: List[str] = []
        if season_cz:
            suffix_parts.append(str(season_cz))
        if day_count_val > 0:
            suffix_parts.append(f"{day_count_val} dnů")
        if similarity_val is not None:
            suffix_parts.append(f"shoda {similarity_val:.2f}")
        return suffix_parts

    @classmethod
    def _build_dashboard_profile_details(
        cls, today_profile: Dict[str, Any], match_score: float
    ) -> str:
        season_cz = cls._get_season_label(today_profile.get("season", ""))
        day_count = today_profile.get("day_count", 0)

        parts: List[str] = []
        if season_cz:
            parts.append(season_cz)
        if day_count:
            parts.append(f"{day_count} podobných dnů")

        details = ", ".join(parts)
        if match_score > 0:
            score_text = f"{int(match_score)}% shoda"
            return f"{details} • {score_text}" if details else score_text
        return details

    @staticmethod
    def _calculate_charging_cost_today(
        timeline_data: List[Dict[str, Any]],
        today_date: datetime.date,
        iso_tz_offset: str,
    ) -> float:
        total = 0.0
        for entry in timeline_data:
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                continue
            try:
                entry_dt = datetime.fromisoformat(
                    timestamp_str.replace("Z", iso_tz_offset)
                )
            except (ValueError, AttributeError):
                continue
            if entry_dt.date() != today_date:
                continue
            charging_kwh = entry.get("charging_kwh", 0)
            spot_price = entry.get("spot_price_czk_per_kwh", 0)
            if charging_kwh > 0 and spot_price > 0:
                total += charging_kwh * spot_price
        return total

    @staticmethod
    def _season_for_month(month: int) -> str:
        if month in {12, 1, 2}:
            return "winter"
        if month in {3, 4, 5}:
            return "spring"
        if month in {6, 7, 8}:
            return "summer"
        return "autumn"

    @staticmethod
    def _transition_type(today_weekday: int, tomorrow_weekday: int) -> Optional[str]:
        if today_weekday == 4 and tomorrow_weekday == 5:
            return "friday_to_saturday"
        if today_weekday == 6 and tomorrow_weekday == 0:
            return "sunday_to_monday"
        return None

    @staticmethod
    def _select_profile_by_prefix(
        profiles: Dict[str, Any], prefix: str, *, prefer_typical: bool
    ) -> Optional[Dict[str, Any]]:
        best_match = None
        for profile_id, profile in profiles.items():
            if not profile_id.startswith(prefix):
                continue
            if not prefer_typical:
                return profile
            if (
                not best_match
                or "_typical" in profile_id
                or len(profile_id.split("_")) == 2
            ):
                best_match = profile
        return best_match

    def calculate_consumption_summary(
        self, adaptive_profiles: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Vypočítá sumarizační hodnoty spotřeby pro dashboard."""
        if not adaptive_profiles or not isinstance(adaptive_profiles, dict):
            return {}

        today_profile = adaptive_profiles.get("today_profile")
        current_hour = datetime.now().hour
        planned_today = 0.0
        if today_profile and isinstance(today_profile, dict):
            hourly = today_profile.get("hourly_consumption", [])
            start_hour = today_profile.get("start_hour", 0)
            planned_today = self._sum_profile_hours(
                hourly, start_hour, current_hour, 24
            )

        tomorrow_profile = adaptive_profiles.get("tomorrow_profile")
        planned_tomorrow = 0.0
        if tomorrow_profile and isinstance(tomorrow_profile, dict):
            hourly = tomorrow_profile.get("hourly_consumption", [])
            start_hour = tomorrow_profile.get("start_hour", 0)
            planned_tomorrow = self._sum_profile_hours(hourly, start_hour, 0, 24)

        profile_today_text = self.format_profile_description(today_profile)
        profile_tomorrow_text = self.format_profile_description(tomorrow_profile)

        _LOGGER.debug(
            "Consumption summary: today=%.1fkWh, tomorrow=%.1fkWh",
            planned_today,
            planned_tomorrow,
        )

        return {
            "planned_consumption_today": round(planned_today, 1),
            "planned_consumption_tomorrow": round(planned_tomorrow, 1),
            "profile_today": profile_today_text,
            "profile_tomorrow": profile_tomorrow_text,
        }

    @staticmethod
    def format_profile_description(profile: Optional[Dict[str, Any]]) -> str:
        """Vrátí lidsky čitelný popis profilu."""
        if not profile or not isinstance(profile, dict):
            return NO_PROFILE_LABEL

        ui = profile.get("ui", {})
        raw_name = ui.get("name", UNKNOWN_PROFILE_LABEL) or UNKNOWN_PROFILE_LABEL
        cleaned_name = AdaptiveConsumptionHelper._normalize_profile_name(raw_name)

        suffix_parts = AdaptiveConsumptionHelper._build_profile_suffix(profile, ui)
        if suffix_parts:
            return f"{cleaned_name} ({', '.join(suffix_parts)})"
        return cleaned_name

    def process_adaptive_consumption_for_dashboard(
        self,
        adaptive_profiles: Optional[Dict[str, Any]],
        timeline_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Zpracuj adaptive data pro dashboard (do attributes)."""
        if not adaptive_profiles or not isinstance(adaptive_profiles, dict):
            _LOGGER.debug(
                "No adaptive profiles for dashboard: type=%s", type(adaptive_profiles)
            )
            return {}

        now = datetime.now()
        current_hour = now.hour

        today_profile = adaptive_profiles.get("today_profile")
        remaining_kwh = 0.0
        if today_profile and "hourly_consumption" in today_profile:
            hourly = today_profile["hourly_consumption"]
            start_hour = today_profile.get("start_hour", 0)
            remaining_kwh = self._sum_profile_hours(
                hourly, start_hour, current_hour, 24
            )

        profile_name = adaptive_profiles.get("profile_name", UNKNOWN_PROFILE_LABEL)
        match_score = adaptive_profiles.get("match_score", 0)

        profile_details = ""
        if today_profile:
            profile_details = self._build_dashboard_profile_details(
                today_profile, match_score
            )

        today_date = now.date()
        charging_cost_today = self._calculate_charging_cost_today(
            timeline_data, today_date, self._iso_tz_offset
        )

        return {
            "remaining_kwh": round(remaining_kwh, 1),
            "profile_name": profile_name,
            "profile_details": profile_details,
            "charging_cost_today": round(charging_cost_today, 0),
        }

    async def get_adaptive_load_prediction(self) -> Optional[Dict[str, Any]]:
        """Načte adaptive load prediction přímo z adaptive_load_profiles sensoru."""
        try:
            profiles_sensor = f"sensor.oig_{self._box_id}_adaptive_load_profiles"

            if not self._hass:
                return None

            profiles_state = self._hass.states.get(profiles_sensor)
            if not profiles_state:
                _LOGGER.debug("Adaptive profiles sensor not found: %s", profiles_sensor)
                return None

            attrs = profiles_state.attributes

            if "today_profile" not in attrs or "tomorrow_profile" not in attrs:
                _LOGGER.debug(
                    "Adaptive sensor missing today_profile or tomorrow_profile"
                )
                return None

            result = {
                "today_profile": attrs["today_profile"],
                "tomorrow_profile": attrs["tomorrow_profile"],
                "match_score": attrs.get("prediction_summary", {}).get(
                    "similarity_score", 0.0
                ),
                "prediction_summary": attrs.get("prediction_summary", {}),
            }

            _LOGGER.debug(
                "✅ Adaptive prediction loaded: today=%.2f kWh, match_score=%.3f",
                result["today_profile"].get("total_kwh", 0),
                result["match_score"],
            )

            return result

        except Exception as e:
            _LOGGER.error("Error in adaptive load prediction: %s", e, exc_info=True)
            return None

    def get_profiles_from_sensor(self) -> Dict[str, Any]:
        """Načte profily z adaptive sensor a převede list na dict."""
        try:
            profiles_sensor = f"sensor.oig_{self._box_id}_adaptive_load_profiles"

            if not self._hass:
                return {}

            profiles_state = self._hass.states.get(profiles_sensor)
            if not profiles_state:
                return {}

            profiles_list = profiles_state.attributes.get("profiles", [])

            if isinstance(profiles_list, list):
                return {
                    p.get("profile_id", f"profile_{i}"): p
                    for i, p in enumerate(profiles_list)
                }
            if isinstance(profiles_list, dict):
                return profiles_list

            _LOGGER.warning("Unexpected profiles type: %s", type(profiles_list))
            return {}

        except Exception as e:
            _LOGGER.debug("Error getting profiles: %s", e)
            return {}

    async def get_today_hourly_consumption(self) -> List[float]:
        """Načte dnešní spotřebu po hodinách (od půlnoci do teď)."""
        try:
            consumption_sensor = f"sensor.oig_{self._box_id}_actual_aco_p"

            if self._hass is None:
                return []

            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            start_time = dt_util.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_time = dt_util.now()

            stats = await self._hass.async_add_executor_job(
                statistics_during_period,
                self._hass,
                start_time,
                end_time,
                {consumption_sensor},
                "hour",
                None,
                {"mean"},
            )

            if not stats or consumption_sensor not in stats:
                return []

            hourly_values = []
            for stat in stats[consumption_sensor]:
                if stat.get("mean") is not None:
                    hourly_values.append(stat["mean"] / 1000)

            return hourly_values

        except Exception as e:
            _LOGGER.debug("Error getting today hourly consumption: %s", e)
            return []

    async def calculate_recent_consumption_ratio(
        self, adaptive_profiles: Optional[Dict[str, Any]], hours: int = 3
    ) -> Optional[float]:
        """Porovná reálnou spotřebu vs plán za posledních N hodin."""
        if (
            not adaptive_profiles
            or not isinstance(adaptive_profiles, dict)
            or "today_profile" not in adaptive_profiles
        ):
            return None

        actual_hourly = await self.get_today_hourly_consumption()
        if not actual_hourly:
            return None

        total_hours = len(actual_hourly)
        if total_hours == 0:
            return None

        lookback = min(hours, total_hours)
        actual_total = sum(actual_hourly[-lookback:])

        today_profile = adaptive_profiles.get("today_profile") or {}
        hourly_plan = today_profile.get("hourly_consumption")
        if not isinstance(hourly_plan, list):
            return None

        start_hour = today_profile.get("start_hour", 0)
        planned_total = 0.0
        start_index = total_hours - lookback
        avg_fallback = today_profile.get("avg_kwh_h", 0.5)

        for idx in range(lookback):
            hour = start_index + idx
            plan_idx = hour - start_hour
            if 0 <= plan_idx < len(hourly_plan):
                planned_total += hourly_plan[plan_idx]
            else:
                planned_total += avg_fallback

        if planned_total <= 0:
            return None

        ratio = actual_total / planned_total
        _LOGGER.debug(
            "[LoadForecast] Recent consumption ratio (last %dh): actual=%.2f kWh, "
            "planned=%.2f kWh → %.2fx",
            lookback,
            actual_total,
            planned_total,
            ratio,
        )
        return ratio

    @staticmethod
    def apply_consumption_boost_to_forecast(
        load_forecast: List[float], ratio: float, hours: int = 3
    ) -> None:
        """Navýší krátkodobý load forecast podle zjištěné odchylky."""
        if not load_forecast:
            return

        capped_ratio = min(ratio, 3.0)
        intervals = min(
            len(load_forecast),
            max(4, int(math.ceil(hours * 4 * min(capped_ratio, 2.5)))),
        )

        for idx in range(intervals):
            load_forecast[idx] = round(load_forecast[idx] * capped_ratio, 4)

        _LOGGER.info(
            "[LoadForecast] Boosted first %d intervals by %.0f%% due to high "
            "consumption drift (ratio %.2fx, capped %.2fx)",
            intervals,
            (capped_ratio - 1) * 100,
            ratio,
            capped_ratio,
        )

    @staticmethod
    def calculate_profile_similarity(
        today_hourly: List[float], profile_hourly: List[float]
    ) -> float:
        """Vypočítá podobnost dnešní křivky s profilem (MAPE scoring)."""
        if not today_hourly:
            return 0

        compare_length = min(len(today_hourly), len(profile_hourly))

        total_error = 0.0
        valid_hours = 0

        for i in range(compare_length):
            actual = today_hourly[i]
            expected = profile_hourly[i]

            if actual > 0:
                total_error += abs(actual - expected) / actual
                valid_hours += 1

        if valid_hours == 0:
            return 0

        avg_error = total_error / valid_hours
        return max(0.0, 100 - (avg_error * 100))

    @staticmethod
    def select_tomorrow_profile(
        profiles: Dict[str, Any], current_time: datetime
    ) -> Optional[Dict[str, Any]]:
        """Vybere profil pro zítřek podle day_type a transition."""
        try:
            tomorrow = current_time + timedelta(days=1)
            tomorrow_weekday = tomorrow.weekday()
            today_weekday = current_time.weekday()

            season = AdaptiveConsumptionHelper._season_for_month(tomorrow.month)
            transition_type = AdaptiveConsumptionHelper._transition_type(
                today_weekday, tomorrow_weekday
            )
            if transition_type:
                transition_profile_id = f"{transition_type}_{season}"
                transition_profile = (
                    AdaptiveConsumptionHelper._select_profile_by_prefix(
                        profiles, transition_profile_id, prefer_typical=False
                    )
                )
                if transition_profile:
                    _LOGGER.debug(
                        "Using transition profile for tomorrow: %s",
                        transition_profile_id,
                    )
                    return transition_profile

            tomorrow_is_weekend = tomorrow_weekday >= 5
            day_type = "weekend" if tomorrow_is_weekend else "weekday"
            standard_profile_id = f"{day_type}_{season}"

            best_match = AdaptiveConsumptionHelper._select_profile_by_prefix(
                profiles, standard_profile_id, prefer_typical=True
            )
            if best_match:
                _LOGGER.debug(
                    "Using standard profile for tomorrow: %s_%s", day_type, season
                )
            return best_match

        except Exception as e:
            _LOGGER.debug("Error selecting tomorrow profile: %s", e)
            return None

    async def get_consumption_today(self) -> Optional[float]:
        """Získat celkovou spotřebu dnes od půlnoci do teď."""
        try:
            consumption_sensor = f"sensor.oig_{self._box_id}_actual_aco_p"

            if self._hass is None:
                return None

            start_time = dt_util.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_time = dt_util.now()

            from homeassistant.components.recorder import history

            states = await self._hass.async_add_executor_job(
                history.get_significant_states,
                self._hass,
                start_time,
                end_time,
                [consumption_sensor],
            )

            if not states or consumption_sensor not in states:
                return None

            consumption_states = states[consumption_sensor]
            if not consumption_states:
                return None

            import statistics

            valid_values = []
            for state in consumption_states:
                try:
                    value = float(state.state)
                    if 0 <= value <= 20000:
                        valid_values.append(value)
                except (ValueError, AttributeError):
                    continue

            if not valid_values:
                return None

            avg_watts = statistics.mean(valid_values)
            hours_elapsed = (end_time - start_time).total_seconds() / 3600
            return (avg_watts / 1000) * hours_elapsed

        except Exception as e:
            _LOGGER.debug("Error getting consumption today: %s", e)
            return None

    def get_load_avg_fallback(self) -> float:
        """Fallback: Získá průměr z load_avg senzorů pro aktuální čas."""
        current_time = dt_util.now()
        is_weekend = current_time.weekday() >= 5
        day_type = "weekend" if is_weekend else "weekday"

        hour = current_time.hour
        if 6 <= hour < 8:
            time_block = "6_8"
        elif 8 <= hour < 12:
            time_block = "8_12"
        elif 12 <= hour < 16:
            time_block = "12_16"
        elif 16 <= hour < 22:
            time_block = "16_22"
        else:
            time_block = "22_6"

        sensor_id = f"sensor.oig_{self._box_id}_load_avg_{time_block}_{day_type}"

        if self._hass:
            sensor_state = self._hass.states.get(sensor_id)
            if sensor_state and sensor_state.state not in ["unknown", "unavailable"]:
                try:
                    watt = float(sensor_state.state)
                    return watt / 1000
                except (ValueError, TypeError):
                    pass

        return 0.48
