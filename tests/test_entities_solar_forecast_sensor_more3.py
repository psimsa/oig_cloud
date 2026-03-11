from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import solar_forecast_sensor as module


class DummyCoordinator:
    def __init__(self):
        self.solar_forecast_data = None
        self.hass = SimpleNamespace()

    def async_add_listener(self, *_a, **_k):
        return lambda: None


class DummyStore:
    def __init__(self, data=None, fail=False):
        self._data = data
        self._fail = fail
        self.saved = None

    async def async_load(self):
        if self._fail:
            raise RuntimeError("load fail")
        return self._data

    async def async_save(self, data):
        if self._fail:
            raise RuntimeError("save fail")
        self.saved = data


def _make_sensor(monkeypatch, sensor_type="solar_forecast", options=None):
    options = options or {"enable_solar_forecast": True}
    coord = DummyCoordinator()
    entry = SimpleNamespace(options=options)
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SOLAR_FORECAST.SENSOR_TYPES_SOLAR_FORECAST",
        {sensor_type: {"name_cs": "Solar"}},
    )
    sensor = module.OigCloudSolarForecastSensor(coord, sensor_type, entry, {"identifiers": set()})
    sensor.hass = SimpleNamespace(
        async_create_task=lambda _coro: None,
        services=SimpleNamespace(async_call=lambda *_a, **_k: None),
        states=SimpleNamespace(get=lambda _eid: None),
    )
    return sensor


@pytest.mark.asyncio
async def test_load_persistent_data_no_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    store = DummyStore({})
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    await sensor._load_persistent_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_load_persistent_data_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    store = DummyStore(fail=True)
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    await sensor._load_persistent_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_save_persistent_data_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    store = DummyStore(fail=True)
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    await sensor._save_persistent_data()


@pytest.mark.asyncio
async def test_load_save_last_api_call_noop(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    await sensor._load_last_api_call()
    await sensor._save_last_api_call()


@pytest.mark.asyncio
async def test_async_added_uses_cached_data(monkeypatch):
    sensor = _make_sensor(
        monkeypatch, options={"solar_forecast_mode": "manual", "enable_solar_forecast": True}
    )
    sensor._last_forecast_data = {"total_today_kwh": 1.0}
    sensor._last_api_call = time = datetime.now().timestamp()
    sensor._should_fetch_data = lambda: False
    async def _load():
        return None

    sensor._load_persistent_data = _load
    await sensor.async_added_to_hass()
    assert sensor.coordinator.solar_forecast_data == sensor._last_forecast_data


@pytest.mark.asyncio
async def test_delayed_initial_fetch_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def _boom():
        raise RuntimeError("bad")

    sensor.async_fetch_forecast_data = _boom
    async def _sleep(_s):
        return None

    monkeypatch.setattr(module.asyncio, "sleep", _sleep)
    await sensor._delayed_initial_fetch()


@pytest.mark.asyncio
async def test_periodic_update_daily_skip(monkeypatch):
    sensor = _make_sensor(monkeypatch, options={"solar_forecast_mode": "daily"})
    now = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
    sensor._last_api_call = now.timestamp()

    called = {"count": 0}

    async def _fetch():
        called["count"] += 1

    sensor.async_fetch_forecast_data = _fetch
    await sensor._periodic_update(now)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_periodic_update_every_4h_skip(monkeypatch):
    sensor = _make_sensor(monkeypatch, options={"solar_forecast_mode": "every_4h"})
    now = datetime.now()
    sensor._last_api_call = now.timestamp()

    called = {"count": 0}

    async def _fetch():
        called["count"] += 1

    sensor.async_fetch_forecast_data = _fetch
    await sensor._periodic_update(now)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_periodic_update_hourly_skip(monkeypatch):
    sensor = _make_sensor(monkeypatch, options={"solar_forecast_mode": "hourly"})
    now = datetime.now()
    sensor._last_api_call = now.timestamp()

    called = {"count": 0}

    async def _fetch():
        called["count"] += 1

    sensor.async_fetch_forecast_data = _fetch
    await sensor._periodic_update(now)
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_manual_update_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def _boom():
        raise RuntimeError("bad")

    sensor.async_fetch_forecast_data = _boom
    assert await sensor.async_manual_update() is False


@pytest.mark.asyncio
async def test_async_will_remove_from_hass(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"count": 0}
    sensor._update_interval_remover = lambda: called.__setitem__("count", 1)
    await sensor.async_will_remove_from_hass()
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_async_fetch_rate_limit(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._last_api_call = time = datetime.now().timestamp()
    sensor._min_api_interval = 300
    await sensor.async_fetch_forecast_data()
    assert sensor._last_api_call == time


@pytest.mark.asyncio
async def test_broadcast_forecast_data_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor.hass = None
    await sensor._broadcast_forecast_data()


def test_process_forecast_data_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    def _boom(_data):
        raise RuntimeError("bad")

    monkeypatch.setattr(sensor, "_convert_to_hourly", _boom)
    result = sensor._process_forecast_data({"result": {"watts": {}}}, None)
    assert "error" in result


def test_convert_to_hourly_invalid_timestamp(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    result = sensor._convert_to_hourly({"bad": 1.0})
    assert result == {}


def test_available_disabled(monkeypatch):
    sensor = _make_sensor(monkeypatch, options={"enable_solar_forecast": False})
    assert sensor.available is False


def test_state_error_path(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    class BadData:
        def get(self, _k, _d=None):
            raise RuntimeError("bad")

    sensor._last_forecast_data = BadData()
    assert sensor.state is None


def test_extra_state_attributes_empty(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._last_forecast_data = None
    assert sensor.extra_state_attributes == {}


def test_extra_state_attributes_invalid_hours(monkeypatch):
    sensor = _make_sensor(monkeypatch, sensor_type="solar_forecast")
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    sensor._last_forecast_data = {
        "total_hourly": {"bad": 100},
        "string1_hourly": {"bad": 100},
        "string2_hourly": {"bad": 100},
        "total_today_kwh": 1.0,
        "string1_today_kwh": 0.5,
        "string2_today_kwh": 0.5,
        "response_time": now.isoformat(),
    }
    attrs = sensor.extra_state_attributes
    assert "today_total_kwh" in attrs


def test_extra_state_attributes_string1_invalid_hour(monkeypatch):
    sensor = _make_sensor(monkeypatch, sensor_type="solar_forecast_string1")
    sensor._last_forecast_data = {
        "string1_hourly": {"bad": 100},
        "string1_today_kwh": 0.0,
        "response_time": datetime.now().isoformat(),
    }
    attrs = sensor.extra_state_attributes
    assert "today_kwh" in attrs


def test_extra_state_attributes_error(monkeypatch):
    sensor = _make_sensor(monkeypatch, sensor_type="solar_forecast_string2")

    class BadData:
        def get(self, _k, _d=None):
            raise RuntimeError("bad")

    sensor._last_forecast_data = BadData()
    attrs = sensor.extra_state_attributes
    assert "error" in attrs
