from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.config import NegativePriceStrategy
from custom_components.oig_cloud.battery_forecast.strategy import hybrid_planning as module
from custom_components.oig_cloud.battery_forecast.strategy.balancing import (
    StrategyBalancingPlan,
)


class DummySim:
    def simulate(self, *, battery_start, mode, solar_kwh, load_kwh, force_charge):
        _ = mode
        _ = force_charge
        return SimpleNamespace(battery_end=battery_start + solar_kwh - load_kwh)


class DummyConfig:
    max_ups_price_czk = 1.0
    min_ups_duration_intervals = 2
    negative_price_strategy = NegativePriceStrategy.CHARGE_GRID


class DummySimConfig:
    ac_dc_efficiency = 0.9


class DummyStrategy:
    MAX_ITERATIONS = 3
    MIN_UPS_PRICE_BAND_PCT = 0.08

    def __init__(self):
        self.config = DummyConfig()
        self.sim_config = DummySimConfig()
        self.simulator = DummySim()
        self._planning_min = 2.0
        self._target = 3.0


def test_get_price_band_delta_pct_invalid_efficiency():
    strategy = DummyStrategy()
    strategy.sim_config.ac_dc_efficiency = None
    assert module.get_price_band_delta_pct(strategy) == strategy.MIN_UPS_PRICE_BAND_PCT
    strategy.sim_config.ac_dc_efficiency = 2.0
    assert module.get_price_band_delta_pct(strategy) == strategy.MIN_UPS_PRICE_BAND_PCT


def test_extend_ups_blocks_by_price_band_blocked():
    strategy = DummyStrategy()
    extended = module.extend_ups_blocks_by_price_band(
        strategy,
        charging_intervals={0},
        prices=[0.5, 0.6, 0.7],
        blocked_indices={1},
    )
    assert extended == set()


def test_plan_charging_intervals_recovery_infeasible():
    strategy = DummyStrategy()
    strategy.config.max_ups_price_czk = 0.1
    charging, reason, _ = module.plan_charging_intervals(
        strategy,
        initial_battery_kwh=0.0,
        prices=[1.0, 1.0],
        solar_forecast=[0.0, 0.0],
        consumption_forecast=[0.5, 0.5],
        balancing_plan=None,
        negative_price_intervals=None,
    )
    assert charging
    assert reason


def test_plan_charging_intervals_negative_prices_and_blocked():
    strategy = DummyStrategy()
    balancing_plan = StrategyBalancingPlan(
        charging_intervals=set(),
        holding_intervals=set(),
        mode_overrides={0: 0},
        is_active=True,
    )
    charging, reason, _ = module.plan_charging_intervals(
        strategy,
        initial_battery_kwh=5.0,
        prices=[-1.0],
        solar_forecast=[0.0],
        consumption_forecast=[0.0],
        balancing_plan=balancing_plan,
        negative_price_intervals=[0],
    )
    assert charging == set()
    assert reason is None


def test_plan_charging_intervals_price_band_extension(monkeypatch):
    strategy = DummyStrategy()
    strategy.config.negative_price_strategy = NegativePriceStrategy.CONSUME

    monkeypatch.setattr(
        module,
        "extend_ups_blocks_by_price_band",
        lambda *_a, **_k: {1},
    )

    charging, reason, price_band = module.plan_charging_intervals(
        strategy,
        initial_battery_kwh=5.0,
        prices=[0.5, 0.5],
        solar_forecast=[0.0, 0.0],
        consumption_forecast=[0.0, 0.0],
        balancing_plan=None,
        negative_price_intervals=None,
    )
    assert reason is None
    assert price_band == {1}
    assert 1 in charging
