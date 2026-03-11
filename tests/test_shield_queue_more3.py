from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import queue as module


class DummyShield:
    def __init__(self):
        self.pending = {}
        self.queue = []
        self.running = None
        self._is_checking = False
        self._state_listener_unsub_called = False
        self._state_listener_unsub = lambda: self._mark_unsub()

    def _mark_unsub(self):
        self._state_listener_unsub_called = True

    async def _log_event(self, *_a, **_k):
        return None

    async def _log_telemetry(self, *_a, **_k):
        return None

    def _notify_state_change(self):
        return None


@pytest.mark.asyncio
async def test_check_loop_clears_listener_when_empty():
    shield = DummyShield()
    await module.check_loop(shield, datetime.now())
    assert shield._state_listener_unsub_called is True


@pytest.mark.asyncio
async def test_check_loop_timeout_formating_mode(monkeypatch):
    shield = DummyShield()
    shield.pending = {
        "oig_cloud.set_formating_mode": {
            "called_at": datetime.now() - timedelta(minutes=3),
            "params": {},
            "entities": {},
        }
    }
    await module.check_loop(shield, datetime.now())
    assert shield.pending == {}
