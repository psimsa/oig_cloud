from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.config import SimulatorConfig
from custom_components.oig_cloud.battery_forecast.physics import interval_simulator
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


def test_interval_result_properties():
    result = interval_simulator.IntervalResult(
        battery_end=5.0,
        grid_import=2.0,
        grid_export=0.5,
        battery_charge=1.2,
        battery_discharge=0.4,
        solar_used_direct=0.0,
        solar_to_battery=0.0,
        solar_exported=0.0,
        solar_curtailed=0.0,
    )
    assert round(result.net_battery_change, 2) == 0.8
    assert result.net_grid_flow == 1.5


def test_simulate_uses_shared_simulator(monkeypatch):
    config = SimulatorConfig(max_capacity_kwh=5.0, min_capacity_kwh=1.0)
    sim = interval_simulator.IntervalSimulator(config)

    class DummyFlows:
        new_soc_kwh = 3.0
        grid_import_kwh = 1.0
        grid_export_kwh = 0.2
        solar_charge_kwh = 0.5
        grid_charge_kwh = 0.4
        battery_charge_kwh = 0.6
        battery_discharge_kwh = 0.3

    monkeypatch.setattr(
        interval_simulator, "simulate_interval", lambda **_k: DummyFlows()
    )

    res = sim.simulate(2.0, CBB_MODE_HOME_I, 1.0, 0.5)
    assert res.solar_used_direct == 0.5

    res = sim.simulate(2.0, CBB_MODE_HOME_III, 1.0, 0.5)
    assert res.solar_used_direct == 0.0


def test_discharge_for_load():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=2.0)

    battery, discharge, grid = sim._discharge_for_load(2.0, 1.0)
    assert discharge == 0.0
    assert grid == 1.0

    battery, discharge, grid = sim._discharge_for_load(4.0, 1.0)
    assert grid == 0.0
    assert discharge > 0.0

    battery, discharge, grid = sim._discharge_for_load(3.0, 5.0)
    assert grid > 0.0
    assert battery == sim._min


def test_simulate_home_i_day_and_night():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=1.0)
    day = sim._simulate_home_i(4.9, solar_kwh=2.0, load_kwh=1.0)
    assert day.grid_export >= 0.0
    assert day.solar_used_direct == 1.0

    deficit = sim._simulate_home_i(2.0, solar_kwh=0.5, load_kwh=1.5)
    assert deficit.grid_import >= 0.0

    night = sim._simulate_home_i(3.0, solar_kwh=0.0, load_kwh=1.0)
    assert night.grid_import >= 0.0


def test_simulate_home_ii():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=1.0)
    day = sim._simulate_home_ii(4.9, solar_kwh=2.0, load_kwh=1.0)
    assert day.solar_used_direct == 1.0

    deficit = sim._simulate_home_ii(2.0, solar_kwh=0.5, load_kwh=1.5)
    assert deficit.grid_import > 0.0

    night = sim._simulate_home_ii(3.0, solar_kwh=0.0, load_kwh=1.0)
    assert night.grid_import >= 0.0


def test_simulate_home_iii():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=1.0)
    day = sim._simulate_home_iii(4.9, solar_kwh=2.0, load_kwh=1.0)
    assert day.grid_import == 1.0

    night = sim._simulate_home_iii(3.0, solar_kwh=0.0, load_kwh=1.0)
    assert night.grid_import >= 0.0

    curtailed = sim._simulate_home_iii(4.0, solar_kwh=3.0, load_kwh=0.0)
    assert curtailed.solar_curtailed >= 0.0


def test_simulate_home_ups():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=1.0)
    res = sim._simulate_home_ups(4.0, solar_kwh=2.0, load_kwh=1.0, force_charge=True)
    assert res.grid_import >= 1.0
    assert res.battery_charge >= 0.0

    res = sim._simulate_home_ups(5.0, solar_kwh=1.0, load_kwh=0.0, force_charge=False)
    assert res.solar_exported >= 0.0

    res = sim._simulate_home_ups(4.5, solar_kwh=2.0, load_kwh=0.0, force_charge=False)
    assert res.solar_curtailed >= 0.0

    res = sim._simulate_home_ups(4.0, solar_kwh=0.0, load_kwh=0.0, force_charge=True)
    assert res.grid_import >= 0.0


def test_calculate_cost():
    sim = interval_simulator.create_simulator()
    result = interval_simulator.IntervalResult(
        battery_end=0.0,
        grid_import=2.0,
        grid_export=1.0,
        battery_charge=0.0,
        battery_discharge=0.0,
        solar_used_direct=0.0,
        solar_to_battery=0.0,
        solar_exported=0.0,
        solar_curtailed=0.0,
    )
    assert sim.calculate_cost(result, 2.0, 1.0) == 3.0


def test_simulate_home_i_and_ii_curtailed():
    sim = interval_simulator.create_simulator(max_capacity=5.0, min_capacity=1.0)
    home_i = sim._simulate_home_i(4.0, solar_kwh=3.0, load_kwh=0.0)
    assert home_i.solar_curtailed >= 0.0

    home_ii = sim._simulate_home_ii(4.0, solar_kwh=3.0, load_kwh=0.0)
    assert home_ii.solar_curtailed >= 0.0


def test_create_simulator():
    sim = interval_simulator.create_simulator(max_capacity=10.0, min_capacity=2.0)
    assert sim.config.max_capacity_kwh == 10.0
