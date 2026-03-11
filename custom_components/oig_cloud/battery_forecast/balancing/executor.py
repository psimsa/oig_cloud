"""Balancing executor - applies balancing plan to modes.

This module handles the application of balancing plans to the
timeline modes, ensuring proper charging and holding periods.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from homeassistant.util import dt as dt_util

from ..types import CBB_MODE_HOME_UPS, INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


@dataclass
class BalancingResult:
    """Result of balancing execution."""

    modes: List[int]
    charging_intervals: List[int]
    holding_intervals: List[int]
    total_ups_added: int
    feasible: bool
    expected_charging_kwh: float
    required_charging_kwh: float
    warning: Optional[str] = None


@dataclass
class BalancingPlanData:
    """Parsed balancing plan data."""

    holding_start: datetime
    holding_end: datetime
    preferred_intervals: Set[datetime] = field(default_factory=set)
    reason: str = "unknown"
    mode: str = "opportunistic"
    target_soc_percent: float = 100.0

    @property
    def deadline(self) -> datetime:
        """Charging deadline is the same as holding start."""
        return self.holding_start


class BalancingExecutor:
    """Executes balancing plan by modifying modes list.

    Balancing has three phases:
    1. CHARGING: Before deadline, charge to 100%
    2. HOLDING: From holding_start to holding_end, maintain 100%
    3. NORMAL: After holding_end, return to normal optimization

    Example:
        executor = BalancingExecutor(
            max_capacity=15.36,
            charge_rate_kw=2.8,
            interval_minutes=15,
        )

        result = executor.apply_balancing(
            modes=[0, 0, 0, ...],  # Initial modes
            spot_prices=[...],
            current_battery=10.0,
            balancing_plan={
                "holding_start": "2025-12-09T21:00:00",
                "holding_end": "2025-12-10T00:00:00",
                "charging_intervals": [...],
            },
        )

        if result.feasible:
            modes = result.modes  # Use modified modes
        else:
            print(f"Warning: {result.warning}")
    """

    def __init__(
        self,
        max_capacity: float,
        charge_rate_kw: float = 2.8,
        efficiency: float = 0.95,
        interval_minutes: int = INTERVAL_MINUTES,
    ) -> None:
        """Initialize executor.

        Args:
            max_capacity: Maximum battery capacity (kWh)
            charge_rate_kw: AC charging rate (kW)
            efficiency: AC/DC charging efficiency
            interval_minutes: Interval length in minutes
        """
        self.max_capacity = max_capacity
        self.charge_rate_kw = charge_rate_kw
        self.efficiency = efficiency
        self.interval_minutes = interval_minutes

        # Derived values
        self.interval_hours = interval_minutes / 60.0
        self.max_charge_per_interval = charge_rate_kw * self.interval_hours * efficiency

    def parse_plan(
        self,
        plan: Dict[str, Any],
    ) -> Optional[BalancingPlanData]:
        """Parse raw balancing plan dict into data object.

        Args:
            plan: Raw balancing plan dict

        Returns:
            BalancingPlanData or None if parsing fails
        """
        try:
            # Parse holding times
            holding_start_raw = plan.get("holding_start")
            holding_end_raw = plan.get("holding_end")

            if not holding_start_raw or not holding_end_raw:
                _LOGGER.warning("Balancing plan missing holding_start or holding_end")
                return None

            # Convert to datetime
            if isinstance(holding_start_raw, str):
                holding_start = datetime.fromisoformat(holding_start_raw)
            else:
                holding_start = holding_start_raw

            if isinstance(holding_end_raw, str):
                holding_end = datetime.fromisoformat(holding_end_raw)
            else:
                holding_end = holding_end_raw

            # Ensure timezone
            if holding_start.tzinfo is None:
                holding_start = dt_util.as_local(holding_start)
            if holding_end.tzinfo is None:
                holding_end = dt_util.as_local(holding_end)

            # Parse preferred intervals
            preferred = set()
            for iv in plan.get("charging_intervals", []):
                try:
                    if isinstance(iv, str):
                        ts = datetime.fromisoformat(iv)
                    elif isinstance(iv, dict):
                        ts = datetime.fromisoformat(iv.get("timestamp", ""))
                    else:
                        continue

                    if ts.tzinfo is None:
                        ts = dt_util.as_local(ts)
                    preferred.add(ts)
                except (ValueError, TypeError):
                    continue

            return BalancingPlanData(
                holding_start=holding_start,
                holding_end=holding_end,
                preferred_intervals=preferred,
                reason=plan.get("reason", "unknown"),
                mode=plan.get("mode", "opportunistic"),
                target_soc_percent=plan.get("target_soc_percent", 100.0),
            )

        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.error(f"Failed to parse balancing plan: {e}")
            return None

    def apply_balancing(
        self,
        modes: List[int],
        spot_prices: List[Dict[str, Any]],
        current_battery: float,
        balancing_plan: Dict[str, Any],
    ) -> BalancingResult:
        """Apply balancing plan to modes list.

        Args:
            modes: List of modes to modify (will be modified in place)
            spot_prices: List of spot price dicts with 'time' and 'price'
            current_battery: Current battery level (kWh)
            balancing_plan: Balancing plan dict

        Returns:
            BalancingResult with modified modes and metrics
        """
        plan = self.parse_plan(balancing_plan)

        if not plan:
            return BalancingResult(
                modes=modes,
                charging_intervals=[],
                holding_intervals=[],
                total_ups_added=0,
                feasible=True,
                expected_charging_kwh=0,
                required_charging_kwh=0,
                warning="Could not parse balancing plan",
            )

        n = len(modes)
        charging_indices: List[int] = []
        holding_indices: List[int] = []

        # Find deadline and holding indices
        deadline_idx = n
        holding_start_idx = n
        holding_end_idx = n

        for i, sp in enumerate(spot_prices):
            try:
                ts = datetime.fromisoformat(sp["time"])
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)

                if ts >= plan.holding_start and holding_start_idx == n:
                    holding_start_idx = i
                    deadline_idx = i

                if ts >= plan.holding_end and holding_end_idx == n:
                    holding_end_idx = i
                    break
            except (ValueError, TypeError):
                continue

        _LOGGER.info(
            f"🔋 Balancing executor: deadline_idx={deadline_idx}, "
            f"holding={holding_start_idx}-{holding_end_idx}"
        )

        # Step 1: Apply preferred intervals (before deadline)
        preferred_used = 0
        for i, sp in enumerate(spot_prices):
            if i >= deadline_idx:
                break
            try:
                ts = datetime.fromisoformat(sp["time"])
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)

                if ts in plan.preferred_intervals:
                    modes[i] = CBB_MODE_HOME_UPS
                    charging_indices.append(i)
                    preferred_used += 1
            except (ValueError, TypeError):
                continue

        # Step 2: Find cheapest intervals before deadline to fill remaining need
        required_kwh = max(0, self.max_capacity - current_battery)
        charging_from_preferred = preferred_used * self.max_charge_per_interval
        remaining_kwh = required_kwh - charging_from_preferred

        if remaining_kwh > 0.1:
            # Find cheapest non-UPS intervals before deadline
            candidates = []
            for i in range(deadline_idx):
                if modes[i] != CBB_MODE_HOME_UPS:
                    candidates.append(
                        {
                            "index": i,
                            "price": spot_prices[i].get("price", 0),
                        }
                    )

            candidates.sort(key=lambda x: x["price"])

            intervals_needed = int(remaining_kwh / self.max_charge_per_interval) + 1

            for cand in candidates[:intervals_needed]:
                idx = cand["index"]
                modes[idx] = CBB_MODE_HOME_UPS
                charging_indices.append(idx)

        # Step 3: Apply holding period (all UPS)
        for i in range(holding_start_idx, min(holding_end_idx, n)):
            modes[i] = CBB_MODE_HOME_UPS
            holding_indices.append(i)

        # Calculate expected vs required charging
        total_charging_intervals = len(set(charging_indices))  # Dedupe
        expected_kwh = total_charging_intervals * self.max_charge_per_interval

        feasible = expected_kwh >= required_kwh * 0.95  # 5% margin
        warning = None

        if not feasible:
            warning = (
                f"May not reach 100% by deadline! "
                f"Can charge {expected_kwh:.1f} kWh, need {required_kwh:.1f} kWh"
            )
            _LOGGER.warning(f"⚠️ BALANCING WARNING: {warning}")

        total_ups = len(set(charging_indices + holding_indices))

        _LOGGER.info(
            f"⚡ BALANCING applied: preferred={preferred_used}, "
            f"additional={len(charging_indices) - preferred_used}, "
            f"holding={len(holding_indices)}, total_UPS={total_ups}"
        )

        return BalancingResult(
            modes=modes,
            charging_intervals=sorted(set(charging_indices)),
            holding_intervals=sorted(set(holding_indices)),
            total_ups_added=total_ups,
            feasible=feasible,
            expected_charging_kwh=expected_kwh,
            required_charging_kwh=required_kwh,
            warning=warning,
        )

    def get_balancing_indices(
        self,
        spot_prices: List[Dict[str, Any]],
        balancing_plan: Dict[str, Any],
    ) -> Tuple[Set[int], Set[int]]:
        """Get indices for balancing (charging + holding).

        Args:
            spot_prices: List of spot price dicts
            balancing_plan: Balancing plan dict

        Returns:
            Tuple of (charging_indices, holding_indices)
        """
        plan = self.parse_plan(balancing_plan)

        if not plan:
            return set(), set()

        charging = set()
        holding = set()

        for i, sp in enumerate(spot_prices):
            try:
                ts = datetime.fromisoformat(sp["time"])
                if ts.tzinfo is None:
                    ts = dt_util.as_local(ts)
                ts_end = ts + timedelta(minutes=self.interval_minutes)

                # Charging: before deadline
                if ts < plan.deadline:
                    charging.add(i)

                # Holding: overlaps holding period
                if ts < plan.holding_end and ts_end > plan.holding_start:
                    holding.add(i)
            except (ValueError, TypeError):
                continue

        return charging, holding

    def estimate_balancing_cost(
        self,
        spot_prices: List[Dict[str, Any]],
        charging_indices: List[int],
        holding_indices: List[int],
        consumption_per_interval: float = 0.125,
    ) -> Tuple[float, float]:
        """Estimate cost of balancing.

        Args:
            spot_prices: List of spot price dicts
            charging_indices: Indices where charging happens
            holding_indices: Indices in holding period
            consumption_per_interval: Average consumption kWh

        Returns:
            Tuple of (charging_cost_czk, holding_cost_czk)
        """
        charging_cost = 0.0
        holding_cost = 0.0

        for idx in charging_indices:
            if idx < len(spot_prices):
                price = spot_prices[idx].get("price", 0)
                charging_cost += self.max_charge_per_interval * price

        for idx in holding_indices:
            if idx < len(spot_prices):
                price = spot_prices[idx].get("price", 0)
                # During holding, consumption comes from grid
                holding_cost += consumption_per_interval * price

        return round(charging_cost, 2), round(holding_cost, 2)
