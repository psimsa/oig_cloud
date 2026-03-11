from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)

    def async_entity_ids(self):
        return list(self._mapping.keys())


class DummyBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event, data, context=None):
        self.fired.append((event, data, context))


class DummyServices:
    async def async_call(self, *_args, **_kwargs):
        return None


class DummyHass:
    def __init__(self, states):
        self.states = DummyStates(states)
        self.bus = DummyBus()
        self.services = DummyServices()
        self.data = {}


class DummyShield:
    def __init__(self, hass):
        self.hass = hass
        self.queue = []
        self.pending = {}
        self.queue_metadata = {}
        self.running = None
        self.mode_tracker = None
        self.last_checked_entity_id = None
        self.entry = SimpleNamespace(entry_id="entry1")
        self._logger = SimpleNamespace(info=lambda *_a, **_k: None, error=lambda *_a, **_k: None)

    def extract_expected_entities(self, *_args, **_kwargs):
        return {}

    def _extract_api_info(self, *_args, **_kwargs):
        return {}

    def _log_security_event(self, *_args, **_kwargs):
        return None

    async def _log_event(self, *_args, **_kwargs):
        return None

    async def _log_telemetry(self, *_args, **_kwargs):
        return None

    def _normalize_value(self, value):
        return str(value or "").strip().lower()

    def _notify_state_change(self):
        return None

    def _check_entity_state_change(self, *_args, **_kwargs):
        return True

    def _setup_state_listener(self):
        return None


@pytest.mark.asyncio
async def test_intercept_service_call_skips_when_no_expected():
    hass = DummyHass({})
    shield = DummyShield(hass)
    await module.intercept_service_call(
        shield, "oig_cloud", "set_box_mode", {"params": {}}, None, False, None
    )
    assert shield.queue == []


@pytest.mark.asyncio
async def test_intercept_service_call_dedup_queue(monkeypatch):
    hass = DummyHass({"sensor.x": SimpleNamespace(state="off")})
    shield = DummyShield(hass)

    def _expected(*_a, **_k):
        return {"sensor.x": "on"}

    shield.extract_expected_entities = _expected
    shield.queue.append(("oig_cloud.set_box_mode", {"mode": "on"}, {"sensor.x": "on"}, None, None, None, False, None))

    await module.intercept_service_call(
        shield, "oig_cloud", "set_box_mode", {"params": {"mode": "on"}}, None, False, None
    )


@pytest.mark.asyncio
async def test_start_call_records_pending(monkeypatch):
    hass = DummyHass({"sensor.x": SimpleNamespace(state="off")})
    shield = DummyShield(hass)
    hass.data = {"oig_cloud": {"entry1": {"service_shield": shield, "coordinator": None}}}

    async def _orig_call(*_args, **_kwargs):
        return None

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "Home 1"},
        {"sensor.x": "on"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )
    assert module.SERVICE_SET_BOX_MODE in shield.pending


@pytest.mark.asyncio
async def test_log_event_branches():
    hass = DummyHass({"sensor.x": SimpleNamespace(state="1", attributes={"friendly_name": "X"})})
    shield = DummyShield(hass)
    await module.log_event(shield, "completed", "svc", {"entities": {"sensor.x": "2"}}, None, None)
    await module.log_event(shield, "timeout", "svc", {"entities": {"sensor.x": "2"}}, None, None)
    await module.log_event(shield, "queued", "svc", {"entities": {"sensor.x": "2"}}, None, None)
    assert hass.bus.fired
