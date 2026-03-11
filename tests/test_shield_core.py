from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import core as core_module


class DummyServices:
    def __init__(self):
        self.calls = []
        self.service_calls = []

    def async_register(self, domain, service, handler, schema=None):
        self.calls.append((domain, service))

    async def async_call(self, domain, service, service_data, blocking=False):
        self.service_calls.append((domain, service, service_data, blocking))


class DummyBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data, context=None):
        self.events.append((event, data, context))


class DummyHass:
    def __init__(self):
        self.services = DummyServices()
        self.bus = DummyBus()
        self.created = []
        self.data = {"core.uuid": "uuid"}
        self.states = DummyStatesCollection([])

    def async_create_task(self, coro):
        self.created.append(coro)
        coro.close()
        return object()


class DummyEvent:
    def __init__(self, entity_id, state):
        self.data = {"entity_id": entity_id, "new_state": state}


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyEntityState(DummyState):
    def __init__(self, entity_id, state, attributes=None):
        super().__init__(state, attributes=attributes)
        self.entity_id = entity_id


class DummyStatesCollection:
    def __init__(self, states):
        self._states = {state.entity_id: state for state in states}

    def async_all(self):
        return list(self._states.values())

    def async_entity_ids(self):
        return list(self._states.keys())

    def get(self, entity_id):
        return self._states.get(entity_id)


@pytest.mark.asyncio
async def test_start_resets_and_schedules(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    shield.pending["svc"] = {"entities": {"sensor.x": "on"}}
    shield.queue.append(("svc", {}, {}, lambda: None, "d", "s", False, None))
    shield.queue_metadata[("svc", "d")] = {"trace_id": "t"}
    shield.running = "svc"

    called = {}

    async def _register_services():
        called["registered"] = True

    def _track_time(_hass, callback, interval):
        called["interval"] = interval
        return lambda: None

    monkeypatch.setattr(shield, "register_services", _register_services)
    monkeypatch.setattr(core_module, "async_track_time_interval", _track_time)

    await shield.start()

    assert called["registered"] is True
    assert called["interval"].seconds == core_module.CHECK_INTERVAL_SECONDS
    assert shield.pending == {}
    assert shield.queue == []
    assert shield.queue_metadata == {}
    assert shield.running is None


def test_setup_state_listener_empty_pending(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    calls = []

    def _unsub():
        calls.append("unsub")

    def _track(*_args, **_kwargs):
        calls.append("track")
        return lambda: None

    shield._state_listener_unsub = _unsub
    monkeypatch.setattr(core_module, "async_track_state_change_event", _track)

    shield._setup_state_listener()

    assert calls == ["unsub"]


def test_setup_state_listener_with_pending(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    shield.pending["svc"] = {
        "entities": {"sensor.oig_123_box_prms_mode": "Home 1"},
        "power_monitor": {"entity_id": "sensor.oig_123_power"},
    }

    captured = {}

    def _track(_hass, entity_ids, callback):
        captured["ids"] = entity_ids
        captured["cb"] = callback
        return lambda: None

    monkeypatch.setattr(core_module, "async_track_state_change_event", _track)

    shield._setup_state_listener()

    assert "sensor.oig_123_box_prms_mode" in captured["ids"]
    assert "sensor.oig_123_power" in captured["ids"]
    assert shield._state_listener_unsub is not None


def test_on_entity_state_changed_triggers_check(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    created = []

    def _create_task(coro):
        created.append(coro)
        coro.close()
        return object()

    hass.async_create_task = _create_task

    event = DummyEvent("sensor.oig_123_box_prms_mode", DummyState("Home 2"))
    shield._on_entity_state_changed(event)

    assert created


def test_notify_state_change_handles_callbacks():
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    called = {"sync": 0, "async": 0}

    def _sync_cb():
        called["sync"] += 1
        return None

    async def _async_cb():
        called["async"] += 1

    shield.register_state_change_callback(_sync_cb)
    shield.register_state_change_callback(_async_cb)

    shield._notify_state_change()

    assert called["sync"] == 1
    assert hass.created


def test_wrapper_methods(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    monkeypatch.setattr(core_module.shield_validation, "normalize_value", lambda v: "x")
    monkeypatch.setattr(core_module.shield_validation, "get_entity_state", lambda h, e: "y")
    monkeypatch.setattr(core_module.shield_validation, "extract_api_info", lambda s, p: {"ok": True})

    assert shield._normalize_value("v") == "x"
    assert shield._get_entity_state("sensor.x") == "y"
    assert shield._extract_api_info("svc", {}) == {"ok": True}


def test_setup_telemetry_initializes_handler(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": False}, data={"username": "user"})

    class DummyTelemetry:
        async def send_event(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.setup_simple_telemetry",
        lambda *_a, **_k: DummyTelemetry(),
    )

    shield = core_module.ServiceShield(hass, entry)

    assert shield.telemetry_handler is not None


def _make_shield_with_states(states, options=None):
    hass = DummyHass()
    hass.states = DummyStatesCollection(states)
    entry = SimpleNamespace(
        options={"no_telemetry": True, "box_id": "123", **(options or {})},
        data={},
    )
    return core_module.ServiceShield(hass, entry)


def test_extract_expected_entities_formating_mode_fake_entity():
    shield = _make_shield_with_states([])

    result = shield.extract_expected_entities("oig_cloud.set_formating_mode", {})

    assert len(result) == 1
    entity_id = next(iter(result.keys()))
    assert entity_id.startswith("fake_formating_mode_")


def test_extract_expected_entities_box_mode_mismatch():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 2")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_box_mode", {"mode": "Home 1"}
    )

    assert result == {"sensor.oig_123_box_prms_mode": "Home 1"}
    assert shield.last_checked_entity_id == "sensor.oig_123_box_prms_mode"


def test_extract_expected_entities_boiler_mode_mapping():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_boiler_manual_mode", "CBB")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_boiler_mode", {"mode": "Manual"}
    )

    assert result
    value = result["sensor.oig_123_boiler_manual_mode"]
    assert value.lower().startswith("man")
    assert value != "Manual"


def test_extract_expected_entities_grid_delivery_limit_only():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "5000")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_grid_delivery", {"limit": 5300}
    )

    assert result == {"sensor.oig_123_invertor_prm1_p_max_feed_grid": "5300"}


def test_extract_expected_entities_grid_delivery_mode_only():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_grid_delivery", {"mode": "limited"}
    )

    assert result == {"sensor.oig_123_invertor_prms_to_grid": "Omezeno"}


def test_check_entity_state_change_variants():
    shield = _make_shield_with_states(
        [
            DummyEntityState("sensor.oig_123_boiler_manual_mode", "CBB"),
            DummyEntityState("sensor.oig_123_box_prms_mode", "Home UPS"),
            DummyEntityState("binary_sensor.oig_123_invertor_prms_to_grid", "Zapnuto"),
            DummyEntityState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "5000"),
        ]
    )

    assert shield._check_entity_state_change(
        "sensor.oig_123_boiler_manual_mode", 0
    )
    assert shield._check_entity_state_change("sensor.oig_123_box_prms_mode", 3)
    assert shield._check_entity_state_change(
        "binary_sensor.oig_123_invertor_prms_to_grid", "omezeno"
    )
    assert shield._check_entity_state_change(
        "sensor.oig_123_invertor_prm1_p_max_feed_grid", 5000
    )


@pytest.mark.asyncio
async def test_log_event_uses_main_entity_for_limit():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [
            DummyEntityState(
                "sensor.oig_123_invertor_prms_to_grid",
                "Omezeno",
                attributes={"friendly_name": "Pretoky"},
            ),
            DummyEntityState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "5000"),
        ]
    )
    entry = SimpleNamespace(options={"no_telemetry": True, "box_id": "123"}, data={})
    shield = core_module.ServiceShield(hass, entry)

    await shield._log_event(
        "completed",
        "oig_cloud.set_grid_delivery",
        {
            "params": {"limit": 5300},
            "entities": {"sensor.oig_123_invertor_prm1_p_max_feed_grid": "5300"},
            "original_states": {},
        },
    )

    events = [evt for evt in hass.bus.events if evt[0] == "logbook_entry"]
    assert events
    assert events[-1][1]["entity_id"] == "sensor.oig_123_invertor_prm1_p_max_feed_grid"
    assert "limit nastaven na 5300W" in events[-1][1]["message"]


@pytest.mark.asyncio
async def test_log_telemetry_sends_event():
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    called = {}

    class DummyTelemetry:
        async def send_event(self, event_type, service_name, data):
            called["event_type"] = event_type
            called["service_name"] = service_name

    shield._telemetry_handler = DummyTelemetry()

    await shield._log_telemetry("queued", "svc", {"k": "v"})

    assert called["event_type"] == "queued"
    assert called["service_name"] == "svc"


@pytest.mark.asyncio
async def test_register_services(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    await shield.register_services()

    assert ("oig_cloud", "shield_status") in hass.services.calls
    assert ("oig_cloud", "shield_queue_info") in hass.services.calls
    assert ("oig_cloud", "shield_remove_from_queue") in hass.services.calls


@pytest.mark.asyncio
async def test_handle_remove_from_queue(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    called = {}

    async def _remove(_shield, _call):
        called["ok"] = True

    monkeypatch.setattr(core_module.shield_queue, "handle_remove_from_queue", _remove)

    await shield._handle_remove_from_queue(SimpleNamespace())

    assert called["ok"] is True


def test_shield_status_and_queue_info(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    monkeypatch.setattr(core_module.shield_queue, "get_shield_status", lambda _s: "ok")
    monkeypatch.setattr(core_module.shield_queue, "get_queue_info", lambda _s: {"q": 1})

    assert shield.get_shield_status() == "ok"
    assert shield.get_queue_info()["q"] == 1


@pytest.mark.asyncio
async def test_check_loop_timeout_formating_mode(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    called = {"event": 0, "telemetry": 0}

    async def _log_event(*_a, **_k):
        called["event"] += 1

    async def _log_telemetry(*_a, **_k):
        called["telemetry"] += 1

    shield._log_event = _log_event
    shield._log_telemetry = _log_telemetry

    shield.pending["oig_cloud.set_formating_mode"] = {
        "called_at": datetime.now() - timedelta(minutes=10),
        "params": {},
        "entities": {},
        "original_states": {},
    }

    await shield._check_loop(datetime.now())

    assert called["event"] == 1
    assert called["telemetry"] == 1


@pytest.mark.asyncio
async def test_check_loop_clears_listener_when_idle():
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    cleared = {"done": False}

    def _unsub():
        cleared["done"] = True

    shield._state_listener_unsub = _unsub

    await shield._check_loop(datetime.now())

    assert cleared["done"] is True
    assert shield._is_checking is False


def _make_shield_with_states(states):
    hass = DummyHass()
    hass.states = DummyStatesCollection(states)
    entry = SimpleNamespace(options={"no_telemetry": True, "box_id": "123"}, data={})
    return core_module.ServiceShield(hass, entry)


def test_extract_expected_entities_box_mode_changes():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 1")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_box_mode", {"mode": "Home 2"}
    )

    assert result == {"sensor.oig_123_box_prms_mode": "Home 2"}
    assert shield.last_checked_entity_id == "sensor.oig_123_box_prms_mode"


def test_extract_expected_entities_box_mode_no_change():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 2")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_box_mode", {"mode": "Home 2"}
    )

    assert result == {}


def test_extract_expected_entities_boiler_mode():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_boiler_manual_mode", "CBB")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_boiler_mode", {"mode": "Manual"}
    )

    assert result == {"sensor.oig_123_boiler_manual_mode": "Manuální"}


def test_extract_expected_entities_grid_delivery_limit_only():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "5000")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_grid_delivery", {"limit": 5300}
    )

    assert result == {"sensor.oig_123_invertor_prm1_p_max_feed_grid": "5300"}


def test_extract_expected_entities_grid_delivery_mode_only():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_grid_delivery", {"mode": "S omezením / Limited"}
    )

    assert result == {"sensor.oig_123_invertor_prms_to_grid": "Omezeno"}


def test_extract_expected_entities_grid_delivery_mode_limit_rejected():
    shield = _make_shield_with_states(
        [DummyEntityState("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")]
    )

    result = shield.extract_expected_entities(
        "oig_cloud.set_grid_delivery", {"mode": "Zapnuto / On", "limit": 4500}
    )

    assert result == {}


def test_extract_expected_entities_formating_mode(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.datetime",
        SimpleNamespace(now=lambda: fixed_now),
    )

    shield = _make_shield_with_states([])
    result = shield.extract_expected_entities("oig_cloud.set_formating_mode", {})

    assert len(result) == 1
    key = next(iter(result.keys()))
    assert key.startswith("fake_formating_mode_")


def test_check_entity_state_change_boiler_and_ssr():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [
            DummyEntityState("sensor.oig_123_boiler_manual_mode", "Manuální"),
            DummyEntityState("sensor.oig_123_ssr_mode", "Zapnuto"),
        ]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    assert shield._check_entity_state_change(
        "sensor.oig_123_boiler_manual_mode", 1
    )
    assert shield._check_entity_state_change("sensor.oig_123_ssr_mode", 1)


def test_check_entity_state_change_grid_mode_binary_sensor():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("binary_sensor.oig_123_invertor_prms_to_grid", "on")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    assert shield._check_entity_state_change(
        "binary_sensor.oig_123_invertor_prms_to_grid", "Omezeno"
    )


def test_check_entity_state_change_box_mode_numeric():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 3")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    assert shield._check_entity_state_change("sensor.oig_123_box_prms_mode", 2)


def test_check_entity_state_change_grid_limit_numeric():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_invertor_prm1_p_max_feed_grid", "4500")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    assert shield._check_entity_state_change(
        "sensor.oig_123_invertor_prm1_p_max_feed_grid", 4500
    )


@pytest.mark.asyncio
async def test_check_loop_completes_and_starts_queue(monkeypatch):
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 2")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    events = []

    async def _log_event(event_type, *_args, **_kwargs):
        events.append(event_type)

    async def _log_telemetry(*_args, **_kwargs):
        return None

    started = {}

    async def _start_call(*_args, **_kwargs):
        started["called"] = True

    shield._log_event = _log_event
    shield._log_telemetry = _log_telemetry
    shield._start_call = _start_call
    shield._notify_state_change = lambda: events.append("notified")
    shield._setup_state_listener = lambda: None

    shield.pending["svc"] = {
        "called_at": datetime.now(),
        "params": {},
        "entities": {"sensor.oig_123_box_prms_mode": "Home 2"},
        "original_states": {},
    }
    shield.queue.append(("next", {}, {}, lambda: None, "d", "s", False, None))

    await shield._check_loop(datetime.now())

    assert "completed" in events
    assert "released" in events
    assert "notified" in events
    assert "svc" not in shield.pending
    assert started["called"] is True


@pytest.mark.asyncio
async def test_check_loop_power_monitor_completion(monkeypatch):
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_power", "3000")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    completed = {"done": False}

    async def _log_event(event_type, *_args, **_kwargs):
        if event_type == "completed":
            completed["done"] = True

    shield._log_event = _log_event

    async def _log_telemetry(*_args, **_kwargs):
        return None

    shield._log_telemetry = _log_telemetry
    shield._notify_state_change = lambda: None
    shield._setup_state_listener = lambda: None

    shield.pending["svc"] = {
        "called_at": datetime.now(),
        "params": {},
        "entities": {"sensor.oig_123_box_prms_mode": "Home UPS"},
        "original_states": {},
        "power_monitor": {
            "entity_id": "sensor.oig_123_power",
            "last_power": 0.0,
            "threshold_kw": 2.5,
            "is_going_to_home_ups": True,
        },
    }

    await shield._check_loop(datetime.now())

    assert completed["done"] is True
    assert "svc" not in shield.pending


@pytest.mark.asyncio
async def test_safe_call_service_boiler_mode():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_boiler_manual_mode", "Manuální")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    ok = await shield._safe_call_service(
        "set_boiler_mode", {"mode": "Manual"}
    )

    assert ok is True
    assert hass.services.service_calls


@pytest.mark.asyncio
async def test_safe_call_service_entity_mode():
    hass = DummyHass()
    hass.states = DummyStatesCollection(
        [DummyEntityState("sensor.oig_123_box_prms_mode", "Home 2")]
    )
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    ok = await shield._safe_call_service(
        "set_box_mode",
        {"entity_id": "sensor.oig_123_box_prms_mode", "mode": "Home 2"},
    )

    assert ok is True


@pytest.mark.asyncio
async def test_check_entities_periodically_success(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(options={"no_telemetry": True}, data={})
    shield = core_module.ServiceShield(hass, entry)

    logged = []

    def _log_security_event(event_type, *_args, **_kwargs):
        logged.append(event_type)

    shield._log_security_event = _log_security_event
    shield._get_entity_state = lambda _eid: "on"
    shield._values_match = lambda current, expected: current == expected

    shield._start_monitoring_task("task1", {"sensor.x": "on"}, timeout=5)

    await shield._check_entities_periodically("task1")

    assert "MONITORING_SUCCESS" in logged


def test_mode_transition_tracker_records_transition(monkeypatch):
    class DummyTrackerHass:
        def __init__(self):
            self._listeners = []

        def async_add_executor_job(self, func, *args):
            return func(*args)

    hass = DummyTrackerHass()
    tracker = core_module.ModeTransitionTracker(hass, "123")

    fixed_now = datetime(2025, 1, 1, 12, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.dt_now", lambda: fixed_now
    )

    tracker.track_request("t1", "Home 1", "Home UPS")

    event = SimpleNamespace(
        data={
            "old_state": SimpleNamespace(state="Home 1", last_changed=fixed_now),
            "new_state": SimpleNamespace(state="Home UPS", last_changed=fixed_now),
        }
    )

    tracker._async_mode_changed(event)

    stats = tracker.get_statistics()
    assert "Home 1→Home UPS" in stats


def test_mode_transition_tracker_offset_fallback():
    tracker = core_module.ModeTransitionTracker(SimpleNamespace(), "123")
    assert tracker.get_offset_for_scenario("Home 1", "Home UPS") == 10.0
