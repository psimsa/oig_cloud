from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyHass:
    def __init__(self):
        self.states = SimpleNamespace(get=lambda _eid: SimpleNamespace(state="on"))


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.queue = []
        self.pending = {}
        self.running = None
        self.queue_metadata = {}
        self.mode_tracker = None
        self.entry = SimpleNamespace(entry_id="1")
        self.last_checked_entity_id = None

    def extract_expected_entities(self, _service, _params):
        return {"sensor.x": "on"}

    def _extract_api_info(self, *_args, **_kwargs):
        return {}

    def _log_security_event(self, *_args, **_kwargs):
        return None

    async def _log_event(self, *_args, **_kwargs):
        return None

    async def _log_telemetry(self, *_args, **_kwargs):
        return None

    def _normalize_value(self, val):
        return val


@pytest.mark.asyncio
async def test_intercept_service_skips_when_no_expected(monkeypatch):
    shield = DummyShield()
    monkeypatch.setattr(shield, "extract_expected_entities", lambda *_a, **_k: {})
    called = {"events": 0}

    async def _log(*_a, **_k):
        called["events"] += 1

    monkeypatch.setattr(shield, "_log_event", _log)
    await module.intercept_service_call(
        shield, "oig_cloud", "set_box_mode", {"params": {}}, None, False, None
    )
    assert called["events"] == 1


@pytest.mark.asyncio
async def test_intercept_service_duplicate_in_queue(monkeypatch):
    shield = DummyShield()
    shield.queue.append(("svc", {"a": 1}, {"sensor.x": "on"}, None, "", "", False, None))

    await module.intercept_service_call(
        shield, "svc", "", {"params": {"a": 1}}, None, False, None
    )
    assert len(shield.queue) == 1


@pytest.mark.asyncio
async def test_intercept_service_all_ok_skips(monkeypatch):
    shield = DummyShield()
    await module.intercept_service_call(
        shield, "svc", "", {"params": {}}, None, False, None
    )
    assert shield.running is None
