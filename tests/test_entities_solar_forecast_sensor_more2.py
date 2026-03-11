from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import solar_forecast_sensor as module
from custom_components.oig_cloud.entities.solar_forecast_sensor import (
    OigCloudSolarForecastSensor,
)


class DummyCoordinator:
    def __init__(self):
        self.solar_forecast_data = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options


class DummyStore:
    def __init__(self, *_a, **_k):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, _data):
        return None


class DummyState:
    def __init__(self, state):
        self.state = state


class DummyStates:
    def __init__(self, entities=None):
        self._entities = entities or {}

    def get(self, entity_id):
        return self._entities.get(entity_id)


class DummyServices:
    async def async_call(self, *_a, **_k):
        return None


def _make_sensor(options, sensor_type="solar_forecast"):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry(options)
    sensor = OigCloudSolarForecastSensor(coordinator, sensor_type, entry, {})
    sensor.async_write_ha_state = lambda: None
    return sensor


def _make_hass():
    return SimpleNamespace(
        states=DummyStates(),
        services=DummyServices(),
        async_create_task=lambda coro: coro,
    )


@pytest.mark.asyncio
async def test_load_persistent_data_empty_and_error(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "manual"})
    sensor.hass = _make_hass()

    store = DummyStore()
    store._data = None
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    await sensor._load_persistent_data()
    assert sensor._last_forecast_data is None

    class BadStore(DummyStore):
        async def async_load(self):
            raise RuntimeError("bad")

    monkeypatch.setattr(module, "Store", lambda *_a, **_k: BadStore())
    await sensor._load_persistent_data()
    assert sensor._last_api_call == 0


@pytest.mark.asyncio
async def test_save_persistent_data_error(monkeypatch):
    sensor = _make_sensor({})
    sensor.hass = _make_hass()

    class BadStore(DummyStore):
        async def async_save(self, _data):
            raise RuntimeError("bad")

    monkeypatch.setattr(module, "Store", lambda *_a, **_k: BadStore())
    await sensor._save_persistent_data()


@pytest.mark.asyncio
async def test_async_added_to_hass_uses_cached(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "manual"})
    sensor.hass = _make_hass()
    sensor._last_forecast_data = {"total_today_kwh": 1.0}
    sensor._last_api_call = 1234.0

    async def _load():
        return None

    monkeypatch.setattr(sensor, "_load_persistent_data", _load)
    monkeypatch.setattr(sensor, "_should_fetch_data", lambda: False)
    monkeypatch.setattr(module, "async_track_time_interval", lambda *_a, **_k: None)

    await sensor.async_added_to_hass()
    assert sensor.coordinator.solar_forecast_data == {"total_today_kwh": 1.0}


@pytest.mark.asyncio
async def test_periodic_update_modes(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily_optimized"})
    sensor._sensor_type = "solar_forecast"
    sensor._last_api_call = 0

    called = {"count": 0}

    async def _fetch():
        called["count"] += 1

    sensor.async_fetch_forecast_data = _fetch
    await sensor._periodic_update(datetime(2025, 1, 1, 6, 1, 0))
    assert called["count"] == 1

    sensor._config_entry.options["solar_forecast_mode"] = "daily"
    sensor._last_api_call = datetime(2025, 1, 1, 6, 0, 0).timestamp()
    await sensor._periodic_update(datetime(2025, 1, 1, 6, 1, 0))
    assert called["count"] == 1

    sensor._config_entry.options["solar_forecast_mode"] = "every_4h"
    sensor._last_api_call = module.time.time()
    await sensor._periodic_update(datetime(2025, 1, 1, 8, 0, 0))
    assert called["count"] == 1

    sensor._config_entry.options["solar_forecast_mode"] = "hourly"
    sensor._last_api_call = module.time.time()
    await sensor._periodic_update(datetime(2025, 1, 1, 8, 0, 0))
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_async_manual_update_failure(monkeypatch):
    sensor = _make_sensor({})
    sensor.hass = _make_hass()

    async def _boom():
        raise RuntimeError("fail")

    sensor.async_fetch_forecast_data = _boom
    assert await sensor.async_manual_update() is False


@pytest.mark.asyncio
async def test_async_will_remove_from_hass():
    sensor = _make_sensor({})
    sensor.hass = _make_hass()
    called = {"count": 0}

    def _remove():
        called["count"] += 1

    sensor._update_interval_remover = _remove
    await sensor.async_will_remove_from_hass()
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_async_fetch_forecast_string2_errors(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor.hass = _make_hass()
    sensor._config_entry.options["solar_forecast_string1_enabled"] = False
    sensor._config_entry.options["solar_forecast_string2_enabled"] = True

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

        def get(self, *_a, **_k):
            return self._responses.pop(0)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    session = DummySession([DummyResponse(422, text="bad")])
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda: session)
    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data is None


@pytest.mark.asyncio
async def test_async_fetch_forecast_timeout_and_error(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": True})
    sensor.hass = _make_hass()
    sensor._last_forecast_data = {"total_today_kwh": 1.0}
    sensor._config_entry.options["solar_forecast_string1_enabled"] = True
    sensor._config_entry.options["solar_forecast_string2_enabled"] = False

    class DummyResponse:
        def __init__(self, status):
            self.status = status

        async def __aenter__(self):
            raise asyncio.TimeoutError()

        async def __aexit__(self, *_args):
            return False

    class DummySession:
        def get(self, *_a, **_k):
            return DummyResponse(200)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda: DummySession())
    await sensor.async_fetch_forecast_data()
    assert sensor._last_forecast_data == {"total_today_kwh": 1.0}

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "_save_persistent_data", _raise)
    await sensor.async_fetch_forecast_data()


def test_process_forecast_data_error():
    sensor = _make_sensor({})
    result = sensor._process_forecast_data({"result": {"watts": "bad"}}, None)
    assert "error" in result


def test_state_and_attributes_branches(monkeypatch):
    sensor = _make_sensor({"enable_solar_forecast": False})
    sensor.hass = _make_hass()
    assert sensor.state is None

    sensor = _make_sensor({"enable_solar_forecast": True}, sensor_type="solar_forecast")
    sensor.hass = _make_hass()
    sensor.coordinator.solar_forecast_data = {"total_today_kwh": 2.0}
    assert sensor.state == 2.0

    sensor._last_forecast_data = {"total_hourly": None}
    attrs = sensor.extra_state_attributes
    assert "error" in attrs
