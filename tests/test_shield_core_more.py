from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import core as module


class DummyHass:
    def __init__(self):
        self.data = {"core.uuid": "abc"}
        self._tasks = []

    def async_create_task(self, coro):
        self._tasks.append(coro)
        coro.close()
        return object()

    class Services:
        def async_register(self, *_args, **_kwargs):
            return None

    @property
    def services(self):
        return self.Services()


def test_notify_state_change_with_coroutine(monkeypatch):
    hass = DummyHass()
    shield = module.ServiceShield(hass, SimpleNamespace(options={}, data={}))
    called = {"count": 0}

    async def _cb():
        called["count"] += 1

    shield.register_state_change_callback(_cb)
    shield._notify_state_change()
    assert called["count"] == 0
    assert hass._tasks


def test_setup_state_listener_collects_entities(monkeypatch):
    hass = DummyHass()
    shield = module.ServiceShield(hass, SimpleNamespace(options={}, data={}))
    shield.pending = {
        "svc": {
            "entities": {"sensor.x": "on"},
            "power_monitor": {"entity_id": "sensor.power"},
        }
    }

    captured = {}

    def _track(_hass, entity_ids, _cb):
        captured["ids"] = entity_ids
        return lambda: None

    monkeypatch.setattr(module, "async_track_state_change_event", _track)
    shield._setup_state_listener()
    assert "sensor.x" in captured["ids"]
    assert "sensor.power" in captured["ids"]


def test_on_entity_state_changed_schedules(monkeypatch):
    hass = DummyHass()
    shield = module.ServiceShield(hass, SimpleNamespace(options={}, data={}))
    event = SimpleNamespace(data={"entity_id": "sensor.x", "new_state": SimpleNamespace(state="on")})
    shield._on_entity_state_changed(event)
    assert hass._tasks


def test_mode_tracker_stats_and_offset(monkeypatch):
    hass = DummyHass()
    tracker = module.ModeTransitionTracker(hass, "123")
    tracker.track_request("t1", "Home 1", "Home 2")
    start = module.dt_now()
    tracker._active_transitions["t1"]["start_time"] = start - timedelta(seconds=5)

    event = SimpleNamespace(
        data={
            "old_state": SimpleNamespace(state="Home 1"),
            "new_state": SimpleNamespace(state="Home 2"),
        }
    )
    tracker._async_mode_changed(event)
    stats = tracker.get_statistics()
    assert stats
    assert tracker.get_offset_for_scenario("Home 1", "Home 2") >= 0


@pytest.mark.asyncio
async def test_mode_tracker_load_history(monkeypatch):
    hass = DummyHass()

    class DummyState:
        def __init__(self, state, last_changed):
            self.state = state
            self.last_changed = last_changed
            self.attributes = {}

    async def _exec(func, *args):
        return func(*args)

    hass.async_add_executor_job = _exec

    def _history(_hass, _start, _end, sensor_id):
        return {
            sensor_id: [
                DummyState("Home 1", datetime(2025, 1, 1, 0, 0)),
                DummyState("Home 2", datetime(2025, 1, 1, 0, 0, 10)),
            ]
        }

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history,
    )
    tracker = module.ModeTransitionTracker(hass, "123")
    await tracker._async_load_historical_data("sensor.oig_123_box_prms_mode")
    assert tracker.get_statistics()
