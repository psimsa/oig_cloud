"""Interval grouping helpers for detail tabs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

_LOGGER = logging.getLogger(__name__)


def group_intervals_by_mode(
    intervals: List[Dict[str, Any]],
    data_type: str,
    mode_names: Dict[int, str],
) -> List[Dict[str, Any]]:
    """Group consecutive intervals by mode and aggregate costs."""
    if not intervals:
        return []

    groups: List[Dict[str, Any]] = []
    current_group = None

    for interval in intervals:
        if interval is None:
            continue

        if data_type == "completed":
            actual = interval.get("actual") or {}
            planned = interval.get("planned") or {}
            actual_mode = actual.get("mode")
            planned_mode = planned.get("mode")
            if actual_mode is not None:
                mode = actual_mode
            elif planned_mode is not None:
                mode = planned_mode
            else:
                mode = "Unknown"
            if len(groups) < 3:
                _LOGGER.info(
                    "[group_intervals_by_mode] completed: time=%s actual_mode=%s planned_mode=%s final_mode=%s",
                    interval.get("time", "?")[:16],
                    actual_mode,
                    planned_mode,
                    mode,
                )
        elif data_type == "planned":
            planned = interval.get("planned") or {}
            mode = planned.get("mode", "Unknown")
        else:
            actual = interval.get("actual") or {}
            planned = interval.get("planned") or {}
            actual_mode = actual.get("mode")
            planned_mode = planned.get("mode")
            if actual_mode is not None:
                mode = actual_mode
            elif planned_mode is not None:
                mode = planned_mode
            else:
                mode = "Unknown"
            _LOGGER.debug(
                "[group_intervals_by_mode] data_type=both: actual_mode=%s planned_mode=%s final_mode=%s",
                actual_mode,
                planned_mode,
                mode,
            )

        if isinstance(mode, int):
            mode = mode_names.get(mode, f"Mode {mode}")
        elif mode != "Unknown":
            mode = str(mode).strip()

        if not mode:
            mode = "Unknown"

        if not current_group or current_group["mode"] != mode:
            current_group = {
                "mode": mode,
                "start_time": interval.get("time", ""),
                "end_time": interval.get("time", ""),
                "intervals": [interval],
            }
            groups.append(current_group)
        else:
            current_group["intervals"].append(interval)
            current_group["end_time"] = interval.get("time", "")

    for group in groups:
        interval_count = len(group["intervals"])
        group["interval_count"] = interval_count

        if data_type in ["completed", "both"]:
            actual_cost = sum(
                iv.get("actual", {}).get("net_cost", 0)
                for iv in group["intervals"]
                if iv.get("actual") is not None
            )
            planned_cost = sum(
                (iv.get("planned") or {}).get("net_cost", 0)
                for iv in group["intervals"]
            )
            actual_savings = sum(
                iv.get("actual", {}).get("savings_vs_home_i", 0)
                for iv in group["intervals"]
                if iv.get("actual") is not None
            )
            planned_savings = sum(
                (iv.get("planned") or {}).get("savings_vs_home_i", 0)
                for iv in group["intervals"]
            )
            delta = actual_cost - planned_cost
            delta_pct = (delta / planned_cost * 100) if planned_cost > 0 else 0.0

            group["actual_cost"] = round(actual_cost, 2)
            group["planned_cost"] = round(planned_cost, 2)
            group["actual_savings"] = round(actual_savings, 2)
            group["planned_savings"] = round(planned_savings, 2)
            group["delta"] = round(delta, 2)
            group["delta_pct"] = round(delta_pct, 1)

        if data_type == "planned":
            planned_cost = sum(
                (iv.get("planned") or {}).get("net_cost", 0)
                for iv in group["intervals"]
            )
            planned_savings = sum(
                (iv.get("planned") or {}).get("savings_vs_home_i", 0)
                for iv in group["intervals"]
            )
            group["planned_cost"] = round(planned_cost, 2)
            group["planned_savings"] = round(planned_savings, 2)

        if group["start_time"]:
            try:
                start_dt = datetime.fromisoformat(group["start_time"])
                group["start_time"] = start_dt.strftime("%H:%M")
            except Exception:  # nosec B110
                pass

        if group["end_time"]:
            try:
                end_dt = datetime.fromisoformat(group["end_time"])
                end_dt = end_dt + timedelta(minutes=15)
                group["end_time"] = end_dt.strftime("%H:%M")
            except Exception:  # nosec B110
                pass

    return groups
