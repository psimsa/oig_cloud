"""Sensor pro automatickou tvorbu adaptivních profilů spotřeby z historických dat."""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# 72h Consumption Profiling Constants
PROFILE_HOURS = 72  # Délka profilu v hodinách (3 dny)
# Plovoucí okno: matching + predikce = vždy 72h celkem
# Před půlnocí: matching až do předchozí půlnoci (max 48h), predikce až do další půlnoci (min 24h)
# Po půlnoci: matching jen 24h zpět, predikce 48h dopředu

# Similarity scoring weights
WEIGHT_CORRELATION = 0.50  # Correlation coefficient weight
WEIGHT_RMSE = 0.30  # RMSE weight (inverted)
WEIGHT_TOTAL = 0.20  # Total consumption difference weight (inverted)

# Profiling tuning
MAX_REASONABLE_KWH_H = 20.0  # 20 kWh/h (~20 kW) sanity limit
MAX_MISSING_HOURS_PER_DAY = 6  # Maximum hours to interpolate within a day
TOP_MATCHES = 7  # Average top-N profiles for stability
FLOOR_RATIO = 0.35  # Min floor as % of reference consumption
DEFAULT_DAYS_BACK = 90  # Fallback when history start can't be resolved


def _get_season(dt: datetime) -> str:
    """Určit roční období z data."""
    month = dt.month
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:
        return "autumn"


def _generate_profile_name(
    hourly_consumption: List[float], season: str, is_weekend: bool
) -> str:
    """
    Generuje lidsky čitelný název profilu na základě charakteristik spotřeby.

    Args:
        hourly_consumption: 24h profil hodinové spotřeby [kWh]
        season: roční období ('winter', 'spring', 'summer', 'autumn')
        is_weekend: True pokud jde o víkend

    Returns:
        Lidsky čitelný název (např. "Pracovní den s topením", "Víkend s praním")
    """
    if not hourly_consumption or len(hourly_consumption) != 24:
        return "Neznámý profil"

    # 1. ZÁKLADNÍ KLASIFIKACE
    day_name = "Víkend" if is_weekend else "Pracovní den"

    # Celková denní spotřeba
    total = sum(hourly_consumption)
    daily_avg = total / 24

    # 2. ANALÝZA PATTERN SHAPE
    morning_avg = float(np.mean(hourly_consumption[6:12]))  # 6-12h
    afternoon_avg = float(np.mean(hourly_consumption[12:18]))  # 12-18h
    evening_avg = float(np.mean(hourly_consumption[18:24]))  # 18-24h
    night_avg = float(np.mean(hourly_consumption[0:6]))  # 0-6h

    # Detekce špiček (špička > 1.3× průměr)
    has_morning_spike = morning_avg > daily_avg * 1.3
    has_evening_spike = evening_avg > daily_avg * 1.3
    has_afternoon_spike = afternoon_avg > daily_avg * 1.3

    # 3. SPECIÁLNÍ DETEKCE
    special_tags = []

    # Topení (zimní vysoká večerní spotřeba)
    if season == "winter" and evening_avg > 1.2:
        special_tags.append("topení")

    # Klimatizace (letní vysoká odpolední spotřeba)
    if season == "summer" and afternoon_avg > 1.0:
        special_tags.append("klimatizace")

    # Praní (víkend s ranní špičkou)
    if is_weekend and has_morning_spike:
        special_tags.append("praní")

    # Home office (pracovní den s vysokou denní spotřebou)
    if not is_weekend and afternoon_avg > 0.8:
        special_tags.append("home office")

    # Vysoká noční spotřeba (bojler?)
    if night_avg > 0.5:
        special_tags.append("noční ohřev")

    # 4. SESTAVENÍ NÁZVU
    if special_tags:
        # Preferovat speciální tag
        main_tag = special_tags[0]
        if main_tag == "topení":
            return f"{day_name} s topením"
        elif main_tag == "klimatizace":
            return f"{day_name} s klimatizací"
        elif main_tag == "praní":
            return f"{day_name} s praním"
        elif main_tag == "home office":
            return "Home office"
        elif main_tag == "noční ohřev":
            return f"{day_name} s nočním ohřevem"

    # Fallback podle špičky
    if has_evening_spike:
        return f"{day_name} - večerní špička"
    elif has_morning_spike:
        return f"{day_name} - ranní špička"
    elif has_afternoon_spike:
        return f"{day_name} - polední špička"
    else:
        return f"{day_name} - běžný"


class OigCloudAdaptiveLoadProfilesSensor(CoordinatorEntity, SensorEntity):
    """
    Sensor pro automatickou analýzu a tvorbu profilů spotřeby.

    - Noční analýza historických dat (02:00)
    - Persistence profilů v attributes
    - UI-friendly zobrazení
    """

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
    ) -> None:
        """Initialize the adaptive profiles sensor."""
        super().__init__(coordinator)

        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._device_info = device_info
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)

        # Stabilní box_id resolution (config entry → proxy → coordinator numeric keys)
        try:
            from .base_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        self._attr_icon = "mdi:chart-timeline-variant-shimmer"
        self._attr_native_unit_of_measurement = None  # State = počet profilů
        self._attr_device_class = None
        self._attr_state_class = None
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Načíst název ze sensor types
        from ..sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")
        self._attr_name = name_cs or name_en or sensor_type

        # 72h Profiling storage
        self._last_profile_created: Optional[datetime] = None
        self._profiling_status: str = "idle"  # idle/creating/ok/error
        self._profiling_error: Optional[str] = None
        self._profiling_task: Optional[Any] = None  # Background task
        self._last_profile_reason: Optional[str] = None

        # Current consumption prediction (from coordinator)
        self._current_prediction: Optional[Dict[str, Any]] = None

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - spustit profiling loop."""
        await super().async_added_to_hass()
        self._hass = self.hass

        # START: Profiling loop jako background task
        _LOGGER.info("Starting consumption profiling loop")
        self._profiling_task = self.hass.async_create_background_task(
            self._profiling_loop(), name="oig_cloud_consumption_profiling_loop"
        )

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA - zrušit profiling task."""
        if self._profiling_task and not self._profiling_task.done():
            self._profiling_task.cancel()
        await super().async_will_remove_from_hass()

    async def _profiling_loop(self) -> None:
        """
        Profiling loop - vytváření adaptivní predikce spotřeby.

        První běh okamžitě (s delay 10s), pak každých 15 minut.
        Historické profily se loadují jednou denně v 00:30.
        """
        try:
            # První běh s delay aby HA dostal čas
            await asyncio.sleep(10)

            _LOGGER.info(
                "📊 Adaptive profiling loop starting - matching every 15 minutes"
            )

            # První běh okamžitě
            await self._create_and_update_profile()

            while True:
                try:
                    # Čekat 15 minut
                    await asyncio.sleep(15 * 60)

                    _LOGGER.debug("📊 Running adaptive matching (15min update)")
                    await self._create_and_update_profile()

                except Exception as e:
                    _LOGGER.error(f"❌ Profiling loop error: {e}", exc_info=True)
                    self._profiling_status = "error"
                    self._profiling_error = str(e)
                    self.async_schedule_update_ha_state(force_refresh=True)

                    # Počkat 5 minut před retry po chybě
                    await asyncio.sleep(5 * 60)

        except asyncio.CancelledError:
            _LOGGER.info("Profiling loop cancelled")
            raise
        except Exception as e:
            _LOGGER.error(f"Fatal profiling loop error: {e}", exc_info=True)

    async def _wait_for_next_profile_window(self) -> None:
        """Počkat do dalšího profiling okna (00:30)."""
        now = dt_util.now()
        target_time = now.replace(hour=0, minute=30, second=0, microsecond=0)

        # Pokud už je po 00:30 dnes, čekat na zítra
        if now >= target_time:
            target_time += timedelta(days=1)

        wait_seconds = (target_time - now).total_seconds()
        _LOGGER.info(
            f"⏱️ Waiting {wait_seconds / 3600:.1f} hours until next profile window at {target_time}"
        )

        await asyncio.sleep(wait_seconds)

    async def _create_and_update_profile(self) -> None:
        """Vytvořit profil a updateovat state."""
        self._profiling_status = "creating"
        self._profiling_error = None
        if self._hass:
            self.async_write_ha_state()

        energy_sensor = f"sensor.oig_{self._box_id}_ac_out_en_day"
        power_sensor = f"sensor.oig_{self._box_id}_actual_aco_p"

        previous_reason = self._last_profile_reason
        self._last_profile_reason = None

        # Najít best matching profile přímo z aktuálních dat
        # (nepotřebujeme ukládat do events - profily jsou on-the-fly)
        prediction = await self._find_best_matching_profile(
            energy_sensor, fallback_sensor=power_sensor
        )

        if prediction:
            self._last_profile_created = dt_util.now()
            self._profiling_status = "ok"
            self._profiling_error = None
            self._current_prediction = prediction
            self._last_profile_reason = None

            _LOGGER.info(
                f"✅ Profile updated: predicted {prediction.get('predicted_total_kwh', 0):.2f} kWh for next 24h"
            )
        else:
            reason = self._last_profile_reason or "unknown"
            if reason.startswith("not_enough_") or reason.startswith("no_"):
                self._profiling_status = "warming_up"
                self._profiling_error = reason
                if reason != previous_reason:
                    _LOGGER.info("Profiling zatím nemá dost dat (%s).", reason)
            else:
                self._profiling_status = "error"
                self._profiling_error = "Failed to create profile"
                _LOGGER.warning("❌ Failed to update consumption profile")

        if self._hass:
            self.async_write_ha_state()

            # Notify dependent sensors (BatteryForecast) that profiles are ready
            if prediction:  # Only signal if we have valid data
                from homeassistant.helpers.dispatcher import async_dispatcher_send

                signal_name = f"oig_cloud_{self._box_id}_profiles_updated"
                _LOGGER.debug(f"📡 Sending signal: {signal_name}")
                async_dispatcher_send(self._hass, signal_name)

    # ============================================================================
    # 72h Consumption Profiling System
    # ============================================================================

    def _get_energy_unit_factor(self, sensor_entity_id: str) -> float:
        """Return conversion factor to kWh for energy sensors."""
        if not self._hass:
            return 0.001
        state = self._hass.states.get(sensor_entity_id)
        unit = None
        if state:
            unit = state.attributes.get("unit_of_measurement")
        if unit and unit.lower() == "kwh":
            return 1.0
        return 0.001  # Wh → kWh

    async def _load_hourly_series(
        self,
        sensor_entity_id: str,
        start_time: datetime,
        end_time: datetime,
        *,
        value_field: str,
    ) -> List[Tuple[datetime, float]]:
        """
        Načíst hodinovou řadu ze statistics tabulky.

        Args:
            sensor_entity_id: Entity ID senzoru
            start_time: začátek rozsahu (local)
            end_time: konec rozsahu (local)
            value_field: "sum" (energy) nebo "mean" (power)
        """
        if not self._hass:
            return []

        try:
            from homeassistant.helpers.recorder import get_instance
            from sqlalchemy import text

            recorder_instance = get_instance(self._hass)
            if not recorder_instance:
                _LOGGER.error("Recorder instance not available")
                return []

            start_ts = int(dt_util.as_utc(start_time).timestamp())
            end_ts = int(dt_util.as_utc(end_time).timestamp())

            def get_statistics():
                """Query statistics for hourly values."""
                from homeassistant.helpers.recorder import session_scope

                instance = get_instance(self._hass)
                with session_scope(
                    hass=self._hass, session=instance.get_session()
                ) as session:
                    query = text(
                        """
                        SELECT s.sum, s.mean, s.state, s.start_ts
                        FROM statistics s
                        INNER JOIN statistics_meta sm ON s.metadata_id = sm.id
                        WHERE sm.statistic_id = :statistic_id
                        AND s.start_ts >= :start_ts
                        AND s.start_ts < :end_ts
                        ORDER BY s.start_ts
                        """
                    )

                    result = session.execute(
                        query,
                        {
                            "statistic_id": sensor_entity_id,
                            "start_ts": start_ts,
                            "end_ts": end_ts,
                        },
                    )
                    return result.fetchall()

            stats_rows = await recorder_instance.async_add_executor_job(get_statistics)
            if not stats_rows:
                return []

            unit_factor = self._get_energy_unit_factor(sensor_entity_id)
            series: List[Tuple[datetime, float]] = []

            for row in stats_rows:
                try:
                    sum_val = row[0]
                    mean_val = row[1]
                    state_val = row[2]
                    timestamp_ts = float(row[3])
                except (ValueError, AttributeError, IndexError, TypeError):
                    continue

                timestamp = datetime.fromtimestamp(timestamp_ts, tz=dt_util.UTC)

                if value_field == "mean":
                    if mean_val is None:
                        continue
                    value = float(mean_val) / 1000.0  # W → kWh/h
                else:
                    raw = sum_val if sum_val is not None else state_val
                    if raw is None:
                        continue
                    value = float(raw) * unit_factor  # Wh → kWh (if needed)

                if value < 0 or value > MAX_REASONABLE_KWH_H:
                    continue

                series.append((dt_util.as_local(timestamp), value))

            return series

        except Exception as e:
            _LOGGER.error(f"Failed to load hourly series: {e}", exc_info=True)
            return []

    async def _get_earliest_statistics_start(
        self, sensor_entity_id: str
    ) -> Optional[datetime]:
        """Najít nejstarší dostupný hodinový záznam pro senzor."""
        if not self._hass:
            return None

        try:
            from homeassistant.helpers.recorder import get_instance, session_scope
            from sqlalchemy import text

            recorder_instance = get_instance(self._hass)
            if not recorder_instance:
                _LOGGER.error("Recorder instance not available")
                return None

            def get_min_start_ts() -> Optional[float]:
                instance = get_instance(self._hass)
                with session_scope(
                    hass=self._hass, session=instance.get_session()
                ) as session:
                    query = text(
                        """
                        SELECT MIN(s.start_ts)
                        FROM statistics s
                        INNER JOIN statistics_meta sm ON s.metadata_id = sm.id
                        WHERE sm.statistic_id = :statistic_id
                        """
                    )
                    result = session.execute(query, {"statistic_id": sensor_entity_id})
                    return result.scalar()

            min_ts = await recorder_instance.async_add_executor_job(get_min_start_ts)
            if min_ts is None:
                return None

            earliest = datetime.fromtimestamp(float(min_ts), tz=dt_util.UTC)
            local = dt_util.as_local(earliest)
            return datetime.combine(
                local.date(), datetime.min.time(), tzinfo=local.tzinfo
            )

        except Exception as e:
            _LOGGER.error(
                f"Failed to resolve earliest statistics start: {e}", exc_info=True
            )
            return None

    def _build_daily_profiles(
        self, hourly_series: List[Tuple[datetime, float]]
    ) -> Tuple[
        Dict[datetime.date, List[float]], Dict[int, float], Dict[datetime.date, int]
    ]:
        """Zarovnat hodinová data na kalendářní dny a dopočítat chybějící hodiny."""
        if not hourly_series:
            return {}, {}, {}

        day_map: Dict[datetime.date, Dict[int, float]] = defaultdict(dict)
        all_values: List[float] = []

        for ts, value in hourly_series:
            day = ts.date()
            hour = ts.hour
            day_map[day][hour] = float(value)
            all_values.append(float(value))

        if not all_values:
            return {}, {}, {}

        hour_medians: Dict[int, float] = {}
        for hour in range(24):
            values = [v.get(hour) for v in day_map.values() if hour in v]
            if values:
                hour_medians[hour] = float(np.median(values))

        global_median = float(np.median(all_values)) if all_values else 0.0

        daily_profiles: Dict[datetime.date, List[float]] = {}
        interpolated_counts: Dict[datetime.date, int] = {}

        for day, hours in day_map.items():
            day_values: List[Optional[float]] = [
                hours.get(h) if h in hours else None for h in range(24)
            ]
            missing = sum(1 for v in day_values if v is None)

            if missing > MAX_MISSING_HOURS_PER_DAY:
                _LOGGER.debug(
                    "Skipping day %s (missing %s hours)", day.isoformat(), missing
                )
                continue

            available = [v for v in day_values if v is not None]
            if not available:
                continue

            day_avg = float(np.mean(available)) if available else global_median
            filled, interpolated = self._fill_missing_hours(
                day_values, hour_medians, day_avg, global_median
            )
            daily_profiles[day] = filled
            interpolated_counts[day] = interpolated

        return daily_profiles, hour_medians, interpolated_counts

    def _fill_missing_hours(
        self,
        day_values: List[Optional[float]],
        hour_medians: Dict[int, float],
        day_avg: float,
        global_median: float,
    ) -> Tuple[List[float], int]:
        """Dopočítat chybějící hodiny (lineárně uvnitř dne, fallback na medián)."""
        return self._fill_missing_values(
            day_values, hour_medians, day_avg, global_median, hour_offset=0
        )

    def _fill_missing_values(
        self,
        values: List[Optional[float]],
        hour_medians: Dict[int, float],
        day_avg: float,
        global_median: float,
        *,
        hour_offset: int = 0,
    ) -> Tuple[List[float], int]:
        """Dopočítat chybějící hodnoty v libovolně dlouhém seznamu."""
        filled = list(values)
        interpolated = 0
        length = len(values)

        for idx, value in enumerate(values):
            if value is not None:
                continue

            prev_idx = next(
                (i for i in range(idx - 1, -1, -1) if values[i] is not None),
                None,
            )
            next_idx = next(
                (i for i in range(idx + 1, length) if values[i] is not None),
                None,
            )

            if prev_idx is not None and next_idx is not None:
                prev_val = float(values[prev_idx])  # type: ignore[arg-type]
                next_val = float(values[next_idx])  # type: ignore[arg-type]
                ratio = (idx - prev_idx) / (next_idx - prev_idx)
                fill_value = prev_val + (next_val - prev_val) * ratio
            else:
                fill_value = hour_medians.get(idx + hour_offset)
                if fill_value is None:
                    fill_value = day_avg if day_avg is not None else global_median

            filled[idx] = float(fill_value)
            interpolated += 1

        return filled, interpolated

    def _build_72h_profiles(
        self, daily_profiles: Dict[datetime.date, List[float]]
    ) -> List[Dict[str, Any]]:
        """Sestavit historické 72h profily z po sobě jdoucích dnů."""
        profiles: List[Dict[str, Any]] = []
        days = sorted(daily_profiles.keys())

        for i in range(len(days) - 2):
            d0, d1, d2 = days[i], days[i + 1], days[i + 2]
            if d1 != d0 + timedelta(days=1) or d2 != d1 + timedelta(days=1):
                continue

            profile_data = daily_profiles[d0] + daily_profiles[d1] + daily_profiles[d2]

            if len(profile_data) != PROFILE_HOURS:
                continue

            profiles.append(
                {
                    "consumption_kwh": profile_data,
                    "total_consumption": float(np.sum(profile_data)),
                    "avg_consumption": float(np.mean(profile_data)),
                    "start_date": d0.isoformat(),
                }
            )

        return profiles

    def _build_current_match(
        self,
        hourly_series: List[Tuple[datetime, float]],
        hour_medians: Dict[int, float],
    ) -> Optional[List[float]]:
        """Sestavit aktuální match okno z včerejška a dneška (dnešek může být neúplný)."""
        if not hourly_series:
            return None

        now = dt_util.now()
        current_hour = now.hour
        today = now.date()
        yesterday = today - timedelta(days=1)

        day_map: Dict[datetime.date, Dict[int, float]] = defaultdict(dict)
        all_values: List[float] = []

        for ts, value in hourly_series:
            day = ts.date()
            hour = ts.hour
            day_map[day][hour] = float(value)
            all_values.append(float(value))

        if not all_values:
            return None

        global_median = float(np.median(all_values)) if all_values else 0.0
        match: List[float] = []

        yesterday_hours = day_map.get(yesterday)
        if not yesterday_hours:
            return None

        yesterday_values: List[Optional[float]] = [
            yesterday_hours.get(h) for h in range(24)
        ]
        missing_y = sum(1 for v in yesterday_values if v is None)
        if missing_y > MAX_MISSING_HOURS_PER_DAY:
            return None

        y_available = [v for v in yesterday_values if v is not None]
        if not y_available:
            return None
        y_avg = float(np.mean(y_available))
        y_filled, _ = self._fill_missing_values(
            yesterday_values, hour_medians, y_avg, global_median, hour_offset=0
        )
        match.extend(y_filled)

        if current_hour == 0:
            return match

        today_hours = day_map.get(today)
        if not today_hours:
            return None

        today_values: List[Optional[float]] = [
            today_hours.get(h) for h in range(current_hour)
        ]
        if not today_values:
            return match

        missing_t = sum(1 for v in today_values if v is None)
        if missing_t > MAX_MISSING_HOURS_PER_DAY:
            return None

        t_available = [v for v in today_values if v is not None]
        if not t_available:
            return None
        t_avg = float(np.mean(t_available))
        t_filled, _ = self._fill_missing_values(
            today_values, hour_medians, t_avg, global_median, hour_offset=0
        )
        match.extend(t_filled)

        return match

    def _apply_floor_to_prediction(
        self,
        predicted: List[float],
        start_hour: int,
        hour_medians: Dict[int, float],
        recent_match: List[float],
    ) -> Tuple[List[float], int]:
        """Aplikovat minimální floor podle historické spotřeby."""
        if not predicted:
            return predicted, 0

        recent_window = recent_match[-24:] if recent_match else []
        recent_avg = float(np.mean(recent_window)) if recent_window else 0.0

        applied = 0
        for idx, value in enumerate(predicted):
            hour = (start_hour + idx) % 24
            base = hour_medians.get(hour, recent_avg)
            floor = base * FLOOR_RATIO if base else 0.0
            if floor > 0 and value < floor:
                predicted[idx] = floor
                applied += 1

        return predicted, applied

    def _calculate_profile_similarity(
        self, current_data: List[float], profile_data: List[float]
    ) -> float:
        """
        Spočítat similarity score mezi aktuálními daty a historickým profilem.

        Scoring:
        - 50% correlation coefficient (Pearsonův korelační koeficient)
        - 30% RMSE (root mean square error - inverted)
        - 20% total consumption difference (inverted)

        Args:
            current_data: Aktuální spotřeba (plovoucí počet hodin)
            profile_data: Historický profil (stejný počet hodin)

        Returns:
            Similarity score 0.0 - 1.0 (1.0 = perfektní match)
        """
        if len(current_data) != len(profile_data):
            _LOGGER.warning(
                f"Invalid data length for similarity: {len(current_data)} != {len(profile_data)}"
            )
            return 0.0

        try:
            # Convert to numpy arrays
            current = np.array(current_data)
            profile = np.array(profile_data)

            # 1. Correlation coefficient (50%)
            correlation = np.corrcoef(current, profile)[0, 1]
            # Normalize to 0-1 (correlation je -1 až 1, chceme jen pozitivní podobnost)
            correlation_score = max(0.0, correlation)

            # 2. RMSE (30%) - lower is better, normalize to 0-1
            rmse = np.sqrt(np.mean((current - profile) ** 2))
            # Normalize: exponenciální decay, RMSE=0 → score=1, RMSE roste → score klesá
            max_reasonable_rmse = 5.0  # kWh
            rmse_score = np.exp(-rmse / max_reasonable_rmse)

            # 3. Total consumption difference (20%) - lower is better
            total_current = np.sum(current)
            total_profile = np.sum(profile)
            if total_profile > 0:
                total_diff = abs(total_current - total_profile) / total_profile
            else:
                total_diff = 1.0 if total_current > 0 else 0.0

            # Normalize: 0% diff → score=1, 100%+ diff → score≈0
            total_score = np.exp(-total_diff)

            # Weighted sum
            similarity = (
                WEIGHT_CORRELATION * correlation_score
                + WEIGHT_RMSE * rmse_score
                + WEIGHT_TOTAL * total_score
            )

            return float(similarity)

        except Exception as e:
            _LOGGER.error(f"Failed to calculate similarity: {e}", exc_info=True)
            return 0.0

    async def _find_best_matching_profile(
        self, current_consumption_sensor: str, fallback_sensor: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Najít matching profil s preferencí energy senzoru."""
        prediction = await self._find_best_matching_profile_for_sensor(
            current_consumption_sensor, value_field="sum"
        )
        if prediction or not fallback_sensor:
            return prediction

        _LOGGER.info(
            "Energy profiling unavailable for %s, falling back to %s",
            current_consumption_sensor,
            fallback_sensor,
        )
        return await self._find_best_matching_profile_for_sensor(
            fallback_sensor, value_field="mean"
        )

    async def _find_best_matching_profile_for_sensor(
        self,
        sensor_entity_id: str,
        *,
        value_field: str,
        days_back: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Najít nejlepší matching 72h profil pro aktuální spotřebu.

        Plovoucí okno:
        - Před půlnocí (např. 20:00): matching 44h zpět, predikce 28h dopředu
        - Po půlnoci (např. 01:00): matching 24h zpět, predikce 48h dopředu
        - Vždy celkem 72h
        """
        if not self._hass:
            return None

        try:
            self._last_profile_reason = None
            now = dt_util.now()
            current_hour = now.hour
            match_hours = current_hour + 24 if current_hour > 0 else 24
            predict_hours = PROFILE_HOURS - match_hours

            _LOGGER.debug(
                "Profiling window: time=%02d:00, matching=%sh, prediction=%sh",
                current_hour,
                match_hours,
                predict_hours,
            )

            end_time = now
            history_label = "all"
            start_time = None
            if days_back is None:
                start_time = await self._get_earliest_statistics_start(sensor_entity_id)
                if not start_time:
                    days_back = DEFAULT_DAYS_BACK
                    history_label = f"{days_back}d (fallback)"
            if start_time is None:
                days_back = days_back or DEFAULT_DAYS_BACK
                history_label = f"{days_back}d"
                start_day = (end_time - timedelta(days=days_back)).date()
                start_time = dt_util.as_local(
                    datetime.combine(start_day, datetime.min.time())
                )

            _LOGGER.debug(
                "Profiling history window: %s → %s (%s)",
                start_time.date().isoformat(),
                end_time.date().isoformat(),
                history_label,
            )
            hourly_series = await self._load_hourly_series(
                sensor_entity_id,
                start_time,
                end_time,
                value_field=value_field,
            )

            if not hourly_series:
                self._last_profile_reason = "no_hourly_stats"
                _LOGGER.debug("No hourly statistics data for %s", sensor_entity_id)
                return None

            daily_profiles, hour_medians, interpolated = self._build_daily_profiles(
                hourly_series
            )

            if len(daily_profiles) < 3:
                self._last_profile_reason = (
                    f"not_enough_daily_profiles_{len(daily_profiles)}"
                )
                _LOGGER.debug(
                    "Not enough daily profiles (need >=3, got %s)",
                    len(daily_profiles),
                )
                return None

            if interpolated:
                _LOGGER.debug(
                    "Daily profiles: %s days, interpolated %s hours",
                    len(daily_profiles),
                    sum(interpolated.values()),
                )

            current_match = self._build_current_match(hourly_series, hour_medians)
            if not current_match or len(current_match) < match_hours:
                current_len = len(current_match) if current_match else 0
                self._last_profile_reason = f"not_enough_current_data_{current_len}"
                _LOGGER.debug(
                    "Not enough current data for matching (need %s, got %s)",
                    match_hours,
                    current_len,
                )
                return None

            profiles = self._build_72h_profiles(daily_profiles)
            if not profiles:
                self._last_profile_reason = "no_historical_profiles"
                _LOGGER.debug("No historical 72h profiles available for matching")
                return None

            scored_profiles: List[Tuple[float, Dict[str, Any]]] = []
            for profile in profiles:
                profile_data = profile.get("consumption_kwh", [])
                if len(profile_data) != PROFILE_HOURS:
                    continue
                profile_match = profile_data[:match_hours]
                score = self._calculate_profile_similarity(current_match, profile_match)
                scored_profiles.append((score, profile))

            if not scored_profiles:
                self._last_profile_reason = "no_matching_profiles"
                _LOGGER.debug("No matching profile found")
                return None

            scored_profiles.sort(key=lambda item: item[0], reverse=True)
            sample_count = min(TOP_MATCHES, len(scored_profiles))
            selected = scored_profiles[:sample_count]

            avg_score = float(np.mean([s for s, _ in selected])) if selected else 0.0

            avg_profile_full: List[float] = []
            for idx in range(PROFILE_HOURS):
                values = [p["consumption_kwh"][idx] for _, p in selected]
                avg_profile_full.append(float(np.mean(values)))

            predicted = avg_profile_full[match_hours : match_hours + predict_hours]
            predicted, floor_applied = self._apply_floor_to_prediction(
                predicted, current_hour, hour_medians, current_match
            )

            result = {
                "similarity_score": avg_score,
                "predicted_consumption": predicted,
                "predicted_total_kwh": float(np.sum(predicted)),
                "predicted_avg_kwh": float(np.mean(predicted)) if predicted else 0.0,
                "matched_profile_total": float(np.sum(avg_profile_full)),
                "matched_profile_full": avg_profile_full,
                "match_hours": match_hours,
                "predict_hours": predict_hours,
                "sample_count": sample_count,
                "matched_profile_sources": [p.get("start_date") for _, p in selected],
                "floor_applied": floor_applied,
                "data_source": sensor_entity_id,
                "interpolated_hours": sum(interpolated.values()) if interpolated else 0,
            }

            _LOGGER.info(
                "🎯 Profile match: score=%.3f, samples=%s, predicted_%sh=%.2f kWh",
                avg_score,
                sample_count,
                predict_hours,
                result["predicted_total_kwh"],
            )

            return result

        except Exception as e:
            _LOGGER.error(f"Failed to find matching profile: {e}", exc_info=True)
            self._last_profile_reason = "error"
            return None

    @property
    def native_value(self) -> Optional[str]:
        """Return profiling status."""
        if self._current_prediction:
            total = self._current_prediction.get("predicted_total_kwh", 0)
            return f"{total:.1f} kWh"
        return "no_data"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return attributes."""
        attrs = {
            "profiling_status": self._profiling_status,
            "profiling_error": self._profiling_error,
            "profiling_reason": self._last_profile_reason,
            "last_profile_created": (
                self._last_profile_created.isoformat()
                if self._last_profile_created
                else None
            ),
        }

        # Add prediction summary if available
        if self._current_prediction:
            attrs["prediction_summary"] = {
                "similarity_score": self._current_prediction.get("similarity_score"),
                "predicted_total_kwh": self._current_prediction.get(
                    "predicted_total_kwh"
                ),
                "predicted_avg_kwh": self._current_prediction.get("predicted_avg_kwh"),
                "sample_count": self._current_prediction.get("sample_count"),
                "match_hours": self._current_prediction.get("match_hours"),
                "data_source": self._current_prediction.get("data_source"),
                "floor_applied": self._current_prediction.get("floor_applied"),
                "interpolated_hours": self._current_prediction.get(
                    "interpolated_hours"
                ),
            }

            # Add today_profile and tomorrow_profile for battery_forecast integration
            predicted = self._current_prediction.get("predicted_consumption", [])
            predict_hours = self._current_prediction.get("predict_hours", 0)

            if predicted and predict_hours > 0:
                similarity_score = self._current_prediction.get("similarity_score", 0)
                sample_count = self._current_prediction.get("sample_count", 1)
                now = dt_util.now()
                current_hour = now.hour

                # Kolik hodin zbývá do půlnoci (včetně aktuální hodiny)
                hours_until_midnight = 24 - current_hour

                # TODAY: Zbývající část dneška (od current_hour do půlnoci)
                # - Vezmi prvních min(hours_until_midnight, predict_hours) hodin z predikce
                today_count = min(hours_until_midnight, predict_hours)
                today_hours = predicted[:today_count]

                # TOMORROW: Zbytek predikce (od půlnoci)
                tomorrow_hours = (
                    predicted[today_count:] if today_count < predict_hours else []
                )

                # Doplnění tomorrow na 24h pokud je kratší (padding s průměrem)
                if len(tomorrow_hours) < 24:
                    avg_hour = (
                        float(np.mean(tomorrow_hours))
                        if len(tomorrow_hours) > 0
                        else 0.5
                    )
                    tomorrow_hours = list(tomorrow_hours) + [avg_hour] * (
                        24 - len(tomorrow_hours)
                    )

                # Vytvoř metadata
                season = _get_season(now)
                is_weekend_today = now.weekday() >= 5
                is_weekend_tomorrow = (now.weekday() + 1) % 7 >= 5

                # Vygenerovat názvy z matched profilu (72h)
                # Pro dnešek: použít zbytek dnešního dne z matched profilu
                # Pro zítřek: použít celý zítřejší den z matched profilu
                matched_profile_full = self._current_prediction.get(
                    "matched_profile_full", []
                )
                today_full: List[float] = []
                name_suffix = (
                    f" ({sample_count} podobných dnů, shoda {similarity_score:.2f})"
                    if sample_count > 1
                    else f" (shoda {similarity_score:.2f})"
                )

                if len(matched_profile_full) >= 72:
                    # Matched profil: [včera 24h | dnes 24h | zítra 24h]
                    today_full = matched_profile_full[24:48]
                    tomorrow_from_matched = matched_profile_full[48:72]

                    # Pro dnešek: vezmi aktuální hodinu až konec dne z matched profilu
                    today_from_matched = today_full[current_hour:]
                else:
                    # Fallback pokud matched profil není dostupný
                    tomorrow_from_matched = tomorrow_hours[:24]
                    today_from_matched = today_hours

                # Generovat názvy z odpovídajících částí matched profilu
                today_name_source = (
                    today_full
                    if len(matched_profile_full) >= 72 and len(today_full) == 24
                    else (
                        today_from_matched
                        if len(today_from_matched) == 24
                        else (
                            today_from_matched + [0.0] * (24 - len(today_from_matched))
                        )
                    )
                )

                today_profile_name = _generate_profile_name(
                    hourly_consumption=today_name_source,
                    season=season,
                    is_weekend=is_weekend_today,
                )
                today_profile_name = f"{today_profile_name}{name_suffix}"

                tomorrow_profile_name = _generate_profile_name(
                    hourly_consumption=tomorrow_from_matched,
                    season=season,
                    is_weekend=is_weekend_tomorrow,
                )
                tomorrow_profile_name = f"{tomorrow_profile_name}{name_suffix}"

                today_profile_data = {
                    "hourly_consumption": today_hours,
                    "start_hour": current_hour,  # Hodina od které začíná pole (14 = index 0 je 14:00)
                    "total_kwh": float(np.sum(today_hours)),
                    "avg_kwh_h": (
                        float(np.mean(today_hours)) if len(today_hours) > 0 else 0.0
                    ),
                    "season": season,
                    "day_count": sample_count,
                    "ui": {
                        "name": today_profile_name,
                        "similarity_score": similarity_score,
                        "sample_count": sample_count,
                    },
                    "characteristics": {
                        "season": season,
                        "is_weekend": is_weekend_today,
                    },
                    "sample_count": sample_count,
                }

                # TOMORROW profile (název už vygenerovaný nahoře)
                tomorrow_profile_data = {
                    "hourly_consumption": tomorrow_hours[:24],
                    "start_hour": 0,  # Zítřek vždy začíná od půlnoci (0:00)
                    "total_kwh": float(np.sum(tomorrow_hours[:24])),
                    "avg_kwh_h": float(np.mean(tomorrow_hours[:24])),
                    "season": season,
                    "day_count": sample_count,
                    "ui": {
                        "name": tomorrow_profile_name,
                        "similarity_score": similarity_score,
                        "sample_count": sample_count,
                    },
                    "characteristics": {
                        "season": season,
                        "is_weekend": is_weekend_tomorrow,
                    },
                    "sample_count": sample_count,
                }

                attrs["today_profile"] = today_profile_data
                attrs["tomorrow_profile"] = tomorrow_profile_data
                attrs["profile_name"] = today_profile_name
                attrs["match_score"] = round(similarity_score * 100, 1)
                attrs["sample_count"] = sample_count

        return attrs

    def get_current_prediction(self) -> Optional[Dict[str, Any]]:
        """Get current consumption prediction for use by other components."""
        return self._current_prediction

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device info."""
        return self._device_info
