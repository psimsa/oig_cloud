"""Baseline helpers for battery forecast plans."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from ..data import history as history_module
from .plan_storage_io import plan_exists_in_storage, save_plan_to_storage

DATE_FMT = "%Y-%m-%d"

_LOGGER = logging.getLogger(__name__)


def is_baseline_plan_invalid(plan: Optional[Dict[str, Any]]) -> bool:
    """Validate baseline plan."""
    if not plan:
        return True

    intervals = plan.get("intervals") or []
    if len(intervals) < 90:
        return True

    filled_intervals = str(plan.get("filled_intervals") or "").strip()
    if filled_intervals in ("00:00-23:45", "00:00-23:59"):
        return True

    nonzero_consumption = sum(
        1
        for interval in intervals
        if abs(float(interval.get("consumption_kwh", 0) or 0)) > 1e-6
    )
    if nonzero_consumption < max(4, len(intervals) // 24):
        return True

    return False


async def create_baseline_plan(sensor: Any, date_str: str) -> bool:  # noqa: C901
    """Create baseline plan for a given date."""
    if not sensor._plans_store:
        _LOGGER.error("Cannot create baseline - Storage Helper not initialized")
        return False

    _LOGGER.info("Creating baseline plan for %s", date_str)

    try:
        hybrid_timeline = getattr(sensor, "_timeline_data", [])

        if not hybrid_timeline:
            fallback_intervals: List[Dict[str, Any]] = []

            if sensor._plans_store:
                try:
                    storage_plans = await sensor._plans_store.async_load() or {}
                    archive_day = (
                        storage_plans.get("daily_archive", {}).get(date_str, {}) or {}
                    )
                    if archive_day.get("plan"):
                        fallback_intervals = archive_day.get("plan") or []
                    if not fallback_intervals:
                        detailed_day = storage_plans.get("detailed", {}).get(
                            date_str, {}
                        )
                        if detailed_day.get("intervals"):
                            fallback_intervals = detailed_day.get("intervals") or []
                except Exception as err:
                    _LOGGER.debug(
                        "Failed to load fallback plans for %s: %s",
                        date_str,
                        err,
                    )

            if (
                not fallback_intervals
                and getattr(sensor, "_daily_plan_state", None)
                and sensor._daily_plan_state.get("date") == date_str
            ):
                fallback_intervals = sensor._daily_plan_state.get("plan") or []

            if fallback_intervals:
                fallback_plan = {
                    "intervals": fallback_intervals,
                    "filled_intervals": None,
                }
                if not is_baseline_plan_invalid(fallback_plan):
                    _LOGGER.info(
                        "Using fallback plan to create baseline for %s",
                        date_str,
                    )
                    return await save_plan_to_storage(
                        sensor,
                        date_str,
                        fallback_intervals,
                        {"baseline": True, "filled_intervals": None},
                    )

            _LOGGER.warning(
                "No HYBRID timeline available - cannot create baseline plan"
            )
            return False

        _LOGGER.debug("Using HYBRID timeline with %s intervals", len(hybrid_timeline))

        date_obj = datetime.strptime(date_str, DATE_FMT).date()
        day_start = datetime.combine(date_obj, datetime.min.time())
        day_start = dt_util.as_local(day_start)

        intervals = []
        filled_count = 0
        first_hybrid_time = None

        for i in range(96):
            interval_start = day_start + timedelta(minutes=i * 15)
            interval_time_str = interval_start.strftime("%H:%M")

            hybrid_interval = None
            for hi in hybrid_timeline:
                hi_time_str = hi.get("time") or hi.get("timestamp", "")
                if not hi_time_str:
                    continue
                try:
                    if "T" in hi_time_str:
                        hi_dt = datetime.fromisoformat(hi_time_str)
                        if hi_dt.tzinfo is None:
                            hi_dt = dt_util.as_local(hi_dt)
                        hi_time_only = hi_dt.strftime("%H:%M")
                    else:
                        hi_time_only = hi_time_str

                    if hi_time_only == interval_time_str:
                        hybrid_interval = hi
                        if first_hybrid_time is None:
                            first_hybrid_time = interval_time_str
                        break
                except Exception:  # nosec B112
                    continue

            if hybrid_interval:
                interval = {
                    "time": interval_time_str,
                    "solar_kwh": round(hybrid_interval.get("solar_kwh", 0), 4),
                    "consumption_kwh": round(hybrid_interval.get("load_kwh", 0), 4),
                    "battery_soc": round(hybrid_interval.get("battery_soc", 50.0), 2),
                    "battery_kwh": round(
                        hybrid_interval.get("battery_capacity_kwh", 7.68), 2
                    ),
                    "grid_import_kwh": round(hybrid_interval.get("grid_import", 0), 4),
                    "grid_export_kwh": round(hybrid_interval.get("grid_export", 0), 4),
                    "mode": hybrid_interval.get("mode", 2),
                    "mode_name": hybrid_interval.get("mode_name", "HOME III"),
                    "spot_price": round(hybrid_interval.get("spot_price", 3.45), 2),
                    "net_cost": round(hybrid_interval.get("net_cost", 0), 2),
                }
            else:
                interval_end = interval_start + timedelta(minutes=15)
                historical_data = await history_module.fetch_interval_from_history(
                    sensor, interval_start, interval_end
                )

                if historical_data:
                    interval = {
                        "time": interval_time_str,
                        "solar_kwh": round(historical_data.get("solar_kwh", 0), 4),
                        "consumption_kwh": round(
                            historical_data.get("consumption_kwh", 0.065), 4
                        ),
                        "battery_soc": round(
                            historical_data.get("battery_soc", 50.0), 2
                        ),
                        "battery_kwh": round(
                            historical_data.get("battery_kwh", 7.68), 2
                        ),
                        "grid_import_kwh": round(
                            historical_data.get("grid_import_kwh", 0), 4
                        ),
                        "grid_export_kwh": round(
                            historical_data.get("grid_export_kwh", 0), 4
                        ),
                        "mode": historical_data.get("mode", 2),
                        "mode_name": historical_data.get("mode_name", "HOME III"),
                        "spot_price": round(historical_data.get("spot_price", 3.45), 2),
                        "net_cost": round(historical_data.get("net_cost", 0), 2),
                    }
                    filled_count += 1
                else:
                    first_soc = 50.0
                    first_mode = 2
                    first_mode_name = "HOME III"

                    if hybrid_timeline:
                        first_hi = hybrid_timeline[0]
                        first_soc = first_hi.get("battery_soc", 50.0)
                        first_mode = first_hi.get("mode", 2)
                        first_mode_name = first_hi.get("mode_name", "HOME III")

                    interval = {
                        "time": interval_time_str,
                        "solar_kwh": 0.0,
                        "consumption_kwh": 0.065,
                        "battery_soc": round(first_soc, 2),
                        "battery_kwh": round((first_soc / 100.0) * 15.36, 2),
                        "grid_import_kwh": 0.065,
                        "grid_export_kwh": 0.0,
                        "mode": first_mode,
                        "mode_name": first_mode_name,
                        "spot_price": 3.45,
                        "net_cost": 0.22,
                    }
                    filled_count += 1

            intervals.append(interval)

        filled_intervals_str = None
        if filled_count > 0 and first_hybrid_time:
            filled_intervals_str = f"00:00-{first_hybrid_time}"

        _LOGGER.info(
            "Baseline plan built: %s intervals, %s from HYBRID, %s filled",
            len(intervals),
            len(intervals) - filled_count,
            filled_count,
        )

        success = await save_plan_to_storage(
            sensor,
            date_str,
            intervals,
            {"baseline": True, "filled_intervals": filled_intervals_str},
        )

        if success:
            _LOGGER.info(
                "Baseline plan created: date=%s, intervals=%s, filled=%s",
                date_str,
                len(intervals),
                filled_intervals_str,
            )
        else:
            _LOGGER.error("Failed to save baseline plan for %s", date_str)

        return success

    except Exception as err:
        _LOGGER.error(
            "Error creating baseline plan for %s: %s",
            date_str,
            err,
            exc_info=True,
        )
        return False


async def ensure_plan_exists(sensor: Any, date_str: str) -> bool:
    """Guarantee plan existence for a date, creating it if needed."""
    exists = await plan_exists_in_storage(sensor, date_str)
    if exists:
        _LOGGER.debug("Plan exists for %s", date_str)
        return True

    _LOGGER.warning("Plan missing for %s, attempting to create...", date_str)

    now = dt_util.now()
    today_str = now.strftime(DATE_FMT)

    if date_str != today_str:
        _LOGGER.warning("Cannot create plan for %s (not today %s)", date_str, today_str)
        return False

    current_hour = now.hour
    current_minute = now.minute

    if current_hour == 0 and 10 <= current_minute < 60:
        _LOGGER.info("Midnight baseline window - creating plan for %s", date_str)
        return await create_baseline_plan(sensor, date_str)

    if (current_hour == 6 and current_minute < 10) or (
        current_hour == 12 and current_minute < 10
    ):
        _LOGGER.info(
            "Retry window (%02d:%02d) - creating plan for %s",
            current_hour,
            current_minute,
            date_str,
        )
        return await create_baseline_plan(sensor, date_str)

    _LOGGER.warning(
        "Emergency baseline creation at %s for %s",
        now.strftime("%H:%M"),
        date_str,
    )
    success = await create_baseline_plan(sensor, date_str)

    if success:
        _LOGGER.info("Emergency baseline created for %s", date_str)
    else:
        _LOGGER.error("Failed to create emergency baseline for %s", date_str)

    return success
