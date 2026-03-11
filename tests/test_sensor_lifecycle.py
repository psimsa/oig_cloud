from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.sensors import sensor_lifecycle


class DummyStore:
    def __init__(self, *_args, **_kwargs):
        self.loaded = {}

    async def async_load(self):
        return self.loaded

    async def async_save(self, data):
        self.loaded = data


class DummyLastState:
    def __init__(self, attributes):
        self.attributes = attributes


class DummyHass:
    def __init__(self):
        self.created = []

    def async_create_task(self, coro):
        self.created.append(coro)
        return coro


class DummySensor:
    def __init__(self):
        self._plans_store = None
        self._precomputed_store = None
        self._hass = DummyHass()
        self.hass = self._hass
        self._config_entry = None
        self._box_id = "123"
        self._side_effects_enabled = True
        self._timeline_data = []
        self._daily_plans_archive = {}
        self._daily_plan_state = None
        self._profiles_dirty = False
        self._data_hash = None
        self._last_update = None
        self._active_charging_plan = None
        self._plan_status = None

        self._update_calls = 0
        self._create_task_calls = []
        self._backfill_called = False
        self._aggregate_daily_called = None
        self._aggregate_weekly_called = None

    def _calculate_data_hash(self, payload):
        return f"hash:{len(payload)}"

    def async_write_ha_state(self):
        self._write_called = True

    async def async_update(self):
        self._update_calls += 1

    async def async_get_last_state(self):
        attrs = {
            "active_plan_data": json.dumps({"requester": "test"}),
            "plan_status": "ready",
            "daily_plan_state": json.dumps({"date": "2025-01-01", "actual": []}),
        }
        return DummyLastState(attrs)

    async def _backfill_daily_archive_from_storage(self):
        self._backfill_called = True

    async def _aggregate_daily(self, date_key):
        self._aggregate_daily_called = date_key

    async def _aggregate_weekly(self, week_key, start_date, end_date):
        self._aggregate_weekly_called = (week_key, start_date, end_date)

    def _log_rate_limited(self, *_args, **_kwargs):
        return None

    def _create_task_threadsafe(self, func, *args):
        self._create_task_calls.append((func, args))


@pytest.mark.asyncio
async def test_async_added_to_hass_restores_and_schedules(monkeypatch):
    sensor = DummySensor()
    precomputed_store = DummyStore()
    precomputed_store.loaded = {
        "timeline_hybrid": [{"time": "2025-01-01T00:00:00"}],
        "last_update": "2025-01-01T00:00:00+00:00",
    }
    plans_store = DummyStore()
    plans_store.loaded = {"daily_archive": {"2025-01-01": {}}}

    def _store_factory(_hass, version, key):
        if "precomputed" in key:
            return precomputed_store
        return plans_store

    monkeypatch.setattr(sensor_lifecycle, "Store", _store_factory)
    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module, "auto_mode_switch_enabled", lambda _s: True
    )
    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module, "start_auto_switch_watchdog", lambda _s: None
    )
    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module,
        "update_auto_switch_schedule",
        lambda *_a, **_k: None,
    )

    scheduled = []

    def _track(_hass, _cb, **kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change", _track
    )

    async def _maybe_call(cb):
        if cb.__name__ != "_mark_ready":
            return
        result = cb()
        if hasattr(result, "__await__"):
            await result

    def _connect(_hass, _signal, callback):
        sensor.hass.created.append(_maybe_call(callback))
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect", _connect
    )

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(sensor_lifecycle.asyncio, "sleep", _sleep)

    await sensor_lifecycle.async_added_to_hass(sensor)

    assert sensor._timeline_data
    assert sensor._data_hash == "hash:1"
    assert sensor._daily_plans_archive
    assert sensor._backfill_called is True
    assert sensor._create_task_calls
    assert len(scheduled) >= 6
    assert sensor._update_calls == 0

    assert sensor.hass.created
    for coro in sensor.hass.created:
        if hasattr(coro, "__await__"):
            await coro
        elif hasattr(coro, "close"):
            coro.close()
    assert sensor._update_calls == 1


@pytest.mark.asyncio
async def test_async_added_to_hass_restore_state_failures(monkeypatch):
    sensor = DummySensor()
    sensor._precomputed_store = DummyStore()
    sensor._plans_store = DummyStore()

    async def _bad_state():
        attrs = {"active_plan_data": "bad-json", "daily_plan_state": "bad-json"}
        return DummyLastState(attrs)

    sensor.async_get_last_state = _bad_state

    monkeypatch.setattr(sensor_lifecycle, "Store", DummyStore)
    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module, "auto_mode_switch_enabled", lambda _s: False
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *_a, **_k: (lambda: None),
    )
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(sensor_lifecycle.asyncio, "sleep", _sleep)

    await sensor_lifecycle.async_added_to_hass(sensor)
    for coro in sensor.hass.created:
        if hasattr(coro, "close"):
            coro.close()

    assert sensor._active_charging_plan is None


@pytest.mark.asyncio
async def test_async_added_to_hass_callbacks(monkeypatch):
    sensor = DummySensor()
    sensor._precomputed_store = DummyStore()
    sensor._precomputed_store.loaded = {
        "timeline_hybrid": [{"time": "x"}],
        "last_update": "bad",
    }

    class PlansStore(DummyStore):
        async def async_load(self):
            return {}

    sensor._plans_store = PlansStore()

    async def _backfill():
        raise RuntimeError("boom")

    sensor._backfill_daily_archive_from_storage = _backfill

    async def _update():
        raise RuntimeError("boom")

    sensor.async_update = _update

    scheduled = []

    def _track(_hass, cb, **kwargs):
        scheduled.append(cb)

    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change", _track
    )

    dispatcher_callbacks = []

    def _connect(_hass, _signal, cb):
        dispatcher_callbacks.append(cb)
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect", _connect
    )

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(sensor_lifecycle.asyncio, "sleep", _sleep)

    await sensor_lifecycle.async_added_to_hass(sensor)

    for cb in scheduled:
        for now in (
            datetime(2025, 1, 4, 10, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc),
        ):
            try:
                await cb(now)
            except Exception:
                pass

    assert dispatcher_callbacks
    await dispatcher_callbacks[0]()

    for coro in sensor.hass.created:
        if hasattr(coro, "close"):
            coro.close()


@pytest.mark.asyncio
async def test_async_added_to_hass_store_failures(monkeypatch):
    sensor = DummySensor()

    class BrokenStore(DummyStore):
        async def async_load(self):
            raise RuntimeError("boom")

    sensor._precomputed_store = BrokenStore()
    sensor._plans_store = BrokenStore()

    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module, "auto_mode_switch_enabled", lambda _s: False
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *_a, **_k: (lambda: None),
    )

    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(sensor_lifecycle.asyncio, "sleep", _sleep)

    await sensor_lifecycle.async_added_to_hass(sensor)

    for coro in sensor.hass.created:
        if hasattr(coro, "close"):
            coro.close()


@pytest.mark.asyncio
async def test_async_added_to_hass_initial_refresh_error(monkeypatch):
    sensor = DummySensor()
    sensor._precomputed_store = DummyStore()
    sensor._plans_store = DummyStore()

    async def _update():
        raise RuntimeError("boom")

    sensor.async_update = _update

    monkeypatch.setattr(
        sensor_lifecycle.auto_switch_module, "auto_mode_switch_enabled", lambda _s: False
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change", lambda *_a, **_k: None
    )

    def _connect(_hass, _signal, callback):
        sensor_lifecycle.asyncio.get_running_loop().create_task(callback())
        return lambda: None

    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect", _connect
    )

    orig_sleep = sensor_lifecycle.asyncio.sleep

    async def _sleep(_seconds):
        await orig_sleep(0)

    monkeypatch.setattr(sensor_lifecycle.asyncio, "sleep", _sleep)

    await sensor_lifecycle.async_added_to_hass(sensor)

    for coro in sensor.hass.created:
        if hasattr(coro, "__await__"):
            try:
                await coro
            except Exception:
                pass
        elif hasattr(coro, "close"):
            coro.close()
