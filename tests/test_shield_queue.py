from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as queue_module


class DummyBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data):
        self.events.append((event, data))


class DummyState:
    def __init__(self, state):
        self.state = state


class DummyStates:
    def __init__(self, states=None):
        self._states = states or {}

    def get(self, entity_id):
        if entity_id in self._states:
            return DummyState(self._states[entity_id])
        return None


class DummyHass:
    def __init__(self, states=None):
        self.bus = DummyBus()
        self.states = DummyStates(states)


class DummyShield:
    def __init__(self, states=None):
        self.hass = DummyHass(states)
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self._state_listener_unsub = None
        self._is_checking = False
        self._active_tasks = {}
        self.check_task = None
        self.logged = []
        self.telemetry = []
        self.security_events = []
        self.notified = 0
        self.start_calls = []

    def _normalize_value(self, value):
        return str(value).lower()

    def _get_entity_state(self, entity_id):
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def _values_match(self, current_value, expected_value):
        return self._normalize_value(current_value) == self._normalize_value(
            expected_value
        )

    async def _log_event(self, *_args, **_kwargs):
        self.logged.append((_args, _kwargs))

    async def _log_telemetry(self, *_args, **_kwargs):
        self.telemetry.append((_args, _kwargs))

    def _log_security_event(self, event_type, details):
        self.security_events.append((event_type, details))

    def _notify_state_change(self):
        self.notified += 1

    async def _start_call(self, *args):
        self.start_calls.append(args)


@pytest.mark.asyncio
async def test_handle_remove_from_queue():
    shield = DummyShield()
    shield.queue = [
        ("oig_cloud.set_box_mode", {"mode": "home1"}, {"box_prms_mode": "home1"}),
        ("oig_cloud.set_grid_delivery", {"mode": "limited"}, {"grid": "limited"}),
    ]
    shield.queue_metadata[("oig_cloud.set_box_mode", str({"mode": "home1"}))] = True
    call = SimpleNamespace(data={"position": 2}, context="ctx")

    await queue_module.handle_remove_from_queue(shield, call)

    assert len(shield.queue) == 1
    assert shield.notified == 1
    assert any(evt[0] == "oig_cloud_shield_queue_removed" for evt in shield.hass.bus.events)


def test_has_pending_mode_change():
    shield = DummyShield()
    shield.pending = {
        "oig_cloud.set_box_mode": {
            "entities": {"box_prms_mode": "Home 2"},
        }
    }
    assert queue_module.has_pending_mode_change(shield, "Home 2") is True


@pytest.mark.asyncio
async def test_check_loop_empty_cleans_listener():
    shield = DummyShield()
    called = {"done": False}

    def _unsub():
        called["done"] = True

    shield._state_listener_unsub = _unsub
    await queue_module.check_loop(shield, None)
    assert called["done"] is True


@pytest.mark.asyncio
async def test_handle_remove_from_queue_invalid_position():
    shield = DummyShield()
    shield.queue = [("svc", {"p": 1}, {"sensor.x": "on"})]
    call = SimpleNamespace(data={"position": 0}, context="ctx")

    await queue_module.handle_remove_from_queue(shield, call)

    assert shield.queue
    assert not shield.hass.bus.events


@pytest.mark.asyncio
async def test_handle_remove_from_queue_running_position():
    shield = DummyShield()
    shield.pending = {"svc": {"entities": {"sensor.x": "on"}}}
    shield.queue = [("svc2", {"p": 2}, {"sensor.y": "off"})]
    call = SimpleNamespace(data={"position": 1}, context="ctx")

    await queue_module.handle_remove_from_queue(shield, call)

    assert len(shield.queue) == 1
    assert not shield.hass.bus.events


@pytest.mark.asyncio
async def test_handle_remove_from_queue_queue_index_error():
    shield = DummyShield()
    shield.pending = {
        "svc1": {"entities": {"sensor.a": "on"}},
        "svc2": {"entities": {"sensor.b": "on"}},
    }
    shield.queue = [("svc3", {"p": 3}, {"sensor.c": "off"})]
    call = SimpleNamespace(data={"position": 2}, context="ctx")

    await queue_module.handle_remove_from_queue(shield, call)

    assert len(shield.queue) == 1
    assert not shield.hass.bus.events


@pytest.mark.asyncio
async def test_check_loop_skips_when_already_running():
    shield = DummyShield()
    shield._is_checking = True

    await queue_module.check_loop(shield, None)

    assert shield._is_checking is True
    assert not shield.logged


@pytest.mark.asyncio
async def test_check_loop_power_monitor_completion():
    shield = DummyShield(states={"sensor.oig_123_power": "3000"})
    shield.running = "svc"
    shield.pending["svc"] = {
        "called_at": datetime.now(),
        "params": {},
        "entities": {"sensor.oig_123_box_prms_mode": "Home UPS"},
        "original_states": {},
        "power_monitor": {
            "entity_id": "sensor.oig_123_power",
            "last_power": 0.0,
            "threshold_kw": 2.5,
            "is_going_to_home_ups": True,
        },
    }

    await queue_module.check_loop(shield, datetime.now())

    assert "svc" not in shield.pending
    assert shield.running is None
    assert any(evt[0][0] == "completed" for evt in shield.logged)


@pytest.mark.asyncio
async def test_check_loop_all_ok_starts_next_call():
    shield = DummyShield(states={"sensor.oig_123_box_prms_mode": "Home 2"})
    shield.pending["svc"] = {
        "called_at": datetime.now(),
        "params": {},
        "entities": {"sensor.oig_123_box_prms_mode": "Home 2"},
        "original_states": {},
    }
    shield.queue.append(("next", {"mode": "Home 3"}, {"sensor.x": "on"}, None, "d", "s", False, None))

    await queue_module.check_loop(shield, datetime.now())

    assert "svc" not in shield.pending
    assert shield.start_calls
    assert shield.notified == 1


def test_start_monitoring_creates_task(monkeypatch):
    shield = DummyShield()
    created = {}

    def _create_task(coro):
        created["coro"] = coro
        if hasattr(coro, "close"):
            coro.close()
        return SimpleNamespace(done=lambda: False, cancelled=lambda: False)

    monkeypatch.setattr(queue_module.asyncio, "create_task", _create_task)

    queue_module.start_monitoring(shield)

    assert created["coro"] is not None
    assert shield.check_task is not None


def test_start_monitoring_skips_when_running(monkeypatch):
    shield = DummyShield()
    shield.check_task = SimpleNamespace(done=lambda: False)

    called = {"count": 0}

    def _create_task(_coro):
        called["count"] += 1
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(queue_module.asyncio, "create_task", _create_task)

    queue_module.start_monitoring(shield)

    assert called["count"] == 0


@pytest.mark.asyncio
async def test_check_entities_periodically_success(monkeypatch):
    shield = DummyShield(states={"sensor.x": "on"})
    shield._active_tasks["task1"] = {
        "expected_entities": {"sensor.x": "on"},
        "timeout": 1,
        "start_time": 0,
    }

    await queue_module.check_entities_periodically(shield, "task1")

    assert any(evt[0] == "MONITORING_SUCCESS" for evt in shield.security_events)


@pytest.mark.asyncio
async def test_check_entities_periodically_timeout(monkeypatch):
    shield = DummyShield(states={"sensor.x": "off"})
    shield._active_tasks["task1"] = {
        "expected_entities": {"sensor.x": "on"},
        "timeout": 0,
        "start_time": 0,
    }

    monkeypatch.setattr(queue_module.time, "time", lambda: 10)

    await queue_module.check_entities_periodically(shield, "task1")

    assert any(evt[0] == "MONITORING_TIMEOUT" for evt in shield.security_events)


@pytest.mark.asyncio
async def test_async_check_loop_error_path(monkeypatch):
    shield = DummyShield()

    async def _check_loop(_shield, _now):
        raise RuntimeError("boom")

    async def _sleep(_delay):
        raise asyncio.CancelledError()

    monkeypatch.setattr(queue_module, "check_loop", _check_loop)
    monkeypatch.setattr(queue_module.asyncio, "sleep", _sleep)

    with pytest.raises(asyncio.CancelledError):
        await queue_module.async_check_loop(shield)
