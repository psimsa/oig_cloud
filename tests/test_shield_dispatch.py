from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as dispatch_module


class DummyState:
    def __init__(self, state):
        self.state = state


class DummyStates:
    def __init__(self, states=None):
        self._states = states or {}

    def get(self, entity_id):
        value = self._states.get(entity_id)
        return DummyState(value) if value is not None else None

    def async_entity_ids(self):
        return list(self._states.keys())


class DummyBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event, data):
        self.fired.append((event, data))


class DummyServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, service_data=None, blocking=False, context=None):
        self.calls.append((domain, service, service_data, blocking))


class DummyHass:
    def __init__(self, states=None):
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
        self.last_checked_entity_id = None
        self.mode_tracker = None
        self._logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)
        self.entry = SimpleNamespace(entry_id="entry", data={}, options={})
        self._security_events = []
        self._events = []
        self._telemetry = []
        self.expected_entities = {}

    def extract_expected_entities(self, _service_name, params):
        return self.expected_entities

    def _extract_api_info(self, _service_name, _params):
        return {"api": True}

    def _log_security_event(self, event_type, details):
        self._security_events.append((event_type, details))

    async def _log_event(self, event_type, service, data, reason=None, context=None):
        self._events.append((event_type, service, data, reason))

    async def _log_telemetry(self, event_type, service, data):
        self._telemetry.append((event_type, service, data))

    def _normalize_value(self, val):
        return str(val) if val is not None else ""

    def _notify_state_change(self):
        self.notified = True

    def _setup_state_listener(self):
        self.listener_set = True

    def _check_entity_state_change(self, _entity_id, _expected):
        return True


@pytest.mark.asyncio
async def test_intercept_splits_grid_delivery():
    hass = DummyHass()
    shield = DummyShield(hass)
    calls = []

    def _extract(service, params):
        calls.append(params)
        return {}

    shield.extract_expected_entities = lambda service, params: _extract(service, params)

    await dispatch_module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_grid_delivery",
        {"params": {"mode": "on", "limit": 1}},
        original_call=None,
        blocking=False,
        context=None,
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_intercept_skips_when_no_expected():
    hass = DummyHass()
    shield = DummyShield(hass)
    shield.expected_entities = {}

    await dispatch_module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {}},
        original_call=None,
        blocking=False,
        context=None,
    )

    assert shield._events
    assert shield._events[-1][0] == "skipped"


@pytest.mark.asyncio
async def test_intercept_dedup_queue():
    hass = DummyHass()
    shield = DummyShield(hass)
    shield.queue.append(("oig_cloud.set_box_mode", {"a": 1}, {"sensor.a": "on"}, None, "oig_cloud", "set_box_mode", False, None))
    shield.expected_entities = {"sensor.a": "on"}

    await dispatch_module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"a": 1}},
        original_call=None,
        blocking=False,
        context=None,
    )

    assert shield._events
    assert shield._events[-1][0] == "ignored"


@pytest.mark.asyncio
async def test_intercept_already_matching_entities():
    hass = DummyHass(states={"sensor.a": "on"})
    shield = DummyShield(hass)
    shield.expected_entities = {"sensor.a": "on"}

    await dispatch_module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "on"}},
        original_call=None,
        blocking=False,
        context=None,
    )

    assert shield._telemetry
    assert shield._events[-1][0] == "skipped"


@pytest.mark.asyncio
async def test_intercept_queue_when_running():
    hass = DummyHass(states={"sensor.a": "off"})
    shield = DummyShield(hass)
    shield.running = "oig_cloud.set_box_mode"
    shield.expected_entities = {"sensor.a": "on"}

    await dispatch_module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"value": "on"}},
        original_call=None,
        blocking=False,
        context=None,
    )

    assert shield.queue
    assert shield._events[-1][0] == "queued"


@pytest.mark.asyncio
async def test_start_call_records_pending():
    hass = DummyHass(states={"sensor.a": "off"})
    shield = DummyShield(hass)

    async def _original_call(domain, service, service_data=None, blocking=False, context=None):
        hass.services.calls.append((domain, service, service_data))

    async def _refresh():
        return None

    hass.data["oig_cloud"] = {"entry": {"coordinator": SimpleNamespace(async_request_refresh=_refresh)}}

    await dispatch_module.start_call(
        shield,
        "oig_cloud.set_grid_delivery",
        {"expected": {"sensor.a": "on"}},
        {"sensor.a": "on"},
        _original_call,
        "oig_cloud",
        "set_grid_delivery",
        False,
        None,
    )

    assert shield.pending
    assert shield.running == "oig_cloud.set_grid_delivery"
    assert hass.bus.fired
    assert hass.services.calls


@pytest.mark.asyncio
async def test_safe_call_service_boiler_mode():
    hass = DummyHass(states={"sensor.boiler_manual_mode": "1"})
    shield = DummyShield(hass)

    ok = await dispatch_module.safe_call_service(
        shield,
        "set_boiler_mode",
        {"entity_id": "sensor.boiler_manual_mode", "mode": "Manual"},
    )

    assert ok is True
