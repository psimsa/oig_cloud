from __future__ import annotations

from custom_components.oig_cloud.battery_forecast.config import (
    HybridConfig, SimulatorConfig)
from custom_components.oig_cloud.battery_forecast.strategy.hybrid import \
    HybridStrategy
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I, CBB_MODE_HOME_UPS)


def _make_prices(n: int, price: float) -> list[dict]:
    return [{"price": price} for _ in range(n)]


def _make_strategy() -> HybridStrategy:
    config = HybridConfig(
        planning_min_percent=33.0,
        target_percent=33.0,
        max_ups_price_czk=10.0,
        min_ups_duration_intervals=2,
    )
    sim_config = SimulatorConfig(
        max_capacity_kwh=15.0,
        min_capacity_kwh=3.0,
        charge_rate_kw=2.8,
        ac_dc_efficiency=0.95,
        dc_ac_efficiency=0.95,
        dc_dc_efficiency=0.95,
    )
    return HybridStrategy(config, sim_config)


def test_recover_from_below_planning_min_schedules_earliest_ups() -> None:
    strategy = _make_strategy()
    spot_prices = _make_prices(6, 5.0)

    result = strategy.optimize(
        initial_battery_kwh=3.0,  # below planning min (33% of 15 kWh = 4.95 kWh)
        spot_prices=spot_prices,
        solar_forecast=[0.0] * 6,
        consumption_forecast=[0.0] * 6,
    )

    assert not result.infeasible
    assert len(result.modes) == 6
    # Recovery should schedule the earliest UPS intervals consecutively.
    assert result.modes[:4] == [CBB_MODE_HOME_UPS] * 4
    assert result.modes[4] == CBB_MODE_HOME_I

    planning_min = strategy.config.planning_min_kwh(
        strategy.sim_config.max_capacity_kwh
    )
    assert result.decisions[3].battery_end >= planning_min - 0.01


def test_recover_from_below_planning_min_respects_max_ups_price() -> None:
    strategy = _make_strategy()
    spot_prices = [{"price": 12.0}, {"price": 5.0}]

    result = strategy.optimize(
        initial_battery_kwh=3.0,
        spot_prices=spot_prices,
        solar_forecast=[0.0, 0.0],
        consumption_forecast=[0.0, 0.0],
    )

    assert result.infeasible
    assert result.infeasible_reason
    assert "max_ups_price_czk" in result.infeasible_reason
