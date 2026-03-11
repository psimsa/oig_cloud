from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.planning import charging_plan


def _timeline_point(ts: str, battery: float, price: float = 2.0):
    return {
        "timestamp": ts,
        "battery_capacity_kwh": battery,
        "spot_price_czk": price,
        "grid_charge_kwh": 0.0,
        "reason": "normal",
    }


def test_economic_charging_plan_skip_low_savings(monkeypatch):
    timeline = [_timeline_point("2025-01-01T00:00:00", 5.0)]

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
        return {"total_charging_cost": 1.01, "min_soc": 2.0, "death_valley_reached": False}

    monkeypatch.setattr(charging_plan, "simulate_forward", _simulate_forward)
    monkeypatch.setattr(charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    result_timeline, _ = charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.5,
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

    assert result_timeline[0]["grid_charge_kwh"] == 0.0


def test_economic_charging_plan_protection_no_candidates(monkeypatch):
    timeline = [_timeline_point("2025-01-01T00:00:00", 1.0)]

    monkeypatch.setattr(
        charging_plan, "calculate_protection_requirement", lambda *_a, **_k: 2.0
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
        enable_blackout_protection=True,
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

    assert metrics == {}
    assert result_timeline[0]["grid_charge_kwh"] == 0.0


def test_economic_charging_plan_protection_breaks_early(monkeypatch):
    timeline = [
        _timeline_point("2025-01-01T00:00:00", 0.0),
        _timeline_point("2025-01-01T00:15:00", 0.0),
    ]

    monkeypatch.setattr(
        charging_plan, "calculate_protection_requirement", lambda *_a, **_k: 0.25
    )
    monkeypatch.setattr(
        charging_plan,
        "get_candidate_intervals",
        lambda *_a, **_k: [
            {"index": 0, "price": 1.0, "timestamp": "t"},
            {"index": 1, "price": 1.0, "timestamp": "t2"},
        ],
    )
    monkeypatch.setattr(charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.1,
        charging_power_kw=1.0,
        max_capacity=10.0,
        enable_blackout_protection=True,
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


def test_smart_charging_plan_target_loop_and_filters(monkeypatch):
    now = datetime.now()
    timeline = [
        {
            "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 10.0 if i == 0 else 1.0,
            "battery_capacity_kwh": 9.9 if i == 1 else 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(4)
    ]
    timeline[-1]["grid_charge_kwh"] = 1.0

    monkeypatch.setattr(
        charging_plan, "recalculate_timeline_from_index", lambda *_a, **_k: None
    )

    _, metrics = charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=2.0,
        target_capacity=10.0,
        max_price=5.0,
        price_threshold=4.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )

    assert metrics["effective_target_kwh"] <= 9.9


def test_smart_charging_plan_hits_max_iterations(monkeypatch):
    now = datetime.now()
    timeline = [
        {
            "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 1.0,
            "battery_capacity_kwh": 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(3)
    ]

    def _reset(_timeline, idx, **_k):
        _timeline[idx]["grid_charge_kwh"] = 0.0

    monkeypatch.setattr(charging_plan, "recalculate_timeline_from_index", _reset)

    charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=0.5,
        target_capacity=10.0,
        max_price=5.0,
        price_threshold=4.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
