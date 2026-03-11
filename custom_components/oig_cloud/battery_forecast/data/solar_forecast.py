"""Solar forecast helpers for battery forecast."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def get_solar_forecast(sensor: Any) -> Dict[str, Any]:
    """Return solar forecast data grouped by day."""
    if not sensor._hass:
        return {}

    if not (
        sensor._config_entry
        and sensor._config_entry.options.get("enable_solar_forecast", False)
    ):
        return {}

    sensor_id = f"sensor.oig_{sensor._box_id}_solar_forecast"
    state = sensor._hass.states.get(sensor_id)

    if not state:
        cached = getattr(sensor.coordinator, "solar_forecast_data", None)
        total_hourly = cached.get("total_hourly") if isinstance(cached, dict) else None
        if isinstance(total_hourly, dict) and total_hourly:
            today = dt_util.now().date()
            tomorrow = today + timedelta(days=1)
            today_total: Dict[str, float] = {}
            tomorrow_total: Dict[str, float] = {}
            for hour_str, watts in total_hourly.items():
                try:
                    hour_dt = datetime.fromisoformat(hour_str)
                    kw = round(float(watts) / 1000.0, 2)
                    if hour_dt.date() == today:
                        today_total[hour_str] = kw
                    elif hour_dt.date() == tomorrow:
                        tomorrow_total[hour_str] = kw
                except Exception:  # nosec B112
                    continue
            sensor._log_rate_limited(
                "solar_forecast_fallback",
                "debug",
                "Solar forecast entity missing; using coordinator cached data (%s)",
                sensor_id,
                cooldown_s=900.0,
            )
            return {"today": today_total, "tomorrow": tomorrow_total}

        sensor._log_rate_limited(
            "solar_forecast_missing",
            "debug",
            "Solar forecast sensor not found yet: %s",
            sensor_id,
            cooldown_s=900.0,
        )
        return {}

    if not state.attributes:
        sensor._log_rate_limited(
            "solar_forecast_no_attrs",
            "debug",
            "Solar forecast sensor has no attributes yet: %s",
            sensor_id,
            cooldown_s=900.0,
        )
        return {}

    today = state.attributes.get("today_hourly_total_kw", {})
    tomorrow = state.attributes.get("tomorrow_hourly_total_kw", {})

    sensor._log_rate_limited(
        "solar_forecast_loaded",
        "debug",
        "Solar forecast loaded: today=%d tomorrow=%d (%s)",
        len(today) if isinstance(today, dict) else 0,
        len(tomorrow) if isinstance(tomorrow, dict) else 0,
        sensor_id,
        cooldown_s=1800.0,
    )

    return {"today": today, "tomorrow": tomorrow}


def get_solar_forecast_strings(sensor: Any) -> Dict[str, Any]:
    """Return per-string solar forecast data."""
    if not sensor._hass:
        return {}

    sensor_id = f"sensor.oig_{sensor._box_id}_solar_forecast"
    state = sensor._hass.states.get(sensor_id)

    if not state or not state.attributes:
        return {}

    return {
        "today_string1_kw": state.attributes.get("today_hourly_string1_kw", {}),
        "today_string2_kw": state.attributes.get("today_hourly_string2_kw", {}),
        "tomorrow_string1_kw": state.attributes.get("tomorrow_hourly_string1_kw", {}),
        "tomorrow_string2_kw": state.attributes.get("tomorrow_hourly_string2_kw", {}),
    }
