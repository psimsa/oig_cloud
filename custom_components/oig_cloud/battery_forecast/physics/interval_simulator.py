"""Interval Simulator - core physics for battery simulation.

This module provides a stateless simulator for single interval calculations.
All CBB modes are implemented according to CBB_MODES_DEFINITIVE.md:

HOME I (mode=0):
    - During day: Solar → Load → Battery, deficit from Battery
    - At night: Battery discharges to cover load (same as II, III)
    - Export: Only when battery is 100% full

HOME II (mode=1):
    - During day: Solar → Load → Battery, deficit from GRID (battery untouched)
    - At night: Battery discharges (same as I, III)
    - Export: Only when battery is 100% full

HOME III (mode=2):
    - During day: ALL solar → Battery, load from GRID
    - At night: Battery discharges (same as I, II)
    - Export: Only when battery is 100% full

HOME UPS (mode=3):
    - Solar → Battery (DC/DC)
    - Load from GRID
    - Grid → Battery (AC/DC) charging enabled
    - Export: Only when battery is 100% full
"""

from dataclasses import dataclass
from typing import Tuple

from ...physics import simulate_interval
from ..config import SimulatorConfig
from ..types import CBB_MODE_HOME_I, CBB_MODE_HOME_II


@dataclass(frozen=True)
class IntervalResult:
    """Result of simulating a single interval.

    All energy values are in kWh for the interval duration.
    """

    battery_end: float  # Battery SoC at end of interval (kWh)
    grid_import: float  # Energy imported from grid (kWh)
    grid_export: float  # Energy exported to grid (kWh)
    battery_charge: float  # Energy charged to battery (kWh)
    battery_discharge: float  # Energy discharged from battery (kWh)
    solar_used_direct: float  # Solar used directly for load (kWh)
    solar_to_battery: float  # Solar charged to battery (kWh)
    solar_exported: float  # Solar exported to grid (kWh)
    solar_curtailed: float  # Solar that couldn't be used (kWh)

    @property
    def net_battery_change(self) -> float:
        """Net change in battery (positive = charge, negative = discharge)."""
        return self.battery_charge - self.battery_discharge

    @property
    def net_grid_flow(self) -> float:
        """Net grid flow (positive = import, negative = export)."""
        return self.grid_import - self.grid_export


class IntervalSimulator:
    """Stateless physics simulator for single intervals.

    This class implements the core physics for all CBB modes.
    It is designed to be:
    - Stateless: All state passed as arguments
    - Pure: Same inputs always produce same outputs
    - Efficient: No logging or side effects

    Example:
        config = SimulatorConfig(max_capacity_kwh=15.36, min_capacity_kwh=3.07)
        simulator = IntervalSimulator(config)

        result = simulator.simulate(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,
            solar_kwh=2.0,
            load_kwh=0.5,
        )
        print(f"Battery: {result.battery_end:.2f} kWh")
    """

    def __init__(self, config: SimulatorConfig) -> None:
        """Initialize simulator with configuration.

        Args:
            config: SimulatorConfig with battery parameters
        """
        self.config = config

        # Cache commonly used values
        self._max = config.max_capacity_kwh
        self._min = config.min_capacity_kwh
        self._dc_dc = config.dc_dc_efficiency
        self._dc_ac = config.dc_ac_efficiency
        self._ac_dc = config.ac_dc_efficiency
        self._max_charge = config.max_charge_per_interval_kwh

    def simulate(
        self,
        battery_start: float,
        mode: int,
        solar_kwh: float,
        load_kwh: float,
        force_charge: bool = False,
    ) -> IntervalResult:
        """Simulate a single interval.

        Args:
            battery_start: Battery level at interval start (kWh)
            mode: CBB mode (0=HOME_I, 1=HOME_II, 2=HOME_III, 3=HOME_UPS)
            solar_kwh: Solar production this interval (kWh)
            load_kwh: Load consumption this interval (kWh)
            force_charge: Force grid charging (for balancing)

        Returns:
            IntervalResult with all energy flows
        """
        # Clamp inputs to valid range
        battery_start = max(0, min(battery_start, self._max))
        solar_kwh = max(0, solar_kwh)
        load_kwh = max(0, load_kwh)

        # Canonical physics lives in shared simulate_interval().
        # Note: force_charge is currently ignored because UPS physics always charges.
        charge_efficiency = self._ac_dc
        discharge_efficiency = self._dc_ac

        flows = simulate_interval(
            mode=mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_start,
            capacity_kwh=self._max,
            hw_min_capacity_kwh=self._min,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            home_charge_rate_kwh_15min=self._max_charge,
        )

        if mode in (CBB_MODE_HOME_I, CBB_MODE_HOME_II):
            solar_used_direct = min(solar_kwh, load_kwh)
        else:
            solar_used_direct = 0.0

        solar_to_battery = flows.solar_charge_kwh
        solar_exported = flows.grid_export_kwh
        solar_curtailed = max(
            0.0,
            solar_kwh - solar_used_direct - solar_to_battery - solar_exported,
        )

        return IntervalResult(
            battery_end=flows.new_soc_kwh,
            grid_import=flows.grid_import_kwh,
            grid_export=flows.grid_export_kwh,
            battery_charge=flows.battery_charge_kwh * charge_efficiency,
            battery_discharge=flows.battery_discharge_kwh,
            solar_used_direct=solar_used_direct,
            solar_to_battery=solar_to_battery,
            solar_exported=solar_exported,
            solar_curtailed=solar_curtailed,
        )

    def _simulate_home_ups(
        self,
        battery_start: float,
        solar_kwh: float,
        load_kwh: float,
        force_charge: bool,
    ) -> IntervalResult:
        """HOME UPS: Grid charging enabled, load from grid.

        Physics:
        - Solar → Battery (DC/DC, 95%)
        - Load → Grid (100%)
        - Grid → Battery (AC/DC, 95%) if space available
        - Export when battery full
        """
        battery = battery_start
        grid_import = 0.0
        grid_export = 0.0
        battery_charge = 0.0
        solar_to_battery = 0.0
        solar_exported = 0.0
        solar_curtailed = 0.0

        # Step 1: Solar to battery (DC/DC)
        battery_space = self._max - battery
        solar_charge_potential = solar_kwh * self._dc_dc
        solar_charge = min(solar_charge_potential, battery_space)

        if solar_charge > 0.001:
            battery += solar_charge
            solar_to_battery = solar_charge / self._dc_dc  # Original solar amount
            battery_charge += solar_charge

        # Step 2: Excess solar handling
        excess_solar = solar_kwh - solar_to_battery
        if excess_solar > 0.001 and battery >= self._max - 0.01:
            # Export only when battery is full
            grid_export = excess_solar
            solar_exported = excess_solar
        elif excess_solar > 0.001:
            # Curtailed (battery not full but no room)
            solar_curtailed = excess_solar  # pragma: no cover

        # Step 3: Load from grid
        grid_import += load_kwh

        # Step 4: Grid charging if space available and forced or beneficial
        # Note: Charging is measured at battery, so no efficiency loss here
        # (efficiency is already accounted for in the measured charge rate)
        battery_space = self._max - battery
        if battery_space > 0.01 and (force_charge or battery < self._max * 0.99):
            max_grid_charge = min(self._max_charge, battery_space)
            if max_grid_charge > 0.01:
                grid_import += max_grid_charge
                battery += max_grid_charge
                battery_charge += max_grid_charge

        # Clamp battery
        battery = max(0, min(battery, self._max))

        return IntervalResult(
            battery_end=battery,
            grid_import=grid_import,
            grid_export=grid_export,
            battery_charge=battery_charge,
            battery_discharge=0.0,
            solar_used_direct=0.0,
            solar_to_battery=solar_to_battery,
            solar_exported=solar_exported,
            solar_curtailed=solar_curtailed,
        )

    def _simulate_home_iii(
        self,
        battery_start: float,
        solar_kwh: float,
        load_kwh: float,
    ) -> IntervalResult:
        """HOME III: Maximum battery charging from solar.

        During day (solar > 0):
        - ALL solar → Battery (DC/DC, 95%)
        - Load → Grid (100%)
        - Export when battery full

        At night (solar = 0):
        - Battery → Load (DC/AC, 88.2%)
        - Deficit from grid
        """
        battery = battery_start
        grid_import = 0.0
        grid_export = 0.0
        battery_charge = 0.0
        battery_discharge = 0.0
        solar_to_battery = 0.0
        solar_exported = 0.0
        solar_curtailed = 0.0

        if solar_kwh > 0.01:
            # Day mode: ALL solar to battery
            battery_space = self._max - battery
            solar_charge_potential = solar_kwh * self._dc_dc
            solar_charge = min(solar_charge_potential, battery_space)

            if solar_charge > 0.001:
                battery += solar_charge
                solar_to_battery = solar_charge / self._dc_dc
                battery_charge = solar_charge

            # Excess solar: export only if battery full
            excess_solar = solar_kwh - solar_to_battery
            if excess_solar > 0.001:
                if battery >= self._max - 0.01:
                    grid_export = excess_solar
                    solar_exported = excess_solar
                else:
                    solar_curtailed = excess_solar  # pragma: no cover

            # ALL load from grid
            grid_import = load_kwh

        else:
            # Night mode: Battery discharges (same as HOME I, II)
            battery, battery_discharge, grid_import = self._discharge_for_load(
                battery, load_kwh
            )

        # Clamp battery
        battery = max(0, min(battery, self._max))

        return IntervalResult(
            battery_end=battery,
            grid_import=grid_import,
            grid_export=grid_export,
            battery_charge=battery_charge,
            battery_discharge=battery_discharge,
            solar_used_direct=0.0,
            solar_to_battery=solar_to_battery,
            solar_exported=solar_exported,
            solar_curtailed=solar_curtailed,
        )

    def _simulate_home_ii(
        self,
        battery_start: float,
        solar_kwh: float,
        load_kwh: float,
    ) -> IntervalResult:
        """HOME II: Battery preservation during day.

        During day (solar > 0):
        - Solar → Load first
        - Excess solar → Battery (DC/DC, 95%)
        - Deficit → Grid (battery UNTOUCHED!)
        - Export when battery full

        At night (solar = 0):
        - Battery → Load (DC/AC, 88.2%)
        - Deficit from grid
        """
        battery = battery_start
        grid_import = 0.0
        grid_export = 0.0
        battery_charge = 0.0
        battery_discharge = 0.0
        solar_used_direct = 0.0
        solar_to_battery = 0.0
        solar_exported = 0.0
        solar_curtailed = 0.0

        if solar_kwh > 0.01:
            # Day mode: Solar covers load first, battery preserved

            if solar_kwh >= load_kwh:
                # Solar covers entire load
                solar_used_direct = load_kwh
                excess_solar = solar_kwh - load_kwh

                # Excess to battery
                battery_space = self._max - battery
                solar_charge_potential = excess_solar * self._dc_dc
                solar_charge = min(solar_charge_potential, battery_space)

                if solar_charge > 0.001:
                    battery += solar_charge
                    solar_to_battery = solar_charge / self._dc_dc
                    battery_charge = solar_charge

                # Remaining excess: export only if battery full
                remaining_excess = excess_solar - solar_to_battery
                if remaining_excess > 0.001:
                    if battery >= self._max - 0.01:
                        grid_export = remaining_excess
                        solar_exported = remaining_excess
                    else:
                        solar_curtailed = remaining_excess  # pragma: no cover
            else:
                # Solar doesn't cover load - grid supplements, battery UNTOUCHED
                solar_used_direct = solar_kwh
                grid_import = load_kwh - solar_kwh

        else:
            # Night mode: Battery discharges (same as HOME I, III)
            battery, battery_discharge, grid_import = self._discharge_for_load(
                battery, load_kwh
            )

        # Clamp battery
        battery = max(0, min(battery, self._max))

        return IntervalResult(
            battery_end=battery,
            grid_import=grid_import,
            grid_export=grid_export,
            battery_charge=battery_charge,
            battery_discharge=battery_discharge,
            solar_used_direct=solar_used_direct,
            solar_to_battery=solar_to_battery,
            solar_exported=solar_exported,
            solar_curtailed=solar_curtailed,
        )

    def _simulate_home_i(
        self,
        battery_start: float,
        solar_kwh: float,
        load_kwh: float,
    ) -> IntervalResult:
        """HOME I: Standard solar priority mode.

        During day (solar > 0):
        - Solar → Load first
        - Excess solar → Battery (DC/DC, 95%)
        - Deficit → Battery (DC/AC, 88.2%)
        - Export when battery full

        At night (solar = 0):
        - Battery → Load (DC/AC, 88.2%)
        - Deficit from grid
        """
        battery = battery_start
        grid_import = 0.0
        grid_export = 0.0
        battery_charge = 0.0
        battery_discharge = 0.0
        solar_used_direct = 0.0
        solar_to_battery = 0.0
        solar_exported = 0.0
        solar_curtailed = 0.0

        if solar_kwh > 0.01:
            # Day mode: Solar → Load → Battery, deficit from battery

            if solar_kwh >= load_kwh:
                # Solar covers entire load
                solar_used_direct = load_kwh
                excess_solar = solar_kwh - load_kwh

                # Excess to battery
                battery_space = self._max - battery
                solar_charge_potential = excess_solar * self._dc_dc
                solar_charge = min(solar_charge_potential, battery_space)

                if solar_charge > 0.001:
                    battery += solar_charge
                    solar_to_battery = solar_charge / self._dc_dc
                    battery_charge = solar_charge

                # Remaining excess: export only if battery full
                remaining_excess = excess_solar - solar_to_battery
                if remaining_excess > 0.001:
                    if battery >= self._max - 0.01:
                        grid_export = remaining_excess
                        solar_exported = remaining_excess
                    else:
                        solar_curtailed = remaining_excess  # pragma: no cover
            else:
                # Solar doesn't cover load - battery supplements (diff from HOME II!)
                solar_used_direct = solar_kwh
                deficit = load_kwh - solar_kwh

                # Try to cover deficit from battery
                battery, battery_discharge, grid_import = self._discharge_for_load(
                    battery, deficit
                )
        else:
            # Night mode: Battery discharges (same as HOME II, III)
            battery, battery_discharge, grid_import = self._discharge_for_load(
                battery, load_kwh
            )

        # Clamp battery
        battery = max(0, min(battery, self._max))

        return IntervalResult(
            battery_end=battery,
            grid_import=grid_import,
            grid_export=grid_export,
            battery_charge=battery_charge,
            battery_discharge=battery_discharge,
            solar_used_direct=solar_used_direct,
            solar_to_battery=solar_to_battery,
            solar_exported=solar_exported,
            solar_curtailed=solar_curtailed,
        )

    def _discharge_for_load(
        self,
        battery: float,
        load_kwh: float,
    ) -> Tuple[float, float, float]:
        """Discharge battery to cover load.

        Args:
            battery: Current battery level (kWh)
            load_kwh: Load to cover (kWh)

        Returns:
            Tuple of (new_battery, discharge_kwh, grid_import_kwh)
        """
        # Available energy from battery (above minimum)
        available_energy = battery - self._min

        if available_energy <= 0:
            # Battery at minimum, all from grid
            return battery, 0.0, load_kwh

        # Energy we can deliver to load (after efficiency loss)
        deliverable = available_energy * self._dc_ac

        if deliverable >= load_kwh:
            # Battery can cover all load
            actual_drain = load_kwh / self._dc_ac
            return battery - actual_drain, actual_drain, 0.0
        else:
            # Battery partially covers, rest from grid
            actual_drain = available_energy  # Drain all available
            covered = deliverable
            grid_import = load_kwh - covered
            return self._min, actual_drain, grid_import

    def calculate_cost(
        self,
        result: IntervalResult,
        spot_price: float,
        export_price: float,
    ) -> float:
        """Calculate net cost for an interval result.

        Args:
            result: IntervalResult from simulation
            spot_price: Buy price (CZK/kWh)
            export_price: Sell price (CZK/kWh)

        Returns:
            Net cost in CZK (positive = cost, negative = revenue)
        """
        import_cost = result.grid_import * spot_price
        export_revenue = result.grid_export * export_price
        return import_cost - export_revenue


# =============================================================================
# Convenience factory function
# =============================================================================


def create_simulator(
    max_capacity: float = 15.36,
    min_capacity: float = 3.07,
    **kwargs: float,
) -> IntervalSimulator:
    """Create an IntervalSimulator with given parameters.

    Args:
        max_capacity: Maximum battery capacity (kWh)
        min_capacity: HW minimum battery capacity (kWh)
        **kwargs: Additional SimulatorConfig parameters

    Returns:
        Configured IntervalSimulator
    """
    config = SimulatorConfig(
        max_capacity_kwh=max_capacity,
        min_capacity_kwh=min_capacity,
        **kwargs,
    )
    return IntervalSimulator(config)
