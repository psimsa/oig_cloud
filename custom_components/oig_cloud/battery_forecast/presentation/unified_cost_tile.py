"""Unified cost tile builders extracted from legacy battery forecast."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.util import dt as dt_util

from .unified_cost_tile_helpers import (
    build_today_cost_data,
    build_tomorrow_cost_data,
    get_yesterday_cost_from_archive,
)

_LOGGER = logging.getLogger(__name__)


async def build_unified_cost_tile(
    sensor: Any, *, mode_names: Optional[Dict[int, str]] = None
) -> Dict[str, Any]:
    """Build Unified Cost Tile data."""
    self = sensor
    mode_names = mode_names or {}

    now = dt_util.now()

    _LOGGER.info("Unified Cost Tile: Building fresh data...")
    build_start = dt_util.now()

    try:
        today_data = await build_today_cost_data(self)
    except Exception as e:
        _LOGGER.error("Failed to build today cost data: %s", e, exc_info=True)
        today_data = {
            "plan_total_cost": 0.0,
            "actual_total_cost": 0.0,
            "delta": 0.0,
            "performance": "on_plan",
            "completed_intervals": 0,
            "total_intervals": 0,
            "progress_pct": 0,
            "eod_prediction": {
                "predicted_total": 0.0,
                "vs_plan": 0.0,
                "confidence": "low",
            },
            "error": str(e),
        }

    try:
        yesterday_data = get_yesterday_cost_from_archive(self, mode_names=mode_names)
    except Exception as e:
        _LOGGER.error("Failed to get yesterday cost data: %s", e, exc_info=True)
        yesterday_data = {
            "plan_total_cost": 0.0,
            "actual_total_cost": 0.0,
            "delta": 0.0,
            "performance": "on_plan",
            "error": str(e),
        }

    try:
        tomorrow_data = await build_tomorrow_cost_data(self, mode_names=mode_names)
    except Exception as e:
        _LOGGER.error("Failed to build tomorrow cost data: %s", e, exc_info=True)
        tomorrow_data = {
            "plan_total_cost": 0.0,
            "error": str(e),
        }

    result = {
        "today": today_data,
        "yesterday": yesterday_data,
        "tomorrow": tomorrow_data,
        "metadata": {
            "last_update": str(now),
            "timezone": str(now.tzinfo),
        },
    }

    build_duration = (dt_util.now() - build_start).total_seconds()
    _LOGGER.info("Unified Cost Tile: Built in %.2fs", build_duration)

    return result
