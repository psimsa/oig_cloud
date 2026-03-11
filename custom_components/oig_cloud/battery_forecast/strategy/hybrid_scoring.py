"""Hybrid strategy scoring helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..config import ChargingStrategy, NegativePriceStrategy
from ..types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    SpotPrice,
)


def extract_prices(spot_prices: List[SpotPrice]) -> List[float]:
    """Extract price values from SpotPrice objects."""
    prices: List[float] = []
    for sp in spot_prices:
        if isinstance(sp, dict):
            prices.append(float(sp.get("price", 0.0)))
        else:
            prices.append(float(sp))
    return prices


def analyze_future_prices(
    strategy,
    prices: List[float],
    export_prices: List[float],
    consumption_forecast: List[float],
) -> Dict[int, Dict[str, float]]:
    """Analyze future prices for forward-looking optimization."""
    _ = export_prices
    analysis: Dict[int, Dict[str, float]] = {}
    n = len(prices)

    # Efficiency constants
    ac_dc_eff = strategy.sim_config.ac_dc_efficiency
    dc_ac_eff = strategy.sim_config.dc_ac_efficiency

    # Calculate night consumption (intervals 56-96 = 20:00-00:00)
    night_start_idx = 56
    night_consumption = sum(
        consumption_forecast[i]
        for i in range(night_start_idx, min(n, night_start_idx + 20))
        if i < len(consumption_forecast)
    )

    for i in range(n):
        current_price = prices[i]

        lookahead_end = min(i + strategy.LOOKAHEAD_INTERVALS, n)
        future_prices = prices[i + 1 : lookahead_end] if i + 1 < n else []

        if not future_prices:
            analysis[i] = {
                "max_future_price": current_price,
                "avg_future_price": current_price,
                "expected_saving": 0.0,
                "should_charge": False,
                "charge_reason": "no_future_data",
                "night_deficit": 0.0,
            }
            continue

        max_future = max(future_prices)
        avg_future = sum(future_prices) / len(future_prices)
        min_future = min(future_prices)

        charge_cost = current_price / ac_dc_eff
        discharge_value = max_future * dc_ac_eff
        expected_saving = discharge_value - charge_cost

        min_spread = current_price * (strategy.MIN_PRICE_SPREAD_PERCENT / 100.0)
        profitable = expected_saving > min_spread

        price_percentile = sum(1 for p in future_prices if p > current_price)
        is_relatively_cheap = price_percentile >= len(future_prices) * 0.7

        intervals_to_night = max(0, night_start_idx - i)
        preparing_for_night = intervals_to_night < 20 and intervals_to_night > 0

        should_charge = False
        charge_reason = "not_profitable"

        if profitable and is_relatively_cheap:
            should_charge = True
            charge_reason = f"arbitrage_{expected_saving:.2f}CZK"
        elif preparing_for_night and is_relatively_cheap:
            should_charge = True
            charge_reason = "night_preparation"
        elif current_price < 0:
            should_charge = True
            charge_reason = "negative_price"
        elif current_price < avg_future * 0.85:
            should_charge = True
            charge_reason = f"below_avg_{current_price:.2f}<{avg_future:.2f}"
        elif is_relatively_cheap and current_price < min_future * 1.05:
            should_charge = True
            charge_reason = f"relative_cheap_{current_price:.2f}"

        analysis[i] = {
            "max_future_price": max_future,
            "avg_future_price": avg_future,
            "min_future_price": min_future,
            "expected_saving": expected_saving,
            "should_charge": should_charge,
            "charge_reason": charge_reason,
            "is_relatively_cheap": is_relatively_cheap,
            "preparing_for_night": preparing_for_night,
            "night_deficit": night_consumption,
        }

    return analysis


def select_best_mode(
    strategy,
    *,
    battery: float,
    solar: float,
    load: float,
    price: float,
    export_price: float,
    cheap_threshold: float,
    expensive_threshold: float,
    very_cheap: float,
    future_info: Optional[Dict[str, float]] = None,
) -> Tuple[int, str, Dict[int, float]]:
    """Select best mode based on scoring."""
    scores: Dict[int, float] = {}

    if future_info is None:
        future_info = {}
    is_relatively_cheap = future_info.get("is_relatively_cheap", False)
    expected_saving = future_info.get("expected_saving", 0.0)

    for mode in [
        CBB_MODE_HOME_I,
        CBB_MODE_HOME_II,
        CBB_MODE_HOME_III,
        CBB_MODE_HOME_UPS,
    ]:
        score = score_mode(
            strategy,
            mode=mode,
            battery=battery,
            solar=solar,
            load=load,
            price=price,
            export_price=export_price,
            cheap_threshold=cheap_threshold,
            expected_saving=expected_saving,
            is_relatively_cheap=is_relatively_cheap,
        )
        scores[mode] = score

    best_mode = max(scores, key=lambda m: scores[m])

    if best_mode == CBB_MODE_HOME_UPS:
        if price <= very_cheap:
            reason = "very_cheap_grid_charge"
        elif battery < strategy._planning_min:
            reason = "low_battery_charge"
        else:
            reason = "opportunistic_charge"
    elif best_mode == CBB_MODE_HOME_III:
        if solar > load:
            reason = "maximize_solar_storage"
        else:
            reason = "preserve_battery_high_solar"
    elif best_mode == CBB_MODE_HOME_II:
        reason = "preserve_battery_day"
    else:
        if price >= expensive_threshold:
            reason = "expensive_use_battery"
        else:
            reason = "normal_operation"

    return best_mode, reason, scores


def score_mode(
    strategy,
    *,
    mode: int,
    battery: float,
    solar: float,
    load: float,
    price: float,
    export_price: float,
    cheap_threshold: float,
    expected_saving: float = 0.0,
    is_relatively_cheap: bool = False,
) -> float:
    """Calculate score for a mode."""
    result = strategy.simulator.simulate(
        battery_start=battery,
        mode=mode,
        solar_kwh=solar,
        load_kwh=load,
    )

    cost = strategy.simulator.calculate_cost(result, price, export_price)

    score = -cost * strategy.config.weight_cost

    if result.battery_end >= strategy._planning_min:
        score += 0.5 * strategy.config.weight_battery_preservation
    if result.battery_end >= strategy._target:
        score += 0.3 * strategy.config.weight_battery_preservation

    if result.solar_used_direct > 0:
        score += result.solar_used_direct * strategy.config.weight_self_consumption

    if result.battery_end < strategy._planning_min:
        deficit = strategy._planning_min - result.battery_end
        score -= deficit * 2.0

    if mode == CBB_MODE_HOME_UPS:
        if strategy.config.charging_strategy == ChargingStrategy.DISABLED:
            score -= 100.0
        elif price > strategy.config.max_ups_price_czk:
            score -= 10.0
        elif price <= cheap_threshold:
            score += 1.0

        if expected_saving > 0 and is_relatively_cheap:
            score += expected_saving * 0.5
        if is_relatively_cheap and battery < strategy._target:
            score += 0.5

    return score


def handle_negative_price(
    strategy,
    *,
    battery: float,
    solar: float,
    load: float,
    price: float,
    export_price: float,
) -> Tuple[int, str]:
    """Handle negative price intervals."""
    _ = load
    _ = price
    _ = export_price
    strategy_mode = strategy.config.negative_price_strategy

    if strategy_mode == NegativePriceStrategy.CHARGE_GRID:
        return CBB_MODE_HOME_UPS, "negative_price_charge"
    if strategy_mode == NegativePriceStrategy.CURTAIL:
        return CBB_MODE_HOME_III, "negative_price_curtail"
    if strategy_mode == NegativePriceStrategy.CONSUME:
        return CBB_MODE_HOME_I, "negative_price_consume"

    if battery < strategy._max - 1.0:
        return CBB_MODE_HOME_UPS, "auto_negative_charge"
    if solar > 0.5:
        return CBB_MODE_HOME_III, "auto_negative_curtail"
    return CBB_MODE_HOME_I, "auto_negative_consume"


def apply_smoothing(
    strategy,
    *,
    decisions: List[Any],
    solar_forecast: List[float],
    consumption_forecast: List[float],
    prices: List[float],
    export_prices: List[float],
) -> List[Any]:
    """Apply smoothing to avoid rapid mode changes."""
    _ = solar_forecast
    _ = consumption_forecast
    _ = prices
    _ = export_prices
    if len(decisions) < 2:
        return decisions

    min_duration = strategy.config.min_mode_duration_intervals

    i = 0
    while i < len(decisions):
        mode = decisions[i].mode
        run_start = i
        while i < len(decisions) and decisions[i].mode == mode:
            i += 1
        run_end = i
        run_length = run_end - run_start

        if run_length < min_duration:
            protected = any(
                decisions[j].is_balancing or decisions[j].is_holding
                for j in range(run_start, run_end)
            )

            if not protected and run_start > 0:
                prev_mode = decisions[run_start - 1].mode
                for j in range(run_start, run_end):
                    decisions[j].mode = prev_mode
                    decisions[j].mode_name = CBB_MODE_NAMES.get(prev_mode, "UNKNOWN")
                    decisions[j].reason = "smoothing_merged"

    return decisions


def calculate_baseline_cost(
    strategy,
    *,
    initial_battery: float,
    solar_forecast: List[float],
    consumption_forecast: List[float],
    prices: List[float],
    export_prices: List[float],
) -> float:
    """Calculate cost with HOME I only (baseline)."""
    battery = initial_battery
    total_cost = 0.0

    for i in range(len(prices)):
        solar = solar_forecast[i] if i < len(solar_forecast) else 0.0
        load = consumption_forecast[i] if i < len(consumption_forecast) else 0.125

        result = strategy.simulator.simulate(
            battery_start=battery,
            mode=CBB_MODE_HOME_I,
            solar_kwh=solar,
            load_kwh=load,
        )

        cost = strategy.simulator.calculate_cost(result, prices[i], export_prices[i])
        total_cost += cost
        battery = result.battery_end

    return total_cost
