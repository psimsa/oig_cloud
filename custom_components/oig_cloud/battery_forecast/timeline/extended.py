"""Extended timeline builders extracted from legacy battery forecast."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from ..data import history as history_module
from .extended_summary import (
    build_today_tile_summary,
    calculate_day_summary,
    format_planned_data,
)

_LOGGER = logging.getLogger(__name__)

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"


async def build_timeline_extended(
    sensor: Any, *, mode_names: Optional[Dict[int, str]] = None
) -> Dict[str, Any]:
    """Build extended timeline structure for API."""
    self = sensor
    mode_names = mode_names or {}

    now = dt_util.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    storage_plans = {}
    if self._plans_store:
        try:
            storage_plans = await self._plans_store.async_load() or {}
            _LOGGER.debug(
                "📦 Loaded Storage Helper data for timeline building: %s days",
                len(storage_plans.get("detailed", {})),
            )
        except Exception as e:
            _LOGGER.error("Failed to load Storage Helper data: %s", e)
            storage_plans = {}

    yesterday_data = await build_day_timeline(
        self, yesterday, storage_plans, mode_names=mode_names
    )
    today_data = await build_day_timeline(
        self, today, storage_plans, mode_names=mode_names
    )
    tomorrow_data = await build_day_timeline(
        self, tomorrow, storage_plans, mode_names=mode_names
    )

    today_tile_summary = build_today_tile_summary(
        self, today_data.get("intervals", []), now
    )

    return {
        "yesterday": yesterday_data,
        "today": today_data,
        "tomorrow": tomorrow_data,
        "today_tile_summary": today_tile_summary,
    }


async def build_day_timeline(  # noqa: C901
    sensor: Any,
    day: date,
    storage_plans: Optional[Dict[str, Any]] = None,
    *,
    mode_names: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Build timeline for a single day."""
    self = sensor
    mode_names = mode_names or {}

    now = dt_util.now()
    today = now.date()

    day_start = dt_util.as_local(datetime.combine(day, datetime.min.time()))
    day_end = dt_util.as_local(datetime.combine(day, datetime.max.time()))

    intervals: List[Dict[str, Any]] = []
    date_str = day.strftime(DATE_FMT)

    if day < today:
        source = "historical_only"
    elif day == today:
        source = "mixed"
    else:
        source = "planned_only"

    historical_modes_lookup = {}
    if source in ["historical_only", "mixed"] and self._hass:
        try:
            fetch_end = day_end if source == "historical_only" else now
            historical_modes_lookup = (
                await history_module.build_historical_modes_lookup(
                    self,
                    day_start=day_start,
                    fetch_end=fetch_end,
                    date_str=date_str,
                    source=source,
                )
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to fetch historical modes from Recorder for %s: %s",
                date_str,
                e,
            )
            historical_modes_lookup = {}

    if source == "historical_only":
        planned_intervals_map: Dict[str, Dict[str, Any]] = {}
        if storage_plans:
            planned_intervals_list: List[Dict[str, Any]] = []
            yesterday_plan = storage_plans.get("detailed", {}).get(date_str, {})
            if yesterday_plan and not self._is_baseline_plan_invalid(yesterday_plan):
                planned_intervals_list = yesterday_plan.get("intervals", [])
            else:
                archive_day = storage_plans.get("daily_archive", {}).get(date_str, {})
                if archive_day and archive_day.get("plan"):
                    planned_intervals_list = archive_day.get("plan", [])
                    archive_plan = {
                        "intervals": planned_intervals_list,
                        "filled_intervals": None,
                    }
                    if self._plans_store and not self._is_baseline_plan_invalid(
                        archive_plan
                    ):
                        try:
                            await self._save_plan_to_storage(
                                date_str,
                                planned_intervals_list,
                                {"baseline": True, "filled_intervals": None},
                            )
                            _LOGGER.info(
                                "Rebuilt baseline plan for %s from daily archive",
                                date_str,
                            )
                        except Exception as err:
                            _LOGGER.debug(
                                "Failed to persist archive baseline for %s: %s",
                                date_str,
                                err,
                            )
                    else:
                        _LOGGER.info(
                            "Using daily archive plan for %s (baseline invalid)",
                            date_str,
                        )
                else:
                    planned_intervals_list = yesterday_plan.get("intervals", [])

            for planned_entry in planned_intervals_list:
                time_key = planned_entry.get("time", "")
                if time_key:
                    try:
                        if "T" in time_key:
                            planned_dt = datetime.fromisoformat(
                                time_key.replace("Z", "+00:00")
                            )
                        else:
                            planned_dt = datetime.combine(
                                day, datetime.strptime(time_key, "%H:%M").time()
                            )
                        planned_dt = dt_util.as_local(planned_dt)
                        time_str = planned_dt.strftime(DATETIME_FMT)
                        planned_intervals_map[time_str] = planned_entry
                    except Exception:  # nosec B112
                        continue

            _LOGGER.debug(
                "📊 Loaded %s planned intervals from Storage for %s",
                len(planned_intervals_map),
                date_str,
            )

        interval_time = day_start
        while interval_time.date() == day:
            interval_time_str = interval_time.strftime(DATETIME_FMT)

            mode_from_recorder = historical_modes_lookup.get(interval_time_str)
            planned_from_storage = planned_intervals_map.get(interval_time_str, {})

            actual_data = {}
            if mode_from_recorder:
                interval_end = interval_time + timedelta(minutes=15)
                historical_metrics = await history_module.fetch_interval_from_history(
                    self, interval_time, interval_end
                )

                if historical_metrics:
                    actual_data = {
                        "mode": mode_from_recorder.get("mode", 0),
                        "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                        "consumption_kwh": historical_metrics.get("consumption_kwh", 0),
                        "solar_kwh": historical_metrics.get("solar_kwh", 0),
                        "battery_soc": historical_metrics.get("battery_soc", 0),
                        "battery_kwh": historical_metrics.get("battery_kwh", 0),
                        "grid_import_kwh": historical_metrics.get("grid_import", 0),
                        "grid_export_kwh": historical_metrics.get("grid_export", 0),
                        "net_cost": historical_metrics.get("net_cost", 0),
                        "savings": 0,
                    }
                else:
                    actual_data = {
                        "mode": mode_from_recorder.get("mode", 0),
                        "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                        "consumption_kwh": 0,
                        "solar_kwh": 0,
                        "battery_soc": 0,
                        "battery_kwh": 0,
                        "grid_import_kwh": 0,
                        "grid_export_kwh": 0,
                        "net_cost": 0,
                        "savings": 0,
                    }

            planned_data = {}
            if planned_from_storage:
                planned_data = {
                    "mode": planned_from_storage.get("mode", 0),
                    "mode_name": planned_from_storage.get("mode_name", "Unknown"),
                    "consumption_kwh": planned_from_storage.get("consumption_kwh", 0),
                    "solar_kwh": planned_from_storage.get("solar_kwh", 0),
                    "battery_soc": planned_from_storage.get("battery_soc", 0),
                    "net_cost": planned_from_storage.get("net_cost", 0),
                }

            mode_match = None
            if actual_data and planned_data:
                actual_mode = actual_data.get("mode")
                planned_mode = planned_data.get("mode")
                mode_match = actual_mode == planned_mode

            intervals.append(
                {
                    "time": interval_time_str,
                    "status": "historical",
                    "planned": planned_data,
                    "actual": actual_data,
                    "delta": None,
                    "mode_match": mode_match,
                }
            )

            interval_time += timedelta(minutes=15)

    elif source == "mixed":
        past_planned = []

        storage_day = storage_plans.get("detailed", {}).get(date_str)
        storage_invalid = (
            self._is_baseline_plan_invalid(storage_day) if storage_day else True
        )
        storage_missing = not storage_day or not storage_day.get("intervals")
        if (
            self._plans_store
            and (storage_missing or storage_invalid)
            and date_str not in self._baseline_repair_attempts
        ):
            self._baseline_repair_attempts.add(date_str)
            _LOGGER.info(
                "Baseline plan missing/invalid for %s, attempting rebuild",
                date_str,
            )
            try:
                repaired = await self._create_baseline_plan(date_str)
            except Exception as err:
                _LOGGER.error(
                    "Baseline rebuild failed for %s: %s",
                    date_str,
                    err,
                    exc_info=True,
                )
                repaired = False
            if repaired:
                try:
                    storage_plans = await self._plans_store.async_load() or {}
                    storage_day = storage_plans.get("detailed", {}).get(date_str)
                    storage_invalid = (
                        self._is_baseline_plan_invalid(storage_day)
                        if storage_day
                        else True
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Failed to reload baseline plan after rebuild for %s: %s",
                        date_str,
                        err,
                        exc_info=True,
                    )
        if storage_day and storage_day.get("intervals") and not storage_invalid:
            past_planned = storage_day["intervals"]
            _LOGGER.debug(
                "📦 Loaded %s planned intervals from Storage Helper for %s",
                len(past_planned),
                day,
            )
        elif (
            hasattr(self, "_daily_plan_state")
            and self._daily_plan_state
            and self._daily_plan_state.get("date") == date_str
        ):
            plan_intervals = self._daily_plan_state.get("plan", [])
            if plan_intervals:
                past_planned = plan_intervals
                _LOGGER.info(
                    "Using in-memory daily plan for %s (baseline invalid)",
                    date_str,
                )
            else:
                actual_intervals = self._daily_plan_state.get("actual", [])
                for interval in actual_intervals:
                    if interval.get("time"):
                        past_planned.append(interval)
            _LOGGER.debug(
                "📋 Loaded %s intervals from _daily_plan_state for %s",
                len(past_planned),
                day,
            )
        elif storage_day and storage_day.get("intervals"):
            past_planned = storage_day["intervals"]
            _LOGGER.warning(
                "Using baseline plan for %s despite invalid data (no fallback)",
                date_str,
            )
        else:
            _LOGGER.debug("⚠️  No past planned data available for %s", day)

        future_planned = []
        all_timeline = getattr(self, "_timeline_data", [])
        parse_errors = 0
        wrong_date = 0
        for interval in all_timeline:
            time_str = interval.get("time")
            if time_str:
                try:
                    interval_dt = datetime.fromisoformat(
                        time_str.replace("Z", "+00:00")
                    )
                    if interval_dt.date() == day:
                        future_planned.append(interval)
                    else:
                        wrong_date += 1
                except (ValueError, TypeError):
                    parse_errors += 1
                    continue

        _LOGGER.debug(
            "📋 Future filter: %s kept, %s wrong_date, %s parse_errors (from %s total)",
            len(future_planned),
            wrong_date,
            parse_errors,
            len(all_timeline),
        )

        _LOGGER.debug(
            "📋 Planned data sources for %s: past=%s intervals from daily_plan, future=%s intervals from active timeline",
            day,
            len(past_planned),
            len(future_planned),
        )

        current_minute = (now.minute // 15) * 15
        current_interval = now.replace(minute=current_minute, second=0, microsecond=0)
        current_interval_naive = current_interval.replace(tzinfo=None)

        planned_lookup: Dict[str, Dict[str, Any]] = {}

        for planned in past_planned:
            time_str = planned.get("time")
            if time_str:
                try:
                    if "T" not in time_str:
                        time_str = f"{date_str}T{time_str}:00"

                    interval_dt = datetime.fromisoformat(
                        time_str.replace("Z", "+00:00")
                    )
                    interval_dt_naive = (
                        interval_dt.replace(tzinfo=None)
                        if interval_dt.tzinfo
                        else interval_dt
                    )

                    if interval_dt_naive < current_interval_naive:
                        lookup_key = interval_dt.strftime(DATETIME_FMT)
                        planned_lookup[lookup_key] = planned
                except (ValueError, TypeError):
                    _LOGGER.warning("Failed to parse time_str: %s", time_str)
                    continue

        added_future = 0
        skipped_future = 0
        for planned in future_planned:
            time_str = planned.get("time")
            if time_str:
                try:
                    interval_dt = datetime.fromisoformat(time_str)
                    if interval_dt >= current_interval_naive:
                        planned_lookup[time_str] = planned
                        added_future += 1
                    else:
                        skipped_future += 1
                except (ValueError, TypeError) as err:
                    _LOGGER.debug("Failed to parse time: %s, error: %s", time_str, err)
                    continue

        _LOGGER.debug(
            "📋 Merge stats: added_future=%s, skipped_future=%s, current_interval=%s",
            added_future,
            skipped_future,
            current_interval_naive,
        )

        _LOGGER.debug(
            "📋 Combined planned lookup: %s total intervals for %s",
            len(planned_lookup),
            day,
        )

        interval_time = day_start
        while interval_time.date() == day:
            interval_time_str = interval_time.strftime(DATETIME_FMT)

            interval_time_naive = (
                interval_time.replace(tzinfo=None)
                if interval_time.tzinfo
                else interval_time
            )
            if interval_time_naive < current_interval_naive:
                status = "historical"
            elif interval_time_naive == current_interval_naive:
                status = "current"
            else:
                status = "planned"

            planned_entry = planned_lookup.get(interval_time_str)
            planned_data = None
            if planned_entry:
                planned_data = format_planned_data(planned_entry)

            if planned_data is None:
                planned_data = {}

            actual_data = None
            if status in ("historical", "current"):
                mode_from_recorder = historical_modes_lookup.get(interval_time_str)
                if mode_from_recorder:
                    interval_end = interval_time + timedelta(minutes=15)
                    historical_metrics = (
                        await history_module.fetch_interval_from_history(
                            self, interval_time, interval_end
                        )
                    )

                    if historical_metrics:
                        actual_data = {
                            "mode": mode_from_recorder.get("mode", 0),
                            "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                            "consumption_kwh": historical_metrics.get(
                                "consumption_kwh", 0
                            ),
                            "solar_kwh": historical_metrics.get("solar_kwh", 0),
                            "battery_soc": historical_metrics.get("battery_soc", 0),
                            "grid_import_kwh": historical_metrics.get("grid_import", 0),
                            "grid_export_kwh": historical_metrics.get("grid_export", 0),
                            "net_cost": historical_metrics.get("net_cost", 0),
                            "savings": 0,
                        }
                    else:
                        actual_data = {
                            "mode": mode_from_recorder.get("mode", 0),
                            "mode_name": mode_from_recorder.get("mode_name", "Unknown"),
                            "consumption_kwh": 0,
                            "solar_kwh": 0,
                            "battery_soc": 0,
                            "grid_import_kwh": 0,
                            "grid_export_kwh": 0,
                            "net_cost": (
                                planned_data.get("net_cost", 0) if planned_data else 0
                            ),
                            "savings": 0,
                        }

            if status == "current":
                current_mode = self._get_current_mode()
                current_mode_name = mode_names.get(current_mode, "HOME I")
                current_soc = self._get_current_battery_soc_percent()
                current_kwh = self._get_current_battery_capacity()

                if actual_data is None:
                    actual_data = {
                        "consumption_kwh": 0,
                        "solar_kwh": 0,
                        "grid_import_kwh": 0,
                        "grid_export_kwh": 0,
                        "net_cost": 0,
                        "savings": 0,
                    }

                actual_data["mode"] = current_mode
                actual_data["mode_name"] = current_mode_name
                if current_soc is not None:
                    actual_data["battery_soc"] = round(current_soc, 1)
                if current_kwh is not None:
                    actual_data["battery_kwh"] = round(current_kwh, 2)

            if actual_data or planned_data:
                intervals.append(
                    {
                        "time": interval_time_str,
                        "status": status,
                        "planned": planned_data,
                        "actual": actual_data,
                        "delta": None,
                    }
                )

            interval_time += timedelta(minutes=15)

    elif source == "planned_only":
        if (
            hasattr(self, "_mode_optimization_result")
            and self._mode_optimization_result
        ):
            optimal_timeline = self._mode_optimization_result.get(
                "optimal_timeline", []
            )

            for interval in optimal_timeline:
                interval_time_str = interval.get("time", "")
                if not interval_time_str:
                    continue

                try:
                    interval_time = datetime.fromisoformat(interval_time_str)
                    if interval_time.tzinfo is None:
                        interval_time = dt_util.as_local(interval_time)
                except Exception:  # nosec B112
                    continue

                if day_start <= interval_time <= day_end:
                    intervals.append(
                        {
                            "time": interval_time_str,
                            "status": "planned",
                            "planned": format_planned_data(interval),
                            "actual": None,
                            "delta": None,
                        }
                    )

    summary = calculate_day_summary(intervals)

    return {
        "date": day.strftime(DATE_FMT),
        "intervals": intervals,
        "summary": summary,
    }
