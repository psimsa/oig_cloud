from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.planning import charging_plan


def test_smart_charging_plan_critical_filters(monkeypatch):
    now = datetime.now()
    timeline = [
        {
            "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 10.0 if i == 0 else 1.0,
            "battery_capacity_kwh": 9.9 if i == 1 else 0.5,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(3)
    ]

    monkeypatch.setattr(
        charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None
    )

    charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=2.0,
        target_capacity=3.0,
        max_price=5.0,
        price_threshold=4.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert timeline[0]["grid_charge_kwh"] == 0.0
    assert timeline[1]["grid_charge_kwh"] == 0.0


def test_smart_charging_plan_critical_candidate_filters(monkeypatch):
    now = datetime.now()
    timeline = [
        {
            "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 10.0 if i == 0 else 1.0,
            "battery_capacity_kwh": 9.95 if i == 1 else 3.0 if i == 0 else 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(3)
    ]

    monkeypatch.setattr(
        charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None
    )

    charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=2.0,
        target_capacity=3.0,
        max_price=5.0,
        price_threshold=4.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert timeline[0]["grid_charge_kwh"] == 0.0
    assert timeline[1]["grid_charge_kwh"] == 0.0
