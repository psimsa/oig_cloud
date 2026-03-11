from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import core as shield_core


class DummyServices:
    def __init__(self):
        self.registered = []

    def async_register(self, domain, service, handler, schema=None):
        self.registered.append((domain, service))


class DummyHass:
    def __init__(self):
        self.services = DummyServices()
        self.data = {"core.uuid": "uuid"}
        self._tasks = []

    def async_create_task(self, coro):
        coro.close()
        self._tasks.append(coro)


def _make_shield(entry_options=None):
    entry_options = entry_options or {}
    entry = SimpleNamespace(options=entry_options, data={"username": "user"})
    hass = DummyHass()
    shield = shield_core.ServiceShield(hass, entry)
    return shield, hass


@pytest.mark.asyncio
async def test_log_telemetry_no_handler():
    shield, _hass = _make_shield()
    shield._telemetry_handler = None
    await shield._log_telemetry("event", "service", {"a": 1})


@pytest.mark.asyncio
async def test_log_telemetry_handler_error():
    shield, _hass = _make_shield()

    class DummyHandler:
        async def send_event(self, *args, **kwargs):
            raise RuntimeError("boom")

    shield._telemetry_handler = DummyHandler()
    await shield._log_telemetry("event", "service")


def test_register_unregister_callbacks():
    shield, _hass = _make_shield()
    cb = lambda: None
    shield.register_state_change_callback(cb)
    assert cb in shield._state_change_callbacks
    shield.unregister_state_change_callback(cb)
    assert cb not in shield._state_change_callbacks


def test_setup_state_listener_no_pending(monkeypatch):
    shield, _hass = _make_shield()
    called = {"count": 0}

    def _track(*_a, **_k):
        called["count"] += 1
        return lambda: None

    monkeypatch.setattr(shield_core, "async_track_state_change_event", _track)
    shield.pending = {}
    shield._setup_state_listener()
    assert called["count"] == 0


def test_setup_state_listener_with_entities(monkeypatch):
    shield, _hass = _make_shield()
    called = {}

    def _track(_hass, entity_ids, _cb):
        called["entity_ids"] = entity_ids
        return lambda: None

    monkeypatch.setattr(shield_core, "async_track_state_change_event", _track)
    shield.pending = {
        "task": {
            "entities": {"sensor.one": "1"},
            "power_monitor": {"entity_id": "sensor.power"},
        }
    }
    shield._setup_state_listener()
    assert "sensor.one" in called["entity_ids"]
    assert "sensor.power" in called["entity_ids"]


def test_on_entity_state_changed_no_state():
    shield, hass = _make_shield()
    event = SimpleNamespace(data={"entity_id": "sensor.x", "new_state": None})
    shield._on_entity_state_changed(event)
    assert hass._tasks == []


def test_on_entity_state_changed_schedules_task():
    shield, hass = _make_shield()
    event = SimpleNamespace(
        data={"entity_id": "sensor.x", "new_state": SimpleNamespace(state="on")}
    )
    shield._on_entity_state_changed(event)
    assert hass._tasks


@pytest.mark.asyncio
async def test_register_services_error(monkeypatch):
    shield, hass = _make_shield()

    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    hass.services.async_register = _raise
    with pytest.raises(RuntimeError):
        await shield.register_services()


@pytest.mark.asyncio
async def test_cleanup_handles_telemetry_and_listener(monkeypatch):
    shield, _hass = _make_shield()
    cleaned = {"closed": False, "unsub": False}

    async def _close():
        cleaned["closed"] = True

    class DummyHandler:
        async def close(self):
            await _close()

    shield._telemetry_handler = DummyHandler()
    shield._state_listener_unsub = lambda: cleaned.__setitem__("unsub", True)

    await shield.cleanup()
    assert cleaned["closed"] is True
    assert cleaned["unsub"] is True


def test_mode_tracker_track_request_same_mode():
    tracker = shield_core.ModeTransitionTracker(DummyHass(), "123")
    tracker.track_request("t1", "HOME_I", "HOME_I")
    assert tracker._active_transitions == {}


def test_mode_tracker_async_mode_changed_no_states():
    tracker = shield_core.ModeTransitionTracker(DummyHass(), "123")
    event = SimpleNamespace(data={"new_state": None, "old_state": None})
    tracker._async_mode_changed(event)


def test_mode_tracker_async_mode_changed_updates():
    tracker = shield_core.ModeTransitionTracker(DummyHass(), "123")
    tracker._active_transitions = {
        "t1": {
            "from_mode": "A",
            "to_mode": "B",
            "start_time": shield_core.dt_now() - timedelta(seconds=5),
        }
    }
    event = SimpleNamespace(
        data={
            "old_state": SimpleNamespace(state="A"),
            "new_state": SimpleNamespace(state="B"),
        }
    )
    tracker._async_mode_changed(event)
    assert "A→B" in tracker._transition_history


def test_mode_tracker_statistics_and_offset():
    tracker = shield_core.ModeTransitionTracker(DummyHass(), "123")
    tracker._transition_history = {"A→B": [1.0, 2.0, 3.0]}
    stats = tracker.get_statistics()
    assert stats["A→B"]["samples"] == 3
    assert tracker.get_offset_for_scenario("A", "B") == stats["A→B"]["p95_seconds"]


@pytest.mark.asyncio
async def test_mode_tracker_load_history_no_data(monkeypatch):
    tracker = shield_core.ModeTransitionTracker(DummyHass(), "123")
    sensor_id = "sensor.oig_123_box_prms_mode"

    def _history(_hass, _start, _end, _sensor_id):
        return {}

    hass = tracker.hass
    hass.async_add_executor_job = lambda func, *args: func(*args)
    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history,
    )
    await tracker._async_load_historical_data(sensor_id)
