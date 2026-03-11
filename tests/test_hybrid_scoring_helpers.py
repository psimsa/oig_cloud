from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.strategy import hybrid_scoring as module
from custom_components.oig_cloud.battery_forecast.config import (
    ChargingStrategy,
    NegativePriceStrategy,
)
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


class DummySim:
    def simulate(self, *, battery_start, mode, solar_kwh, load_kwh):
        return SimpleNamespace(
            battery_end=battery_start + (solar_kwh - load_kwh),
            solar_used_direct=solar_kwh,
        )

    def calculate_cost(self, _result, price, export_price):
        return price - export_price


class DummyConfig:
    weight_cost = 1.0
    weight_battery_preservation = 1.0
    weight_self_consumption = 1.0
    charging_strategy = ChargingStrategy.OPPORTUNISTIC
    max_ups_price_czk = 3.0
    min_mode_duration_intervals = 2
    negative_price_strategy = NegativePriceStrategy.CONSUME


class DummyStrategy:
    LOOKAHEAD_INTERVALS = 4
    MIN_PRICE_SPREAD_PERCENT = 10

    def __init__(self):
        self.sim_config = SimpleNamespace(ac_dc_efficiency=0.9, dc_ac_efficiency=0.9)
        self.simulator = DummySim()
        self.config = DummyConfig()
        self._planning_min = 20.0
        self._target = 50.0
        self._max = 100.0


def test_extract_prices():
    prices = module.extract_prices([{"price": 1.0}, 2.0, {"price": 3.5}])
    assert prices == [1.0, 2.0, 3.5]


def test_analyze_future_prices_negative():
    strategy = DummyStrategy()
    analysis = module.analyze_future_prices(
        strategy,
        prices=[-1.0, -2.0, -3.0, -4.0],
        export_prices=[0.0, 0.0, 0.0, 0.0],
        consumption_forecast=[0.1] * 4,
    )
    assert analysis[0]["should_charge"] is True
    assert analysis[0]["charge_reason"] == "negative_price"


def test_handle_negative_price_variants():
    strategy = DummyStrategy()
    strategy.config.negative_price_strategy = NegativePriceStrategy.CHARGE_GRID
    mode, reason = module.handle_negative_price(strategy, battery=10, solar=0, load=0, price=-1, export_price=0)
    assert mode == CBB_MODE_HOME_UPS
    assert reason == "negative_price_charge"

    strategy.config.negative_price_strategy = NegativePriceStrategy.CURTAIL
    mode, reason = module.handle_negative_price(strategy, battery=10, solar=1, load=0, price=-1, export_price=0)
    assert mode == CBB_MODE_HOME_III
    assert reason == "negative_price_curtail"


def test_apply_smoothing_merges_short_runs():
    strategy = DummyStrategy()
    decisions = [
        SimpleNamespace(mode=CBB_MODE_HOME_I, mode_name="HOME I", reason="base", is_balancing=False, is_holding=False),
        SimpleNamespace(mode=CBB_MODE_HOME_UPS, mode_name="UPS", reason="short", is_balancing=False, is_holding=False),
        SimpleNamespace(mode=CBB_MODE_HOME_I, mode_name="HOME I", reason="base", is_balancing=False, is_holding=False),
    ]
    smoothed = module.apply_smoothing(
        strategy,
        decisions=decisions,
        solar_forecast=[],
        consumption_forecast=[],
        prices=[],
        export_prices=[],
    )
    assert smoothed[1].mode == CBB_MODE_HOME_I
    assert smoothed[1].reason == "smoothing_merged"


def test_score_mode_ups_penalized_when_disabled():
    strategy = DummyStrategy()
    strategy.config.charging_strategy = ChargingStrategy.DISABLED

    score_ups = module.score_mode(
        strategy,
        mode=CBB_MODE_HOME_UPS,
        battery=30.0,
        solar=0.0,
        load=0.5,
        price=4.0,
        export_price=0.0,
        cheap_threshold=2.0,
    )
    score_home = module.score_mode(
        strategy,
        mode=CBB_MODE_HOME_I,
        battery=30.0,
        solar=0.0,
        load=0.5,
        price=4.0,
        export_price=0.0,
        cheap_threshold=2.0,
    )
    assert score_ups < score_home


def test_calculate_baseline_cost():
    strategy = DummyStrategy()
    total = module.calculate_baseline_cost(
        strategy,
        initial_battery=10.0,
        solar_forecast=[0.1, 0.1],
        consumption_forecast=[0.2, 0.2],
        prices=[1.0, 2.0],
        export_prices=[0.0, 0.0],
    )
    assert total == 3.0
