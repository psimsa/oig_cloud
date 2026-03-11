from __future__ import annotations

from custom_components.oig_cloud.battery_forecast.planning import (
    charging_plan_adjustments as module,
)


def _timeline(prices, capacities):
    return [
        {
            "spot_price_czk": price,
            "battery_capacity_kwh": cap,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for price, cap in zip(prices, capacities)
    ]


def test_find_first_minimum_violation():
    timeline = _timeline([1.0, 2.0], [5.0, 0.5])
    assert module.find_first_minimum_violation(timeline, 1.0) == 1
    assert module.find_first_minimum_violation(timeline, 0.1) is None


def test_find_cheapest_hour_before_filters():
    timeline = _timeline([10.0, 2.0, 1.0], [5.0, 5.0, 5.0])
    timeline[1]["grid_charge_kwh"] = 1.0
    assert module.find_cheapest_hour_before(timeline, 2, 5.0, 4.0) is None


def test_fix_minimum_capacity_no_candidate(monkeypatch):
    timeline = _timeline([10.0, 9.0], [0.5, 0.5])
    result = module.fix_minimum_capacity_violations(
        timeline=timeline,
        min_capacity=1.0,
        max_price=1.0,
        price_threshold=1.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result == timeline


def test_ensure_target_capacity_no_candidate():
    timeline = _timeline([10.0, 9.0], [0.5, 0.5])
    result = module.ensure_target_capacity_at_end(
        timeline=timeline,
        target_capacity=5.0,
        max_price=1.0,
        price_threshold=1.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        min_capacity=1.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result == timeline


def test_ensure_target_capacity_empty_timeline():
    timeline = []
    result = module.ensure_target_capacity_at_end(
        timeline=timeline,
        target_capacity=5.0,
        max_price=1.0,
        price_threshold=1.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        min_capacity=1.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result == []


def test_ensure_target_capacity_already_met():
    timeline = _timeline([1.0], [5.0])
    result = module.ensure_target_capacity_at_end(
        timeline=timeline,
        target_capacity=2.0,
        max_price=5.0,
        price_threshold=5.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        min_capacity=1.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result[0]["grid_charge_kwh"] == 0.0


def test_find_cheapest_suitable_hour():
    timeline = _timeline([5.0, 2.0, 3.0], [5.0, 5.0, 5.0])
    idx = module.find_cheapest_suitable_hour(timeline, max_price=4.0, price_threshold=4.0)
    assert idx == 1


def test_find_cheapest_hour_before_returns_best():
    timeline = _timeline([3.0, 1.0, 2.0], [5.0, 5.0, 5.0])
    idx = module.find_cheapest_hour_before(timeline, 3, max_price=4.0, price_threshold=4.0)
    assert idx == 1


def test_find_cheapest_hour_before_price_threshold_excludes():
    timeline = _timeline([3.5, 3.1], [5.0, 5.0])
    assert (
        module.find_cheapest_hour_before(timeline, 2, max_price=5.0, price_threshold=3.0)
        is None
    )


def test_find_cheapest_suitable_hour_price_threshold_excludes():
    timeline = _timeline([3.5, 3.1], [5.0, 5.0])
    assert (
        module.find_cheapest_suitable_hour(timeline, max_price=5.0, price_threshold=3.0)
        is None
    )


def test_fix_minimum_capacity_hits_max_iterations(monkeypatch):
    timeline = _timeline([1.0, 1.0], [0.5, 0.5])

    monkeypatch.setattr(module, "find_first_minimum_violation", lambda *_a, **_k: 0)
    monkeypatch.setattr(module, "find_cheapest_hour_before", lambda *_a, **_k: 0)
    monkeypatch.setattr(module, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    result = module.fix_minimum_capacity_violations(
        timeline=timeline,
        min_capacity=1.0,
        max_price=5.0,
        price_threshold=5.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result[0]["grid_charge_kwh"] > 0


def test_ensure_target_capacity_hits_max_iterations(monkeypatch):
    timeline = _timeline([1.0], [0.0])

    monkeypatch.setattr(module, "find_cheapest_suitable_hour", lambda *_a, **_k: 0)
    monkeypatch.setattr(module, "recalculate_timeline_from_index", lambda *_a, **_k: None)

    result = module.ensure_target_capacity_at_end(
        timeline=timeline,
        target_capacity=10.0,
        max_price=5.0,
        price_threshold=5.0,
        charging_power_kw=2.0,
        max_capacity=10.0,
        min_capacity=0.0,
        efficiency=1.0,
        mode_label_home_ups="UPS",
        mode_label_home_i="I",
    )
    assert result[0]["grid_charge_kwh"] > 0
