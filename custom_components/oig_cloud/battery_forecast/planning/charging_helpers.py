"""Charging plan helpers for battery forecast."""

from __future__ import annotations

from typing import Any, Dict, List

from ..types import MODE_LABEL_HOME_I, MODE_LABEL_HOME_UPS
from . import charging_plan as charging_plan_module


def economic_charging_plan(
    sensor: Any,
    *,
    timeline_data: List[Dict[str, Any]],
    min_capacity_kwh: float,
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
    iso_tz_offset: str,
    target_reason: str = "default",
) -> List[Dict[str, Any]]:
    """Build economic charging plan and store metrics."""
    config = sensor._config_entry.options or sensor._config_entry.data
    min_capacity_percent = config.get("min_capacity_percent", 20.0)
    min_capacity_floor = (min_capacity_percent / 100.0) * max_capacity
    efficiency = sensor._get_battery_efficiency()

    timeline, metrics = charging_plan_module.economic_charging_plan(
        timeline_data=timeline_data,
        min_capacity_kwh=min_capacity_kwh,
        min_capacity_floor=min_capacity_floor,
        effective_minimum_kwh=effective_minimum_kwh,
        target_capacity_kwh=target_capacity_kwh,
        max_charging_price=max_charging_price,
        min_savings_margin=min_savings_margin,
        charging_power_kw=charging_power_kw,
        max_capacity=max_capacity,
        enable_blackout_protection=enable_blackout_protection,
        blackout_protection_hours=blackout_protection_hours,
        blackout_target_soc_percent=blackout_target_soc_percent,
        enable_weather_risk=enable_weather_risk,
        weather_risk_level=weather_risk_level,
        weather_target_soc_percent=weather_target_soc_percent,
        target_reason=target_reason,
        battery_efficiency=efficiency,
        config=config,
        iso_tz_offset=iso_tz_offset,
        mode_label_home_ups=MODE_LABEL_HOME_UPS,
        mode_label_home_i=MODE_LABEL_HOME_I,
    )
    if metrics:
        sensor._charging_metrics = metrics

    return timeline


def smart_charging_plan(
    sensor: Any,
    *,
    timeline: List[Dict[str, Any]],
    min_capacity: float,
    target_capacity: float,
    max_price: float,
    price_threshold: float,
    charging_power_kw: float,
    max_capacity: float,
) -> List[Dict[str, Any]]:
    """Build smart charging plan and store metrics."""
    timeline_result, metrics = charging_plan_module.smart_charging_plan(
        timeline=timeline,
        min_capacity=min_capacity,
        target_capacity=target_capacity,
        max_price=max_price,
        price_threshold=price_threshold,
        charging_power_kw=charging_power_kw,
        max_capacity=max_capacity,
        efficiency=sensor._get_battery_efficiency(),
        mode_label_home_ups=MODE_LABEL_HOME_UPS,
        mode_label_home_i=MODE_LABEL_HOME_I,
    )
    if metrics:
        sensor._charging_metrics = metrics

    return timeline_result
