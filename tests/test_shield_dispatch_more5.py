from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data, context=None):
        self.events.append((event, data))


class DummyHass:
    def __init__(self):
        self.bus = DummyBus()
        self.states = SimpleNamespace(get=lambda _eid: None)
        self.services = SimpleNamespace(async_call=lambda *_a, **_k: None)
        self.data = {"oig_cloud": {}}


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self.mode_tracker = None
        self.last_checked_entity_id = None
        self.entry = SimpleNamespace(entry_id="entry1")
        self._setup_state_listener = lambda: None
        self.logged = []
        self.telemetry = []

    def extract_expected_entities(self, _service, _params):
        return {}

    def _extract_api_info(self, *_a, **_k):
        return {}

    def _normalize_value(self, val):
        return str(val) if val is not None else ""

    async def _log_event(self, event_type, service, data, reason=None, context=None):
        self.logged.append((event_type, service, data, reason))

    async def _log_telemetry(self, event_type, service, data):
        self.telemetry.append((event_type, service, data))

    def _notify_state_change(self):
        return None

    def _log_security_event(self, *_a, **_k):
        return None


@pytest.mark.asyncio
async def test_intercept_service_call_no_expected():
    shield = DummyShield()
    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "x"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert shield.logged


@pytest.mark.asyncio
async def test_intercept_service_call_duplicate_queue():
    shield = DummyShield()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "1"}
    shield.queue = [
        (
            "oig_cloud.set_box_mode",
            {"value": "x"},
            {"sensor.x": "1"},
            None,
            "",
            "",
            False,
            None,
        )
    ]
    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "x"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert any(evt[0] == "ignored" for evt in shield.logged)


@pytest.mark.asyncio
async def test_intercept_service_call_all_ok():
    shield = DummyShield()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "on"}
    shield.hass.states = SimpleNamespace(get=lambda _eid: SimpleNamespace(state="on"))
    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "on"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert any(evt[0] == "skipped" for evt in shield.logged)


@pytest.mark.asyncio
async def test_intercept_service_call_queues_when_running():
    shield = DummyShield()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "1"}
    shield.running = "oig_cloud.set_box_mode"
    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "1"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert shield.queue
    assert shield.queue_metadata


@pytest.mark.asyncio
async def test_log_event_limit_change_message():
    shield = DummyShield()
    shield.hass.states = SimpleNamespace(
        get=lambda _eid: SimpleNamespace(state="0", attributes={"friendly_name": "Limit"})
    )
    await module.log_event(
        shield,
        "completed",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x_invertor_prm1_p_max_feed_grid": "200"}},
    )
    events = [evt for evt in shield.hass.bus.events if evt[0] == "logbook_entry"]
    assert events
    assert "limit nastaven" in events[-1][1]["message"]
