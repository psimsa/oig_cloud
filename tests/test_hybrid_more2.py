from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.config import HybridConfig, SimulatorConfig
from custom_components.oig_cloud.battery_forecast.strategy.hybrid import (
    HybridResult,
    HybridStrategy,
    calculate_optimal_mode,
)
from custom_components.oig_cloud.battery_forecast.strategy.balancing import (
    StrategyBalancingPlan,
)
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_UPS,
)


class DummySimulator:
    def simulate(
        self,
        *,
        battery_start,
        mode,
        solar_kwh,
        load_kwh,
        force_charge=False,
    ):
        _ = mode
        _ = force_charge
        return SimpleNamespace(
            battery_end=battery_start + solar_kwh - load_kwh,
            grid_import=1.0,
            grid_export=0.0,
        )

    def calculate_cost(self, _result, price, export_price):
        return price - export_price


def test_hybrid_result_savings_percent_zero():
    result = HybridResult(
        decisions=[],
        total_cost_czk=0.0,
        baseline_cost_czk=0.0,
        savings_czk=0.0,
        total_grid_import_kwh=0.0,
        total_grid_export_kwh=0.0,
        final_battery_kwh=0.0,
        mode_counts={},
        ups_intervals=0,
        calculation_time_ms=0.0,
        negative_prices_detected=False,
        balancing_applied=False,
    )
    assert result.savings_percent == 0.0


def test_calculate_optimal_mode(monkeypatch):
    def _select(_self, **_k):
        return CBB_MODE_HOME_UPS, "reason", {}

    monkeypatch.setattr(HybridStrategy, "_select_best_mode", _select)
    mode, reason = calculate_optimal_mode(
        battery=1.0,
        solar=0.0,
        load=0.0,
        price=1.0,
        export_price=0.0,
        config=HybridConfig(),
        sim_config=SimulatorConfig(),
    )
    assert mode == CBB_MODE_HOME_UPS
    assert reason == "reason"


def test_optimize_reason_branches(monkeypatch):
    config = HybridConfig()
    sim_config = SimulatorConfig()
    strategy = HybridStrategy(config, sim_config)
    strategy.simulator = DummySimulator()

    def _plan(*_a, **_k):
        return {4}, None, {4}

    def _neg(*_a, **_k):
        return CBB_MODE_HOME_UPS, "negative"

    monkeypatch.setattr(strategy, "_plan_charging_intervals", _plan)
    monkeypatch.setattr(strategy, "_handle_negative_price", _neg)

    balancing_plan = StrategyBalancingPlan(
        charging_intervals={2},
        holding_intervals={1},
        mode_overrides={0: CBB_MODE_HOME_I},
        is_active=True,
    )

    result = strategy.optimize(
        initial_battery_kwh=5.0,
        spot_prices=[
            {"price": 1.0},
            {"price": 1.0},
            {"price": 1.0},
            {"price": -1.0},
            {"price": 1.0},
            {"price": 1.0},
        ],
        solar_forecast=[0.0] * 6,
        consumption_forecast=[0.0] * 6,
        balancing_plan=balancing_plan,
        export_prices=[0.0] * 6,
    )

    reasons = [d.reason for d in result.decisions]
    assert reasons[0] == "balancing_override"
    assert reasons[1] == "holding_period"
    assert reasons[2] == "balancing_charge"
    assert reasons[3] == "negative"
    assert reasons[4] == "price_band_hold"
    assert reasons[5] == "default_discharge"
