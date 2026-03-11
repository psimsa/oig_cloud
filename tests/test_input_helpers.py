from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.data import input as input_module


def test_get_solar_for_timestamp_today() -> None:
    now = datetime.now().replace(minute=15, second=0, microsecond=0)
    hour_key = now.replace(minute=0, second=0, microsecond=0).isoformat()

    solar_forecast = {"today": {hour_key: 4.0}}
    assert input_module.get_solar_for_timestamp(now, solar_forecast) == 1.0


def test_get_load_avg_for_timestamp_match() -> None:
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"

    load_avg_sensors = {
        "sensor.test": {
            "day_type": day_type,
            "time_range": (0, 24),
            "value": 800.0,
        }
    }

    assert input_module.get_load_avg_for_timestamp(now, load_avg_sensors) == 0.2


def test_get_load_avg_for_timestamp_empty() -> None:
    now = datetime.now()
    assert input_module.get_load_avg_for_timestamp(now, {}) == 0.125
