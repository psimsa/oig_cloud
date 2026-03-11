from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.data import solar_forecast


class DummyState:
    def __init__(self, attributes=None):
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
    def __init__(self, hass, enable_forecast=True):
        self._hass = hass
        self._box_id = "123"
        self._config_entry = DummyConfigEntry(
            {"enable_solar_forecast": enable_forecast}
        )
        self.coordinator = type("C", (), {"solar_forecast_data": {}})()

    def _log_rate_limited(self, *_args, **_kwargs):
        return None


def test_get_solar_forecast_no_hass():
    sensor = DummySensor(None)
    assert solar_forecast.get_solar_forecast(sensor) == {}


def test_get_solar_forecast_disabled():
    sensor = DummySensor(DummyHass({}), enable_forecast=False)
    assert solar_forecast.get_solar_forecast(sensor) == {}


def test_get_solar_forecast_missing_state_with_cache():
    hass = DummyHass({})
    sensor = DummySensor(hass)
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    sensor.coordinator.solar_forecast_data = {
        "total_hourly": {
            datetime.combine(today, datetime.min.time()).isoformat(): 1000,
            datetime.combine(tomorrow, datetime.min.time()).isoformat(): 2000,
            "bad": "nope",
        }
    }
    data = solar_forecast.get_solar_forecast(sensor)
    assert data["today"]
    assert data["tomorrow"]


def test_get_solar_forecast_no_attrs():
    hass = DummyHass({"sensor.oig_123_solar_forecast": DummyState(None)})
    sensor = DummySensor(hass)
    assert solar_forecast.get_solar_forecast(sensor) == {}


def test_get_solar_forecast_strings_missing():
    sensor = DummySensor(DummyHass({}))
    assert solar_forecast.get_solar_forecast_strings(sensor) == {}


def test_get_solar_forecast_missing_state_no_cache():
    hass = DummyHass({})
    sensor = DummySensor(hass)
    sensor.coordinator.solar_forecast_data = {"total_hourly": {}}
    assert solar_forecast.get_solar_forecast(sensor) == {}


def test_get_solar_forecast_strings_no_hass():
    sensor = DummySensor(None)
    assert solar_forecast.get_solar_forecast_strings(sensor) == {}
