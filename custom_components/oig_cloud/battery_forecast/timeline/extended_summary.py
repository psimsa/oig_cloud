"""Extended timeline summary helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util


def aggregate_cost_by_day(timeline: List[Dict[str, Any]]) -> Dict[str, float]:
    """Aggregate planned cost by day."""
    day_costs: Dict[str, float] = {}
    for interval in timeline:
        ts = interval.get("time")
        if not ts:
            continue
        try:
            day = datetime.fromisoformat(ts).date().isoformat()
        except Exception:  # nosec B112
            continue
        day_costs.setdefault(day, 0.0)
        day_costs[day] += interval.get("net_cost", 0.0)
    return day_costs


def get_day_cost_from_timeline(
    timeline: List[Dict[str, Any]], target_day: date
) -> Optional[float]:
    """Sum net_cost for specific date."""
    if not timeline:
        return None

    total = 0.0
    found = False
    for interval in timeline:
        ts = interval.get("time")
        if not ts:
            continue
        try:
            interval_day = datetime.fromisoformat(ts).date()
        except Exception:  # nosec B112
            continue
        if interval_day == target_day:
            total += interval.get("net_cost", 0.0)
            found = True
    return total if found else None


def format_planned_data(planned: Dict[str, Any]) -> Dict[str, Any]:
    """Format planned data for API."""

    def _pick(keys, default=0.0):
        for key in keys:
            if key in planned and planned.get(key) is not None:
                return planned.get(key)
        return default

    battery_kwh = _pick(["battery_kwh", "battery_capacity_kwh", "battery_soc"], 0.0)
    consumption_kwh = _pick(["load_kwh", "consumption_kwh"], 0.0)
    grid_import = _pick(["grid_import", "grid_import_kwh"], 0.0)
    grid_export = _pick(["grid_export", "grid_export_kwh"], 0.0)
    spot_price = _pick(["spot_price", "spot_price_czk"], 0.0)

    return {
        "mode": planned.get("mode", 0),
        "mode_name": planned.get("mode_name", "HOME I"),
        "battery_kwh": round(battery_kwh, 2),
        "solar_kwh": round(_pick(["solar_kwh"], 0.0), 3),
        "consumption_kwh": round(consumption_kwh, 3),
        "grid_import": round(grid_import, 3),
        "grid_export": round(grid_export, 3),
        "spot_price": round(spot_price, 2),
        "net_cost": round(planned.get("net_cost", 0), 2),
        "savings_vs_home_i": round(planned.get("savings_vs_home_i", 0), 2),
        "decision_reason": planned.get("decision_reason"),
        "decision_metrics": planned.get("decision_metrics"),
    }


def format_actual_data(
    actual: Dict[str, Any], planned: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Format actual data for API."""
    if not actual:
        return None

    result = {
        "mode": actual.get("mode", 0),
        "mode_name": actual.get("mode_name", "HOME I"),
        "battery_kwh": round(actual.get("battery_kwh", 0), 2),
        "grid_import": round(actual.get("grid_import", 0), 3),
        "grid_export": round(actual.get("grid_export", 0), 3),
        "net_cost": round(actual.get("net_cost", 0), 2),
        "solar_kwh": round(actual.get("solar_kwh", 0), 3),
        "consumption_kwh": round(actual.get("consumption_kwh", 0), 3),
        "spot_price": round(actual.get("spot_price", 0), 2),
        "export_price": round(actual.get("export_price", 0), 2),
    }

    if "savings_vs_home_i" in actual:
        result["savings_vs_home_i"] = round(actual.get("savings_vs_home_i", 0), 2)
    elif planned:
        result["savings_vs_home_i"] = round(planned.get("savings_vs_home_i", 0), 2)
    else:
        result["savings_vs_home_i"] = 0

    return result


def calculate_day_summary(intervals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate summary for a day."""
    planned_cost = sum(
        i.get("planned", {}).get("net_cost", 0) for i in intervals if i.get("planned")
    )
    actual_cost = sum(
        i.get("actual", {}).get("net_cost", 0) for i in intervals if i.get("actual")
    )

    historical_count = sum(1 for i in intervals if i.get("status") == "historical")

    delta_cost = actual_cost - planned_cost if historical_count > 0 else None
    accuracy_pct = (
        round((1 - abs(delta_cost) / planned_cost) * 100, 1)
        if planned_cost > 0 and delta_cost is not None
        else None
    )

    return {
        "planned_total_cost": round(planned_cost, 2) if planned_cost > 0 else None,
        "actual_total_cost": round(actual_cost, 2) if actual_cost > 0 else None,
        "delta_cost": round(delta_cost, 2) if delta_cost is not None else None,
        "accuracy_pct": accuracy_pct,
        "intervals_count": len(intervals),
        "historical_count": historical_count,
    }


def build_today_tile_summary(
    sensor: Any, intervals: List[Dict[str, Any]], now: datetime
) -> Dict[str, Any]:
    """Build summary for the today tile."""
    if not intervals:
        return get_empty_tile_summary(now)

    current_minute = (now.minute // 15) * 15
    current_interval_time = now.replace(minute=current_minute, second=0, microsecond=0)

    historical = []
    future = []

    for interval in intervals:
        try:
            interval_time_str = interval.get("time", "")
            if not interval_time_str:
                continue

            interval_time = datetime.fromisoformat(interval_time_str)
            if interval_time.tzinfo is None:
                interval_time = dt_util.as_local(interval_time)

            if interval_time < current_interval_time and interval.get("actual"):
                historical.append(interval)
            else:
                future.append(interval)
        except Exception:  # nosec B112
            continue

    def safe_get_cost(interval: Dict[str, Any], key: str) -> float:
        data = interval.get(key)
        if data is None:
            return 0.0
        if isinstance(data, dict):
            return float(data.get("net_cost", 0))
        return 0.0

    planned_so_far = sum(safe_get_cost(h, "planned") for h in historical)
    actual_so_far = sum(safe_get_cost(h, "actual") for h in historical)
    delta = actual_so_far - planned_so_far
    delta_pct = (delta / planned_so_far * 100) if planned_so_far > 0 else 0.0

    planned_future = sum(safe_get_cost(f, "planned") for f in future)
    eod_plan = planned_so_far + planned_future

    eod_prediction = actual_so_far + planned_future
    eod_delta = eod_prediction - eod_plan
    eod_delta_pct = (eod_delta / eod_plan * 100) if eod_plan > 0 else 0.0

    total_intervals = len(intervals)
    historical_count = len(historical)
    progress_pct = (
        (historical_count / total_intervals * 100) if total_intervals > 0 else 0.0
    )

    if progress_pct < 25:
        confidence = "low"
    elif progress_pct < 50:
        confidence = "medium"
    elif progress_pct < 75:
        confidence = "good"
    else:
        confidence = "high"

    mini_chart_data = []
    for interval in intervals:
        interval_time_str = interval.get("time", "")
        if not interval_time_str:
            continue

        try:
            interval_time = datetime.fromisoformat(interval_time_str)
            if interval_time.tzinfo is None:
                interval_time = dt_util.as_local(interval_time)

            is_current = (
                current_interval_time
                <= interval_time
                < current_interval_time + timedelta(minutes=15)
            )

            delta_value = None
            if interval.get("actual") and interval.get("delta"):
                delta_value = interval["delta"].get("net_cost")

            mini_chart_data.append(
                {
                    "time": interval_time_str,
                    "delta": delta_value,
                    "is_historical": bool(interval.get("actual")),
                    "is_current": is_current,
                }
            )
        except Exception:  # nosec B112
            continue

    return {
        "progress_pct": round(progress_pct, 1),
        "planned_so_far": round(planned_so_far, 2),
        "actual_so_far": round(actual_so_far, 2),
        "delta": round(delta, 2),
        "delta_pct": round(delta_pct, 1),
        "eod_prediction": round(eod_prediction, 2),
        "eod_plan": round(eod_plan, 2),
        "eod_delta": round(eod_delta, 2),
        "eod_delta_pct": round(eod_delta_pct, 1),
        "confidence": confidence,
        "mini_chart_data": mini_chart_data,
        "current_time": now.strftime("%H:%M"),
        "last_updated": now.isoformat(),
        "intervals_total": total_intervals,
        "intervals_historical": historical_count,
        "intervals_future": len(future),
    }


def get_empty_tile_summary(now: datetime) -> Dict[str, Any]:
    """Empty tile summary when no data is available."""
    return {
        "progress_pct": 0.0,
        "planned_so_far": 0.0,
        "actual_so_far": 0.0,
        "delta": 0.0,
        "delta_pct": 0.0,
        "eod_prediction": 0.0,
        "eod_plan": 0.0,
        "eod_delta": 0.0,
        "eod_delta_pct": 0.0,
        "confidence": "none",
        "mini_chart_data": [],
        "current_time": now.strftime("%H:%M"),
        "last_updated": now.isoformat(),
        "intervals_total": 0,
        "intervals_historical": 0,
        "intervals_future": 0,
    }
