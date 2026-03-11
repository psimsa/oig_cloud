from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import solar_forecast_sensor as module
from custom_components.oig_cloud.entities.solar_forecast_sensor import (
    OigCloudSolarForecastSensor,
    _parse_forecast_hour,
)


class DummyCoordinator:
    def __init__(self):
        self.solar_forecast_data = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options


def _make_sensor(options, sensor_type="solar_forecast"):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry(options)
    sensor = OigCloudSolarForecastSensor(coordinator, sensor_type, entry, {})
    sensor.async_write_ha_state = lambda: None
    return sensor


class DummyResponse:
    def __init__(self, status, payload=None, text=""):
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class DummySession:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def test_parse_forecast_hour_invalid():
    assert _parse_forecast_hour("bad") is None


def test_should_fetch_data_modes(monkeypatch):
    base = {"enable_solar_forecast": True}
    sensor = _make_sensor({**base, "solar_forecast_mode": "daily_optimized"})
    assert sensor._should_fetch_data() is True

    fixed_now = 1_700_000_000.0
    monkeypatch.setattr(module.time, "time", lambda: fixed_now)
    sensor._last_api_call = fixed_now - 3601
    sensor._config_entry.options["solar_forecast_mode"] = "hourly"
    assert sensor._should_fetch_data() is True
    sensor._last_api_call = fixed_now - 100
    assert sensor._should_fetch_data() is False

    sensor._config_entry.options["solar_forecast_mode"] = "manual"
    assert sensor._should_fetch_data() is False


def test_get_update_interval():
    sensor = _make_sensor({"enable_solar_forecast": True})
    assert sensor._get_update_interval("hourly") == timedelta(hours=1)
    assert sensor._get_update_interval("manual") is None


@pytest.mark.asyncio
async def test_periodic_update_daily_optimized_skips(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily_optimized"})
    sensor._sensor_type = "solar_forecast"
    sensor._last_api_call = 1_700_000_000.0

    now = datetime(2025, 1, 1, 7, 10, 0)
    await sensor._periodic_update(now)


@pytest.mark.asyncio
async def test_periodic_update_daily_only_at_six(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily"})
    sensor._sensor_type = "solar_forecast"

    called = {"count": 0}

    async def _fetch():
        called["count"] += 1

    sensor.async_fetch_forecast_data = _fetch

    await sensor._periodic_update(datetime(2025, 1, 1, 7, 0, 0))
    assert called["count"] == 0

    await sensor._periodic_update(datetime(2025, 1, 1, 6, 0, 0))
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_async_fetch_forecast_rate_limit(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor._last_api_call = module.time.time()
    sensor._min_api_interval = 300

    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_async_fetch_forecast_string1_422(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor._config_entry.options["solar_forecast_string1_enabled"] = True
    sensor._config_entry.options["solar_forecast_string2_enabled"] = False

    session = DummySession([DummyResponse(422, text="bad")])
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda: session)

    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_async_fetch_forecast_no_strings(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor._config_entry.options["solar_forecast_string1_enabled"] = False
    sensor._config_entry.options["solar_forecast_string2_enabled"] = False

    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_async_fetch_forecast_success(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor._config_entry.options["solar_forecast_string1_enabled"] = True
    sensor._config_entry.options["solar_forecast_string2_enabled"] = False

    payload = {
        "result": {
            "watts": {"2025-01-01T10:00:00+00:00": 1000},
            "watt_hours_day": {"2025-01-01": 2000},
        }
    }
    session = DummySession([DummyResponse(200, payload=payload)])
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda: session)

    async def _save():
        return None

    async def _broadcast():
        return None

    sensor._save_persistent_data = _save
    sensor._broadcast_forecast_data = _broadcast

    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data is not None
    assert sensor.coordinator.solar_forecast_data is not None


def test_process_forecast_data_string2_only():
    sensor = _make_sensor({"enable_solar_forecast": True})
    data_string2 = {
        "result": {
            "watts": {"2025-01-01T10:00:00+00:00": 500},
            "watt_hours_day": {"2025-01-01": 1000},
        }
    }
    result = sensor._process_forecast_data(None, data_string2)
    assert result["string1_today_kwh"] == 0
    assert result["string2_today_kwh"] == 1.0
    assert result["total_today_kwh"] == 1.0


def test_convert_to_hourly_invalid_timestamp():
    sensor = _make_sensor({"enable_solar_forecast": True})
    output = sensor._convert_to_hourly({"bad": 1000})
    assert output == {}


def test_extra_state_attributes_string1_and_string2():
    sensor = _make_sensor({"enable_solar_forecast": True}, sensor_type="solar_forecast_string1")
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hour_key = now.isoformat()
    sensor._last_forecast_data = {
        "response_time": now.isoformat(),
        "string1_today_kwh": 2.5,
        "string1_hourly": {hour_key: 500},
    }
    attrs = sensor.extra_state_attributes
    assert attrs["today_kwh"] == 2.5
    assert attrs["current_hour_kw"] == 0.5

    sensor = _make_sensor({"enable_solar_forecast": True}, sensor_type="solar_forecast_string2")
    sensor._last_forecast_data = {
        "response_time": now.isoformat(),
        "string2_today_kwh": 3.0,
        "string2_hourly": {hour_key: 1000, "bad": 200},
    }
    attrs = sensor.extra_state_attributes
    assert attrs["today_kwh"] == 3.0
    assert attrs["current_hour_kw"] == 1.0
