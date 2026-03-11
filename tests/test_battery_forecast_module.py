"""Tests for battery_forecast module."""

from datetime import datetime, timedelta

import pytest


# Test imports work
def test_types_import():
    """Test that types module imports correctly."""
    from custom_components.oig_cloud.battery_forecast.types import (
        CBB_MODE_HOME_I, CBB_MODE_HOME_II, CBB_MODE_HOME_III,
        CBB_MODE_HOME_UPS, CBB_MODE_NAMES, get_mode_name, is_charging_mode)

    assert CBB_MODE_HOME_I == 0
    assert CBB_MODE_HOME_II == 1
    assert CBB_MODE_HOME_III == 2
    assert CBB_MODE_HOME_UPS == 3

    assert get_mode_name(0) == "HOME I"
    assert get_mode_name(3) == "HOME UPS"

    assert is_charging_mode(3) is True
    assert is_charging_mode(0) is False


def test_simulator_basic():
    """Test basic SoC simulation."""
    from custom_components.oig_cloud.battery_forecast.physics.interval_simulator import \
        create_simulator
    from custom_components.oig_cloud.battery_forecast.types import (
        CBB_MODE_HOME_III, CBB_MODE_HOME_UPS)

    sim = create_simulator(
        max_capacity=15.0,
        min_capacity=3.0,
        charge_rate_kw=2.8,
        dc_ac_efficiency=0.88,
        ac_dc_efficiency=0.95,
        dc_dc_efficiency=0.95,
    )

    # HOME III: ALL solar → battery, load from GRID
    result = sim.simulate(
        battery_start=10.0,
        mode=CBB_MODE_HOME_III,
        solar_kwh=0.5,
        load_kwh=0.2,
    )

    assert result.battery_end > 10.0
    assert result.grid_import == pytest.approx(0.2, abs=0.01)

    # UPS charging
    result = sim.simulate(
        battery_start=10.0,
        mode=CBB_MODE_HOME_UPS,
        solar_kwh=0.0,
        load_kwh=0.2,
        force_charge=True,
    )

    assert result.battery_end > 10.0
    assert result.grid_import > 0.0


def test_simulator_timeline():
    """Test full timeline simulation via interval loop."""
    from custom_components.oig_cloud.battery_forecast.physics.interval_simulator import \
        create_simulator
    from custom_components.oig_cloud.battery_forecast.types import (
        CBB_MODE_HOME_III, CBB_MODE_HOME_UPS)

    sim = create_simulator(
        max_capacity=15.0,
        min_capacity=3.0,
        charge_rate_kw=2.8,
        dc_ac_efficiency=0.88,
        ac_dc_efficiency=0.95,
        dc_dc_efficiency=0.95,
    )

    modes = [
        CBB_MODE_HOME_UPS,
        CBB_MODE_HOME_UPS,
        CBB_MODE_HOME_III,
        CBB_MODE_HOME_III,
        CBB_MODE_HOME_III,
        CBB_MODE_HOME_III,
    ]
    solar = [0.0, 0.0, 0.5, 1.0, 0.5, 0.0]
    consumption = [0.2, 0.2, 0.3, 0.3, 0.3, 0.3]

    battery = 8.0
    trajectory = []
    imports = []

    for mode, solar_kwh, load_kwh in zip(modes, solar, consumption):
        trajectory.append(battery)
        result = sim.simulate(
            battery_start=battery,
            mode=mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            force_charge=mode == CBB_MODE_HOME_UPS,
        )
        imports.append(result.grid_import)
        battery = result.battery_end

    assert len(trajectory) == 6
    assert trajectory[0] == 8.0
    assert trajectory[1] >= 8.0
    assert sum(imports) > 0


def test_mode_selector():
    """Test mode selection logic via HybridStrategy."""
    from custom_components.oig_cloud.battery_forecast.config import (
        HybridConfig, SimulatorConfig)
    from custom_components.oig_cloud.battery_forecast.strategy import \
        StrategyBalancingPlan
    from custom_components.oig_cloud.battery_forecast.strategy.hybrid import \
        HybridStrategy
    from custom_components.oig_cloud.battery_forecast.types import (
        CBB_MODE_HOME_I, CBB_MODE_HOME_UPS)

    strategy = HybridStrategy(
        HybridConfig(planning_min_percent=20.0, target_percent=80.0),
        SimulatorConfig(max_capacity_kwh=15.0, min_capacity_kwh=3.0),
    )

    now = datetime.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=i * 15)).isoformat(), "price": 3.0}
        for i in range(4)
    ]
    solar = [0.0] * 4
    consumption = [0.2] * 4

    balancing_plan = StrategyBalancingPlan(
        charging_intervals={0},
        holding_intervals=set(),
        mode_overrides={},
        is_active=True,
    )
    result = strategy.optimize(
        initial_battery_kwh=10.0,
        spot_prices=spot_prices,
        solar_forecast=solar,
        consumption_forecast=consumption,
        balancing_plan=balancing_plan,
    )
    assert result.decisions[0].mode == CBB_MODE_HOME_UPS
    assert result.decisions[0].is_balancing

    result_no_bal = strategy.optimize(
        initial_battery_kwh=10.0,
        spot_prices=spot_prices,
        solar_forecast=solar,
        consumption_forecast=consumption,
        balancing_plan=None,
    )
    assert result_no_bal.decisions[0].mode == CBB_MODE_HOME_I


def test_hybrid_optimizer_basic():
    """Test HYBRID strategy basic functionality."""
    from custom_components.oig_cloud.battery_forecast.config import (
        HybridConfig, SimulatorConfig)
    from custom_components.oig_cloud.battery_forecast.strategy.hybrid import \
        HybridStrategy

    strategy = HybridStrategy(
        HybridConfig(planning_min_percent=20.0, target_percent=80.0),
        SimulatorConfig(max_capacity_kwh=15.0, min_capacity_kwh=3.0),
    )

    now = datetime.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=i * 15)).isoformat(), "price": 3.0 + (i % 4)}
        for i in range(24)
    ]
    solar = [0.0] * 8 + [0.5, 1.0, 1.5, 1.5, 1.0, 0.5] + [0.0] * 10
    consumption = [0.2] * 24

    result = strategy.optimize(
        initial_battery_kwh=10.0,
        spot_prices=spot_prices,
        solar_forecast=solar,
        consumption_forecast=consumption,
    )

    assert len(result.modes) == 24
    assert result.total_cost_czk >= 0
    assert "HOME I" in result.mode_counts


def test_balancing_executor():
    """Test balancing executor."""
    from zoneinfo import ZoneInfo

    from custom_components.oig_cloud.battery_forecast.balancing.executor import \
        BalancingExecutor

    executor = BalancingExecutor(
        max_capacity=15.0,
        charge_rate_kw=2.8,
    )

    tz = ZoneInfo("Europe/Prague")
    now = datetime.now(tz)

    plan = executor.parse_plan(
        {
            "holding_start": (now + timedelta(hours=3)).isoformat(),
            "holding_end": (now + timedelta(hours=6)).isoformat(),
            "charging_intervals": [],
            "reason": "test",
        }
    )

    assert plan is not None
    assert plan.reason == "test"

    modes = [0] * 24
    spot_prices = [
        {"time": (now + timedelta(minutes=i * 15)).isoformat(), "price": 3.0}
        for i in range(24)
    ]

    result = executor.apply_balancing(
        modes=modes,
        spot_prices=spot_prices,
        current_battery=10.0,
        balancing_plan={
            "holding_start": (now + timedelta(hours=2)).isoformat(),
            "holding_end": (now + timedelta(hours=4)).isoformat(),
        },
    )

    assert result.total_ups_added > 0
    assert len(result.holding_intervals) > 0


def test_timeline_builder():
    """Test timeline builder."""
    from custom_components.oig_cloud.battery_forecast.timeline.planner import \
        build_planner_timeline

    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    spot_prices = [
        {"time": (now + timedelta(minutes=i * 15)).isoformat(), "price": 3.0}
        for i in range(4)
    ]
    export_prices = [
        {"time": entry["time"], "price": 2.0} for entry in spot_prices
    ]
    solar_forecast = {"today": {now.isoformat(): 2.0}}

    timeline = build_planner_timeline(
        modes=[0, 0, 2, 2],
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast=solar_forecast,
        load_forecast=[0.2, 0.2, 0.2, 0.2],
        current_capacity=10.0,
        max_capacity=15.0,
        hw_min_capacity=3.0,
        efficiency=0.9,
        home_charge_rate_kw=2.8,
    )

    assert len(timeline) == 4
    assert timeline[0]["mode"] == 0


def test_strategy_to_timeline():
    """Test strategy output feeds timeline builder."""
    from custom_components.oig_cloud.battery_forecast.config import (
        HybridConfig, SimulatorConfig)
    from custom_components.oig_cloud.battery_forecast.strategy.hybrid import \
        HybridStrategy
    from custom_components.oig_cloud.battery_forecast.timeline.planner import \
        build_planner_timeline

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    spot_prices = [
        {"time": (now + timedelta(minutes=i * 15)).isoformat(), "price": 2.5}
        for i in range(8)
    ]
    export_prices = [
        {"time": entry["time"], "price": 2.0} for entry in spot_prices
    ]
    solar_forecast = {"today": {now.isoformat(): 1.6}}
    load_forecast = [0.2] * 8

    strategy = HybridStrategy(
        HybridConfig(planning_min_percent=20.0, target_percent=80.0),
        SimulatorConfig(max_capacity_kwh=15.0, min_capacity_kwh=3.0),
    )

    result = strategy.optimize(
        initial_battery_kwh=8.0,
        spot_prices=spot_prices,
        solar_forecast=[0.0] * 8,
        consumption_forecast=load_forecast,
    )

    timeline = build_planner_timeline(
        modes=result.modes,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast=solar_forecast,
        load_forecast=load_forecast,
        current_capacity=8.0,
        max_capacity=15.0,
        hw_min_capacity=3.0,
        efficiency=0.9,
        home_charge_rate_kw=2.8,
    )

    assert len(timeline) == len(result.modes)
    assert timeline[0]["mode"] == result.modes[0]
