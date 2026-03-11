"""Scenario and cost analysis helpers for battery forecast."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List

from homeassistant.util import dt as dt_util

from ..data.input import get_solar_for_timestamp
from ..physics import simulate_interval as physics_simulate_interval
from ..types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)

_LOGGER = logging.getLogger(__name__)


def simulate_interval(
    *,
    mode: int,
    solar_kwh: float,
    load_kwh: float,
    battery_soc_kwh: float,
    capacity_kwh: float,
    hw_min_capacity_kwh: float,
    spot_price_czk: float,
    export_price_czk: float,
    charge_efficiency: float = 0.95,
    discharge_efficiency: float = 0.95,
    home_charge_rate_kwh_15min: float = 0.7,
    planning_min_capacity_kwh: float | None = None,
) -> dict:
    """Simulate one 15-minute interval and return costs."""
    effective_min = (
        planning_min_capacity_kwh
        if planning_min_capacity_kwh is not None
        else hw_min_capacity_kwh
    )

    flows = physics_simulate_interval(
        mode=mode,
        solar_kwh=solar_kwh,
        load_kwh=load_kwh,
        battery_soc_kwh=battery_soc_kwh,
        capacity_kwh=capacity_kwh,
        hw_min_capacity_kwh=effective_min,
        charge_efficiency=charge_efficiency,
        discharge_efficiency=discharge_efficiency,
        home_charge_rate_kwh_15min=home_charge_rate_kwh_15min,
    )

    grid_cost_czk = flows.grid_import_kwh * spot_price_czk
    export_revenue_czk = flows.grid_export_kwh * export_price_czk
    net_cost_czk = grid_cost_czk - export_revenue_czk

    return {
        "new_soc_kwh": flows.new_soc_kwh,
        "grid_import_kwh": flows.grid_import_kwh,
        "grid_export_kwh": flows.grid_export_kwh,
        "battery_charge_kwh": flows.battery_charge_kwh,
        "battery_discharge_kwh": flows.battery_discharge_kwh,
        "grid_cost_czk": grid_cost_czk,
        "export_revenue_czk": export_revenue_czk,
        "net_cost_czk": net_cost_czk,
    }


def calculate_interval_cost(
    simulation_result: Dict[str, Any],
    spot_price: float,
    export_price: float,
    time_of_day: str,
) -> Dict[str, Any]:
    """Calculate direct and opportunity cost for one interval."""
    direct_cost = simulation_result["net_cost"]

    battery_discharge = simulation_result.get("battery_discharge", 0.0)
    evening_peak_price = 6.0

    opportunity_cost = 0.0
    if battery_discharge > 0.001 and time_of_day in ["night", "midday"]:
        opportunity_cost = (evening_peak_price - spot_price) * battery_discharge

    total_cost = direct_cost + opportunity_cost

    return {
        "direct_cost": direct_cost,
        "opportunity_cost": opportunity_cost,
        "total_cost": total_cost,
    }


def calculate_fixed_mode_cost(
    sensor: Any,
    *,
    fixed_mode: int,
    current_capacity: float,
    max_capacity: float,
    min_capacity: float,
    spot_prices: List[Dict[str, Any]],
    export_prices: List[Dict[str, Any]],
    solar_forecast: Dict[str, Any],
    load_forecast: List[float],
    physical_min_capacity: float | None = None,
) -> Dict[str, Any]:
    """Calculate cost for staying in a single mode for all intervals."""
    effective_min = (
        physical_min_capacity if physical_min_capacity is not None else min_capacity
    )

    planning_minimum = min_capacity
    penalty_cost = 0.0
    planning_violations = 0
    efficiency = sensor._get_battery_efficiency()

    total_cost = 0.0
    total_grid_import = 0.0
    battery_soc = current_capacity
    timeline_cache = []

    for t in range(len(spot_prices)):
        timestamp_str = spot_prices[t].get("time", "")
        spot_price = spot_prices[t].get("price", 0.0)
        export_price = (
            export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
        )
        load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

        solar_kwh = 0.0
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            solar_kwh = get_solar_for_timestamp(
                timestamp,
                solar_forecast,
                log_rate_limited=sensor._log_rate_limited,
            )
        except Exception:
            solar_kwh = 0.0

        sim_result = simulate_interval(
            mode=fixed_mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_soc,
            capacity_kwh=max_capacity,
            hw_min_capacity_kwh=effective_min,
            spot_price_czk=spot_price,
            export_price_czk=export_price,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
        )

        total_cost += sim_result["net_cost_czk"]
        total_grid_import += sim_result.get("grid_import_kwh", 0.0)
        battery_soc = sim_result["new_soc_kwh"]

        if battery_soc < planning_minimum:
            deficit = planning_minimum - battery_soc
            interval_penalty = (deficit * spot_price) / efficiency
            penalty_cost += interval_penalty
            planning_violations += 1

        if fixed_mode == CBB_MODE_HOME_I:
            timeline_cache.append(
                {
                    "time": timestamp_str,
                    "net_cost": sim_result["net_cost_czk"],
                }
            )

    adjusted_total_cost = total_cost + penalty_cost

    return {
        "total_cost": round(total_cost, 2),
        "grid_import_kwh": round(total_grid_import, 2),
        "final_battery_kwh": round(battery_soc, 2),
        "penalty_cost": round(penalty_cost, 2),
        "planning_violations": planning_violations,
        "adjusted_total_cost": round(adjusted_total_cost, 2),
    }


def calculate_mode_baselines(
    sensor: Any,
    *,
    current_capacity: float,
    max_capacity: float,
    physical_min_capacity: float,
    spot_prices: List[Dict[str, Any]],
    export_prices: List[Dict[str, Any]],
    solar_forecast: Dict[str, Any],
    load_forecast: List[float],
) -> Dict[str, Dict[str, Any]]:
    """Calculate baseline costs for all modes."""
    baselines: Dict[str, Dict[str, Any]] = {}

    mode_mapping = [
        (CBB_MODE_HOME_I, "HOME_I"),
        (CBB_MODE_HOME_II, "HOME_II"),
        (CBB_MODE_HOME_III, "HOME_III"),
        (CBB_MODE_HOME_UPS, "HOME_UPS"),
    ]

    _LOGGER.debug(
        "Calculating baselines: physical_min=%.2f kWh (%.0f%%)",
        physical_min_capacity,
        physical_min_capacity / max_capacity * 100,
    )

    for mode_id, mode_name in mode_mapping:
        result = calculate_fixed_mode_cost(
            sensor,
            fixed_mode=mode_id,
            current_capacity=current_capacity,
            max_capacity=max_capacity,
            min_capacity=physical_min_capacity,
            spot_prices=spot_prices,
            export_prices=export_prices,
            solar_forecast=solar_forecast,
            load_forecast=load_forecast,
            physical_min_capacity=physical_min_capacity,
        )

        baselines[mode_name] = result

        penalty_info = ""
        if result["planning_violations"] > 0:
            penalty_info = (
                f", penalty={result['penalty_cost']:.2f} CZK "
                f"({result['planning_violations']} violations)"
            )

        _LOGGER.debug(
            "  %s: cost=%.2f CZK%s, grid_import=%.2f kWh, final_battery=%.2f kWh, "
            "adjusted_cost=%.2f CZK",
            mode_name,
            result["total_cost"],
            penalty_info,
            result["grid_import_kwh"],
            result["final_battery_kwh"],
            result["adjusted_total_cost"],
        )

    return baselines


def calculate_do_nothing_cost(
    sensor: Any,
    *,
    current_capacity: float,
    max_capacity: float,
    min_capacity: float,
    spot_prices: List[Dict[str, Any]],
    export_prices: List[Dict[str, Any]],
    solar_forecast: Dict[str, Any],
    load_forecast: List[float],
) -> float:
    """Calculate costs if current mode stays unchanged."""
    current_mode = sensor._get_current_mode()
    efficiency = sensor._get_battery_efficiency()

    _LOGGER.debug(
        "[DO NOTHING] Calculating cost for current mode: %s",
        current_mode,
    )

    total_cost = 0.0
    battery_soc = current_capacity

    for t in range(len(spot_prices)):
        timestamp_str = spot_prices[t].get("time", "")
        spot_price = spot_prices[t].get("price", 0.0)
        export_price = (
            export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
        )
        load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

        solar_kwh = 0.0
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            solar_kwh = get_solar_for_timestamp(
                timestamp,
                solar_forecast,
                log_rate_limited=sensor._log_rate_limited,
            )
        except Exception:
            solar_kwh = 0.0

        sim_result = simulate_interval(
            mode=current_mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_soc,
            capacity_kwh=max_capacity,
            hw_min_capacity_kwh=min_capacity,
            spot_price_czk=spot_price,
            export_price_czk=export_price,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
        )

        total_cost += sim_result["net_cost_czk"]
        battery_soc = sim_result["new_soc_kwh"]

    return total_cost


def calculate_full_ups_cost(
    sensor: Any,
    *,
    current_capacity: float,
    max_capacity: float,
    min_capacity: float,
    spot_prices: List[Dict[str, Any]],
    export_prices: List[Dict[str, Any]],
    solar_forecast: Dict[str, Any],
    load_forecast: List[float],
) -> float:
    """Calculate cost for charging to full at cheapest night intervals."""
    efficiency = sensor._get_battery_efficiency()
    needed_kwh = max_capacity - current_capacity
    ac_charging_limit = 0.7
    intervals_needed = (
        int(math.ceil(needed_kwh / ac_charging_limit)) if needed_kwh > 0.001 else 0
    )

    _LOGGER.debug(
        "[FULL UPS] Need %.2f kWh to reach %.2f kWh, requires %s intervals",
        needed_kwh,
        max_capacity,
        intervals_needed,
    )

    night_intervals = []
    for t, price_data in enumerate(spot_prices):
        timestamp_str = price_data.get("time", "")
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            hour = timestamp.hour
            if 22 <= hour or hour < 6:
                night_intervals.append((t, price_data.get("price", 0.0)))
        except Exception:  # nosec B112
            continue

    night_sorted = sorted(night_intervals, key=lambda x: x[1])
    cheapest_intervals = set([idx for idx, _price in night_sorted[:intervals_needed]])

    if cheapest_intervals:
        _LOGGER.debug(
            "[FULL UPS] Selected %s cheapest night intervals from %s total",
            len(cheapest_intervals),
            len(night_intervals),
        )

    total_cost = 0.0
    battery_soc = current_capacity

    for t in range(len(spot_prices)):
        timestamp_str = spot_prices[t].get("time", "")
        spot_price = spot_prices[t].get("price", 0.0)
        export_price = (
            export_prices[t].get("price", 0.0) if t < len(export_prices) else 0.0
        )
        load_kwh = load_forecast[t] if t < len(load_forecast) else 0.0

        solar_kwh = 0.0
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            solar_kwh = get_solar_for_timestamp(
                timestamp,
                solar_forecast,
                log_rate_limited=sensor._log_rate_limited,
            )
        except Exception:
            solar_kwh = 0.0

        if t in cheapest_intervals and battery_soc < max_capacity:
            mode = CBB_MODE_HOME_UPS
        else:
            mode = CBB_MODE_HOME_I

        sim_result = simulate_interval(
            mode=mode,
            solar_kwh=solar_kwh,
            load_kwh=load_kwh,
            battery_soc_kwh=battery_soc,
            capacity_kwh=max_capacity,
            hw_min_capacity_kwh=min_capacity,
            spot_price_czk=spot_price,
            export_price_czk=export_price,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
        )

        total_cost += sim_result["net_cost_czk"]
        battery_soc = sim_result["new_soc_kwh"]

    return total_cost


def generate_alternatives(  # noqa: C901
    sensor: Any,
    *,
    spot_prices: List[Dict[str, Any]],
    solar_forecast: Dict[str, Any],
    load_forecast: List[float],
    optimal_cost_48h: float,
    current_capacity: float,
    max_capacity: float,
    efficiency: float,
) -> Dict[str, Dict[str, Any]]:
    """Generate what-if alternatives for all fixed modes."""
    now = dt_util.now()
    today_start = datetime.combine(now.date(), datetime.min.time())
    today_start = dt_util.as_local(today_start)
    tomorrow_end = today_start + timedelta(hours=48)

    home_i_timeline_cache = []

    def simulate_mode(mode: int) -> float:
        battery = current_capacity
        total_cost = 0.0

        for i, price_data in enumerate(spot_prices):
            timestamp_str = price_data.get("time", "")
            if not timestamp_str:
                continue

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp.tzinfo is None:
                    timestamp = dt_util.as_local(timestamp)
                if not (today_start <= timestamp < tomorrow_end):
                    continue
            except Exception:  # nosec B112
                continue

            try:
                solar_kwh = get_solar_for_timestamp(
                    timestamp,
                    solar_forecast,
                    log_rate_limited=sensor._log_rate_limited,
                )
            except Exception:
                solar_kwh = 0.0

            load_kwh = load_forecast[i] if i < len(load_forecast) else 0.125
            price = price_data.get("price", 0)

            grid_import = 0.0
            grid_export = 0.0
            net_cost = 0.0

            if mode == 0:
                if solar_kwh >= load_kwh:
                    surplus = solar_kwh - load_kwh
                    battery += surplus
                    if battery > max_capacity:
                        grid_export = battery - max_capacity
                        battery = max_capacity
                        net_cost = -grid_export * price
                        total_cost += net_cost
                else:
                    deficit = load_kwh - solar_kwh
                    battery -= deficit / efficiency
                    if battery < 0:
                        grid_import = -battery * efficiency
                        battery = 0
                        net_cost = grid_import * price
                        total_cost += net_cost

                home_i_timeline_cache.append(
                    {"time": timestamp_str, "net_cost": net_cost}
                )

            elif mode == 1:
                if solar_kwh >= load_kwh:
                    surplus = solar_kwh - load_kwh
                    battery += surplus
                    if battery > max_capacity:
                        grid_export = battery - max_capacity
                        battery = max_capacity
                        total_cost -= grid_export * price
                else:
                    grid_import = load_kwh - solar_kwh
                    total_cost += grid_import * price

            elif mode == 2:
                battery += solar_kwh
                if battery > max_capacity:
                    grid_export = battery - max_capacity
                    battery = max_capacity
                    total_cost -= grid_export * price
                grid_import = load_kwh
                total_cost += grid_import * price

            elif mode == 3:
                if price < 1.5:
                    charge_amount = min(2.8 / 4.0, max_capacity - battery)
                    if charge_amount > 0:
                        grid_import += charge_amount
                        total_cost += charge_amount * price
                        battery += charge_amount * efficiency

                if solar_kwh >= load_kwh:
                    surplus = solar_kwh - load_kwh
                    battery += surplus
                    if battery > max_capacity:
                        grid_export = battery - max_capacity
                        battery = max_capacity
                        total_cost -= grid_export * price
                else:
                    deficit = load_kwh - solar_kwh
                    battery -= deficit / efficiency
                    if battery < 0:
                        extra_import = -battery * efficiency
                        battery = 0
                        grid_import += extra_import
                        total_cost += extra_import * price

            battery = max(0, min(battery, max_capacity))

        return total_cost

    alternatives: Dict[str, Dict[str, Any]] = {}
    mode_names = {
        0: "HOME I",
        1: "HOME II",
        2: "HOME III",
        3: "HOME UPS",
    }

    for mode, name in mode_names.items():
        cost = simulate_mode(mode)
        delta = cost - optimal_cost_48h
        alternatives[name] = {
            "cost_czk": round(cost, 2),
            "delta_czk": round(delta, 2),
        }

    alternatives["DO NOTHING"] = {
        "cost_czk": round(optimal_cost_48h, 2),
        "delta_czk": 0.0,
        "current_mode": "Optimized",
    }

    return alternatives
