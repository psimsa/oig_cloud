from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.oig_cloud.battery_forecast.planning import charging_plan


def _timeline_point(ts: str, battery: float, price: float = 2.0):
    return {
        "timestamp": ts,
        "battery_capacity_kwh": battery,
        "spot_price_czk": price,
        "grid_charge_kwh": 0.0,
        "reason": "normal",
    }


def test_economic_charging_plan_no_candidates(monkeypatch):
    timeline = [_timeline_point("2025-01-01T00:00:00", 5.0)]

    monkeypatch.setattr(
        charging_plan, "calculate_protection_requirement", lambda *_a, **_k: None
    )
    monkeypatch.setattr(charging_plan, "get_candidate_intervals", lambda *_a, **_k: [])

    result_timeline, metrics = charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.1,
        charging_power_kw=2.0,
        max_capacity=10.0,
        enable_blackout_protection=False,
        blackout_protection_hours=2,
        blackout_target_soc_percent=20.0,
        enable_weather_risk=False,
        weather_risk_level="low",
        weather_target_soc_percent=30.0,
        target_reason="test",
        battery_efficiency=1.0,
        config={},
        iso_tz_offset="+00:00",
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert result_timeline == timeline
    assert metrics == {}


def test_economic_charging_plan_death_valley_fix(monkeypatch):
    timeline = [
        _timeline_point("2025-01-01T00:00:00", 5.0),
        _timeline_point("2025-01-01T00:15:00", 4.0),
    ]

    monkeypatch.setattr(
        charging_plan, "calculate_protection_requirement", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        charging_plan,
        "get_candidate_intervals",
        lambda *_a, **_k: [{"index": 0, "price": 2.0, "timestamp": "t"}],
    )

    def _simulate_forward(*_a, **kwargs):
        if kwargs.get("charge_now"):
            return {"total_charging_cost": 1.0}
        return {"total_charging_cost": 10.0, "min_soc": 0.0, "death_valley_reached": True}

    monkeypatch.setattr(charging_plan, "simulate_forward", _simulate_forward)
    monkeypatch.setattr(charging_plan, "calculate_minimum_charge", lambda *_a, **_k: 0.5)
    monkeypatch.setattr(charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    result_timeline, _ = charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.1,
        charging_power_kw=2.0,
        max_capacity=10.0,
        enable_blackout_protection=False,
        blackout_protection_hours=2,
        blackout_target_soc_percent=20.0,
        enable_weather_risk=False,
        weather_risk_level="low",
        weather_target_soc_percent=30.0,
        target_reason="test",
        battery_efficiency=1.0,
        config={},
        iso_tz_offset="+00:00",
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert result_timeline[0]["reason"] == "death_valley_fix"
    assert result_timeline[0]["grid_charge_kwh"] > 0


def test_economic_charging_plan_economic_charge(monkeypatch):
    timeline = [
        _timeline_point("2025-01-01T00:00:00", 5.0),
        _timeline_point("2025-01-01T00:15:00", 4.0),
    ]

    monkeypatch.setattr(
        charging_plan, "calculate_protection_requirement", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        charging_plan,
        "get_candidate_intervals",
        lambda *_a, **_k: [{"index": 0, "price": 1.0, "timestamp": "t"}],
    )

    def _simulate_forward(*_a, **kwargs):
        if kwargs.get("charge_now"):
            return {"total_charging_cost": 1.0}
        return {"total_charging_cost": 2.0, "min_soc": 2.0, "death_valley_reached": False}

    monkeypatch.setattr(charging_plan, "simulate_forward", _simulate_forward)
    monkeypatch.setattr(charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    result_timeline, metrics = charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.1,
        charging_power_kw=2.0,
        max_capacity=10.0,
        enable_blackout_protection=False,
        blackout_protection_hours=2,
        blackout_target_soc_percent=20.0,
        enable_weather_risk=False,
        weather_risk_level="low",
        weather_target_soc_percent=30.0,
        target_reason="test",
        battery_efficiency=1.0,
        config={},
        iso_tz_offset="+00:00",
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert result_timeline[0]["reason"] == "economic_charge"
    assert metrics["algorithm"] == "economic"


def test_smart_charging_plan_critical_fix(monkeypatch):
    now = datetime.now()
    timeline = [
        {
            "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 1.0,
            "battery_capacity_kwh": 0.0 if i == 2 else 5.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(4)
    ]

    monkeypatch.setattr(
        charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None
    )

    result_timeline, metrics = charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=1.0,
        target_capacity=5.0,
        max_price=5.0,
        price_threshold=4.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert "target_capacity_kwh" in metrics
    assert any(point["grid_charge_kwh"] > 0 for point in result_timeline)
