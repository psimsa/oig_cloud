from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyBus:
    def async_fire(self, *_a, **_k):
        return None


class DummyStates:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def get(self, entity_id):
        return self._mapping.get(entity_id)

    def async_entity_ids(self):
        return list(self._mapping.keys())


class DummyHass:
    def __init__(self, states=None):
        self.states = DummyStates(states)
        self.bus = DummyBus()
        self.services = SimpleNamespace(async_call=lambda *_a, **_k: None)
        self.data = {"oig_cloud": {}}


class DummyCoordinator:
    async def async_request_refresh(self):
        return None


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self.mode_tracker = None
        self.entry = SimpleNamespace(entry_id="entry")
        self.last_checked_entity_id = None
        self.logged = []
        self.telemetry = []
        self._logger = SimpleNamespace(info=lambda *_a, **_k: None, error=lambda *_a, **_k: None)

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

    def _setup_state_listener(self):
        return None

    def _check_entity_state_change(self, *_a, **_k):
        return True


class DummyModeTracker:
    def __init__(self):
        self.calls = []

    def track_request(self, trace_id, from_mode, to_mode):
        self.calls.append((trace_id, from_mode, to_mode))


@pytest.mark.asyncio
async def test_intercept_service_call_duplicate_pending():
    shield = DummyShield()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "1"}
    shield.pending = {"oig_cloud.set_box_mode": {"entities": {"sensor.x": "1"}}}
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
async def test_start_call_power_monitor_and_refresh(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass(
        {
            "sensor.oig_123_actual_aci_wtotal": SimpleNamespace(state="100"),
        }
    )
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": object()}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    called = {"count": 0}

    async def _orig_call(*_a, **_k):
        called["count"] += 1

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )
    assert called["count"] == 1
    assert module.SERVICE_SET_BOX_MODE in shield.pending


@pytest.mark.asyncio
async def test_start_call_power_monitor_missing_box_id(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass()
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": object()}

    def _raise(_coord):
        raise RuntimeError("no box")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        _raise,
    )

    async def _orig_call(*_a, **_k):
        return None

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )


@pytest.mark.asyncio
async def test_start_call_power_monitor_missing_entity(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass()
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": object()}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    async def _orig_call(*_a, **_k):
        return None

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )


@pytest.mark.asyncio
async def test_start_call_power_monitor_unavailable_state(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass(
        {
            "sensor.oig_123_actual_aci_wtotal": SimpleNamespace(state="unavailable"),
        }
    )
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": object()}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    async def _orig_call(*_a, **_k):
        return None

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )


@pytest.mark.asyncio
async def test_start_call_power_monitor_invalid_value(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass(
        {
            "sensor.oig_123_actual_aci_wtotal": SimpleNamespace(state="bad"),
        }
    )
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": object()}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    async def _orig_call(*_a, **_k):
        return None

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )


@pytest.mark.asyncio
async def test_intercept_tracks_mode_on_queue(monkeypatch):
    shield = DummyShield()
    shield.mode_tracker = DummyModeTracker()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "1"}
    shield.running = module.SERVICE_SET_BOX_MODE

    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"current_value": "A", "value": "B"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert shield.mode_tracker.calls


@pytest.mark.asyncio
async def test_intercept_tracks_mode_on_start(monkeypatch):
    shield = DummyShield()
    shield.mode_tracker = DummyModeTracker()
    shield.extract_expected_entities = lambda *_a, **_k: {"sensor.x": "1"}

    async def _start(*_a, **_k):
        return None

    monkeypatch.setattr(module, "start_call", _start)

    await module.intercept_service_call(
        shield,
        "oig_cloud",
        "set_box_mode",
        {"params": {"current_value": "A", "value": "B"}},
        lambda *_a, **_k: None,
        False,
        None,
    )
    assert shield.mode_tracker.calls


@pytest.mark.asyncio
async def test_log_event_variants():
    shield = DummyShield()
    shield.hass.states = SimpleNamespace(
        get=lambda _eid: SimpleNamespace(
            state="off",
            attributes={"friendly_name": "Entity"},
        )
    )

    await module.log_event(
        shield,
        "started",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x": "1"}},
    )
    await module.log_event(
        shield,
        "timeout",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x": "1"}},
    )
    await module.log_event(
        shield,
        "released",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x": "1"}},
    )
    await module.log_event(
        shield,
        "cancelled",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x": "1"}},
    )
    await module.log_event(
        shield,
        "unknown",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x": "1"}},
    )


@pytest.mark.asyncio
async def test_log_event_timeout_limit_change():
    shield = DummyShield()
    shield.hass.states = SimpleNamespace(
        get=lambda _eid: SimpleNamespace(
            state="1",
            attributes={"friendly_name": "Limit"},
        )
    )
    await module.log_event(
        shield,
        "timeout",
        "oig_cloud.set_grid_delivery",
        {"entities": {"sensor.x_invertor_prm1_p_max_feed_grid": "2"}},
    )
@pytest.mark.asyncio
async def test_start_call_refresh_warning(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass()
    shield.hass.data["oig_cloud"]["entry"] = {"service_shield": shield, "coordinator": None}

    async def _orig_call(*_a, **_k):
        return None

    await module.start_call(
        shield,
        "oig_cloud.set_grid_delivery",
        {"mode": "on"},
        {"sensor.x": "1"},
        _orig_call,
        "oig_cloud",
        "set_grid_delivery",
        False,
        None,
    )


@pytest.mark.asyncio
async def test_safe_call_service_boiler_and_mode(monkeypatch):
    shield = DummyShield()
    shield.hass = DummyHass(
        {
            "sensor.oig_123_boiler_manual_mode": SimpleNamespace(state="Manuální"),
            "sensor.oig_123_box_prms_mode": SimpleNamespace(state="Home 2"),
        }
    )
    shield.hass.states.async_entity_ids = lambda: [
        "sensor.oig_123_boiler_manual_mode"
    ]
    async def _call(*_a, **_k):
        return None
    shield.hass.services = SimpleNamespace(async_call=_call)

    assert await module.safe_call_service(
        shield,
        "set_boiler_mode",
        {"entity_id": "sensor.oig_123_boiler_manual_mode", "mode": "Manual"},
    )
    assert await module.safe_call_service(
        shield,
        "set_box_mode",
        {"entity_id": "sensor.oig_123_box_prms_mode", "mode": "Home 2"},
    )
