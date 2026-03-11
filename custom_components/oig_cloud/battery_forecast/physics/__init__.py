"""Physics layer for battery simulation.

This package contains the core physics simulation for CBB battery modes.
"""

from ...physics import simulate_interval
from .interval_simulator import IntervalResult, IntervalSimulator

__all__ = [
    "IntervalSimulator",
    "IntervalResult",
    "simulate_interval",
]
