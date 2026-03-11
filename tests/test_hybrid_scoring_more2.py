from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.config import (
    ChargingStrategy,
    NegativePriceStrategy,
)
from custom_components.oig_cloud.battery_forecast.strategy import hybrid_scoring as module
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


class DummySim:
    def simulate(self, *, battery_start, mode, solar_kwh, load_kwh):
        _ = mode
        return SimpleNamespace(
            battery_end=battery_start + solar_kwh - load_kwh,
            solar_used_direct=solar_kwh,
        )

    def calculate_cost(self, _result, price, export_price):
        return price - export_price


class DummyConfig:
    weight_cost = 1.0
    weight_battery_preservation = 1.0
    weight_self_consumption = 1.0
    charging_strategy = ChargingStrategy.BELOW_THRESHOLD
    max_ups_price_czk = 5.0
    min_mode_duration_intervals = 2
    negative_price_strategy = NegativePriceStrategy.AUTO


class DummyStrategy:
    LOOKAHEAD_INTERVALS = 4
    MIN_PRICE_SPREAD_PERCENT = 10

    def __init__(self):
        self.sim_config = SimpleNamespace(ac_dc_efficiency=0.9, dc_ac_efficiency=0.9)
        self.simulator = DummySim()
        self.config = DummyConfig()
        self._planning_min = 2.0
        self._target = 4.0
        self._max = 10.0


def test_analyze_future_prices_no_future_data():
    strategy = DummyStrategy()
    analysis = module.analyze_future_prices(
        strategy,
        prices=[1.0],
        export_prices=[0.0],
        consumption_forecast=[0.1],
    )
    assert analysis[0]["charge_reason"] == "no_future_data"


def test_analyze_future_prices_profitable_and_night():
    strategy = DummyStrategy()
    analysis = module.analyze_future_prices(
        strategy,
        prices=[1.0, 5.0, 6.0, 7.0],
        export_prices=[0.0, 0.0, 0.0, 0.0],
        consumption_forecast=[0.1] * 4,
    )
    assert analysis[0]["should_charge"] is True


def test_select_best_mode_reason_branches(monkeypatch):
    strategy = DummyStrategy()

    def _score(strategy, mode, **_k):
        return {CBB_MODE_HOME_UPS: 10, CBB_MODE_HOME_III: 5, CBB_MODE_HOME_II: 3, CBB_MODE_HOME_I: 1}[mode]

    monkeypatch.setattr(module, "score_mode", _score)
    mode, reason, _ = module.select_best_mode(
        strategy,
        battery=1.0,
        solar=2.0,
        load=1.0,
        price=0.1,
        export_price=0.0,
        cheap_threshold=1.0,
        expensive_threshold=2.0,
        very_cheap=0.2,
    )
    assert mode == CBB_MODE_HOME_UPS
    assert reason == "very_cheap_grid_charge"


def test_score_mode_branches():
    strategy = DummyStrategy()
    strategy.config.charging_strategy = ChargingStrategy.DISABLED
    score_ups = module.score_mode(
        strategy,
        mode=CBB_MODE_HOME_UPS,
        battery=5.0,
        solar=0.0,
        load=0.5,
        price=1.0,
        export_price=0.0,
        cheap_threshold=2.0,
        expected_saving=1.0,
        is_relatively_cheap=True,
    )
    assert score_ups < 0

    strategy.config.charging_strategy = ChargingStrategy.BELOW_THRESHOLD
    score_ups = module.score_mode(
        strategy,
        mode=CBB_MODE_HOME_UPS,
        battery=5.0,
        solar=0.0,
        load=0.5,
        price=1.0,
        export_price=0.0,
        cheap_threshold=2.0,
        expected_saving=1.0,
        is_relatively_cheap=True,
    )
    assert score_ups > 0


def test_handle_negative_price_auto_variants():
    strategy = DummyStrategy()
    mode, reason = module.handle_negative_price(
        strategy,
        battery=1.0,
        solar=0.0,
        load=0.0,
        price=-1.0,
        export_price=0.0,
    )
    assert mode == CBB_MODE_HOME_UPS
    assert reason == "auto_negative_charge"

    mode, reason = module.handle_negative_price(
        strategy,
        battery=9.5,
        solar=1.0,
        load=0.0,
        price=-1.0,
        export_price=0.0,
    )
    assert mode == CBB_MODE_HOME_III
    assert reason == "auto_negative_curtail"

    mode, reason = module.handle_negative_price(
        strategy,
        battery=9.5,
        solar=0.0,
        load=0.0,
        price=-1.0,
        export_price=0.0,
    )
    assert mode == CBB_MODE_HOME_I
    assert reason == "auto_negative_consume"


def test_apply_smoothing_protected_and_short():
    strategy = DummyStrategy()
    decisions = [
        SimpleNamespace(mode=CBB_MODE_HOME_I, mode_name="HOME I", reason="base", is_balancing=False, is_holding=False),
        SimpleNamespace(mode=CBB_MODE_HOME_UPS, mode_name="UPS", reason="short", is_balancing=True, is_holding=False),
    ]
    smoothed = module.apply_smoothing(
        strategy,
        decisions=decisions,
        solar_forecast=[],
        consumption_forecast=[],
        prices=[],
        export_prices=[],
    )
    assert smoothed[1].mode == CBB_MODE_HOME_UPS

    assert module.apply_smoothing(strategy, decisions=[decisions[0]], solar_forecast=[], consumption_forecast=[], prices=[], export_prices=[]) == [decisions[0]]
