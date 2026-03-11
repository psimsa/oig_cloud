from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyShield:
    def __init__(self):
        self.hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *_a, **_k: None))
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None

    async def _log_event(self, *_a, **_k):
        return None

    def _notify_state_change(self):
        return None

    def _normalize_value(self, val):
        return val


@pytest.mark.asyncio
async def test_handle_remove_from_queue_running_position():
    shield = DummyShield()
    shield.running = "svc"
    shield.pending = {"svc": {"entities": {}}}
    await module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 1}, context=None))
    assert shield.running == "svc"


@pytest.mark.asyncio
async def test_handle_remove_from_queue_index_error():
    shield = DummyShield()
    shield.queue = [("svc", {"a": 1}, {"sensor.x": "on"}, None, "", "", False, None)]
    await module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 99}, context=None))
    assert len(shield.queue) == 1


def test_has_pending_mode_change_running():
    shield = DummyShield()
    shield.running = module.SERVICE_SET_BOX_MODE
    assert module.has_pending_mode_change(shield, "Any") is True
