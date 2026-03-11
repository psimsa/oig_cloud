from datetime import datetime, timedelta, timezone

from custom_components.oig_cloud.battery_forecast.data import input as input_module


def test_get_solar_for_timestamp_tomorrow_and_missing():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    tomorrow = now + timedelta(days=1)
    hour_key = tomorrow.replace(minute=0, second=0, microsecond=0).isoformat()

    solar_forecast = {"tomorrow": {hour_key: 8.0}}
    assert input_module.get_solar_for_timestamp(tomorrow, solar_forecast) == 2.0

    assert input_module.get_solar_for_timestamp(tomorrow, {"tomorrow": {}}) == 0.0


def test_get_solar_for_timestamp_invalid_value():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hour_key = now.replace(minute=0, second=0, microsecond=0).isoformat()
    solar_forecast = {"today": {hour_key: "bad"}}
    assert input_module.get_solar_for_timestamp(now, solar_forecast) == 0.0


def test_get_solar_for_timestamp_timezone_aware_key():
    aware = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hour_key = aware.replace(tzinfo=None).isoformat()
    solar_forecast = {"today": {hour_key: 4.0}}
    assert input_module.get_solar_for_timestamp(aware, solar_forecast) == 1.0


def test_get_load_avg_for_timestamp_no_match():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    load_avg_sensors = {
        "sensor.test": {"day_type": day_type, "time_range": (1, 2), "value": 700.0}
    }
    assert input_module.get_load_avg_for_timestamp(now, load_avg_sensors) == 0.125


def test_get_load_avg_for_timestamp_zero_value_fallback():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    load_avg_sensors = {
        "sensor.test": {"day_type": day_type, "time_range": (0, 24), "value": 0}
    }
    assert input_module.get_load_avg_for_timestamp(now, load_avg_sensors) == 0.125


def test_get_load_avg_for_timestamp_invalid_range():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    day_type = "weekend" if now.weekday() >= 5 else "weekday"
    load_avg_sensors = {
        "sensor.test": {"day_type": day_type, "time_range": "bad", "value": 800.0}
    }
    assert input_module.get_load_avg_for_timestamp(now, load_avg_sensors) == 0.125


def test_empty_load_avg_state_flag():
    class DummyState:
        pass

    state = DummyState()
    now = datetime.now()
    assert input_module.get_load_avg_for_timestamp(now, {}, state=state) == 0.125
    assert getattr(state, "_empty_load_sensors_logged", False) is True


def test_get_solar_for_timestamp_logs_lookup_and_value():
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    hour_key = now.replace(minute=0, second=0, microsecond=0).isoformat()
    calls = []

    def _log_rate_limited(*args, **kwargs):
        calls.append((args, kwargs))

    class BadLenDict(dict):
        def __len__(self):
            raise RuntimeError("bad len")

    input_module._log_solar_lookup(
        timestamp=now,
        hour_key=hour_key,
        data=BadLenDict({hour_key: 1.0}),
        hourly_kw=1.0,
        log_rate_limited=_log_rate_limited,
    )
    input_module._log_solar_value(
        timestamp=now.replace(hour=14),
        hour_key=hour_key,
        hourly_kw=2.0,
        log_rate_limited=_log_rate_limited,
    )

    assert calls


def test_get_load_avg_for_timestamp_midnight_wrap_and_day_type_skip():
    now = datetime(2025, 1, 1, 0, 0, 0)
    load_avg_sensors = {
        "sensor.weekend": {"day_type": "weekend", "time_range": (22, 6), "value": 600},
        "sensor.weekday": {"day_type": "weekday", "time_range": (22, 6), "value": 800},
    }
    assert input_module.get_load_avg_for_timestamp(now, load_avg_sensors) == 0.2
