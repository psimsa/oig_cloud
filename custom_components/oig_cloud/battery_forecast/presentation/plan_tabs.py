"""Plan tab helpers for detail tabs."""

from __future__ import annotations

import copy
from typing import Any, Dict


def decorate_plan_tabs(
    primary_tabs: Dict[str, Any],
    secondary_tabs: Dict[str, Any],
    primary_plan: str,
    secondary_plan: str,
) -> Dict[str, Any]:
    """Attach metadata and optional comparison blocks to plan tabs."""
    result: Dict[str, Any] = {}

    for key, tab_data in primary_tabs.items():
        tab_copy = {
            "date": tab_data.get("date"),
            "mode_blocks": copy.deepcopy(tab_data.get("mode_blocks", [])),
            "summary": copy.deepcopy(tab_data.get("summary", {})),
            "intervals": copy.deepcopy(tab_data.get("intervals", [])),
        }

        metadata = tab_data.get("metadata", {}).copy()
        metadata["active_plan"] = primary_plan
        metadata["comparison_plan_available"] = (
            secondary_plan if secondary_tabs.get(key) else None
        )
        tab_copy["metadata"] = metadata

        comparison_source = secondary_tabs.get(key)
        if comparison_source:
            has_current = any(
                block.get("status") == "current"
                for block in tab_copy.get("mode_blocks", [])
            )
            if not has_current:
                comparison_blocks = [
                    block
                    for block in comparison_source.get("mode_blocks", [])
                    if block.get("status") in ("current", "planned")
                ]
                if comparison_blocks:
                    tab_copy["comparison"] = {
                        "plan": secondary_plan,
                        "mode_blocks": comparison_blocks,
                    }

        result[key] = tab_copy

    return result
