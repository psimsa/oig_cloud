from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast import task_utils
from custom_components.oig_cloud.battery_forecast.storage import plan_storage_io


class DummyLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, callback):
        self.calls.append(callback)
        callback()


class DummyHass:
    def __init__(self, loop):
        self.loop = loop
        self.created = []
        self.components = SimpleNamespace(
            persistent_notification=SimpleNamespace(create=lambda *_a, **_k: None)
        )

    def async_create_task(self, coro):
        coro.close()
        self.created.append(True)
        return object()


class DummyStore:
    def __init__(self, data=None, fail_load=False, fail_save=False):
        self.data = data or {}
        self.fail_load = fail_load
        self.fail_save = fail_save
        self.saved = None

    async def async_load(self):
        if self.fail_load:
            raise RuntimeError("load failed")
        return self.data

    async def async_save(self, data):
        if self.fail_save:
            raise RuntimeError("save failed")
        self.saved = data
        self.data = data


class DummySensor:
    def __init__(self, hass=None):
        self._hass = hass
        self._forecast_retry_unsub = None
        self._in_memory_plan_cache = {}

    async def async_update(self):
        return None


@pytest.mark.asyncio
async def test_create_task_threadsafe_same_loop():
    loop = asyncio.get_running_loop()
    hass = DummyHass(loop)
    sensor = DummySensor(hass=hass)

    async def _coro():
        return 1

    task_utils.create_task_threadsafe(sensor, _coro)
    assert hass.created


def test_create_task_threadsafe_other_loop():
    loop = DummyLoop()
    hass = DummyHass(loop)
    sensor = DummySensor(hass=hass)

    async def _coro():
        return 1

    task_utils.create_task_threadsafe(sensor, _coro)
    assert loop.calls


def test_schedule_forecast_retry(monkeypatch):
    sensor = DummySensor(hass=object())
    called = {}

    def _fake_call_later(_hass, _delay, callback):
        called["cb"] = callback
        return lambda: None

    monkeypatch.setattr(task_utils, "async_call_later", _fake_call_later)
    task_utils.schedule_forecast_retry(sensor, 10.0)

    assert sensor._forecast_retry_unsub is not None
    called["cb"](datetime.now())
    task_utils.schedule_forecast_retry(sensor, 10.0)
    assert sensor._forecast_retry_unsub is not None


def test_schedule_forecast_retry_early_exit():
    sensor = DummySensor(hass=None)
    task_utils.schedule_forecast_retry(sensor, 10.0)
    assert sensor._forecast_retry_unsub is None

    sensor = DummySensor(hass=object())
    task_utils.schedule_forecast_retry(sensor, 0.0)
    assert sensor._forecast_retry_unsub is None

    sensor._forecast_retry_unsub = lambda: None
    task_utils.schedule_forecast_retry(sensor, 10.0)
    assert sensor._forecast_retry_unsub is not None


def test_create_task_threadsafe_no_hass():
    sensor = DummySensor(hass=None)

    async def _coro():
        return 1

    task_utils.create_task_threadsafe(sensor, _coro)


@pytest.mark.asyncio
async def test_save_and_load_plan_storage():
    sensor = DummySensor()
    sensor._plans_store = DummyStore(data={})

    intervals = [{"time": "2025-01-01T00:00:00"}]
    ok = await plan_storage_io.save_plan_to_storage(
        sensor, "2025-01-01", intervals, {"baseline": True}
    )

    assert ok is True
    assert sensor._plans_store.saved["detailed"]["2025-01-01"]["baseline"] is True

    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-01")
    assert loaded["intervals"] == intervals


@pytest.mark.asyncio
async def test_save_plan_storage_failure_creates_cache():
    sensor = DummySensor()
    sensor._plans_store = DummyStore(fail_save=True)

    await plan_storage_io.save_plan_to_storage(
        sensor, "2025-01-02", [{"time": "t"}], {"baseline": False}
    )

    assert "2025-01-02" in sensor._in_memory_plan_cache


@pytest.mark.asyncio
async def test_save_plan_storage_creates_cache_attr():
    sensor = DummySensor()
    sensor._plans_store = DummyStore(fail_save=True)
    delattr(sensor, "_in_memory_plan_cache")

    await plan_storage_io.save_plan_to_storage(
        sensor, "2025-01-02", [{"time": "t"}], {"baseline": False}
    )
    assert sensor._in_memory_plan_cache["2025-01-02"]["intervals"]


@pytest.mark.asyncio
async def test_save_plan_storage_no_store():
    sensor = DummySensor()
    sensor._plans_store = None
    ok = await plan_storage_io.save_plan_to_storage(sensor, "2025-01-05", [], None)
    assert ok is False


@pytest.mark.asyncio
async def test_save_plan_storage_failure_with_retry(monkeypatch):
    loop = asyncio.get_running_loop()
    sensor = DummySensor(hass=DummyHass(loop))
    sensor._plans_store = DummyStore(fail_save=True)

    called = {}

    def _fake_call_later(_hass, _delay, callback):
        called["cb"] = callback
        return lambda: None

    monkeypatch.setattr(plan_storage_io, "async_call_later", _fake_call_later)

    ok = await plan_storage_io.save_plan_to_storage(
        sensor, "2025-01-06", [{"time": "t"}], {"baseline": True}
    )
    assert ok is False
    assert "cb" in called

    retry_cb = called["cb"]
    await retry_cb(None)
    sensor._plans_store.fail_save = False
    await retry_cb(None)


@pytest.mark.asyncio
async def test_load_plan_storage_empty_and_missing_plan():
    sensor = DummySensor()
    sensor._plans_store = DummyStore(data={})
    sensor._in_memory_plan_cache["2025-01-07"] = {"intervals": [{"time": "cached"}]}
    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-07")
    assert loaded["intervals"][0]["time"] == "cached"

    sensor._plans_store = DummyStore(data={"detailed": {}})
    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-07")
    assert loaded["intervals"][0]["time"] == "cached"

    sensor._in_memory_plan_cache = {}
    assert await plan_storage_io.load_plan_from_storage(sensor, "2025-01-07") is None

    sensor._plans_store = DummyStore(data={})
    assert await plan_storage_io.load_plan_from_storage(sensor, "2025-01-07") is None


@pytest.mark.asyncio
async def test_load_plan_storage_error_fallback():
    sensor = DummySensor()
    sensor._plans_store = DummyStore(fail_load=True)
    sensor._in_memory_plan_cache["2025-01-08"] = {"intervals": [{"time": "cached"}]}
    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-08")
    assert loaded["intervals"][0]["time"] == "cached"

    sensor._in_memory_plan_cache = {}
    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-08")
    assert loaded is None


@pytest.mark.asyncio
async def test_plan_exists_in_storage():
    sensor = DummySensor()
    sensor._plans_store = None
    assert await plan_storage_io.plan_exists_in_storage(sensor, "2025-01-01") is False

    sensor._plans_store = DummyStore(data={})
    assert await plan_storage_io.plan_exists_in_storage(sensor, "2025-01-01") is False

    sensor._plans_store = DummyStore(data={"detailed": {"2025-01-01": {}}})
    assert await plan_storage_io.plan_exists_in_storage(sensor, "2025-01-01") is True

    sensor._plans_store = DummyStore(fail_load=True)
    assert await plan_storage_io.plan_exists_in_storage(sensor, "2025-01-01") is False


@pytest.mark.asyncio
async def test_load_plan_storage_fallback_cache():
    sensor = DummySensor()
    sensor._plans_store = None
    sensor._in_memory_plan_cache = {"2025-01-03": {"intervals": [{"time": "x"}]}}

    loaded = await plan_storage_io.load_plan_from_storage(sensor, "2025-01-03")
    assert loaded["intervals"][0]["time"] == "x"


@pytest.mark.asyncio
async def test_load_plan_storage_no_cache():
    sensor = DummySensor()
    sensor._plans_store = None
    assert await plan_storage_io.load_plan_from_storage(sensor, "2025-01-04") is None
