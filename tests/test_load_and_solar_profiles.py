from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.data import (
    load_profiles,
    solar_forecast,
)


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, mapping):
        self.states = DummyStates(mapping)


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options


class DummySensor:
    def __init__(self, hass, box_id="123", enable_forecast=True):
        self._hass = hass
        self._box_id = box_id
        self._config_entry = DummyConfigEntry(
            {"enable_solar_forecast": enable_forecast}
        )
        self.coordinator = type("C", (), {"solar_forecast_data": {}})()

    def _log_rate_limited(self, *_args, **_kwargs):
        return None


def test_get_load_avg_sensors():
    entity_id = "sensor.oig_123_load_avg_6_8_weekday"
    hass = DummyHass({entity_id: DummyState("150")})
    sensor = DummySensor(hass)

    result = load_profiles.get_load_avg_sensors(sensor)
    assert entity_id in result
    assert result[entity_id]["value"] == 150.0


def test_get_solar_forecast_from_attributes():
    attrs = {
        "today_hourly_total_kw": {"2025-01-01T10:00:00": 1.5},
        "tomorrow_hourly_total_kw": {"2025-01-02T10:00:00": 2.0},
    }
    hass = DummyHass({"sensor.oig_123_solar_forecast": DummyState("ok", attrs)})
    sensor = DummySensor(hass)

    forecast = solar_forecast.get_solar_forecast(sensor)
    assert forecast["today"]
    assert forecast["tomorrow"]


def test_get_solar_forecast_from_cache():
    hass = DummyHass({})
    sensor = DummySensor(hass)
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)
    sensor.coordinator.solar_forecast_data = {
        "total_hourly": {
            datetime.combine(today, datetime.min.time()).isoformat(): 1000,
            datetime.combine(tomorrow, datetime.min.time()).isoformat(): 2000,
        }
    }

    forecast = solar_forecast.get_solar_forecast(sensor)
    assert forecast["today"]
    assert forecast["tomorrow"]


def test_get_solar_forecast_strings():
    attrs = {
        "today_hourly_string1_kw": {"2025-01-01T10:00:00": 1.0},
        "today_hourly_string2_kw": {"2025-01-01T10:00:00": 1.1},
        "tomorrow_hourly_string1_kw": {"2025-01-02T10:00:00": 2.0},
        "tomorrow_hourly_string2_kw": {"2025-01-02T10:00:00": 2.1},
    }
    hass = DummyHass({"sensor.oig_123_solar_forecast": DummyState("ok", attrs)})
    sensor = DummySensor(hass)

    result = solar_forecast.get_solar_forecast_strings(sensor)
    assert result["today_string1_kw"]
    assert result["tomorrow_string2_kw"]
