"""Detail tab block helpers for battery forecast."""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.util import dt as dt_util

from ..timeline.planner import format_planner_reason
from ..utils_common import format_time_label, safe_nested_get

_LOGGER = logging.getLogger(__name__)


def determine_block_status(
    first_interval: Dict[str, Any],
    last_interval: Dict[str, Any],
    tab_name: str,
    now: datetime,
) -> str:
    """Determine block status: completed | current | planned."""
    if tab_name == "yesterday":
        return "completed"
    if tab_name == "tomorrow":
        return "planned"

    start_time_str = first_interval.get("time", "")
    end_time_str = last_interval.get("time", "")

    if not start_time_str or not end_time_str:
        return "planned"

    try:
        start_time = datetime.fromisoformat(start_time_str)
        end_time = datetime.fromisoformat(end_time_str)

        if start_time.tzinfo is None:
            start_time = dt_util.as_local(start_time)
        if end_time.tzinfo is None:
            end_time = dt_util.as_local(end_time)

        end_time = end_time + timedelta(minutes=15)

        current_minute = (now.minute // 15) * 15
        current_interval_time = now.replace(
            minute=current_minute, second=0, microsecond=0
        )

        start_time_naive = (
            start_time.replace(tzinfo=None) if start_time.tzinfo else start_time
        )
        end_time_naive = end_time.replace(tzinfo=None) if end_time.tzinfo else end_time
        current_interval_naive = current_interval_time.replace(tzinfo=None)

        if end_time_naive <= current_interval_naive:
            return "completed"
        if start_time_naive <= current_interval_naive < end_time_naive:
            return "current"
        return "planned"
    except Exception as err:
        _LOGGER.warning("[determine_block_status] Error parsing times: %s", err)
        return "planned"


def get_mode_from_intervals(
    intervals: List[Dict[str, Any]],
    key: str,
    mode_names: Dict[int, str],
) -> Optional[str]:
    """Get mode name from intervals (actual or planned)."""
    for interval in intervals:
        data = interval.get(key)
        if data and isinstance(data, dict):
            mode = data.get("mode")
            if isinstance(mode, int):
                return mode_names.get(mode, f"Mode {mode}")
            if mode:
                return str(mode)
    return None


def summarize_block_reason(
    sensor: Any, group_intervals: List[Dict[str, Any]], block: Dict[str, Any]
) -> Optional[str]:
    planned_entries = [
        iv.get("planned")
        for iv in group_intervals
        if isinstance(iv.get("planned"), dict)
    ]
    actual_entries = [
        iv.get("actual") for iv in group_intervals if isinstance(iv.get("actual"), dict)
    ]
    entries_source = planned_entries if planned_entries else actual_entries
    if not entries_source:
        return None

    metrics_list = (
        [p.get("decision_metrics") or {} for p in planned_entries]
        if planned_entries
        else []
    )

    guard_metrics = (
        next((m for m in metrics_list if m.get("guard_active")), None)
        if metrics_list
        else None
    )
    if guard_metrics:
        guard_type = guard_metrics.get("guard_type")
        if guard_type == "guard_exception_soc":
            planned_mode = guard_metrics.get("guard_planned_mode") or block.get(
                "mode_planned"
            )
            return (
                "Výjimka guardu: SoC pod plánovacím minimem – "
                f"povolujeme {planned_mode}."
            )

        forced_mode = guard_metrics.get("guard_forced_mode") or block.get(
            "mode_planned"
        )
        guard_until = guard_metrics.get("guard_until")
        guard_until_label = format_time_label(guard_until)
        if guard_until_label != "--:--":
            return f"Stabilizace: držíme režim {forced_mode} do {guard_until_label}."
        return f"Stabilizace: držíme režim {forced_mode} 60 min po poslední změně."

    reason_codes = [
        m.get("planner_reason_code")
        for m in metrics_list
        if m.get("planner_reason_code")
    ]
    dominant_code = Counter(reason_codes).most_common(1)[0][0] if reason_codes else None

    def _mean(values: List[Optional[float]]) -> Optional[float]:
        vals = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
        if not vals:
            return None
        return sum(vals) / len(vals)

    def _avg_from_metrics(key: str) -> Optional[float]:
        if not metrics_list:
            return None
        return _mean([m.get(key) for m in metrics_list if m.get(key) is not None])

    def _avg_from_entries(key: str) -> Optional[float]:
        return _mean(
            [
                entry.get(key)
                for entry in entries_source
                if isinstance(entry.get(key), (int, float))
            ]
        )

    prices: List[Optional[float]] = []
    for entry in entries_source:
        price = entry.get("spot_price")
        if price is None:
            price = entry.get("spot_price_czk")
        if price is None:
            price = (entry.get("decision_metrics") or {}).get("spot_price_czk")
        prices.append(price)
    avg_price = _mean(prices)

    avg_future_ups = _avg_from_metrics("future_ups_avg_price_czk")
    avg_grid_charge = _avg_from_metrics("grid_charge_kwh")
    avg_home1_saving = _avg_from_metrics("home1_saving_czk")
    avg_recharge_cost = _avg_from_metrics("recharge_cost_czk")
    avg_solar = _avg_from_entries("solar_kwh")
    avg_load = _avg_from_entries("consumption_kwh")

    start_kwh = block.get("battery_kwh_start")
    end_kwh = block.get("battery_kwh_end")
    delta_kwh = (
        (end_kwh - start_kwh)
        if isinstance(start_kwh, (int, float)) and isinstance(end_kwh, (int, float))
        else None
    )

    opts = (
        sensor._config_entry.options if getattr(sensor, "_config_entry", None) else {}
    )
    max_ups_price = float(opts.get("max_ups_price_czk", 10.0))
    efficiency = float(sensor._get_battery_efficiency() or 0.0)
    if 0 < efficiency <= 1.0:
        band_pct = max(0.08, (1.0 / efficiency) - 1.0)
    else:
        band_pct = 0.08

    mode_label = block.get("mode_planned") or block.get("mode_historical") or ""
    mode_upper = str(mode_label).upper()

    if dominant_code:
        if dominant_code == "price_band_hold":
            if avg_price is not None:
                if avg_future_ups is not None and avg_price <= avg_future_ups - 0.01:
                    return (
                        "UPS držíme v cenovém pásmu ±"
                        f"{band_pct * 100:.0f}% "
                        f"(průměr {avg_price:.2f} Kč/kWh, "
                        f"levnější než další okna {avg_future_ups:.2f} Kč/kWh)."
                    )
                return (
                    "UPS držíme v cenovém pásmu ±"
                    f"{band_pct * 100:.0f}% "
                    f"(průměr {avg_price:.2f} Kč/kWh)."
                )
            return "UPS držíme v cenovém pásmu dle účinnosti."

        reason_text = format_planner_reason(dominant_code, spot_price=avg_price)
        if reason_text:
            if avg_price is not None and "Kč/kWh" not in reason_text:
                reason_text = f"{reason_text} (průměr {avg_price:.2f} Kč/kWh)."
            return reason_text

    if "UPS" in mode_upper:
        charge_kwh = None
        if avg_grid_charge is not None and avg_grid_charge > 0.01:
            charge_kwh = avg_grid_charge
        elif delta_kwh is not None and delta_kwh > 0.05:
            charge_kwh = delta_kwh

        if avg_price is not None:
            if avg_price <= max_ups_price + 0.0001:
                detail = (
                    "Nabíjíme ze sítě"
                    + (f" (+{charge_kwh:.2f} kWh)" if charge_kwh else "")
                    + f": {avg_price:.2f} Kč/kWh ≤ limit {max_ups_price:.2f}."
                )
                if avg_future_ups is not None and avg_price <= avg_future_ups - 0.01:
                    detail += (
                        " Je levnější než další UPS okna "
                        f"({avg_future_ups:.2f} Kč/kWh)."
                    )
                return detail
            detail = (
                f"UPS režim i přes vyšší cenu {avg_price:.2f} Kč/kWh "
                f"(limit {max_ups_price:.2f})"
            )
            if charge_kwh:
                detail += f", nabíjení +{charge_kwh:.2f} kWh."
            else:
                detail += "."
            return detail
        return "UPS režim (plánované nabíjení)."

    if "HOME II" in mode_upper or "HOME 2" in mode_upper:
        if avg_home1_saving is not None and avg_recharge_cost is not None:
            return (
                "Držíme baterii (HOME II): HOME I by ušetřil ~"
                f"{avg_home1_saving:.2f} Kč, dobíjení v UPS ~{avg_recharge_cost:.2f} Kč."
            )
        return "Držíme baterii (HOME II), bez vybíjení do zátěže."

    if "HOME III" in mode_upper or "HOME 3" in mode_upper:
        if avg_solar is not None and avg_load is not None and avg_solar > avg_load:
            return (
                "HOME III: FVE pokrývá spotřebu "
                f"({avg_solar:.2f} kWh > {avg_load:.2f} kWh), "
                "maximalizujeme nabíjení."
            )
        return "Maximalizujeme nabíjení z FVE, spotřeba jde ze sítě."

    if "HOME I" in mode_upper or "HOME 1" in mode_upper:
        if delta_kwh is not None and delta_kwh < -0.05:
            if avg_price is not None and avg_future_ups is not None:
                delta_price = avg_price - avg_future_ups
                if delta_price > 0.01:
                    return (
                        "Vybíjíme baterii (-"
                        f"{abs(delta_kwh):.2f} kWh), protože UPS by byl "
                        f"o {delta_price:.2f} Kč/kWh dražší "
                        f"(nyní {avg_price:.2f}, UPS okna {avg_future_ups:.2f})."
                    )
            if avg_price is not None and avg_price > max_ups_price + 0.0001:
                return (
                    "Vybíjíme baterii (-"
                    f"{abs(delta_kwh):.2f} kWh), cena {avg_price:.2f} Kč/kWh "
                    f"je nad limitem UPS {max_ups_price:.2f} Kč/kWh."
                )
            return (
                "Vybíjíme baterii (-" f"{abs(delta_kwh):.2f} kWh) místo odběru ze sítě."
            )
        if delta_kwh is not None and delta_kwh > 0.05:
            return (
                "Solár pokrývá spotřebu, přebytky ukládáme do baterie "
                f"(+{delta_kwh:.2f} kWh)."
            )
        if avg_solar is not None and avg_load is not None and avg_solar >= avg_load:
            return (
                "Solár pokrývá spotřebu "
                f"({avg_solar:.2f} kWh ≥ {avg_load:.2f} kWh), "
                "baterie se výrazně nemění."
            )
        return "Solár pokrývá spotřebu, baterie se výrazně nemění."

    reasons = [
        p.get("decision_reason") for p in entries_source if p.get("decision_reason")
    ]
    if reasons:
        return Counter(reasons).most_common(1)[0][0]

    return None


def build_mode_blocks_for_tab(  # noqa: C901
    sensor: Any,
    intervals: List[Dict[str, Any]],
    tab_name: str,
    *,
    mode_names: Dict[int, str],
) -> List[Dict[str, Any]]:
    """Build mode blocks for a detail tab."""
    if not intervals:
        return []

    now = dt_util.now()

    if tab_name == "yesterday":
        data_type = "completed"
    elif tab_name == "today":
        data_type = "both"
    else:
        data_type = "planned"

    mode_groups = sensor._group_intervals_by_mode(
        intervals, data_type
    )  # pylint: disable=protected-access

    _LOGGER.info(
        "[build_mode_blocks_for_tab] tab=%s, data_type=%s, intervals_count=%s, mode_groups_count=%s",
        tab_name,
        data_type,
        len(intervals),
        len(mode_groups),
    )

    total_capacity = (
        sensor._get_total_battery_capacity() or 0.0
    )  # pylint: disable=protected-access

    def _extract_soc_payload(
        interval_entry: Dict[str, Any], branch: str
    ) -> Tuple[float, float]:
        source = (
            interval_entry.get(branch) if isinstance(interval_entry, dict) else None
        )
        if not isinstance(source, dict):
            return (0.0, 0.0)

        raw_soc = source.get("battery_soc")
        raw_kwh = source.get("battery_kwh")

        if raw_kwh is None:
            raw_kwh = source.get("battery_capacity_kwh")

        soc_percent = None
        kwh_value = raw_kwh

        if raw_soc is not None:
            if total_capacity > 0 and raw_soc <= total_capacity + 0.01:
                kwh_value = raw_soc if kwh_value is None else kwh_value
            else:
                soc_percent = raw_soc

        if soc_percent is None and kwh_value is not None and total_capacity > 0:
            soc_percent = (kwh_value / total_capacity) * 100.0

        if soc_percent is not None and kwh_value is None and total_capacity > 0:
            kwh_value = (soc_percent / 100.0) * total_capacity

        return (round(soc_percent or 0.0, 1), round(kwh_value or 0.0, 2))

    def _interval_net(interval_entry: Dict[str, Any], branch: str) -> Optional[float]:
        if not isinstance(interval_entry.get(branch), dict):
            return None
        import_val = safe_nested_get(
            interval_entry, branch, "grid_import", default=None
        )
        if import_val is None:
            import_val = safe_nested_get(
                interval_entry, branch, "grid_import_kwh", default=None
            )
        export_val = safe_nested_get(
            interval_entry, branch, "grid_export", default=None
        )
        if export_val is None:
            export_val = safe_nested_get(
                interval_entry, branch, "grid_export_kwh", default=None
            )
        if import_val is None and export_val is None:
            return None
        return (import_val or 0.0) - (export_val or 0.0)

    mode_blocks = []
    for group in mode_groups:
        group_intervals = group.get("intervals", [])
        if not group_intervals:
            continue

        block = {
            "mode_historical": group.get("mode", "Unknown"),
            "mode_planned": group.get("mode", "Unknown"),
            "mode_match": True,
            "status": determine_block_status(
                group_intervals[0], group_intervals[-1], tab_name, now
            ),
            "start_time": group.get("start_time", ""),
            "end_time": group.get("end_time", ""),
            "interval_count": group.get("interval_count", 0),
        }

        duration_hours = block["interval_count"] * 0.25
        block["duration_hours"] = round(duration_hours, 2)

        if data_type in ["completed", "both"]:
            block["cost_historical"] = group.get("actual_cost", 0.0)
            block["cost_planned"] = group.get("planned_cost", 0.0)
            block["cost_delta"] = group.get("delta", 0.0)

            historical_mode = get_mode_from_intervals(
                group_intervals, "actual", mode_names
            )
            planned_mode = get_mode_from_intervals(
                group_intervals, "planned", mode_names
            )
            block["mode_historical"] = historical_mode or "Unknown"
            block["mode_planned"] = planned_mode or "Unknown"
            block["mode_match"] = historical_mode == planned_mode
        else:
            block["cost_planned"] = group.get("planned_cost", 0.0)
            block["cost_historical"] = None
            block["cost_delta"] = None

        first_interval = group_intervals[0]
        last_interval = group_intervals[-1]

        if data_type in ["completed", "both"]:
            start_soc_pct, start_soc_kwh = _extract_soc_payload(
                first_interval, "actual"
            )
            end_soc_pct, end_soc_kwh = _extract_soc_payload(last_interval, "actual")
        else:
            start_soc_pct, start_soc_kwh = _extract_soc_payload(
                first_interval, "planned"
            )
            end_soc_pct, end_soc_kwh = _extract_soc_payload(last_interval, "planned")

        block["battery_soc_start"] = start_soc_pct
        block["battery_soc_end"] = end_soc_pct
        block["battery_kwh_start"] = start_soc_kwh
        block["battery_kwh_end"] = end_soc_kwh

        solar_plan_total = 0.0
        solar_actual_total = 0.0
        solar_actual_samples = 0

        consumption_plan_total = 0.0
        consumption_actual_total = 0.0
        consumption_actual_samples = 0

        grid_plan_net_total = 0.0
        grid_actual_net_total = 0.0
        grid_actual_samples = 0

        grid_plan_export_total = 0.0
        grid_actual_export_total = 0.0
        grid_export_actual_samples = 0

        for iv in group_intervals:
            solar_plan_total += safe_nested_get(iv, "planned", "solar_kwh", default=0)
            consumption_plan_total += safe_nested_get(
                iv, "planned", "consumption_kwh", default=0
            )
            grid_plan_net_total += _interval_net(iv, "planned") or 0.0
            grid_plan_export_total += safe_nested_get(
                iv, "planned", "grid_export", default=0
            ) or safe_nested_get(iv, "planned", "grid_export_kwh", default=0)

            actual_solar = safe_nested_get(iv, "actual", "solar_kwh", default=None)
            if actual_solar is not None:
                solar_actual_total += actual_solar
                solar_actual_samples += 1

            actual_consumption = safe_nested_get(
                iv, "actual", "consumption_kwh", default=None
            )
            if actual_consumption is not None:
                consumption_actual_total += actual_consumption
                consumption_actual_samples += 1

            actual_net = _interval_net(iv, "actual")
            if actual_net is not None:
                grid_actual_net_total += actual_net
                grid_actual_samples += 1

            actual_export = safe_nested_get(iv, "actual", "grid_export", default=None)
            if actual_export is None:
                actual_export = safe_nested_get(
                    iv, "actual", "grid_export_kwh", default=None
                )
            if actual_export is not None:
                grid_actual_export_total += actual_export
                grid_export_actual_samples += 1

        def _round_or_none(value: float, samples: int) -> Optional[float]:
            return round(value, 2) if samples > 0 else None

        block["solar_planned_kwh"] = round(solar_plan_total, 2)
        block["solar_actual_kwh"] = _round_or_none(
            solar_actual_total, solar_actual_samples
        )

        block["consumption_planned_kwh"] = round(consumption_plan_total, 2)
        block["consumption_actual_kwh"] = _round_or_none(
            consumption_actual_total, consumption_actual_samples
        )

        block["grid_import_planned_kwh"] = round(grid_plan_net_total, 2)
        block["grid_import_actual_kwh"] = _round_or_none(
            grid_actual_net_total, grid_actual_samples
        )

        block["grid_export_planned_kwh"] = round(grid_plan_export_total, 2)
        block["grid_export_actual_kwh"] = _round_or_none(
            grid_actual_export_total, grid_export_actual_samples
        )

        block["solar_total_kwh"] = (
            block["solar_actual_kwh"]
            if block["solar_actual_kwh"] is not None
            else block["solar_planned_kwh"]
        )
        block["consumption_total_kwh"] = (
            block["consumption_actual_kwh"]
            if block["consumption_actual_kwh"] is not None
            else block["consumption_planned_kwh"]
        )
        block["grid_import_total_kwh"] = (
            block["grid_import_actual_kwh"]
            if block["grid_import_actual_kwh"] is not None
            else block["grid_import_planned_kwh"]
        )
        block["grid_export_total_kwh"] = (
            block["grid_export_actual_kwh"]
            if block["grid_export_actual_kwh"] is not None
            else block["grid_export_planned_kwh"]
        )

        def _calc_delta(
            actual_val: Optional[float], planned_val: float
        ) -> Optional[float]:
            if actual_val is None:
                return None
            return round(actual_val - planned_val, 2)

        block["solar_delta_kwh"] = _calc_delta(
            block["solar_actual_kwh"], block["solar_planned_kwh"]
        )
        block["consumption_delta_kwh"] = _calc_delta(
            block["consumption_actual_kwh"], block["consumption_planned_kwh"]
        )
        block["grid_import_delta_kwh"] = _calc_delta(
            block["grid_import_actual_kwh"], block["grid_import_planned_kwh"]
        )
        block["grid_export_delta_kwh"] = _calc_delta(
            block["grid_export_actual_kwh"], block["grid_export_planned_kwh"]
        )

        block_reason = summarize_block_reason(sensor, group_intervals, block)
        if block_reason:
            block["interval_reasons"] = [
                {
                    "time": block.get("start_time", ""),
                    "reason": block_reason,
                }
            ]

        if data_type in ["completed", "both"] and block["mode_match"]:
            block["adherence_pct"] = 100
        elif data_type in ["completed", "both"]:
            block["adherence_pct"] = 0
        else:
            block["adherence_pct"] = None

        mode_blocks.append(block)

    return mode_blocks
