"""Shared physics for CBB mode simulation (15-minute interval)."""

from __future__ import annotations

from dataclasses import dataclass

from .const import HOME_I, HOME_II, HOME_III, HOME_UPS


@dataclass(frozen=True)
class IntervalPhysicsResult:
    """Result of simulating a single interval."""

    new_soc_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    grid_charge_kwh: float = 0.0
    solar_charge_kwh: float = 0.0


def simulate_interval(
    *,
    mode: int,
    solar_kwh: float,
    load_kwh: float,
    battery_soc_kwh: float,
    capacity_kwh: float,
    hw_min_capacity_kwh: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    home_charge_rate_kwh_15min: float,
) -> IntervalPhysicsResult:
    """Simulate one 15-minute interval for a given CBB mode.

    This function implements the canonical mode physics (HW minimum only).
    """
    solar_kwh = max(0.0, float(solar_kwh))
    load_kwh = max(0.0, float(load_kwh))
    capacity_kwh = max(0.0, float(capacity_kwh))
    hw_min_capacity_kwh = max(0.0, float(hw_min_capacity_kwh))

    soc = max(0.0, min(capacity_kwh, float(battery_soc_kwh)))
    grid_import = 0.0
    grid_export = 0.0
    battery_charge = 0.0
    battery_discharge = 0.0
    grid_charge_raw = 0.0
    solar_charge_raw = 0.0

    # Night optimization: HOME I/II/III behave identically when solar is zero.
    if solar_kwh < 0.001 and mode in (HOME_I, HOME_II, HOME_III):
        available_battery = max(0.0, soc - hw_min_capacity_kwh)
        usable_from_battery = available_battery * discharge_efficiency

        covered_by_battery = min(load_kwh, usable_from_battery)
        if covered_by_battery > 0.001:
            battery_discharge = covered_by_battery / discharge_efficiency
            soc -= battery_discharge

        remaining = load_kwh - covered_by_battery
        if remaining > 0.001:
            grid_import += remaining

        soc = max(hw_min_capacity_kwh, soc)
        return IntervalPhysicsResult(
            new_soc_kwh=min(capacity_kwh, soc),
            grid_import_kwh=grid_import,
            grid_export_kwh=0.0,
            battery_charge_kwh=0.0,
            battery_discharge_kwh=battery_discharge,
            grid_charge_kwh=0.0,
            solar_charge_kwh=0.0,
        )

    # HOME I (0): Solar -> Load, surplus -> Battery, deficit -> Battery.
    if mode == HOME_I:
        if solar_kwh >= load_kwh:
            surplus = solar_kwh - load_kwh
            battery_space = max(0.0, capacity_kwh - soc)
            charge_amount = min(surplus, battery_space)
            if charge_amount > 0.001:
                battery_charge = charge_amount
                solar_charge_raw = charge_amount
                soc = min(capacity_kwh, soc + charge_amount * charge_efficiency)
            remaining_surplus = surplus - charge_amount
            if remaining_surplus > 0.001:
                grid_export += remaining_surplus
        else:
            deficit = load_kwh - solar_kwh
            available_battery = max(0.0, soc - hw_min_capacity_kwh)
            usable_from_battery = available_battery * discharge_efficiency

            covered_by_battery = min(deficit, usable_from_battery)
            if covered_by_battery > 0.001:
                battery_discharge = covered_by_battery / discharge_efficiency
                soc -= battery_discharge

            remaining_deficit = deficit - covered_by_battery
            if remaining_deficit > 0.001:
                grid_import += remaining_deficit

            soc = max(hw_min_capacity_kwh, soc)

        return IntervalPhysicsResult(
            new_soc_kwh=min(capacity_kwh, soc),
            grid_import_kwh=grid_import,
            grid_export_kwh=grid_export,
            battery_charge_kwh=battery_charge,
            battery_discharge_kwh=battery_discharge,
            grid_charge_kwh=grid_charge_raw,
            solar_charge_kwh=solar_charge_raw,
        )

    # HOME II (1): Solar -> Load, surplus -> Battery, deficit -> Grid (battery untouched).
    if mode == HOME_II:
        if solar_kwh >= load_kwh:
            surplus = solar_kwh - load_kwh
            battery_space = max(0.0, capacity_kwh - soc)
            charge_amount = min(surplus, battery_space)
            if charge_amount > 0.001:
                battery_charge = charge_amount
                solar_charge_raw = charge_amount
                soc = min(capacity_kwh, soc + charge_amount * charge_efficiency)
            remaining_surplus = surplus - charge_amount
            if remaining_surplus > 0.001:
                grid_export += remaining_surplus
        else:
            grid_import += load_kwh - solar_kwh

        return IntervalPhysicsResult(
            new_soc_kwh=min(capacity_kwh, soc),
            grid_import_kwh=grid_import,
            grid_export_kwh=grid_export,
            battery_charge_kwh=battery_charge,
            battery_discharge_kwh=0.0,
            grid_charge_kwh=grid_charge_raw,
            solar_charge_kwh=solar_charge_raw,
        )

    # HOME III (2): All solar -> Battery, load -> Grid.
    if mode == HOME_III:
        battery_space = max(0.0, capacity_kwh - soc)
        charge_amount = min(solar_kwh, battery_space)
        if charge_amount > 0.001:
            battery_charge = charge_amount
            solar_charge_raw = charge_amount
            soc = min(capacity_kwh, soc + charge_amount * charge_efficiency)
        remaining_solar = solar_kwh - charge_amount
        if remaining_solar > 0.001:
            grid_export += remaining_solar
        grid_import += load_kwh

        return IntervalPhysicsResult(
            new_soc_kwh=min(capacity_kwh, soc),
            grid_import_kwh=grid_import,
            grid_export_kwh=grid_export,
            battery_charge_kwh=battery_charge,
            battery_discharge_kwh=0.0,
            grid_charge_kwh=grid_charge_raw,
            solar_charge_kwh=solar_charge_raw,
        )

    # HOME UPS (3): solar + grid -> battery, load -> grid.
    if mode == HOME_UPS:
        battery_space = max(0.0, capacity_kwh - soc)

        # Solar -> battery (no rate limit)
        solar_to_battery = min(solar_kwh, battery_space)

        # Grid -> battery (rate-limited)
        remaining_space = battery_space - solar_to_battery
        grid_to_battery = min(home_charge_rate_kwh_15min, remaining_space)

        total_charge = solar_to_battery + grid_to_battery
        if total_charge > 0.001:
            battery_charge = total_charge
            grid_charge_raw = grid_to_battery
            solar_charge_raw = solar_to_battery
            soc = min(capacity_kwh, soc + total_charge * charge_efficiency)

        grid_import += load_kwh + grid_to_battery

        remaining_solar = solar_kwh - solar_to_battery
        if remaining_solar > 0.001:
            grid_export += remaining_solar

        return IntervalPhysicsResult(
            new_soc_kwh=min(capacity_kwh, soc),
            grid_import_kwh=grid_import,
            grid_export_kwh=grid_export,
            battery_charge_kwh=battery_charge,
            battery_discharge_kwh=0.0,
            grid_charge_kwh=grid_charge_raw,
            solar_charge_kwh=solar_charge_raw,
        )

    # Unknown mode -> fall back to HOME I
    return simulate_interval(
        mode=HOME_I,
        solar_kwh=solar_kwh,
        load_kwh=load_kwh,
        battery_soc_kwh=soc,
        capacity_kwh=capacity_kwh,
        hw_min_capacity_kwh=hw_min_capacity_kwh,
        charge_efficiency=charge_efficiency,
        discharge_efficiency=discharge_efficiency,
        home_charge_rate_kwh_15min=home_charge_rate_kwh_15min,
    )
