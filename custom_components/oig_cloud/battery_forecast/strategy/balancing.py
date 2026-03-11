"""Strategy-layer balancing plan helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass(slots=True)
class StrategyBalancingPlan:
    """Balancing plan normalized for strategy layer.

    Uses interval indices (0..n-1) for the current planning horizon.
    """

    charging_intervals: Set[int] = field(default_factory=set)
    holding_intervals: Set[int] = field(default_factory=set)
    mode_overrides: Dict[int, int] = field(default_factory=dict)
    is_active: bool = True
