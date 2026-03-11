from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.balancing.executor import (
    BalancingExecutor,
)


def test_parse_plan_missing_fields():
    executor = BalancingExecutor(max_capacity=10)
    assert executor.parse_plan({}) is None


def test_parse_plan_preferred_intervals_variants():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": "2025-01-01T01:00:00",
        "holding_end": "2025-01-01T02:00:00",
        "charging_intervals": [
            "2025-01-01T00:00:00",
            {"timestamp": "2025-01-01T00:15:00"},
            {"timestamp": "bad"},
        ],
    }
    parsed = executor.parse_plan(plan)
    assert parsed is not None
    assert len(parsed.preferred_intervals) == 2


def test_apply_balancing_infeasible_warning():
    executor = BalancingExecutor(max_capacity=10, charge_rate_kw=1.0, efficiency=1.0)
    modes = [0, 0]
    spot_prices = [
        {"time": "2025-01-01T00:00:00", "price": 1.0},
        {"time": "2025-01-01T00:15:00", "price": 2.0},
    ]
    plan = {
        "holding_start": "2025-01-01T00:15:00",
        "holding_end": "2025-01-01T00:30:00",
        "charging_intervals": [],
    }
    result = executor.apply_balancing(modes, spot_prices, 0.0, plan)
    assert result.feasible is False
    assert result.warning


def test_get_balancing_indices_and_costs():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": "2025-01-01T00:15:00",
        "holding_end": "2025-01-01T00:45:00",
    }
    spot_prices = [
        {"time": "2025-01-01T00:00:00", "price": 1.0},
        {"time": "2025-01-01T00:15:00", "price": 2.0},
        {"time": "2025-01-01T00:30:00", "price": 3.0},
        {"time": "bad", "price": 4.0},
    ]
    charging, holding = executor.get_balancing_indices(spot_prices, plan)
    assert 0 in charging
    assert 1 in holding
    assert 2 in holding

    charging_cost, holding_cost = executor.estimate_balancing_cost(
        spot_prices, sorted(charging), sorted(holding), consumption_per_interval=0.1
    )
    assert charging_cost > 0
    assert holding_cost > 0


def test_parse_plan_datetime_objects_and_invalid_interval():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": datetime(2025, 1, 1, 1, 0, 0),
        "holding_end": datetime(2025, 1, 1, 2, 0, 0),
        "charging_intervals": [{"timestamp": None}],
        "mode": "forced",
    }
    parsed = executor.parse_plan(plan)
    assert parsed is not None
    assert parsed.mode == "forced"


def test_apply_balancing_uses_preferred_and_cheapest():
    executor = BalancingExecutor(max_capacity=5, charge_rate_kw=2.0, efficiency=1.0)
    modes = [0, 0, 0]
    spot_prices = [
        {"time": "2025-01-01T00:00:00", "price": 5.0},
        {"time": "2025-01-01T00:15:00", "price": 1.0},
        {"time": "2025-01-01T00:30:00", "price": 2.0},
    ]
    plan = {
        "holding_start": "2025-01-01T00:30:00",
        "holding_end": "2025-01-01T00:45:00",
        "charging_intervals": ["2025-01-01T00:00:00"],
    }
    result = executor.apply_balancing(modes, spot_prices, 0.0, plan)
    assert result.charging_intervals
    assert result.holding_intervals


def test_get_balancing_indices_handles_bad_time():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": "2025-01-01T00:15:00",
        "holding_end": "2025-01-01T00:45:00",
    }
    charging, holding = executor.get_balancing_indices(
        [{"time": None, "price": 1.0}], plan
    )
    assert charging == set()
    assert holding == set()
