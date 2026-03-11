"""Mode recommendation helpers extracted from battery forecast sensor."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


def create_mode_recommendations(
    optimal_timeline: List[Dict[str, Any]],
    *,
    hours_ahead: int = 48,
    now: Optional[datetime] = None,
    mode_home_i: int,
    mode_home_ii: int,
    mode_home_iii: int,
    mode_home_ups: int,
) -> List[Dict[str, Any]]:
    """Create user-friendly recommendations from the optimized timeline."""
    if not optimal_timeline:
        return []

    try:
        current_time = now or datetime.now()

        # Mode recommendations: only future intervals (today from now, tomorrow full day).
        tomorrow_end = datetime.combine(
            current_time.date() + timedelta(days=1), datetime.max.time()
        )

        future_intervals = [
            interval
            for interval in optimal_timeline
            if interval.get("time")
            and current_time <= datetime.fromisoformat(interval["time"]) <= tomorrow_end
        ]

        if not future_intervals:
            return []

        recommendations: List[Dict[str, Any]] = []
        current_block: Optional[Dict[str, Any]] = None
        block_intervals: List[Dict[str, Any]] = []

        for interval in future_intervals:
            mode = interval.get("mode")
            mode_name = interval.get("mode_name", f"MODE_{mode}")
            time_str = interval.get("time", "")

            if current_block is None:
                current_block = {
                    "mode": mode,
                    "mode_name": mode_name,
                    "from_time": time_str,
                    "to_time": None,
                    "intervals_count": 1,
                }
                block_intervals = [interval]
            elif current_block["mode"] == mode:
                current_block["intervals_count"] += 1
                block_intervals.append(interval)
            else:
                if block_intervals:
                    last_interval_time = block_intervals[-1].get("time", "")
                    try:
                        last_dt = datetime.fromisoformat(last_interval_time)
                        end_dt = last_dt + timedelta(minutes=15)
                        current_block["to_time"] = end_dt.isoformat()
                    except Exception:
                        current_block["to_time"] = last_interval_time

                add_block_details(
                    current_block,
                    block_intervals,
                    mode_home_i=mode_home_i,
                    mode_home_ii=mode_home_ii,
                    mode_home_iii=mode_home_iii,
                    mode_home_ups=mode_home_ups,
                )
                current_block["_intervals"] = block_intervals
                recommendations.append(current_block)

                current_block = {
                    "mode": mode,
                    "mode_name": mode_name,
                    "from_time": time_str,
                    "to_time": None,
                    "intervals_count": 1,
                }
                block_intervals = [interval]

        if current_block and block_intervals:
            last_interval_time = block_intervals[-1].get("time", "")
            try:
                last_dt = datetime.fromisoformat(last_interval_time)
                end_dt = last_dt + timedelta(minutes=15)
                current_block["to_time"] = end_dt.isoformat()
            except Exception:
                current_block["to_time"] = last_interval_time

            add_block_details(
                current_block,
                block_intervals,
                mode_home_i=mode_home_i,
                mode_home_ii=mode_home_ii,
                mode_home_iii=mode_home_iii,
                mode_home_ups=mode_home_ups,
            )
            current_block["_intervals"] = block_intervals
            recommendations.append(current_block)

        split_recommendations: List[Dict[str, Any]] = []
        for block in recommendations:
            from_dt = datetime.fromisoformat(block["from_time"])
            to_dt = datetime.fromisoformat(block["to_time"])

            if from_dt.date() == to_dt.date():
                block.pop("_intervals", None)
                split_recommendations.append(block)
            else:
                midnight = datetime.combine(
                    from_dt.date() + timedelta(days=1), datetime.min.time()
                )

                intervals = block.get("_intervals", [])
                intervals1 = [
                    i
                    for i in intervals
                    if datetime.fromisoformat(i.get("time", "")) < midnight
                ]
                intervals2 = [
                    i
                    for i in intervals
                    if datetime.fromisoformat(i.get("time", "")) >= midnight
                ]

                block1 = {
                    "mode": block["mode"],
                    "mode_name": block["mode_name"],
                    "from_time": block["from_time"],
                    "to_time": midnight.isoformat(),
                    "intervals_count": len(intervals1),
                }
                duration1 = (midnight - from_dt).total_seconds() / 3600
                block1["duration_hours"] = round(duration1, 2)
                if intervals1:
                    add_block_details(
                        block1,
                        intervals1,
                        mode_home_i=mode_home_i,
                        mode_home_ii=mode_home_ii,
                        mode_home_iii=mode_home_iii,
                        mode_home_ups=mode_home_ups,
                    )
                split_recommendations.append(block1)

                block2 = {
                    "mode": block["mode"],
                    "mode_name": block["mode_name"],
                    "from_time": midnight.isoformat(),
                    "to_time": block["to_time"],
                    "intervals_count": len(intervals2),
                }
                duration2 = (to_dt - midnight).total_seconds() / 3600
                block2["duration_hours"] = round(duration2, 2)
                if intervals2:
                    add_block_details(
                        block2,
                        intervals2,
                        mode_home_i=mode_home_i,
                        mode_home_ii=mode_home_ii,
                        mode_home_iii=mode_home_iii,
                        mode_home_ups=mode_home_ups,
                    )
                split_recommendations.append(block2)

        return split_recommendations
    except Exception as exc:
        _LOGGER.error("Failed to create mode recommendations: %s", exc)
        return []


def add_block_details(
    block: Dict[str, Any],
    intervals: List[Dict[str, Any]],
    *,
    mode_home_i: int,
    mode_home_ii: int,
    mode_home_iii: int,
    mode_home_ups: int,
) -> None:
    """Add metrics and rationale to a recommendation block."""
    try:
        from_dt = datetime.fromisoformat(block["from_time"])
        to_dt = datetime.fromisoformat(block["to_time"])
        duration = (to_dt - from_dt).total_seconds() / 3600 + 0.25
        block["duration_hours"] = round(duration, 2)
    except Exception:
        block["duration_hours"] = block["intervals_count"] * 0.25

    if not intervals:
        return

    total_cost = sum(i.get("net_cost", 0) for i in intervals)
    block["total_cost"] = round(total_cost, 2)
    block["savings_vs_home_i"] = 0.0

    solar_vals = [i.get("solar_kwh", 0) * 4 for i in intervals]
    load_vals = [i.get("load_kwh", 0) * 4 for i in intervals]
    spot_prices = [i.get("spot_price", 0) for i in intervals]

    block["avg_solar_kw"] = (
        round(sum(solar_vals) / len(solar_vals), 2)
        if solar_vals and any(v > 0 for v in solar_vals)
        else 0.0
    )
    block["avg_load_kw"] = (
        round(sum(load_vals) / len(load_vals), 2) if load_vals else 0.0
    )
    block["avg_spot_price"] = (
        round(sum(spot_prices) / len(spot_prices), 2) if spot_prices else 0.0
    )

    mode = block["mode"]
    solar_kw = block["avg_solar_kw"]
    load_kw = block["avg_load_kw"]
    spot_price = block["avg_spot_price"]

    if mode == mode_home_i:
        if solar_kw > load_kw + 0.1:
            surplus_kw = solar_kw - load_kw
            block["rationale"] = (
                "Nabíjíme baterii z FVE přebytku "
                f"({surplus_kw:.1f} kW) - ukládáme levnou energii na později"
            )
        elif solar_kw > 0.2:
            deficit_kw = load_kw - solar_kw
            block["rationale"] = (
                f"FVE pokrývá část spotřeby ({solar_kw:.1f} kW), "
                f"baterie doplňuje {deficit_kw:.1f} kW"
            )
        else:
            block["rationale"] = (
                "Vybíjíme baterii pro pokrytí spotřeby - šetříme "
                f"{spot_price:.1f} Kč/kWh ze sítě"
            )
    elif mode == mode_home_ii:
        if solar_kw > load_kw + 0.1:
            surplus_kw = solar_kw - load_kw
            block["rationale"] = (
                "Nabíjíme baterii z FVE přebytku "
                f"({surplus_kw:.1f} kW) - připravujeme na večerní špičku"
            )
        else:
            if spot_price > 4.0:
                block["rationale"] = (
                    f"Grid pokrývá spotřebu ({spot_price:.1f} Kč/kWh) - "
                    "ale ještě ne vrcholová cena"
                )
            else:
                block["rationale"] = (
                    f"Levný proud ze sítě ({spot_price:.1f} Kč/kWh) - "
                    "šetříme baterii na dražší období"
                )
    elif mode == mode_home_iii:
        if solar_kw > 0.2:
            block["rationale"] = (
                "Maximální nabíjení baterie - veškeré FVE "
                f"({solar_kw:.1f} kW) jde do baterie, spotřeba ze sítě"
            )
        else:
            block["rationale"] = (
                "Vybíjíme baterii pro pokrytí spotřeby - šetříme "
                f"{spot_price:.1f} Kč/kWh ze sítě"
            )
    elif mode == mode_home_ups:
        if spot_price < 3.0:
            block["rationale"] = (
                "Nabíjíme ze sítě - velmi levný proud "
                f"({spot_price:.1f} Kč/kWh), připravujeme plnou baterii"
            )
        else:
            block["rationale"] = (
                f"Nabíjíme ze sítě ({spot_price:.1f} Kč/kWh) - "
                "připravujeme na dražší špičku"
            )
    else:
        block["rationale"] = "Optimalizovaný režim podle aktuálních podmínek"
