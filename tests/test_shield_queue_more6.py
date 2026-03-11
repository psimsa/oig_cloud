from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data, context=None):
        self.events.append((event, data))


class DummyStates:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, states=None):
        self.bus = DummyBus()
        self.states = DummyStates(states)


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
        self.logged = []
        self.telemetry = []

    def _normalize_value(self, val):
        return str(val) if val is not None else ""

    async def _log_event(self, event_type, service, data, reason=None, context=None):
        self.logged.append((event_type, service, data, reason))

    async def _log_telemetry(self, event_type, service, data):
        self.telemetry.append((event_type, service, data))

    def _notify_state_change(self):
        return None

    def _setup_state_listener(self):
        return None

    async def _start_call(self, *_a, **_k):
        return None

    def _get_entity_state(self, entity_id):
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def _values_match(self, current, expected):
        return current == expected

    def _log_security_event(self, *_a, **_k):
        return None


@pytest.mark.asyncio
async def test_handle_status_and_queue_info():
    shield = DummyShield()
    await module.handle_shield_status(shield, SimpleNamespace(data={}, context=None))
    await module.handle_queue_info(shield, SimpleNamespace(data={}, context=None))
    assert shield.hass.bus.events


@pytest.mark.asyncio
async def test_handle_remove_from_queue_paths():
    shield = DummyShield()
    call = SimpleNamespace(data={"position": 0}, context=None)
    await module.handle_remove_from_queue(shield, call)

    shield.pending = {"svc": {"entities": {}}}
    call = SimpleNamespace(data={"position": 1}, context=None)
    await module.handle_remove_from_queue(shield, call)

    shield.pending = {}
    shield.queue = [("svc", {"a": 1}, {"x": "1"}, None, "", "", False, None)]
    call = SimpleNamespace(data={"position": 1}, context=None)
    await module.handle_remove_from_queue(shield, call)
    assert not shield.queue


def test_has_pending_mode_change_variants():
    shield = DummyShield()
    assert module.has_pending_mode_change(shield, None) is False

    shield.pending = {"oig_cloud.set_box_mode": {"entities": {"x": "home"}}}
    assert module.has_pending_mode_change(shield, "home") is True
    assert module.has_pending_mode_change(shield, None) is True

    shield.pending = {}
    shield.queue = [("oig_cloud.set_box_mode", {}, {"x": "home"}, None, "", "", False, None)]
    assert module.has_pending_mode_change(shield, "home") is True

    shield.queue = []
    shield.running = "oig_cloud.set_box_mode"
    assert module.has_pending_mode_change(shield, None) is True

    shield.running = None
    shield.pending = {"oig_cloud.set_box_mode": {"entities": {}}}
    assert module.has_pending_mode_change(shield, "home") is False


@pytest.mark.asyncio
async def test_check_loop_timeout_and_completion(monkeypatch):
    shield = DummyShield()
    past = datetime.now() - timedelta(minutes=20)
    shield.pending = {
        "oig_cloud.set_formating_mode": {
            "called_at": past,
            "params": {},
            "entities": {"fake_formating_mode_1": "completed"},
            "original_states": {},
        }
    }
    await module.check_loop(shield, datetime.now())
    assert not shield.pending

    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
        }
    }
    shield.hass.states = DummyStates({"sensor.a": SimpleNamespace(state="1")})
    await module.check_loop(shield, datetime.now())
    assert not shield.pending

    shield._is_checking = True
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_check_loop_timeout_non_formatting():
    shield = DummyShield()
    past = datetime.now() - timedelta(minutes=20)
    shield.pending = {
        "svc": {
            "called_at": past,
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
        }
    }
    await module.check_loop(shield, datetime.now())
    assert not shield.pending


@pytest.mark.asyncio
async def test_check_loop_power_monitor(monkeypatch):
    shield = DummyShield()
    past = datetime.now()
    shield.pending = {
        "svc": {
            "called_at": past,
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
            "power_monitor": {
                "entity_id": "sensor.power",
                "baseline_power": 0.0,
                "last_power": 0.0,
                "target_mode": "HOME UPS",
                "is_going_to_home_ups": True,
                "threshold_kw": 0.001,
                "started_at": past,
            },
        }
    }
    shield.hass.states = DummyStates({"sensor.power": SimpleNamespace(state="2")})
    await module.check_loop(shield, datetime.now())
    assert not shield.pending


@pytest.mark.asyncio
async def test_check_loop_power_monitor_missing_entity():
    shield = DummyShield()
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
            "power_monitor": {
                "entity_id": "sensor.power",
                "baseline_power": 0.0,
                "last_power": 0.0,
                "target_mode": "HOME UPS",
                "is_going_to_home_ups": True,
                "threshold_kw": 0.1,
                "started_at": datetime.now(),
            },
        }
    }
    shield.hass.states = DummyStates({})
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_check_loop_power_monitor_unavailable():
    shield = DummyShield()
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
            "power_monitor": {
                "entity_id": "sensor.power",
                "baseline_power": 0.0,
                "last_power": 0.0,
                "target_mode": "HOME UPS",
                "is_going_to_home_ups": False,
                "threshold_kw": 0.001,
                "started_at": datetime.now(),
            },
        }
    }
    shield.hass.states = DummyStates(
        {"sensor.power": SimpleNamespace(state="unknown")}
    )
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_check_loop_invertor_and_binary(monkeypatch):
    shield = DummyShield()
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {
                "sensor.oig_123_invertor_prm1_p_max_feed_grid": "bad",
                "binary_sensor.oig_123_invertor_prms_to_grid": "omezeno",
            },
            "original_states": {},
        }
    }
    shield.hass.states = DummyStates(
        {
            "sensor.oig_123_invertor_prm1_p_max_feed_grid": SimpleNamespace(state="x"),
            "binary_sensor.oig_123_invertor_prms_to_grid": SimpleNamespace(state="zapnuto"),
        }
    )
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_check_loop_mismatch_logs():
    shield = DummyShield()
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"sensor.a": "1"},
            "original_states": {},
        }
    }
    shield.hass.states = DummyStates({"sensor.a": SimpleNamespace(state="0")})
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_check_loop_fake_formating_wait():
    shield = DummyShield()
    shield.pending = {
        "svc": {
            "called_at": datetime.now(),
            "params": {},
            "entities": {"fake_formating_mode_1": "done"},
            "original_states": {},
        }
    }
    await module.check_loop(shield, datetime.now())


@pytest.mark.asyncio
async def test_start_monitoring_and_check_entities(monkeypatch):
    shield = DummyShield()
    module.start_monitoring_task(shield, "task", {"sensor.a": "1"}, timeout=1)
    assert "task" in shield._active_tasks

    shield.hass.states = DummyStates({"sensor.a": SimpleNamespace(state="1")})
    shield._values_match = lambda current, expected: True
    await module.check_entities_periodically(shield, "task")


@pytest.mark.asyncio
async def test_check_loop_empty_unsub():
    shield = DummyShield()
    called = {"count": 0}
    def _unsub():
        called["count"] += 1
    shield._state_listener_unsub = _unsub
    await module.check_loop(shield, datetime.now())
    assert called["count"] == 1


def test_start_monitoring_warns_done_task(monkeypatch):
    shield = DummyShield()
    shield.check_task = SimpleNamespace(done=lambda: True)

    created = {"count": 0}

    def _fake_create_task(_coro):
        _coro.close()
        created["count"] += 1
        return SimpleNamespace(done=lambda: False, cancelled=lambda: False)

    monkeypatch.setattr(module.asyncio, "create_task", _fake_create_task)

    module.start_monitoring(shield)
    assert created["count"] == 1
