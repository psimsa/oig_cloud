from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.planning import scenario_analysis
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


class DummySensor:
    def __init__(self):
        self._log_rate_limited = None

    def _get_battery_efficiency(self):
        return 1.0

    def _get_current_mode(self):
        return CBB_MODE_HOME_II


def test_simulate_interval_uses_planning_min(monkeypatch):
    def _simulate(**kwargs):
        return SimpleNamespace(
            new_soc_kwh=2.0,
            grid_import_kwh=1.0,
            grid_export_kwh=0.0,
            battery_charge_kwh=0.5,
            battery_discharge_kwh=0.2,
        )

    monkeypatch.setattr(
        scenario_analysis, "physics_simulate_interval", _simulate
    )
    result = scenario_analysis.simulate_interval(
        mode=CBB_MODE_HOME_I,
        solar_kwh=1.0,
        load_kwh=1.0,
        battery_soc_kwh=2.0,
        capacity_kwh=5.0,
        hw_min_capacity_kwh=1.0,
        spot_price_czk=2.0,
        export_price_czk=1.0,
        planning_min_capacity_kwh=2.0,
    )
    assert result["net_cost_czk"] == 2.0


def test_calculate_interval_cost_opportunity():
    result = scenario_analysis.calculate_interval_cost(
        {"net_cost": 1.0, "battery_discharge": 1.0},
        spot_price=2.0,
        export_price=0.5,
        time_of_day="night",
    )
    assert result["opportunity_cost"] > 0


@pytest.mark.asyncio
async def test_calculate_fixed_mode_cost_with_penalty(monkeypatch):
    sensor = DummySensor()
    spot_prices = [{"time": "2025-01-01T00:00:00", "price": 2.0}]
    export_prices = [{"price": 0.5}]

    async def _solar(*_a, **_k):
        return 0.0

    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )

    calls = {"count": 0}

    def _simulate(**kwargs):
        calls["count"] += 1
        return {
            "new_soc_kwh": 0.0,
            "grid_import_kwh": 1.0,
            "grid_export_kwh": 0.0,
            "net_cost_czk": 2.0,
        }

    monkeypatch.setattr(scenario_analysis, "simulate_interval", _simulate)

    result = scenario_analysis.calculate_fixed_mode_cost(
        sensor,
        fixed_mode=CBB_MODE_HOME_I,
        current_capacity=2.0,
        max_capacity=5.0,
        min_capacity=1.0,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast={},
        load_forecast=[1.0],
        physical_min_capacity=1.0,
    )
    assert result["planning_violations"] == 1
    assert result["adjusted_total_cost"] >= result["total_cost"]


@pytest.mark.asyncio
async def test_calculate_fixed_mode_cost_bad_timestamp(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )
    monkeypatch.setattr(
        scenario_analysis,
        "simulate_interval",
        lambda **_k: {"net_cost_czk": 0.0, "new_soc_kwh": 1.0},
    )

    result = scenario_analysis.calculate_fixed_mode_cost(
        sensor,
        fixed_mode=CBB_MODE_HOME_I,
        current_capacity=1.0,
        max_capacity=5.0,
        min_capacity=1.0,
        spot_prices=[{"time": "bad", "price": 1.0}],
        export_prices=[{"price": 0.0}],
        solar_forecast={},
        load_forecast=[0.0],
        physical_min_capacity=1.0,
    )
    assert result["total_cost"] == 0.0


def test_calculate_mode_baselines(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis,
        "calculate_fixed_mode_cost",
        lambda *_a, **_k: {
            "total_cost": 1.0,
            "grid_import_kwh": 0.0,
            "final_battery_kwh": 1.0,
            "penalty_cost": 0.0,
            "planning_violations": 0,
            "adjusted_total_cost": 1.0,
        },
    )
    baselines = scenario_analysis.calculate_mode_baselines(
        sensor,
        current_capacity=1.0,
        max_capacity=5.0,
        physical_min_capacity=1.0,
        spot_prices=[],
        export_prices=[],
        solar_forecast={},
        load_forecast=[],
    )
    assert "HOME_I" in baselines
    assert "HOME_UPS" in baselines


def test_calculate_mode_baselines_with_penalty(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis,
        "calculate_fixed_mode_cost",
        lambda *_a, **_k: {
            "total_cost": 1.0,
            "grid_import_kwh": 0.0,
            "final_battery_kwh": 1.0,
            "penalty_cost": 1.0,
            "planning_violations": 1,
            "adjusted_total_cost": 2.0,
        },
    )
    baselines = scenario_analysis.calculate_mode_baselines(
        sensor,
        current_capacity=1.0,
        max_capacity=5.0,
        physical_min_capacity=1.0,
        spot_prices=[],
        export_prices=[],
        solar_forecast={},
        load_forecast=[],
    )
    assert baselines["HOME_I"]["planning_violations"] == 1


@pytest.mark.asyncio
async def test_calculate_do_nothing_cost(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )
    monkeypatch.setattr(
        scenario_analysis,
        "simulate_interval",
        lambda **_k: {"net_cost_czk": 1.0, "new_soc_kwh": 1.0},
    )
    cost = scenario_analysis.calculate_do_nothing_cost(
        sensor,
        current_capacity=1.0,
        max_capacity=5.0,
        min_capacity=1.0,
        spot_prices=[{"time": "2025-01-01T00:00:00", "price": 1.0}],
        export_prices=[{"price": 0.0}],
        solar_forecast={},
        load_forecast=[0.5],
    )
    assert cost == 1.0


@pytest.mark.asyncio
async def test_calculate_do_nothing_cost_bad_timestamp(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis,
        "simulate_interval",
        lambda **_k: {"net_cost_czk": 0.0, "new_soc_kwh": 1.0},
    )
    cost = scenario_analysis.calculate_do_nothing_cost(
        sensor,
        current_capacity=1.0,
        max_capacity=5.0,
        min_capacity=1.0,
        spot_prices=[{"time": "bad", "price": 1.0}],
        export_prices=[{"price": 0.0}],
        solar_forecast={},
        load_forecast=[0.5],
    )
    assert cost == 0.0


@pytest.mark.asyncio
async def test_calculate_full_ups_cost(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )
    monkeypatch.setattr(
        scenario_analysis,
        "simulate_interval",
        lambda **_k: {"net_cost_czk": 1.0, "new_soc_kwh": 1.0},
    )

    spot_prices = [
        {"time": "2025-01-01T23:00:00", "price": 0.5},
        {"time": "2025-01-02T01:00:00", "price": 1.0},
    ]
    export_prices = [{"price": 0.0}, {"price": 0.0}]
    cost = scenario_analysis.calculate_full_ups_cost(
        sensor,
        current_capacity=1.0,
        max_capacity=2.4,
        min_capacity=1.0,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast={},
        load_forecast=[0.1, 0.1],
    )
    assert cost == 2.0


@pytest.mark.asyncio
async def test_calculate_full_ups_cost_bad_timestamp(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )
    monkeypatch.setattr(
        scenario_analysis,
        "simulate_interval",
        lambda **_k: {"net_cost_czk": 0.0, "new_soc_kwh": 1.0},
    )
    cost = scenario_analysis.calculate_full_ups_cost(
        sensor,
        current_capacity=1.0,
        max_capacity=2.0,
        min_capacity=1.0,
        spot_prices=[{"time": "bad", "price": 1.0}],
        export_prices=[{"price": 0.0}],
        solar_forecast={},
        load_forecast=[0.1],
    )
    assert cost == 0.0


def test_generate_alternatives(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 0, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.dt_util.now",
        lambda: fixed_now,
    )
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )

    spot_prices = [
        {"time": fixed_now.isoformat(), "price": 1.0},
        {"time": "", "price": 2.0},
    ]
    alternatives = scenario_analysis.generate_alternatives(
        sensor,
        spot_prices=spot_prices,
        solar_forecast={},
        load_forecast=[0.2, 0.2],
        optimal_cost_48h=1.0,
        current_capacity=1.0,
        max_capacity=2.0,
        efficiency=1.0,
    )
    assert "HOME I" in alternatives
    assert "DO NOTHING" in alternatives


def test_generate_alternatives_bad_timestamp(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 0, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.dt_util.now",
        lambda: fixed_now,
    )
    monkeypatch.setattr(
        scenario_analysis, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )

    spot_prices = [
        {"time": "bad", "price": 1.0},
        {"time": fixed_now.isoformat(), "price": 2.0},
    ]
    alternatives = scenario_analysis.generate_alternatives(
        sensor,
        spot_prices=spot_prices,
        solar_forecast={},
        load_forecast=[0.2, 0.2],
        optimal_cost_48h=1.0,
        current_capacity=1.0,
        max_capacity=2.0,
        efficiency=1.0,
    )
    assert alternatives["HOME I"]["cost_czk"] >= 0.0


def test_generate_alternatives_branches(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 0, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.dt_util.now",
        lambda: fixed_now,
    )

    def _solar(ts, *_a, **_k):
        if ts.hour == 0:
            return 5.0
        if ts.hour == 1:
            return 0.0
        raise RuntimeError("boom")

    monkeypatch.setattr(scenario_analysis, "get_solar_for_timestamp", _solar)

    spot_prices = [
        {"time": fixed_now.isoformat(), "price": 1.0},
        {"time": (fixed_now + timedelta(hours=1)).isoformat(), "price": 2.0},
        {"time": (fixed_now + timedelta(hours=2)).isoformat(), "price": 0.5},
        {"time": (fixed_now + timedelta(days=3)).isoformat(), "price": 1.0},
    ]
    alternatives = scenario_analysis.generate_alternatives(
        sensor,
        spot_prices=spot_prices,
        solar_forecast={},
        load_forecast=[0.5, 6.0, 0.5, 0.5],
        optimal_cost_48h=1.0,
        current_capacity=1.0,
        max_capacity=2.0,
        efficiency=1.0,
    )
    assert alternatives["HOME I"]["cost_czk"] >= 0.0
