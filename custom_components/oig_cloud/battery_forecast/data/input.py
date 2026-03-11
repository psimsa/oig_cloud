"""Input helpers for battery forecast (solar/load lookup)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)


def _hour_key(timestamp: datetime) -> str:
    hour_ts = timestamp.replace(minute=0, second=0, microsecond=0)
    if hour_ts.tzinfo is not None:
        return hour_ts.replace(tzinfo=None).isoformat()
    return hour_ts.isoformat()


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _log_solar_lookup(
    *,
    timestamp: datetime,
    hour_key: str,
    data: Dict[str, Any],
    hourly_kw: Any,
    log_rate_limited: Optional[Any],
) -> None:
    if timestamp.hour not in (7, 8, 9, 10) or not log_rate_limited:
        return
    try:
        keys_count = len(data)
    except Exception:
        keys_count = -1
    log_rate_limited(
        "solar_lookup_debug",
        "debug",
        "🔍 SOLAR LOOKUP: ts=%s hour_key=%s keys=%s value=%s",
        timestamp.isoformat(),
        hour_key,
        keys_count,
        hourly_kw,
        cooldown_s=3600.0,
    )


def _log_solar_value(
    *,
    timestamp: datetime,
    hour_key: str,
    hourly_kw: float,
    log_rate_limited: Optional[Any],
) -> None:
    if timestamp.hour not in (14, 15, 16) or not log_rate_limited:
        return
    log_rate_limited(
        "solar_values_debug",
        "debug",
        "Solar sample for %s: key=%s kW=%.3f 15min_kWh=%.3f",
        timestamp.strftime("%H:%M"),
        hour_key,
        hourly_kw,
        hourly_kw / 4.0,
        cooldown_s=3600.0,
    )


def _log_empty_load_avg(state: Optional[Any]) -> None:
    if state is None or getattr(state, "_empty_load_sensors_logged", False):
        return
    _LOGGER.debug(
        "load_avg_sensors dictionary is empty - using fallback 500W "
        "(statistics sensors may not be available yet)"
    )
    setattr(state, "_empty_load_sensors_logged", True)


def _is_in_time_range(current_hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour <= end_hour:
        return start_hour <= current_hour < end_hour
    return current_hour >= start_hour or current_hour < end_hour


def _valid_time_range(time_range: Any) -> Optional[tuple[int, int]]:
    if not time_range or not isinstance(time_range, tuple) or len(time_range) != 2:
        return None
    return time_range


def _watts_to_kwh_per_15min(
    watts: float, *, entity_id: str, timestamp: datetime
) -> float:
    kwh_per_hour = watts / 1000.0
    kwh_per_15min = kwh_per_hour / 4.0
    _LOGGER.debug(
        "Matched %s for %s: %sW → %.5f kWh/15min",
        entity_id,
        timestamp.strftime("%H:%M"),
        watts,
        kwh_per_15min,
    )
    return kwh_per_15min


def get_solar_for_timestamp(
    timestamp: datetime,
    solar_forecast: Dict[str, Any],
    *,
    log_rate_limited: Optional[Any] = None,
) -> float:
    """Get solar production for a timestamp (kWh per 15min)."""
    today = datetime.now().date()
    is_today = timestamp.date() == today

    data = solar_forecast.get("today" if is_today else "tomorrow", {})

    if not data:
        return 0.0

    hour_key = _hour_key(timestamp)
    hourly_kw = data.get(hour_key, 0.0)
    _log_solar_lookup(
        timestamp=timestamp,
        hour_key=hour_key,
        data=data,
        hourly_kw=hourly_kw,
        log_rate_limited=log_rate_limited,
    )

    hourly_kw_value = _safe_float(hourly_kw)
    if hourly_kw_value is None:
        _LOGGER.warning(
            "Invalid solar value for %s: %s (type=%s), key=%s",
            timestamp.strftime("%H:%M"),
            hourly_kw,
            type(hourly_kw),
            hour_key,
        )
        return 0.0

    _log_solar_value(
        timestamp=timestamp,
        hour_key=hour_key,
        hourly_kw=hourly_kw_value,
        log_rate_limited=log_rate_limited,
    )
    return hourly_kw_value / 4.0


def get_load_avg_for_timestamp(
    timestamp: datetime,
    load_avg_sensors: Dict[str, Any],
    *,
    state: Optional[Any] = None,
) -> float:
    """Get load average for a timestamp (kWh per 15min)."""
    if not load_avg_sensors:
        _log_empty_load_avg(state)
        return 0.125

    day_type = "weekend" if timestamp.weekday() >= 5 else "weekday"
    current_hour = timestamp.hour

    for entity_id, sensor_data in load_avg_sensors.items():
        if sensor_data.get("day_type", "") != day_type:
            continue

        time_range = _valid_time_range(sensor_data.get("time_range"))
        if not time_range:
            continue

        start_hour, end_hour = time_range

        if not _is_in_time_range(current_hour, start_hour, end_hour):
            continue

        watts = sensor_data.get("value", 0.0)
        if watts == 0:
            watts = 500.0
            _LOGGER.debug(
                "No consumption data yet for %s, using fallback: 500W",
                timestamp.strftime("%H:%M"),
            )
        return _watts_to_kwh_per_15min(watts, entity_id=entity_id, timestamp=timestamp)

    _LOGGER.debug(
        "No load_avg sensor found for %s (%s), searched %s sensors - using fallback 500W",
        timestamp.strftime("%H:%M"),
        day_type,
        len(load_avg_sensors),
    )
    return 0.125
