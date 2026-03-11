"""Charging plan utility helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def get_candidate_intervals(
    timeline: List[Dict[str, Any]],
    max_charging_price: float,
    *,
    current_time: Optional[datetime] = None,
    iso_tz_offset: str = "+00:00",
) -> List[Dict[str, Any]]:
    """Get candidate intervals for charging."""
    if current_time is None:
        current_time = dt_util.now()

    candidates = []

    for i, interval in enumerate(timeline):
        price = interval.get("spot_price_czk", float("inf"))
        timestamp_str = interval.get("timestamp", "")

        try:
            interval_time = datetime.fromisoformat(
                timestamp_str.replace("Z", iso_tz_offset)
            )
        except Exception:  # nosec B112
            continue

        if price >= max_charging_price:
            continue

        interval_time_naive = (
            interval_time.replace(tzinfo=None)
            if interval_time.tzinfo
            else interval_time
        )
        current_time_naive = (
            current_time.replace(tzinfo=None) if current_time.tzinfo else current_time
        )

        if interval_time_naive <= current_time_naive:
            continue

        candidates.append(
            {
                "index": i,
                "price": price,
                "timestamp": timestamp_str,
                "interval_time": interval_time,
            }
        )

    candidates.sort(key=lambda x: x["price"])

    if not candidates:
        _LOGGER.warning(
            "No charging intervals available - all prices above max_charging_price (%.2f Kč/kWh)",
            max_charging_price,
        )

    return candidates


def simulate_forward(
    timeline: List[Dict[str, Any]],
    start_index: int,
    charge_now: bool,
    charge_amount_kwh: float,
    horizon_hours: int,
    effective_minimum_kwh: float,
    efficiency: float,
) -> Dict[str, Any]:
    """Forward simulate SoC over a horizon."""
    if start_index >= len(timeline):
        return {
            "total_charging_cost": 0,
            "min_soc": 0,
            "final_soc": 0,
            "death_valley_reached": True,
            "charging_events": [],
        }

    sim_timeline = [dict(point) for point in timeline]

    soc = sim_timeline[start_index].get("battery_capacity_kwh", 0)
    total_cost = 0
    charging_events = []

    if charge_now and charge_amount_kwh > 0:
        soc += charge_amount_kwh
        price = sim_timeline[start_index].get("spot_price_czk", 0)
        cost = charge_amount_kwh * price
        total_cost += cost

        charging_events.append(
            {
                "index": start_index,
                "kwh": charge_amount_kwh,
                "price": price,
                "cost": cost,
                "reason": "scenario_test",
            }
        )

        sim_timeline[start_index]["battery_capacity_kwh"] = soc
        sim_timeline[start_index]["grid_charge_kwh"] = charge_amount_kwh

    min_soc = soc
    horizon_intervals = horizon_hours * 4

    for i in range(
        start_index + 1, min(start_index + horizon_intervals, len(sim_timeline))
    ):
        prev_soc = sim_timeline[i - 1].get("battery_capacity_kwh", 0)

        solar_kwh = sim_timeline[i].get("solar_production_kwh", 0)
        load_kwh = sim_timeline[i].get("consumption_kwh", 0)
        grid_kwh = sim_timeline[i].get("grid_charge_kwh", 0)
        reason = sim_timeline[i].get("reason", "")

        is_balancing = reason.startswith("balancing_")
        is_ups_mode = grid_kwh > 0 or is_balancing

        if is_ups_mode:
            net_energy = solar_kwh + grid_kwh
        else:
            if solar_kwh >= load_kwh:
                net_energy = (solar_kwh - load_kwh) + grid_kwh
            else:
                load_from_battery = load_kwh - solar_kwh
                battery_drain = load_from_battery / efficiency
                net_energy = -battery_drain + grid_kwh

        soc = prev_soc + net_energy
        sim_timeline[i]["battery_capacity_kwh"] = soc

        min_soc = min(min_soc, soc)

    final_soc = sim_timeline[
        min(start_index + horizon_intervals - 1, len(sim_timeline) - 1)
    ].get("battery_capacity_kwh", 0)
    death_valley_reached = min_soc < effective_minimum_kwh

    return {
        "total_charging_cost": total_cost,
        "min_soc": min_soc,
        "final_soc": final_soc,
        "death_valley_reached": death_valley_reached,
        "charging_events": charging_events,
    }


def calculate_minimum_charge(
    scenario_wait_min_soc: float,
    effective_minimum_kwh: float,
    max_charge_per_interval: float,
) -> float:
    """Calculate minimum charge required to avoid minimum violation."""
    shortage = effective_minimum_kwh - scenario_wait_min_soc

    if shortage <= 0:
        return 0

    charge_needed = shortage * 1.1
    return min(charge_needed, max_charge_per_interval)


def calculate_protection_requirement(
    timeline: List[Dict[str, Any]],
    max_capacity: float,
    *,
    config: Dict[str, Any],
    iso_tz_offset: str = "+00:00",
) -> Optional[float]:
    """Calculate required SoC for blackout/weather protection."""
    required_soc = 0.0

    enable_blackout = config.get("enable_blackout_protection", False)
    if enable_blackout:
        blackout_hours = config.get("blackout_protection_hours", 12)
        blackout_target_percent = config.get("blackout_target_soc_percent", 60.0)

        current_time = dt_util.now()
        blackout_end = current_time + timedelta(hours=blackout_hours)

        blackout_consumption = 0.0
        for point in timeline:
            try:
                timestamp_str = point.get("timestamp", "")
                point_time = datetime.fromisoformat(
                    timestamp_str.replace("Z", iso_tz_offset)
                )
            except Exception:  # nosec B112
                continue

            if point_time <= blackout_end:
                blackout_consumption += point.get("consumption_kwh", 0)

        required_soc_blackout = max(
            blackout_consumption,
            (blackout_target_percent / 100.0) * max_capacity,
        )

        required_soc = max(required_soc, required_soc_blackout)

    enable_weather = config.get("enable_weather_risk", False)
    if enable_weather:
        weather_risk_level = config.get("weather_risk_level", "low")
        weather_target_percent = config.get("weather_target_soc_percent", 50.0)

        weather_multiplier = {
            "low": 0.5,
            "medium": 0.75,
            "high": 1.0,
        }.get(weather_risk_level, 0.5)

        weather_target = (weather_target_percent / 100.0) * max_capacity
        required_soc = max(required_soc, weather_target * weather_multiplier)

    if required_soc > 0:
        return required_soc

    return None


def recalculate_timeline_from_index(
    timeline: List[Dict[str, Any]],
    start_index: int,
    *,
    max_capacity: float,
    min_capacity: float,
    efficiency: float,
    mode_label_home_ups: str,
    mode_label_home_i: str,
) -> None:
    """Recalculate battery trajectory from a given index."""
    for i in range(start_index, len(timeline)):
        if i == 0:
            continue

        prev_point = timeline[i - 1]
        curr_point = timeline[i]

        prev_capacity = prev_point.get("battery_capacity_kwh", 0)
        solar_kwh = curr_point.get("solar_production_kwh", 0)
        grid_kwh = curr_point.get("grid_charge_kwh", 0)
        load_kwh = curr_point.get("consumption_kwh", 0)
        reason = curr_point.get("reason", "")

        is_balancing = reason.startswith("balancing_")
        is_ups_mode = grid_kwh > 0 or is_balancing

        if is_ups_mode:
            net_energy = solar_kwh + grid_kwh
        else:
            if solar_kwh >= load_kwh:
                net_energy = (solar_kwh - load_kwh) + grid_kwh
            else:
                load_from_battery = load_kwh - solar_kwh
                battery_drain = load_from_battery / efficiency
                net_energy = -battery_drain + grid_kwh

        curr_point["solar_charge_kwh"] = round(max(0, solar_kwh - load_kwh), 2)

        new_capacity = prev_capacity + net_energy
        new_capacity = min(new_capacity, max_capacity)
        if new_capacity < min_capacity:
            new_capacity = min_capacity
        new_capacity = max(0.0, new_capacity)

        curr_point["battery_capacity_kwh"] = round(new_capacity, 2)
        curr_point["mode"] = mode_label_home_ups if is_ups_mode else mode_label_home_i
