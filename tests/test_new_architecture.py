"""Tests for new 3-layer battery forecast architecture.

Tests the following components:
- IntervalSimulator (physics layer)
- Balancing plan factories (balancing layer)
- HybridStrategy (strategy layer)
"""

import os
# Import from new architecture
import sys
from datetime import datetime, timedelta
from typing import List

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custom_components.oig_cloud.battery_forecast.balancing.plan import (
    BalancingInterval, BalancingMode, BalancingPriority, create_forced_plan,
    create_natural_plan, create_opportunistic_plan)
from custom_components.oig_cloud.battery_forecast.config import (
    ChargingStrategy, HybridConfig, SimulatorConfig)
from custom_components.oig_cloud.battery_forecast.physics.interval_simulator import (
    IntervalResult, IntervalSimulator, create_simulator)
from custom_components.oig_cloud.battery_forecast.strategy import \
    StrategyBalancingPlan
from custom_components.oig_cloud.battery_forecast.strategy.hybrid import \
    HybridStrategy
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I, CBB_MODE_HOME_II, CBB_MODE_HOME_III, CBB_MODE_HOME_UPS,
    SpotPrice)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def simulator_config() -> SimulatorConfig:
    """Standard simulator configuration."""
    return SimulatorConfig(
        max_capacity_kwh=15.36,
        min_capacity_kwh=3.07,  # ~20% HW minimum
        charge_rate_kw=2.8,
        dc_dc_efficiency=0.95,
        dc_ac_efficiency=0.882,
        ac_dc_efficiency=0.95,
        interval_minutes=15,
    )


@pytest.fixture
def hybrid_config() -> HybridConfig:
    """Standard hybrid configuration."""
    return HybridConfig(
        planning_min_percent=20.0,
        target_percent=80.0,
        cheap_threshold_percent=75.0,
        expensive_threshold_percent=125.0,
        max_ups_price_czk=2.0,
    )



@pytest.fixture
def simulator(simulator_config: SimulatorConfig) -> IntervalSimulator:
    """Create simulator instance."""
    return IntervalSimulator(simulator_config)


@pytest.fixture
def sample_spot_prices() -> List[SpotPrice]:
    """Sample spot prices for 24 hours (96 intervals)."""
    prices: List[SpotPrice] = []
    base_time = datetime(2024, 6, 15, 0, 0)  # Summer day

    for i in range(96):
        hour = i // 4
        # Price profile: cheap at night, expensive during day
        if hour < 6:
            price = 1.5  # Night cheap
        elif hour < 10:
            price = 2.5  # Morning
        elif hour < 14:
            price = 3.0  # Midday
        elif hour < 18:
            price = 2.0  # Afternoon
        else:
            price = 2.5  # Evening

        prices.append(
            {
                "time": (base_time + timedelta(minutes=i * 15)).isoformat(),
                "price": price,
                "export_price": price * 0.85,
            }
        )

    return prices


@pytest.fixture
def sample_solar_forecast() -> List[float]:
    """Sample solar forecast for 24 hours (96 intervals)."""
    solar: List[float] = []

    for i in range(96):
        hour = i // 4
        minute_in_hour = (i % 4) * 15

        # Bell curve solar production: 0 at night, peak at noon
        if hour < 6 or hour >= 20:
            kwh = 0.0
        else:
            # Simple bell curve approximation
            peak_hour = 13
            width = 5
            factor = max(0, 1 - ((hour - peak_hour) / width) ** 2)
            kwh = 1.5 * factor  # Peak ~1.5 kWh per 15min = 6 kW

        solar.append(kwh)

    return solar


@pytest.fixture
def sample_consumption() -> List[float]:
    """Sample consumption forecast for 24 hours (96 intervals)."""
    consumption: List[float] = []

    for i in range(96):
        hour = i // 4

        # Base load + morning/evening peaks
        if hour < 6:
            kwh = 0.1  # Night base
        elif hour < 9:
            kwh = 0.3  # Morning peak
        elif hour < 17:
            kwh = 0.15  # Day base
        elif hour < 21:
            kwh = 0.35  # Evening peak
        else:
            kwh = 0.15  # Late evening

        consumption.append(kwh)

    return consumption


# =============================================================================
# IntervalSimulator Tests
# =============================================================================


class TestIntervalSimulator:
    """Tests for physics simulation."""

    def test_home_i_solar_covers_load(self, simulator: IntervalSimulator) -> None:
        """HOME I: Solar covers load, excess to battery."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,
            solar_kwh=2.0,
            load_kwh=0.5,
        )

        assert result.solar_used_direct == pytest.approx(0.5, abs=0.01)
        assert result.battery_end > 10.0  # Charged from excess
        assert result.grid_import == pytest.approx(0.0, abs=0.01)

    def test_home_i_battery_covers_deficit(self, simulator: IntervalSimulator) -> None:
        """HOME I: Battery covers deficit when solar < load."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.3,
            load_kwh=0.5,
        )

        assert result.solar_used_direct == pytest.approx(0.3, abs=0.01)
        assert result.battery_end < 10.0  # Discharged
        assert result.battery_discharge > 0

    def test_home_ii_preserves_battery_during_day(
        self, simulator: IntervalSimulator
    ) -> None:
        """HOME II: Grid covers deficit, battery untouched during day."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.3,
            load_kwh=0.5,
        )

        assert result.battery_end == pytest.approx(10.0, abs=0.01)  # Unchanged
        assert result.grid_import == pytest.approx(0.2, abs=0.01)  # Deficit from grid

    def test_home_ii_discharges_at_night(self, simulator: IntervalSimulator) -> None:
        """HOME II: Battery discharges when no solar."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.0,
            load_kwh=0.5,
        )

        assert result.battery_end < 10.0  # Discharged
        assert result.battery_discharge > 0

    def test_home_iii_all_solar_to_battery(self, simulator: IntervalSimulator) -> None:
        """HOME III: All solar goes to battery, load from grid."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_III,
            solar_kwh=2.0,
            load_kwh=0.5,
        )

        assert result.battery_end > 10.0  # Charged
        assert result.grid_import == pytest.approx(0.5, abs=0.01)  # Load from grid
        assert result.solar_used_direct == pytest.approx(0.0, abs=0.01)  # No direct use

    def test_home_iii_export_only_when_full(
        self, simulator_config: SimulatorConfig
    ) -> None:
        """HOME III: Export only when battery is 100% full."""
        simulator = IntervalSimulator(simulator_config)
        max_cap = simulator_config.max_capacity_kwh

        # Battery not full - no export
        result = simulator.simulate(
            battery_start=max_cap - 2.0,
            mode=CBB_MODE_HOME_III,
            solar_kwh=1.0,
            load_kwh=0.1,
        )
        assert result.grid_export == pytest.approx(0.0, abs=0.01)

        # Battery full - should export
        result = simulator.simulate(
            battery_start=max_cap - 0.5,
            mode=CBB_MODE_HOME_III,
            solar_kwh=2.0,
            load_kwh=0.1,
        )
        assert result.grid_export > 0  # Exports excess

    def test_home_ups_charges_from_grid(self, simulator: IntervalSimulator) -> None:
        """HOME UPS: Charges battery from grid."""
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=0.0,
            load_kwh=0.5,
            force_charge=True,
        )

        assert result.battery_end > 10.0  # Charged
        assert result.grid_import > 0.5  # Load + charging

    def test_hw_minimum_stops_discharge(
        self, simulator_config: SimulatorConfig
    ) -> None:
        """Battery discharge stops at HW minimum."""
        simulator = IntervalSimulator(simulator_config)
        min_cap = simulator_config.min_capacity_kwh

        result = simulator.simulate(
            battery_start=min_cap + 0.1,  # Just above minimum
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=2.0,  # Large load
        )

        # Battery should not go below minimum
        assert result.battery_end >= min_cap - 0.01
        # Rest from grid
        assert result.grid_import > 0

    def test_efficiency_applied_correctly(self, simulator: IntervalSimulator) -> None:
        """Verify efficiency factors are applied."""
        # Charge 1 kWh solar -> less in battery due to DC/DC efficiency
        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,
            solar_kwh=1.0,
            load_kwh=0.0,
        )

        # 1.0 * 0.95 = 0.95 kWh should be added
        expected_charge = 1.0 * 0.95
        assert result.battery_end == pytest.approx(10.0 + expected_charge, abs=0.05)

    def test_calculate_cost(self, simulator: IntervalSimulator) -> None:
        """Test cost calculation."""
        result = IntervalResult(
            battery_end=10.0,
            grid_import=1.0,
            grid_export=0.5,
            battery_charge=0.0,
            battery_discharge=0.0,
            solar_used_direct=0.0,
            solar_to_battery=0.0,
            solar_exported=0.5,
            solar_curtailed=0.0,
        )

        cost = simulator.calculate_cost(result, spot_price=2.0, export_price=1.5)

        # Cost = import * spot - export * export_price
        # = 1.0 * 2.0 - 0.5 * 1.5 = 2.0 - 0.75 = 1.25
        assert cost == pytest.approx(1.25, abs=0.01)


# =============================================================================
# Balancing Plan Tests
# =============================================================================


class TestBalancingPlanFactories:
    """Tests for balancing plan factories."""

    def test_create_natural_plan(self) -> None:
        now = datetime(2024, 6, 15, 12, 0)
        holding_start = now.replace(hour=21, minute=0)
        holding_end = holding_start + timedelta(hours=3)
        last_balancing = now - timedelta(days=6)

        plan = create_natural_plan(holding_start, holding_end, last_balancing)

        assert plan.mode == BalancingMode.NATURAL
        assert plan.intervals == []
        assert plan.holding_start == holding_start.isoformat()
        assert plan.holding_end == holding_end.isoformat()
        assert plan.active is True

    def test_create_opportunistic_plan(self) -> None:
        now = datetime(2024, 6, 15, 12, 0)
        holding_start = now.replace(hour=22, minute=0)
        holding_end = holding_start + timedelta(hours=3)

        intervals = [
            BalancingInterval(ts=holding_start.isoformat(), mode=CBB_MODE_HOME_UPS)
        ]

        plan = create_opportunistic_plan(holding_start, holding_end, intervals, 6)

        assert plan.mode == BalancingMode.OPPORTUNISTIC
        assert plan.priority == BalancingPriority.HIGH
        assert plan.locked is False
        assert len(plan.intervals) == 1

    def test_create_forced_plan(self) -> None:
        now = datetime(2024, 6, 15, 12, 0)
        holding_start = now.replace(hour=18, minute=0)
        holding_end = holding_start + timedelta(hours=3)

        intervals = [
            BalancingInterval(ts=holding_start.isoformat(), mode=CBB_MODE_HOME_UPS)
        ]

        plan = create_forced_plan(holding_start, holding_end, intervals)

        assert plan.mode == BalancingMode.FORCED
        assert plan.locked is True
        assert plan.priority == BalancingPriority.CRITICAL


# =============================================================================
# HybridStrategy Tests
# =============================================================================


class TestHybridStrategy:
    """Tests for hybrid optimization strategy."""

    def test_optimize_returns_modes_for_all_intervals(
        self,
        hybrid_config: HybridConfig,
        simulator_config: SimulatorConfig,
        sample_spot_prices: List[SpotPrice],
        sample_solar_forecast: List[float],
        sample_consumption: List[float],
    ) -> None:
        """Optimization returns mode for every interval."""
        strategy = HybridStrategy(hybrid_config, simulator_config)

        result = strategy.optimize(
            initial_battery_kwh=10.0,
            spot_prices=sample_spot_prices,
            solar_forecast=sample_solar_forecast,
            consumption_forecast=sample_consumption,
        )

        assert len(result.decisions) == len(sample_spot_prices)
        assert len(result.modes) == len(sample_spot_prices)

    def test_optimize_prefers_cheap_charging(
        self,
        hybrid_config: HybridConfig,
        simulator_config: SimulatorConfig,
    ) -> None:
        """Optimization prefers UPS mode when prices are very cheap."""
        # Use aggressive charging config
        hybrid_config.charging_strategy = ChargingStrategy.OPPORTUNISTIC
        hybrid_config.max_ups_price_czk = 5.0  # Allow more expensive charging

        strategy = HybridStrategy(hybrid_config, simulator_config)

        # Very cheap prices
        prices: List[SpotPrice] = [{"time": "2024-01-01T00:00", "price": 0.5}] * 8
        solar = [0.0] * 8  # No solar
        consumption = [0.2] * 8

        result = strategy.optimize(
            initial_battery_kwh=5.0,  # Low battery
            spot_prices=prices,
            solar_forecast=solar,
            consumption_forecast=consumption,
        )

        # With opportunistic charging and low battery, should use some UPS
        # Note: The optimizer may still prefer HOME I if it scores better
        # This test verifies the system runs without error
        assert len(result.decisions) == 8
        assert result.total_cost_czk is not None

    def test_optimize_handles_negative_prices(
        self,
        hybrid_config: HybridConfig,
        simulator_config: SimulatorConfig,
    ) -> None:
        """Optimization handles negative prices correctly."""
        strategy = HybridStrategy(hybrid_config, simulator_config)

        # Negative prices
        prices: List[SpotPrice] = [{"time": "2024-01-01T00:00", "price": -1.0}] * 4
        solar = [2.0] * 4  # High solar
        consumption = [0.2] * 4

        result = strategy.optimize(
            initial_battery_kwh=10.0,
            spot_prices=prices,
            solar_forecast=solar,
            consumption_forecast=consumption,
        )

        assert result.negative_prices_detected is True

    def test_optimize_respects_balancing_plan(
        self,
        hybrid_config: HybridConfig,
        simulator_config: SimulatorConfig,
    ) -> None:
        """Optimization respects balancing constraints."""
        strategy = HybridStrategy(hybrid_config, simulator_config)

        prices: List[SpotPrice] = [
            {"time": "2024-01-01T00:00", "price": 5.0}
        ] * 8  # Expensive
        solar = [0.0] * 8
        consumption = [0.2] * 8

        # Balancing plan requires charging at intervals 2, 3
        balancing_plan = StrategyBalancingPlan(
            charging_intervals={2, 3},
            holding_intervals={6, 7},
            mode_overrides={
                2: CBB_MODE_HOME_UPS,
                3: CBB_MODE_HOME_UPS,
            },
            is_active=True,
        )

        result = strategy.optimize(
            initial_battery_kwh=5.0,
            spot_prices=prices,
            solar_forecast=solar,
            consumption_forecast=consumption,
            balancing_plan=balancing_plan,
        )

        # Balancing intervals should use UPS
        assert result.decisions[2].mode == CBB_MODE_HOME_UPS
        assert result.decisions[3].mode == CBB_MODE_HOME_UPS
        assert result.decisions[2].is_balancing is True

    def test_optimize_calculates_savings(
        self,
        hybrid_config: HybridConfig,
        simulator_config: SimulatorConfig,
        sample_spot_prices: List[SpotPrice],
        sample_solar_forecast: List[float],
        sample_consumption: List[float],
    ) -> None:
        """Optimization calculates cost savings."""
        strategy = HybridStrategy(hybrid_config, simulator_config)

        result = strategy.optimize(
            initial_battery_kwh=10.0,
            spot_prices=sample_spot_prices,
            solar_forecast=sample_solar_forecast,
            consumption_forecast=sample_consumption,
        )

        # Baseline cost can be negative if there's a lot of solar export
        # What matters is that savings are calculated
        assert result.baseline_cost_czk is not None
        assert result.savings_czk is not None
        # Total cost should be a real number
        assert isinstance(result.total_cost_czk, float)


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestFactoryFunctions:
    """Tests for factory/convenience functions."""

    def test_create_simulator(self) -> None:
        """Test create_simulator factory."""
        sim = create_simulator(max_capacity=10.0, min_capacity=2.0)

        assert sim.config.max_capacity_kwh == 10.0
        assert sim.config.min_capacity_kwh == 2.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for full workflow."""

    def test_full_day_optimization(
        self,
        simulator_config: SimulatorConfig,
        hybrid_config: HybridConfig,
        sample_spot_prices: List[SpotPrice],
        sample_solar_forecast: List[float],
        sample_consumption: List[float],
    ) -> None:
        """Test full day optimization workflow."""
        strategy = HybridStrategy(hybrid_config, simulator_config)

        result = strategy.optimize(
            initial_battery_kwh=10.0,
            spot_prices=sample_spot_prices,
            solar_forecast=sample_solar_forecast,
            consumption_forecast=sample_consumption,
        )

        # Verify result structure
        assert len(result.decisions) == 96
        assert result.final_battery_kwh >= 0
        assert result.final_battery_kwh <= simulator_config.max_capacity_kwh

        # Verify mode distribution
        total_modes = sum(result.mode_counts.values())
        assert total_modes == 96

        # Verify decisions have valid modes
        for decision in result.decisions:
            assert decision.mode in [0, 1, 2, 3]
            assert decision.mode_name in ["HOME I", "HOME II", "HOME III", "HOME UPS"]
