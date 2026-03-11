"""State attribute helpers for battery forecast sensor."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


def build_extra_state_attributes(
    sensor: Any, *, debug_expose_baseline_timeline: bool
) -> Dict[str, Any]:
    """Build lean extra_state_attributes payload."""
    attrs = {
        "last_update": sensor._last_update.isoformat() if sensor._last_update else None,
        "data_source": "simplified_calculation",
        "current_battery_kwh": (
            round(
                sensor._timeline_data[0].get(
                    "battery_soc",
                    sensor._timeline_data[0].get("battery_capacity_kwh", 0),
                ),
                2,
            )
            if sensor._timeline_data and len(sensor._timeline_data) > 0
            else 0
        ),
        "current_timestamp": (
            sensor._timeline_data[0].get(
                "time", sensor._timeline_data[0].get("timestamp")
            )
            if sensor._timeline_data and len(sensor._timeline_data) > 0
            else None
        ),
        "max_capacity_kwh": sensor._get_max_battery_capacity(),
        "min_capacity_kwh": sensor._get_min_battery_capacity(),
        "timeline_points_count": (
            len(sensor._timeline_data) if sensor._timeline_data else 0
        ),
        "timeline_horizon_hours": (
            round((len(sensor._timeline_data) * 15 / 60), 1)
            if sensor._timeline_data
            else 0
        ),
        "data_hash": sensor._data_hash if sensor._data_hash else "unknown",
        "api_endpoint": f"/api/oig_cloud/battery_forecast/{sensor._box_id}/timeline",
        "api_query_params": "?type=active (default) | baseline | both",
        "api_note": "Full timeline data available via REST API (reduces memory by 96%)",
    }

    if hasattr(sensor, "_charging_metrics") and sensor._charging_metrics:
        attrs.update(sensor._charging_metrics)

    if hasattr(sensor, "_consumption_summary") and sensor._consumption_summary:
        attrs.update(sensor._consumption_summary)

    if hasattr(sensor, "_balancing_cost") and sensor._balancing_cost:
        attrs["balancing_cost"] = sensor._balancing_cost

    plan_snapshot: Optional[Dict[str, Any]] = None
    if getattr(sensor, "_balancing_plan_snapshot", None):
        plan_snapshot = sensor._balancing_plan_snapshot
    elif hasattr(sensor, "_active_charging_plan") and sensor._active_charging_plan:
        plan_snapshot = sensor._active_charging_plan

    if plan_snapshot:
        attrs["active_plan_data"] = json.dumps(plan_snapshot)

    attrs["plan_status"] = getattr(sensor, "_plan_status", "none")

    if (
        hasattr(sensor, "_mode_optimization_result")
        and sensor._mode_optimization_result
    ):
        mo = sensor._mode_optimization_result
        attrs["mode_optimization"] = {
            "total_cost_czk": round(mo.get("total_cost_48h", 0), 2),
            "total_savings_vs_home_i_czk": round(mo.get("total_savings_48h", 0), 2),
            "total_cost_72h_czk": round(mo.get("total_cost", 0), 2),
            "modes_distribution": {
                "HOME_I": mo["optimal_modes"].count(0),
                "HOME_II": mo["optimal_modes"].count(1),
                "HOME_III": mo["optimal_modes"].count(2),
                "HOME_UPS": mo["optimal_modes"].count(3),
            },
            "home_i_intervals": mo["optimal_modes"].count(0),
            "home_ii_intervals": mo["optimal_modes"].count(1),
            "home_iii_intervals": mo["optimal_modes"].count(2),
            "home_ups_intervals": mo["optimal_modes"].count(3),
            "timeline_length": len(mo.get("optimal_timeline", [])),
        }

        if mo.get("baselines"):
            attrs["mode_optimization"]["baselines"] = mo["baselines"]
            attrs["mode_optimization"]["best_baseline"] = mo.get("best_baseline")
            attrs["mode_optimization"]["hybrid_cost"] = round(
                mo.get("hybrid_cost", 0), 2
            )
            attrs["mode_optimization"]["best_baseline_cost"] = round(
                mo.get("best_baseline_cost", 0), 2
            )
            attrs["mode_optimization"]["savings_vs_best"] = round(
                mo.get("savings_vs_best", 0), 2
            )
            attrs["mode_optimization"]["savings_percentage"] = round(
                mo.get("savings_percentage", 0), 1
            )

        if mo.get("alternatives"):
            attrs["mode_optimization"]["alternatives"] = mo["alternatives"]

        boiler_total = sum(
            interval.get("boiler_charge", 0)
            for interval in mo.get("optimal_timeline", [])
        )
        curtailed_total = sum(
            interval.get("curtailed_loss", 0)
            for interval in mo.get("optimal_timeline", [])
        )

        if boiler_total > 0.001 or curtailed_total > 0.001:
            attrs["boiler_summary"] = {
                "total_energy_kwh": round(boiler_total, 2),
                "intervals_used": sum(
                    1
                    for i in mo.get("optimal_timeline", [])
                    if i.get("boiler_charge", 0) > 0.001
                ),
                "avoided_export_loss_czk": round(curtailed_total, 2),
            }

    if debug_expose_baseline_timeline:
        _LOGGER.warning(
            "DEBUG MODE: Full timeline in attributes (280 KB)! "
            "Set DEBUG_EXPOSE_BASELINE_TIMELINE=False for production."
        )
        attrs["timeline_data"] = sensor._timeline_data
        if hasattr(sensor, "_baseline_timeline"):
            attrs["baseline_timeline_data"] = sensor._baseline_timeline

    return attrs


def calculate_data_hash(timeline_data: List[Dict[str, Any]]) -> str:
    """Return SHA-256 hash of timeline data."""
    if not timeline_data:
        return "empty"

    data_str = json.dumps(timeline_data, sort_keys=True)
    return hashlib.sha256(data_str.encode()).hexdigest()
