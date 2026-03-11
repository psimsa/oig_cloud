from __future__ import annotations

from custom_components.oig_cloud.battery_forecast.balancing.executor import (
    BalancingExecutor,
)


def test_parse_plan_invalid_interval_type_skips():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": "2025-01-01T01:00:00",
        "holding_end": "2025-01-01T02:00:00",
        "charging_intervals": [123],
    }
    parsed = executor.parse_plan(plan)
    assert parsed is not None
    assert parsed.preferred_intervals == set()


def test_parse_plan_invalid_holding_start_returns_none():
    executor = BalancingExecutor(max_capacity=10)
    plan = {
        "holding_start": "bad",
        "holding_end": "2025-01-01T02:00:00",
    }
    assert executor.parse_plan(plan) is None


def test_apply_balancing_returns_warning_on_invalid_plan():
    executor = BalancingExecutor(max_capacity=10)
    result = executor.apply_balancing(
        modes=[0, 0],
        spot_prices=[{"time": "2025-01-01T00:00:00", "price": 1.0}],
        current_battery=5.0,
        balancing_plan={"holding_start": "2025-01-01T00:00:00"},
    )
    assert result.warning


def test_apply_balancing_handles_bad_spot_time():
    executor = BalancingExecutor(max_capacity=10)
    modes = [0, 0]
    spot_prices = [
        {"time": "bad", "price": 1.0},
        {"time": "2025-01-01T00:15:00", "price": 2.0},
    ]
    plan = {
        "holding_start": "2025-01-01T00:15:00",
        "holding_end": "2025-01-01T00:30:00",
        "charging_intervals": ["2025-01-01T00:15:00"],
    }
    result = executor.apply_balancing(modes, spot_prices, 0.0, plan)
    assert result.modes


def test_get_balancing_indices_invalid_plan_returns_empty():
    executor = BalancingExecutor(max_capacity=10)
    charging, holding = executor.get_balancing_indices(
        [{"time": "2025-01-01T00:00:00", "price": 1.0}], {}
    )
    assert charging == set()
    assert holding == set()
