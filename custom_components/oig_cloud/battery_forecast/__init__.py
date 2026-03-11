"""Battery forecast module - modular architecture for battery optimization.

This module provides:
- Timeline building and SoC simulation
- HYBRID multi-mode optimization algorithm
- Balancing plan execution
- Mode management (HOME I/II/III/UPS)

Architecture (modular layout):
    battery_forecast/
    ├── __init__.py          # This file - exports
    ├── types.py             # TypedDicts, Enums, Constants
    ├── config.py            # Planner configuration
    ├── utils_common.py      # Shared helpers
    ├── task_utils.py        # Async/task helpers
    ├── data/                # Inputs (history, pricing, solar, profiles)
    ├── planning/            # Planning + guard logic
    ├── presentation/        # Detail tabs + UI payloads
    ├── storage/             # Storage helpers for plans
    ├── sensors/             # HA entity adapters
    ├── physics/             # Physics simulation
    ├── strategy/            # Optimization strategies
    ├── timeline/
    ├── balancing/           # Balancing logic
"""

from .physics import IntervalResult, IntervalSimulator
from .strategy import HybridResult, HybridStrategy
from .types import (  # Mode constants; TypedDicts; Constants; Helper functions
    AC_CHARGING_DISABLED_MODES,
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    CBB_MODE_SERVICE_MAP,
    DEFAULT_CHARGE_RATE_KW,
    DEFAULT_EFFICIENCY,
    INTERVAL_MINUTES,
    MIN_MODE_DURATION,
    TRANSITION_COSTS,
    BalancingPlan,
    CBBMode,
    ModeRecommendation,
    OptimizationResult,
    SpotPrice,
    TimelineInterval,
    get_mode_name,
    is_charging_mode,
)

__all__ = [
    # Mode constants
    "CBBMode",
    "CBB_MODE_HOME_I",
    "CBB_MODE_HOME_II",
    "CBB_MODE_HOME_III",
    "CBB_MODE_HOME_UPS",
    "CBB_MODE_NAMES",
    "CBB_MODE_SERVICE_MAP",
    "AC_CHARGING_DISABLED_MODES",
    # TypedDicts
    "TimelineInterval",
    "SpotPrice",
    "BalancingPlan",
    "OptimizationResult",
    "ModeRecommendation",
    # Constants
    "TRANSITION_COSTS",
    "MIN_MODE_DURATION",
    "DEFAULT_EFFICIENCY",
    "DEFAULT_CHARGE_RATE_KW",
    "INTERVAL_MINUTES",
    # Helper functions
    "get_mode_name",
    "is_charging_mode",
    # NEW: Physics layer
    "IntervalSimulator",
    "IntervalResult",
    # NEW: Strategy layer
    "HybridStrategy",
    "HybridResult",
]
