"""Charging plan adjustment helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .charging_plan_utils import recalculate_timeline_from_index

_LOGGER = logging.getLogger(__name__)


def fix_minimum_capacity_violations(
    *,
    timeline: List[Dict[str, Any]],
    min_capacity: float,
    max_price: float,
    price_threshold: float,
    charging_power_kw: float,
    max_capacity: float,
    efficiency: float,
    mode_label_home_ups: str,
    mode_label_home_i: str,
) -> List[Dict[str, Any]]:
    """Fix any minimum capacity violations by adding charging."""
    max_iterations = 50
    iteration = 0

    while iteration < max_iterations:
        violation_index = find_first_minimum_violation(timeline, min_capacity)
        if violation_index is None:
            break

        _LOGGER.debug(
            "Found minimum violation at index %s, capacity=%.2fkWh",
            violation_index,
            timeline[violation_index]["battery_capacity_kwh"],
        )

        charging_index = find_cheapest_hour_before(
            timeline, violation_index, max_price, price_threshold
        )

        if charging_index is None:
            _LOGGER.warning(
                "Cannot fix minimum violation at index %s - no suitable charging time found",
                violation_index,
            )
            break

        charge_kwh = charging_power_kw / 4.0
        old_charge = timeline[charging_index].get("grid_charge_kwh", 0)
        timeline[charging_index]["grid_charge_kwh"] = old_charge + charge_kwh
        if timeline[charging_index].get("reason") == "normal":
            timeline[charging_index]["reason"] = "legacy_violation_fix"

        _LOGGER.debug(
            "Adding %.2fkWh charging at index %s, price=%.2fCZK",
            charge_kwh,
            charging_index,
            timeline[charging_index]["spot_price_czk"],
        )

        recalculate_timeline_from_index(
            timeline,
            charging_index,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            efficiency=efficiency,
            mode_label_home_ups=mode_label_home_ups,
            mode_label_home_i=mode_label_home_i,
        )
        iteration += 1

    if iteration >= max_iterations:
        _LOGGER.warning("Reached max iterations in minimum capacity fixing")

    return timeline


def ensure_target_capacity_at_end(
    *,
    timeline: List[Dict[str, Any]],
    target_capacity: float,
    max_price: float,
    price_threshold: float,
    charging_power_kw: float,
    max_capacity: float,
    min_capacity: float,
    efficiency: float,
    mode_label_home_ups: str,
    mode_label_home_i: str,
) -> List[Dict[str, Any]]:
    """Ensure target capacity at end of timeline."""
    if not timeline:
        return timeline

    max_iterations = 50
    iteration = 0

    while iteration < max_iterations:
        final_capacity = timeline[-1].get("battery_capacity_kwh", 0)
        if final_capacity >= target_capacity:
            _LOGGER.debug(
                "Target capacity achieved: %.2fkWh >= %.2fkWh",
                final_capacity,
                target_capacity,
            )
            break

        shortage = target_capacity - final_capacity
        _LOGGER.debug("Target capacity shortage: %.2fkWh", shortage)

        charging_index = find_cheapest_suitable_hour(
            timeline, max_price, price_threshold
        )

        if charging_index is None:
            _LOGGER.warning(
                "Cannot achieve target capacity - no suitable charging time found"
            )
            break

        charge_kwh = charging_power_kw / 4.0
        old_charge = timeline[charging_index].get("grid_charge_kwh", 0)
        timeline[charging_index]["grid_charge_kwh"] = old_charge + charge_kwh
        if timeline[charging_index].get("reason") == "normal":
            timeline[charging_index]["reason"] = "legacy_target_ensure"

        _LOGGER.debug(
            "Adding %.2fkWh charging at index %s for target capacity",
            charge_kwh,
            charging_index,
        )

        recalculate_timeline_from_index(
            timeline,
            charging_index,
            max_capacity=max_capacity,
            min_capacity=min_capacity,
            efficiency=efficiency,
            mode_label_home_ups=mode_label_home_ups,
            mode_label_home_i=mode_label_home_i,
        )
        iteration += 1

    if iteration >= max_iterations:
        _LOGGER.warning("Reached max iterations in target capacity ensuring")

    return timeline


def find_first_minimum_violation(
    timeline: List[Dict[str, Any]], min_capacity: float
) -> Optional[int]:
    """Find the first interval where capacity drops below minimum."""
    for i, point in enumerate(timeline):
        if point.get("battery_capacity_kwh", 0) < min_capacity:
            return i
    return None


def find_cheapest_hour_before(
    timeline: List[Dict[str, Any]],
    violation_index: int,
    max_price: float,
    price_threshold: float,
) -> Optional[int]:
    """Find cheapest suitable interval before a violation."""
    candidates = []

    for i in range(violation_index):
        price = timeline[i].get("spot_price_czk", float("inf"))

        if price > max_price:
            continue
        if price > price_threshold:
            continue

        existing_charge = timeline[i].get("grid_charge_kwh", 0)
        if existing_charge > 0:
            continue

        candidates.append((i, price))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def find_cheapest_suitable_hour(
    timeline: List[Dict[str, Any]],
    max_price: float,
    price_threshold: float,
) -> Optional[int]:
    """Find cheapest suitable interval in entire timeline."""
    candidates = []

    for i, point in enumerate(timeline):
        price = point.get("spot_price_czk", float("inf"))

        if price > max_price:
            continue
        if price > price_threshold:
            continue

        existing_charge = point.get("grid_charge_kwh", 0)
        if existing_charge > 0:
            continue

        candidates.append((i, price))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]
