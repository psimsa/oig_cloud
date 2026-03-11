"""Detail tabs builders extracted from legacy battery forecast."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .detail_tabs_blocks import build_mode_blocks_for_tab
from .detail_tabs_summary import calculate_tab_summary, default_metrics_summary

_LOGGER = logging.getLogger(__name__)


async def build_detail_tabs(
    sensor: Any,
    *,
    tab: Optional[str] = None,
    plan: str = "hybrid",
    mode_names: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Build Detail Tabs data (aggregated mode blocks)."""
    _ = plan
    mode_names = mode_names or {}

    timeline_extended = await sensor.build_timeline_extended()
    hybrid_tabs = await build_hybrid_detail_tabs(
        sensor, tab=tab, timeline_extended=timeline_extended, mode_names=mode_names
    )

    return sensor._decorate_plan_tabs(  # pylint: disable=protected-access
        primary_tabs=hybrid_tabs,
        secondary_tabs={},
        primary_plan="hybrid",
        secondary_plan="none",
    )


async def build_hybrid_detail_tabs(
    sensor: Any,
    *,
    tab: Optional[str] = None,
    timeline_extended: Optional[Dict[str, Any]] = None,
    mode_names: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Internal helper that builds hybrid detail tabs."""
    if tab is None:
        tabs_to_process = ["yesterday", "today", "tomorrow"]
    elif tab in ["yesterday", "today", "tomorrow"]:
        tabs_to_process = [tab]
    else:
        _LOGGER.warning("Invalid tab requested: %s, returning all tabs", tab)
        tabs_to_process = ["yesterday", "today", "tomorrow"]

    result: Dict[str, Any] = {}
    if timeline_extended is None:
        timeline_extended = await sensor.build_timeline_extended()

    mode_names = mode_names or {}

    for tab_name in tabs_to_process:
        tab_data = timeline_extended.get(tab_name, {})
        intervals = tab_data.get("intervals", [])
        date_str = tab_data.get("date", "")

        if not intervals:
            tab_result = {
                "date": date_str,
                "mode_blocks": [],
                "summary": {
                    "total_cost": 0.0,
                    "overall_adherence": 100,
                    "mode_switches": 0,
                    "metrics": default_metrics_summary(),
                },
                "intervals": [],
            }
        else:
            mode_blocks = build_mode_blocks_for_tab(
                sensor, intervals, tab_name, mode_names=mode_names
            )
            summary = calculate_tab_summary(sensor, mode_blocks, intervals)
            tab_result = {
                "date": date_str,
                "mode_blocks": mode_blocks,
                "summary": summary,
                "intervals": intervals,
            }

        result[tab_name] = tab_result

    return result
