from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyHass:
    def __init__(self):
        self.bus = SimpleNamespace(async_fire=lambda *_a, **_k: None)


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None

    async def _log_event(self, *_args, **_kwargs):
        return None

    def _notify_state_change(self):
        return None

    def _normalize_value(self, val):
        return val


@pytest.mark.asyncio
async def test_handle_remove_from_queue_invalid_position():
    shield = DummyShield()
    await module.handle_remove_from_queue(shield, SimpleNamespace(data={"position": 1}, context=None))
    assert shield.queue == []


def test_get_shield_status_and_queue_info():
    shield = DummyShield()
    assert module.get_shield_status(shield) == "Neaktivní"
    shield.running = "svc"
    assert module.get_shield_status(shield) == "Běží: svc"
    shield.running = None
    shield.queue.append(("svc", {}, {}, None, "", "", False, None))
    assert module.get_shield_status(shield) == "Ve frontě: 1 služeb"

    info = module.get_queue_info(shield)
    assert info["queue_length"] == 1


def test_has_pending_mode_change_target():
    shield = DummyShield()
    shield.pending["oig_cloud.set_box_mode"] = {"entities": {"sensor.x": "Home 1"}}
    assert module.has_pending_mode_change(shield, "Home 1") is True
    assert module.has_pending_mode_change(shield, "Home 2") is False
