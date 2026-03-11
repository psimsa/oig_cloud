from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data):
        self.events.append((event, data))


class DummyHass:
    def __init__(self, states=None):
        self.bus = DummyBus()
        self.states = states or SimpleNamespace(get=lambda _eid: None)


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self._is_checking = False
        self._state_listener_unsub = None
        self._active_tasks = {}
        self.check_task = None

    async def _log_event(self, *_a, **_k):
        return None

    async def _log_telemetry(self, *_a, **_k):
        return None

    def _notify_state_change(self):
        return None

    def _normalize_value(self, val):
        return val

    def _get_entity_state(self, _eid):
        return "on"

    def _values_match(self, current, expected):
        return current == expected

    def _log_security_event(self, *_a, **_k):
        return None


@pytest.mark.asyncio
async def test_handle_shield_status_and_queue_info():
    shield = DummyShield()
    await module.handle_shield_status(shield, SimpleNamespace())
    await module.handle_queue_info(shield, SimpleNamespace())
    assert shield.hass.bus.events


def test_get_queue_info_and_status():
    shield = DummyShield()
    shield.queue = [("svc", {}, {}, None, "", "", False, None)]
    info = module.get_queue_info(shield)
    assert info["queue_length"] == 1
    assert module.get_shield_status(shield).startswith("Ve frontě")


def test_has_pending_mode_change_matches():
    shield = DummyShield()
    shield.pending = {
        module.SERVICE_SET_BOX_MODE: {"entities": {"sensor.x": "HOME"}}
    }
    assert module.has_pending_mode_change(shield, "HOME") is True


@pytest.mark.asyncio
async def test_check_loop_skips_when_checking():
    shield = DummyShield()
    shield._is_checking = True
    await module.check_loop(shield, datetime.now())
    assert shield._is_checking is True


@pytest.mark.asyncio
async def test_check_loop_power_monitor_completion():
    shield = DummyShield()
    shield.hass = DummyHass(
        states=SimpleNamespace(get=lambda _eid: SimpleNamespace(state="3000"))
    )
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"sensor.x": "on"},
            "power_monitor": {
                "entity_id": "sensor.power",
                "last_power": 0,
                "threshold_kw": 2.5,
                "is_going_to_home_ups": True,
            },
        }
    }
    await module.check_loop(shield, datetime.now())
    assert shield.pending == {}


@pytest.mark.asyncio
async def test_check_entities_periodically_success():
    shield = DummyShield()
    shield._active_tasks["t1"] = {
        "expected_entities": {"sensor.x": "on"},
        "timeout": 10,
        "start_time": 0,
        "status": "monitoring",
    }
    await module.check_entities_periodically(shield, "t1")
    assert "t1" in shield._active_tasks


@pytest.mark.asyncio
async def test_check_entities_periodically_timeout(monkeypatch):
    shield = DummyShield()
    shield._active_tasks["t2"] = {
        "expected_entities": {"sensor.x": "off"},
        "timeout": 1,
        "start_time": 0,
        "status": "monitoring",
    }
    monkeypatch.setattr(module.time, "time", lambda: 2)
    shield._values_match = lambda *_a, **_k: False
    await module.check_entities_periodically(shield, "t2")
    assert "t2" in shield._active_tasks


def test_start_monitoring_creates_task(monkeypatch):
    shield = DummyShield()
    created = {"task": None}

    def _create_task(_coro):
        _coro.close()
        task = SimpleNamespace(done=lambda: False, cancelled=lambda: False)
        created["task"] = task
        return task

    monkeypatch.setattr(module.asyncio, "create_task", _create_task)
    module.start_monitoring(shield)
    assert shield.check_task is created["task"]
