"""Charging plan helpers extracted from the battery forecast sensor."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .charging_plan_utils import (
    calculate_minimum_charge,
    calculate_protection_requirement,
    get_candidate_intervals,
    recalculate_timeline_from_index,
    simulate_forward,
)

_LOGGER = logging.getLogger(__name__)


def economic_charging_plan(
    *,
    timeline_data: List[Dict[str, Any]],
    min_capacity_kwh: float,
    min_capacity_floor: float,
    effective_minimum_kwh: float,
    target_capacity_kwh: float,
    max_charging_price: float,
    min_savings_margin: float,
    charging_power_kw: float,
    max_capacity: float,
    enable_blackout_protection: bool,
    blackout_protection_hours: int,
    blackout_target_soc_percent: float,
    enable_weather_risk: bool,
    weather_risk_level: str,
    weather_target_soc_percent: float,
    target_reason: str,
    battery_efficiency: float,
    config: Dict[str, Any],
    iso_tz_offset: str,
    mode_label_home_ups: str,
    mode_label_home_i: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Economic charging plan with forward simulation."""
    timeline = [dict(point) for point in timeline_data]

    charge_per_interval = charging_power_kw / 4.0
    current_time = datetime.now()

    protection_soc_kwh = calculate_protection_requirement(
        timeline,
        max_capacity,
        config=config,
        iso_tz_offset=iso_tz_offset,
    )

    if protection_soc_kwh is not None:
        current_soc = timeline[0].get("battery_capacity_kwh", 0)
        protection_shortage = protection_soc_kwh - current_soc

        if protection_shortage > 0:
            _LOGGER.warning(
                "PROTECTION OVERRIDE: Need %.2fkWh to reach protection target %.2fkWh (current: %.2fkWh)",
                protection_shortage,
                protection_soc_kwh,
                current_soc,
            )

            candidates = get_candidate_intervals(
                timeline,
                max_charging_price,
                current_time=current_time,
                iso_tz_offset=iso_tz_offset,
            )

            if not candidates:
                _LOGGER.error(
                    "PROTECTION FAILED: No charging candidates under max_price=%sCZK",
                    max_charging_price,
                )
            else:
                charged = 0.0
                for candidate in candidates:
                    if charged >= protection_shortage:
                        break

                    idx = candidate["index"]
                    old_charge = timeline[idx].get("grid_charge_kwh", 0)
                    timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
                    if timeline[idx].get("reason") == "normal":
                        timeline[idx]["reason"] = "protection_charge"
                    charged += charge_per_interval

                    _LOGGER.info(
                        "PROTECTION: Adding %.2fkWh at %s (price %.2fCZK)",
                        charge_per_interval,
                        candidate["timestamp"],
                        candidate["price"],
                    )

                    recalculate_timeline_from_index(
                        timeline,
                        idx,
                        max_capacity=max_capacity,
                        min_capacity=min_capacity_floor,
                        efficiency=battery_efficiency,
                        mode_label_home_ups=mode_label_home_ups,
                        mode_label_home_i=mode_label_home_i,
                    )

                _LOGGER.info(
                    "PROTECTION: Charged %.2fkWh / %.2fkWh needed",
                    charged,
                    protection_shortage,
                )

    candidates = get_candidate_intervals(
        timeline,
        max_charging_price,
        current_time=current_time,
        iso_tz_offset=iso_tz_offset,
    )

    if not candidates:
        _LOGGER.warning(
            "No economic charging candidates under max_price=%sCZK",
            max_charging_price,
        )
        return timeline, {}

    _LOGGER.info("Found %s economic charging candidates", len(candidates))

    for candidate in candidates:
        idx = candidate["index"]
        price = candidate["price"]
        timestamp = candidate["timestamp"]

        horizon_hours = min(48, len(timeline) - idx)

        result_charge = simulate_forward(
            timeline=timeline,
            start_index=idx,
            charge_now=True,
            charge_amount_kwh=charge_per_interval,
            horizon_hours=horizon_hours,
            effective_minimum_kwh=effective_minimum_kwh,
            efficiency=battery_efficiency,
        )
        cost_charge = result_charge["total_charging_cost"]

        result_wait = simulate_forward(
            timeline=timeline,
            start_index=idx,
            charge_now=False,
            charge_amount_kwh=0,
            horizon_hours=horizon_hours,
            effective_minimum_kwh=effective_minimum_kwh,
            efficiency=battery_efficiency,
        )
        cost_wait = result_wait["total_charging_cost"]
        min_soc_wait = result_wait["min_soc"]
        death_valley_wait = result_wait["death_valley_reached"]

        if death_valley_wait:
            shortage = effective_minimum_kwh - min_soc_wait

            if shortage > 0:
                min_charge = calculate_minimum_charge(
                    scenario_wait_min_soc=min_soc_wait,
                    effective_minimum_kwh=effective_minimum_kwh,
                    max_charge_per_interval=charge_per_interval,
                )

                _LOGGER.warning(
                    "DEATH VALLEY at %s: Need %.2fkWh (min_soc_wait=%.2fkWh, effective_min=%.2fkWh)",
                    timestamp,
                    min_charge,
                    min_soc_wait,
                    effective_minimum_kwh,
                )

                old_charge = timeline[idx].get("grid_charge_kwh", 0)
                timeline[idx]["grid_charge_kwh"] = old_charge + min_charge
                if timeline[idx].get("reason") == "normal":
                    timeline[idx]["reason"] = "death_valley_fix"

                recalculate_timeline_from_index(
                    timeline,
                    idx,
                    max_capacity=max_capacity,
                    min_capacity=min_capacity_floor,
                    efficiency=battery_efficiency,
                    mode_label_home_ups=mode_label_home_ups,
                    mode_label_home_i=mode_label_home_i,
                )

                _LOGGER.info(
                    "DEATH VALLEY FIX: Added %.2fkWh at %s (price %.2fCZK)",
                    min_charge,
                    timestamp,
                    price,
                )

                continue

        savings_per_kwh = (cost_wait - cost_charge) / charge_per_interval

        if savings_per_kwh >= min_savings_margin:
            old_charge = timeline[idx].get("grid_charge_kwh", 0)
            timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
            if timeline[idx].get("reason") == "normal":
                timeline[idx]["reason"] = "economic_charge"

            recalculate_timeline_from_index(
                timeline,
                idx,
                max_capacity=max_capacity,
                min_capacity=min_capacity_floor,
                efficiency=battery_efficiency,
                mode_label_home_ups=mode_label_home_ups,
                mode_label_home_i=mode_label_home_i,
            )

            _LOGGER.info(
                "ECONOMIC: Added %.2fkWh at %s (price %.2fCZK, savings %.3fCZK/kWh > %.3fCZK/kWh)",
                charge_per_interval,
                timestamp,
                price,
                savings_per_kwh,
                min_savings_margin,
            )
        else:
            _LOGGER.debug(
                "ECONOMIC: Skipping %s (price %.2fCZK, savings %.3fCZK/kWh < %.3fCZK/kWh)",
                timestamp,
                price,
                savings_per_kwh,
                min_savings_margin,
            )

    final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
    target_achieved = final_capacity >= target_capacity_kwh
    min_achieved = final_capacity >= min_capacity_kwh

    metrics = {
        "algorithm": "economic",
        "target_capacity_kwh": target_capacity_kwh,
        "effective_minimum_kwh": effective_minimum_kwh,
        "final_capacity_kwh": final_capacity,
        "min_capacity_kwh": min_capacity_kwh,
        "target_achieved": target_achieved,
        "min_achieved": min_achieved,
        "shortage_kwh": (
            max(0, target_capacity_kwh - final_capacity) if not target_achieved else 0
        ),
        "protection_enabled": enable_blackout_protection or enable_weather_risk,
        "protection_soc_kwh": protection_soc_kwh,
        "optimal_target_info": {
            "target_kwh": target_capacity_kwh,
            "target_percent": (target_capacity_kwh / max_capacity * 100),
            "reason": target_reason,
        },
    }

    _LOGGER.info(
        "Economic charging complete: final=%.2fkWh, target=%.2fkWh, achieved=%s",
        final_capacity,
        target_capacity_kwh,
        target_achieved,
    )

    return timeline, metrics


def smart_charging_plan(
    *,
    timeline: List[Dict[str, Any]],
    min_capacity: float,
    target_capacity: float,
    max_price: float,
    price_threshold: float,
    charging_power_kw: float,
    max_capacity: float,
    efficiency: float,
    mode_label_home_ups: str,
    mode_label_home_i: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Smart charging plan using cheapest intervals."""
    charge_per_interval = charging_power_kw / 4.0

    critical_intervals = []
    min_capacity_in_timeline = float("inf")
    min_capacity_timestamp = None

    for i, point in enumerate(timeline):
        capacity = point.get("battery_capacity_kwh", 0)
        if capacity < min_capacity:
            critical_intervals.append(i)
        if capacity < min_capacity_in_timeline:
            min_capacity_in_timeline = capacity
            min_capacity_timestamp = point.get("timestamp", "unknown")

    final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
    energy_needed_for_target = max(0, target_capacity - final_capacity)

    _LOGGER.info(
        "Smart charging: %s critical intervals, min_capacity_in_timeline: %.2fkWh @ %s, min_threshold: %.2fkWh, need %.2fkWh for target",
        len(critical_intervals),
        min_capacity_in_timeline,
        min_capacity_timestamp,
        min_capacity,
        energy_needed_for_target,
    )

    if critical_intervals:
        first_critical = critical_intervals[0]

        _LOGGER.info(
            "First critical interval at index %s, capacity: %.2fkWh",
            first_critical,
            timeline[first_critical].get("battery_capacity_kwh", 0),
        )

        critical_capacity = timeline[first_critical].get("battery_capacity_kwh", 0)
        energy_needed = min_capacity - critical_capacity

        if energy_needed > 0:
            _LOGGER.info(
                "Need %.2fkWh to reach minimum at critical point", energy_needed
            )

            charging_candidates = []
            for i in range(first_critical):
                point = timeline[i]
                price = point.get("spot_price_czk", float("inf"))
                capacity = point.get("battery_capacity_kwh", 0)

                if price > max_price:
                    continue

                if capacity >= max_capacity * 0.99:
                    continue

                charging_candidates.append(
                    {
                        "index": i,
                        "price": price,
                        "capacity": capacity,
                        "timestamp": point.get("timestamp", ""),
                    }
                )

            charging_candidates.sort(key=lambda x: x["price"])

            added_energy = 0
            while added_energy < energy_needed and charging_candidates:
                best = charging_candidates.pop(0)
                idx = best["index"]

                old_charge = timeline[idx].get("grid_charge_kwh", 0)
                timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
                if timeline[idx].get("reason") == "normal":
                    timeline[idx]["reason"] = "legacy_critical"
                added_energy += charge_per_interval

                _LOGGER.debug(
                    "Critical fix: Adding %.2fkWh at index %s (price %.2fCZK), total added: %.2fkWh",
                    charge_per_interval,
                    idx,
                    best["price"],
                    added_energy,
                )

                recalculate_timeline_from_index(
                    timeline,
                    idx,
                    max_capacity=max_capacity,
                    min_capacity=min_capacity,
                    efficiency=efficiency,
                    mode_label_home_ups=mode_label_home_ups,
                    mode_label_home_i=mode_label_home_i,
                )

                new_critical_capacity = timeline[first_critical].get(
                    "battery_capacity_kwh", 0
                )
                if new_critical_capacity >= min_capacity:
                    _LOGGER.info(
                        "Critical interval fixed: capacity now %.2fkWh >= %.2fkWh",
                        new_critical_capacity,
                        min_capacity,
                    )
                    break

    max_iterations = 100
    iteration = 0

    effective_target = target_capacity
    if target_capacity >= max_capacity * 0.99:
        effective_target = max_capacity * 0.99

    while iteration < max_iterations:
        current_final_capacity = timeline[-1].get("battery_capacity_kwh", 0)

        if current_final_capacity >= effective_target:
            _LOGGER.info(
                "Target capacity achieved: %.2fkWh >= %.2fkWh (original target: %.2fkWh)",
                current_final_capacity,
                effective_target,
                target_capacity,
            )
            break

        shortage = effective_target - current_final_capacity

        charging_candidates = []
        for i, point in enumerate(timeline):
            price = point.get("spot_price_czk", float("inf"))
            capacity = point.get("battery_capacity_kwh", 0)
            existing_charge = point.get("grid_charge_kwh", 0)

            if price > max_price:
                continue

            if capacity >= max_capacity * 0.99:
                continue

            if i >= len(timeline) - 1:
                continue

            if existing_charge >= charge_per_interval * 0.99:
                continue

            charging_candidates.append(
                {
                    "index": i,
                    "price": price,
                    "capacity": capacity,
                    "timestamp": point.get("timestamp", ""),
                    "existing_charge": existing_charge,
                }
            )

        charging_candidates.sort(key=lambda x: x["price"])

        if not charging_candidates:
            _LOGGER.warning(
                "No more charging candidates available, shortage: %.2fkWh",
                shortage,
            )
            break

        best_candidate = charging_candidates[0]
        idx = best_candidate["index"]

        old_charge = timeline[idx].get("grid_charge_kwh", 0)
        timeline[idx]["grid_charge_kwh"] = old_charge + charge_per_interval
        if timeline[idx].get("reason") == "normal":
            timeline[idx]["reason"] = "legacy_target"

        _LOGGER.debug(
            "Target charging: Adding %.2fkWh at index %s (price %.2fCZK, timestamp %s), shortage: %.2fkWh, capacity before: %.2fkWh",
            charge_per_interval,
            idx,
            best_candidate["price"],
            best_candidate["timestamp"],
            shortage,
            best_candidate["capacity"],
        )

        recalculate_timeline_from_index(
            timeline,
            idx,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            efficiency=efficiency,
            mode_label_home_ups=mode_label_home_ups,
            mode_label_home_i=mode_label_home_i,
        )

        iteration += 1

    if iteration >= max_iterations:
        _LOGGER.warning("Reached max iterations in smart charging plan")

    final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
    target_achieved = final_capacity >= effective_target
    min_achieved = final_capacity >= min_capacity

    metrics = {
        "target_capacity_kwh": target_capacity,
        "effective_target_kwh": effective_target,
        "final_capacity_kwh": final_capacity,
        "min_capacity_kwh": min_capacity,
        "target_achieved": target_achieved,
        "min_achieved": min_achieved,
        "shortage_kwh": (
            max(0, effective_target - final_capacity) if not target_achieved else 0
        ),
    }

    return timeline, metrics
