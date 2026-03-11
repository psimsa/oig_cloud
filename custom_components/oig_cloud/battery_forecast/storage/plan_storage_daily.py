"""Daily plan helpers for battery forecast plans."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .plan_storage_baseline import create_baseline_plan
from .plan_storage_io import plan_exists_in_storage

DATE_FMT = "%Y-%m-%d"

_LOGGER = logging.getLogger(__name__)


async def maybe_fix_daily_plan(sensor: Any) -> None:  # noqa: C901
    """Fix daily plan state and create baseline after midnight."""
    now = dt_util.now()
    today_str = now.strftime(DATE_FMT)

    if not hasattr(sensor, "_daily_plan_state"):
        sensor._daily_plan_state = None

    if now.hour == 0 and 10 <= now.minute < 60:
        plan_exists = await plan_exists_in_storage(sensor, today_str)
        if not plan_exists:
            _LOGGER.info(
                "Post-midnight baseline creation window: %s",
                now.strftime("%H:%M"),
            )
            baseline_created = await create_baseline_plan(sensor, today_str)
            if baseline_created:
                _LOGGER.info(
                    "Baseline plan created in Storage Helper for %s", today_str
                )
            else:
                _LOGGER.warning("Failed to create baseline plan for %s", today_str)
        else:
            _LOGGER.debug("Baseline plan already exists for %s", today_str)

    if (
        sensor._daily_plan_state
        and sensor._daily_plan_state.get("date") == today_str
        and len(sensor._daily_plan_state.get("plan", [])) > 0
    ):
        _LOGGER.debug(
            "Daily plan for %s already in memory with %s intervals, keeping it",
            today_str,
            len(sensor._daily_plan_state.get("plan", [])),
        )
        return

    if (
        sensor._daily_plan_state is None
        or sensor._daily_plan_state.get("date") != today_str
        or not sensor._daily_plan_state.get("plan", [])
    ):
        if sensor._daily_plan_state:
            yesterday_date = sensor._daily_plan_state.get("date")
            sensor._daily_plans_archive[yesterday_date] = (
                sensor._daily_plan_state.copy()
            )

            cutoff_date = (now.date() - timedelta(days=7)).strftime(DATE_FMT)
            sensor._daily_plans_archive = {
                date: plan
                for date, plan in sensor._daily_plans_archive.items()
                if date >= cutoff_date
            }

            _LOGGER.info(
                "Archived daily plan for %s (archive size: %s days)",
                yesterday_date,
                len(sensor._daily_plans_archive),
            )

            if sensor._plans_store:
                try:
                    storage_data = await sensor._plans_store.async_load() or {}
                    storage_data["daily_archive"] = sensor._daily_plans_archive
                    await sensor._plans_store.async_save(storage_data)
                    _LOGGER.info(
                        "Saved daily plans archive to storage (%s days)",
                        len(sensor._daily_plans_archive),
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Failed to save daily plans archive: %s",
                        err,
                        exc_info=True,
                    )

        if (
            hasattr(sensor, "_mode_optimization_result")
            and sensor._mode_optimization_result
        ):
            optimal_timeline = getattr(sensor, "_timeline_data", [])
            if not optimal_timeline:
                optimal_timeline = sensor._mode_optimization_result.get(
                    "optimal_timeline", []
                )

            mode_recommendations = sensor._mode_optimization_result.get(
                "mode_recommendations", []
            )

            today_start = datetime.combine(now.date(), datetime.min.time())
            today_start = dt_util.as_local(today_start)
            today_end = datetime.combine(now.date(), datetime.max.time())
            today_end = dt_util.as_local(today_end)

            today_timeline = []
            for interval in optimal_timeline:
                if not interval.get("time"):
                    continue
                try:
                    interval_time = datetime.fromisoformat(interval["time"])
                    if interval_time.tzinfo is None:
                        interval_time = dt_util.as_local(interval_time)
                    if today_start <= interval_time <= today_end:
                        today_timeline.append(interval)
                except Exception:  # nosec B112
                    continue

            today_blocks = []
            for block in mode_recommendations:
                if not block.get("from_time"):
                    continue
                try:
                    block_time = datetime.fromisoformat(block["from_time"])
                    if block_time.tzinfo is None:
                        block_time = dt_util.as_local(block_time)
                    if today_start <= block_time <= today_end:
                        today_blocks.append(block)
                except Exception:  # nosec B112
                    continue

            expected_total_cost = sum(i.get("net_cost", 0) for i in today_timeline)

            plan_intervals = []
            for interval in today_timeline:
                plan_intervals.append(
                    {
                        "time": interval.get("timestamp"),
                        "solar_kwh": round(interval.get("solar_kwh", 0), 4),
                        "consumption_kwh": round(interval.get("load_kwh", 0), 4),
                        "battery_soc": round(interval.get("battery_soc", 0), 2),
                        "battery_capacity_kwh": round(
                            interval.get("battery_capacity_kwh", 0), 2
                        ),
                        "grid_import_kwh": round(interval.get("grid_import", 0), 4),
                        "grid_export_kwh": round(interval.get("grid_export", 0), 4),
                        "mode": interval.get("mode", 0),
                        "mode_name": interval.get("mode_name", "N/A"),
                        "spot_price": round(interval.get("spot_price", 0), 2),
                        "net_cost": round(interval.get("net_cost", 0), 2),
                    }
                )

            existing_actual = []
            if (
                hasattr(sensor, "_daily_plan_state")
                and sensor._daily_plan_state
                and sensor._daily_plan_state.get("date") == today_str
            ):
                existing_actual = sensor._daily_plan_state.get("actual", [])
                _LOGGER.debug(
                    "[Fix Plan] Preserving %s existing actual intervals",
                    len(existing_actual),
                )

            sensor._daily_plan_state = {
                "date": today_str,
                "created_at": now.isoformat(),
                "plan": plan_intervals,
                "actual": existing_actual,
            }

            _LOGGER.info(
                "Fixed daily plan for %s: %s plan intervals, %s existing actual, "
                "expected_cost=%.2f CZK",
                today_str,
                len(plan_intervals),
                len(existing_actual),
                expected_total_cost,
            )
        else:
            _LOGGER.warning(
                "No HYBRID optimization result available to fix daily plan for %s",
                today_str,
            )
            sensor._daily_plan_state = {
                "date": today_str,
                "created_at": now.isoformat(),
                "plan": [],
                "actual": [],
            }
