"""Balancing helpers for battery forecast sensor."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)


def update_balancing_plan_snapshot(sensor: Any, plan: Optional[Dict[str, Any]]) -> None:
    """Keep BalancingManager plan snapshot in sync with legacy plan handling."""

    def _is_balancing_requester(requester: Optional[str]) -> bool:
        if not requester:
            return False
        return requester.lower() in {"balancingmanager", "balancing_manager"}

    sensor._balancing_plan_snapshot = plan

    if plan:
        if not sensor._active_charging_plan or _is_balancing_requester(
            sensor._active_charging_plan.get("requester")
        ):
            sensor._active_charging_plan = plan
    else:
        if sensor._active_charging_plan and _is_balancing_requester(
            sensor._active_charging_plan.get("requester")
        ):
            sensor._active_charging_plan = None


def get_balancing_plan(sensor: Any) -> Optional[Dict[str, Any]]:
    """Get balancing plan from battery_balancing sensor."""
    if not sensor._hass:
        return None

    sensor_id = f"sensor.oig_{sensor._box_id}_battery_balancing"
    state = sensor._hass.states.get(sensor_id)

    if not state or not state.attributes:
        _LOGGER.debug("Battery balancing sensor %s not available", sensor_id)
        return None

    planned = state.attributes.get("planned")
    if not planned:
        _LOGGER.debug("No balancing window planned")
        return None

    _LOGGER.info(
        "Balancing plan: %s from %s to %s",
        planned.get("reason"),
        planned.get("holding_start"),
        planned.get("holding_end"),
    )

    return planned


async def plan_balancing(
    sensor: Any,
    requested_start: datetime,
    requested_end: datetime,
    target_soc: float,
    mode: str,
) -> Dict[str, Any]:
    """Compute balancing plan for requested window."""
    try:
        _LOGGER.info(
            "Balancing request: %s window=%s-%s target=%s%%",
            mode,
            requested_start.strftime("%H:%M"),
            requested_end.strftime("%H:%M"),
            target_soc,
        )

        charging_intervals = []
        current = requested_start
        while current < requested_end:
            charging_intervals.append(current.isoformat())
            current += timedelta(minutes=15)

        return {
            "can_do": True,
            "charging_intervals": charging_intervals,
            "actual_holding_start": requested_start.isoformat(),
            "actual_holding_end": requested_end.isoformat(),
            "reason": "Temporary implementation - always accepts",
        }

    except Exception as err:
        _LOGGER.error("Failed to plan balancing: %s", err, exc_info=True)
        return {
            "can_do": False,
            "charging_intervals": [],
            "actual_holding_start": None,
            "actual_holding_end": None,
            "reason": f"Error: {err}",
        }
