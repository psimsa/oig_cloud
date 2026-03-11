from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event, data):
        self.fired.append((event, data))


class DummyHass:
    def __init__(self, states=None):
        self.bus = DummyBus()
        self.states = states or {}


class DummyShield:
    def __init__(self):
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self._state_listener_unsub = None
        self._is_checking = False
        self.hass = DummyHass()
        self.check_task = None

    async def _log_event(self, *_args, **_kwargs):
        return None

    async def _log_telemetry(self, *_args, **_kwargs):
        return None

    def _normalize_value(self, value):
        return str(value or "").strip().lower()

    def _notify_state_change(self):
        return None

    def _get_entity_state(self, entity_id):
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def _values_match(self, current, expected):
        return str(current) == str(expected)


def test_get_shield_status_and_queue_info():
    shield = DummyShield()
    assert module.get_shield_status(shield) == "Neaktivní"
    shield.running = "svc"
    assert "Běží" in module.get_shield_status(shield)
    info = module.get_queue_info(shield)
    assert info["queue_length"] == 0


def test_has_pending_mode_change():
    shield = DummyShield()
    shield.pending["oig_cloud.set_box_mode"] = {"entities": {"sensor.x": "Home 2"}}
    assert module.has_pending_mode_change(shield, "home 2") is True


@pytest.mark.asyncio
async def test_handle_remove_from_queue_invalid_position():
    shield = DummyShield()
    call = SimpleNamespace(data={"position": 2}, context=None)
    await module.handle_remove_from_queue(shield, call)
    assert shield.queue == []


@pytest.mark.asyncio
async def test_check_loop_timeout_completion():
    shield = DummyShield()
    shield.pending["oig_cloud.set_formating_mode"] = {
        "called_at": datetime.now() - timedelta(minutes=3),
        "params": {},
        "entities": {},
    }
    await module.check_loop(shield, datetime.now())
    assert shield.pending == {}
