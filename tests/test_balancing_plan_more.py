from __future__ import annotations

from datetime import datetime

from custom_components.oig_cloud.battery_forecast.balancing import plan as plan_module


def test_balancing_interval_to_from_dict():
    interval = plan_module.BalancingInterval(ts="2025-01-01T00:00:00", mode=3)
    data = interval.to_dict()
    parsed = plan_module.BalancingInterval.from_dict(data)
    assert parsed.mode == 3


def test_balancing_plan_to_json_and_from_json():
    plan = plan_module.BalancingPlan(
        mode=plan_module.BalancingMode.NATURAL,
        created_at="2025-01-01T00:00:00",
        reason="ok",
        holding_start="2025-01-01T01:00:00",
        holding_end="2025-01-01T04:00:00",
    )
    json_str = plan.to_json()
    loaded = plan_module.BalancingPlan.from_json(json_str)
    assert loaded.mode == plan_module.BalancingMode.NATURAL


def test_balancing_plan_from_dict_datetime_passthrough():
    now = datetime(2025, 1, 1, 0, 0, 0)
    data = {
        "mode": "natural",
        "created_at": now,
        "reason": "ok",
        "holding_start": now,
        "holding_end": now,
        "priority": "normal",
        "active": True,
    }
    plan = plan_module.BalancingPlan.from_dict(data)
    assert plan.created_at == now
