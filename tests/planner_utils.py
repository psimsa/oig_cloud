"""Utility functions for offline planner simulation/grid search."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

HOME_I = 0
HOME_II = 1
HOME_III = 2
HOME_UPS = 3
MODES = (HOME_I, HOME_II, HOME_III, HOME_UPS)


@dataclass
class Scenario:
    metadata: Dict[str, float]
    spot_prices: List[Dict[str, float]]
    load_kwh: List[float]
    solar_kwh: List[float]


def load_scenario(path: Path) -> Scenario:
    data = json.loads(path.read_text())
    return Scenario(
        metadata=data["metadata"],
        spot_prices=data["spot_prices"],
        load_kwh=data["load_kwh"],
        solar_kwh=data["solar_kwh"],
    )


def simulate_interval(
    mode: int,
    soc_kwh: float,
    solar_kwh: float,
    load_kwh: float,
    price_czk: float,
    export_price_czk: float,
    metadata: Dict[str, float],
) -> Dict[str, float]:
    """Simplified 15min simulation covering four CBB modes."""

    eff = metadata["efficiency"]
    capacity = metadata["max_capacity"]
    charge_limit = metadata["home_charge_rate_kw"] / 4.0

    soc = max(0.0, min(capacity, soc_kwh))
    grid_import = 0.0

    if mode == HOME_I:
        solar_used = min(solar_kwh, load_kwh)
        remaining_load = load_kwh - solar_used

        if remaining_load > 0.0:
            discharge = min(soc, remaining_load / eff)
            soc -= discharge
            remaining_load -= discharge * eff

        if remaining_load > 0.0:
            grid_import += remaining_load

        surplus = max(0.0, solar_kwh - solar_used)
        charge = min(capacity - soc, surplus * eff)
        soc += charge

    elif mode == HOME_II:
        solar_used = min(solar_kwh, load_kwh)
        remaining_load = load_kwh - solar_used
        if remaining_load > 0.0:
            grid_import += remaining_load

        surplus = max(0.0, solar_kwh - solar_used)
        charge = min(capacity - soc, surplus * eff)
        soc += charge

    elif mode == HOME_III:
        grid_import += load_kwh
        charge = min(capacity - soc, solar_kwh * eff)
        soc += charge

    elif mode == HOME_UPS:
        grid_import += load_kwh
        charge_raw = min(charge_limit, max(0.0, capacity - soc))
        soc += charge_raw * eff
        grid_import += charge_raw

    else:
        raise ValueError(f"Unsupported mode {mode}")

    soc = max(0.0, min(capacity, soc))
    net_cost = grid_import * price_czk
    return {"new_soc": soc, "net_cost": net_cost}


def optimize_modes(
    scenario: Scenario,
    *,
    soc_step_kwh: float,
    min_penalty: float,
    target_penalty: float,
) -> Tuple[List[int], List[float], float]:
    """Dynamic programming optimizer mirroring autonomy planner."""

    spot = scenario.spot_prices
    solar = scenario.solar_kwh
    load = scenario.load_kwh
    meta = scenario.metadata
    n = len(spot)

    capacity = meta["max_capacity"]
    min_capacity = meta["min_capacity"]
    target_capacity = meta["target_capacity"]

    levels = [i * soc_step_kwh for i in range(int(capacity / soc_step_kwh) + 1)]

    def _soc_to_idx(value: float) -> int:
        idx = int(round(value / soc_step_kwh))
        return max(0, min(len(levels) - 1, idx))

    INF = 10**12
    dp = [[INF] * len(levels) for _ in range(n + 1)]
    choice: List[List[int]] = [[-1] * len(levels) for _ in range(n)]

    for s_idx, soc in enumerate(levels):
        deficit = max(0.0, target_capacity - soc)
        dp[n][s_idx] = deficit * target_penalty

    for i in range(n - 1, -1, -1):
        price = spot[i]["price"]
        export_price = spot[i].get("export_price", price * 0.4)
        solar_kwh = solar[i]
        load_kwh = load[i]

        for s_idx, soc in enumerate(levels):
            best_cost = INF

            for mode in MODES:
                interval = simulate_interval(
                    mode,
                    soc,
                    solar_kwh,
                    load_kwh,
                    price,
                    export_price,
                    meta,
                )
                new_soc = interval["new_soc"]

                penalty = 0.0
                if new_soc < min_capacity:
                    penalty += (min_capacity - new_soc) * min_penalty
                future_idx = _soc_to_idx(new_soc)
                future_cost = dp[i + 1][future_idx]

                total = interval["net_cost"] + penalty + future_cost
                if total < best_cost:
                    best_cost = total
                    choice[i][s_idx] = mode

            dp[i][s_idx] = best_cost

    start_soc = meta["initial_soc"]
    current_idx = _soc_to_idx(start_soc)
    modes: List[int] = []
    trace: List[float] = []
    total_cost = 0.0

    for i in range(n):
        mode = choice[i][current_idx]
        if mode == -1:
            mode = HOME_I

        trace.append(levels[current_idx])
        interval = simulate_interval(
            mode,
            levels[current_idx],
            solar[i],
            load[i],
            spot[i]["price"],
            spot[i].get("export_price", spot[i]["price"] * 0.4),
            meta,
        )
        modes.append(mode)
        total_cost += interval["net_cost"]
        current_idx = _soc_to_idx(interval["new_soc"])

    return modes, trace, total_cost


def trace_metrics(trace: Sequence[float], meta: Dict[str, float]) -> Dict[str, float]:
    min_soc = min(trace)
    max_soc = max(trace)
    min_cap = meta["min_capacity"]
    max_cap = meta["max_capacity"]
    time_below = sum(1 for soc in trace if soc < min_cap + 1.0) / len(trace)
    time_near_max = sum(1 for soc in trace if soc > max_cap - 1.0) / len(trace)
    return {
        "min_soc": min_soc,
        "max_soc": max_soc,
        "time_below_buffer": time_below,
        "time_near_max": time_near_max,
    }
