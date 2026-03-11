"""Aggregation helpers for battery forecast plans."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .plan_storage_io import load_plan_from_storage
from ..utils_common import safe_nested_get

DATE_FMT = "%Y-%m-%d"

_LOGGER = logging.getLogger(__name__)


async def aggregate_daily(sensor: Any, date_str: str) -> bool:
    """Aggregate daily plan into a summary."""
    if not sensor._plans_store:
        _LOGGER.error("Cannot aggregate - Storage Helper not initialized")
        return False

    _LOGGER.info("Aggregating daily plan for %s", date_str)

    try:
        plan = await load_plan_from_storage(sensor, date_str)
        if not plan:
            _LOGGER.warning(
                "No detailed plan found for %s, skipping aggregation", date_str
            )
            return False

        intervals = plan.get("intervals", [])
        if not intervals:
            _LOGGER.warning("Empty intervals for %s, skipping aggregation", date_str)
            return False

        total_cost = sum(iv.get("net_cost", 0) for iv in intervals)
        total_solar = sum(iv.get("solar_kwh", 0) for iv in intervals)
        total_consumption = sum(iv.get("consumption_kwh", 0) for iv in intervals)
        total_grid_import = sum(iv.get("grid_import_kwh", 0) for iv in intervals)
        total_grid_export = sum(iv.get("grid_export_kwh", 0) for iv in intervals)

        soc_values = [
            iv.get("battery_soc", 0)
            for iv in intervals
            if iv.get("battery_soc") is not None
        ]
        avg_battery_soc = sum(soc_values) / len(soc_values) if soc_values else 0
        min_battery_soc = min(soc_values) if soc_values else 0
        max_battery_soc = max(soc_values) if soc_values else 0

        daily_aggregate = {
            "planned": {
                "total_cost": round(total_cost, 2),
                "total_solar": round(total_solar, 2),
                "total_consumption": round(total_consumption, 2),
                "total_grid_import": round(total_grid_import, 2),
                "total_grid_export": round(total_grid_export, 2),
                "avg_battery_soc": round(avg_battery_soc, 1),
                "min_battery_soc": round(min_battery_soc, 1),
                "max_battery_soc": round(max_battery_soc, 1),
            }
        }

        data = await sensor._plans_store.async_load() or {}
        if "daily" not in data:
            data["daily"] = {}

        data["daily"][date_str] = daily_aggregate
        await sensor._plans_store.async_save(data)

        _LOGGER.info(
            "Daily aggregate saved for %s: cost=%.2f CZK, solar=%.2f kWh, consumption=%.2f kWh",
            date_str,
            total_cost,
            total_solar,
            total_consumption,
        )

        cutoff_date = (
            datetime.strptime(date_str, DATE_FMT).date() - timedelta(days=7)
        ).strftime(DATE_FMT)

        detailed = data.get("detailed", {})
        dates_to_delete = [d for d in detailed.keys() if d < cutoff_date]

        if dates_to_delete:
            for old_date in dates_to_delete:
                del data["detailed"][old_date]
                _LOGGER.debug("Deleted detailed plan for %s (>7 days old)", old_date)

            await sensor._plans_store.async_save(data)
            _LOGGER.info("Cleaned up %s old detailed plans", len(dates_to_delete))

        return True

    except Exception as err:
        _LOGGER.error(
            "Error aggregating daily plan for %s: %s",
            date_str,
            err,
            exc_info=True,
        )
        return False


async def aggregate_weekly(
    sensor: Any, week_str: str, start_date: str, end_date: str
) -> bool:
    """Aggregate weekly plan summary."""
    if not sensor._plans_store:
        _LOGGER.error("Cannot aggregate - Storage Helper not initialized")
        return False

    _LOGGER.info(
        "Aggregating weekly plan for %s (%s to %s)",
        week_str,
        start_date,
        end_date,
    )

    try:
        data = await sensor._plans_store.async_load() or {}
        daily_plans = data.get("daily", {})

        start = datetime.strptime(start_date, DATE_FMT).date()
        end = datetime.strptime(end_date, DATE_FMT).date()

        week_days = []
        current = start
        while current <= end:
            day_str = current.strftime(DATE_FMT)
            if day_str in daily_plans:
                week_days.append(daily_plans[day_str])
            current += timedelta(days=1)

        if not week_days:
            _LOGGER.warning(
                "No daily plans found for %s, skipping aggregation", week_str
            )
            return False

        total_cost = sum(
            safe_nested_get(day, "planned", "total_cost", default=0)
            for day in week_days
        )
        total_solar = sum(
            safe_nested_get(day, "planned", "total_solar", default=0)
            for day in week_days
        )
        total_consumption = sum(
            safe_nested_get(day, "planned", "total_consumption", default=0)
            for day in week_days
        )
        total_grid_import = sum(
            safe_nested_get(day, "planned", "total_grid_import", default=0)
            for day in week_days
        )
        total_grid_export = sum(
            safe_nested_get(day, "planned", "total_grid_export", default=0)
            for day in week_days
        )

        weekly_aggregate = {
            "start_date": start_date,
            "end_date": end_date,
            "days_count": len(week_days),
            "planned": {
                "total_cost": round(total_cost, 2),
                "total_solar": round(total_solar, 2),
                "total_consumption": round(total_consumption, 2),
                "total_grid_import": round(total_grid_import, 2),
                "total_grid_export": round(total_grid_export, 2),
            },
        }

        if "weekly" not in data:
            data["weekly"] = {}

        data["weekly"][week_str] = weekly_aggregate
        await sensor._plans_store.async_save(data)

        _LOGGER.info(
            "Weekly aggregate saved for %s: cost=%.2f CZK, solar=%.2f kWh, %s days",
            week_str,
            total_cost,
            total_solar,
            len(week_days),
        )

        cutoff_daily = (
            datetime.strptime(end_date, DATE_FMT).date() - timedelta(days=30)
        ).strftime(DATE_FMT)

        daily_to_delete = [d for d in daily_plans.keys() if d < cutoff_daily]

        if daily_to_delete:
            for old_date in daily_to_delete:
                del data["daily"][old_date]
                _LOGGER.debug("Deleted daily plan for %s (>30 days old)", old_date)

            _LOGGER.info("Cleaned up %s old daily plans", len(daily_to_delete))

        weekly_plans = data.get("weekly", {})
        current_year_week = datetime.now().isocalendar()[:2]
        cutoff_week_number = current_year_week[1] - 52
        cutoff_year = (
            current_year_week[0] if cutoff_week_number > 0 else current_year_week[0] - 1
        )

        weekly_to_delete = []
        for week_key in weekly_plans.keys():
            try:
                year, week = week_key.split("-W")
                year, week = int(year), int(week)
                if year < cutoff_year or (
                    year == cutoff_year and week < cutoff_week_number
                ):
                    weekly_to_delete.append(week_key)
            except Exception:  # nosec B112
                continue

        if weekly_to_delete:
            for old_week in weekly_to_delete:
                del data["weekly"][old_week]
                _LOGGER.debug("Deleted weekly plan for %s (>52 weeks old)", old_week)

            _LOGGER.info("Cleaned up %s old weekly plans", len(weekly_to_delete))

        if daily_to_delete or weekly_to_delete:
            await sensor._plans_store.async_save(data)

        return True

    except Exception as err:
        _LOGGER.error(
            "Error aggregating weekly plan for %s: %s",
            week_str,
            err,
            exc_info=True,
        )
        return False


async def backfill_daily_archive_from_storage(sensor: Any) -> None:
    """Backfill daily plans archive from stored detailed plans."""
    if not sensor._plans_store:
        _LOGGER.warning("Cannot backfill - no storage helper")
        return

    try:
        storage_data = await sensor._plans_store.async_load() or {}
        detailed_plans = storage_data.get("detailed", {})

        if not detailed_plans:
            _LOGGER.info("No detailed plans in storage - nothing to backfill")
            return

        now = dt_util.now()
        backfilled_count = 0
        for days_ago in range(1, 8):
            date_str = (now.date() - timedelta(days=days_ago)).strftime(DATE_FMT)

            if date_str in sensor._daily_plans_archive:
                continue

            if date_str in detailed_plans:
                plan_data = detailed_plans[date_str]
                intervals = plan_data.get("intervals", [])
                sensor._daily_plans_archive[date_str] = {
                    "date": date_str,
                    "plan": intervals,
                    "actual": intervals,
                    "created_at": plan_data.get("created_at"),
                }
                backfilled_count += 1
                _LOGGER.debug(
                    "Backfilled archive for %s from storage (%s intervals)",
                    date_str,
                    len(intervals),
                )

        if backfilled_count > 0:
            _LOGGER.info("Backfilled %s days into archive", backfilled_count)
            storage_data["daily_archive"] = sensor._daily_plans_archive
            await sensor._plans_store.async_save(storage_data)
            _LOGGER.info("Saved backfilled archive to storage")
        else:
            _LOGGER.debug("No days needed backfilling")

    except Exception as err:
        _LOGGER.error("Failed to backfill daily archive: %s", err, exc_info=True)
