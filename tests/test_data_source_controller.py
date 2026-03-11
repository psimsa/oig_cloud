from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from homeassistant.util import dt as dt_util

import pytest
from unittest.mock import Mock

from custom_components.oig_cloud.core import data_source as module


class DummyState:
    def __init__(self, entity_id, state, last_updated=None, last_changed=None):
        self.entity_id = entity_id
        self.state = state
        self.last_updated = last_updated
        self.last_changed = last_changed or last_updated
        self.attributes = {}


class DummyStates:
    def __init__(self, states):
        self._states = {s.entity_id: s for s in states}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_all(self, domain):
        prefix = f"{domain}."
        return [s for s in self._states.values() if s.entity_id.startswith(prefix)]


class DummyBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event, data):
        self.fired.append((event, data))

    def async_listen(self, _event, _cb):
        return lambda: None


class DummyHass:
    def __init__(self, states):
        self.states = DummyStates(states)
        self.data = {module.DOMAIN: {}}
        self.bus = DummyBus()

    def async_create_task(self, _coro):
        return None


def _make_entry(mode, box_id="123"):
    return SimpleNamespace(
        entry_id="entry1",
        options={"data_source_mode": mode, "box_id": box_id},
    )


def test_init_data_source_state_local_ok():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
        DummyState("sensor.oig_local_123_ac_out", "1", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    state = module.init_data_source_state(hass, entry)

    assert state.local_available is True
    assert state.effective_mode == module.DATA_SOURCE_LOCAL_ONLY


def test_init_data_source_state_proxy_mismatch():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "999", last_updated=now),
        DummyState("sensor.oig_local_123_ac_out", "1", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")

    state = module.init_data_source_state(hass, entry)

    assert state.local_available is False
    assert state.reason == "proxy_box_id_mismatch"


def test_update_state_cloud_only_forces_cloud():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_CLOUD_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    changed, mode_changed = controller._update_state(force=True)

    assert changed is True
    assert mode_changed is True
    state = module.get_data_source_state(hass, entry.entry_id)
    assert state.effective_mode == module.DATA_SOURCE_CLOUD_ONLY


def test_on_any_state_change_tracks_pending():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)

    assert "sensor.oig_local_123_ac_out" in controller._pending_local_entities
    assert controller._last_local_entity_update is not None


def test_on_any_state_change_ignored_cloud_only():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_CLOUD_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)

    assert not controller._pending_local_entities


def test_on_any_state_change_wrong_entity():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.other_123_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)

    assert not controller._pending_local_entities


def test_schedule_debounced_poke_failure():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]

    class ErrorHass(DummyHass):
        def async_create_task(self, _coro):
            raise RuntimeError("no task")

    hass = ErrorHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._debouncer.async_call = lambda: None

    controller._schedule_debounced_poke()


def test_update_state_proxy_missing():
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    changed, mode_changed = controller._update_state(force=True)

    assert changed is True
    assert mode_changed is True


def test_on_effective_mode_changed_handles_errors():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_CLOUD_ONLY)

    class DummyCoordinator:
        def async_request_refresh(self):
            raise RuntimeError("boom")

    controller = module.DataSourceController(hass, entry, coordinator=DummyCoordinator())
    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_CLOUD_ONLY,
            effective_mode=module.DATA_SOURCE_CLOUD_ONLY,
            local_available=False,
            last_local_data=now,
            reason="local_missing",
        )
    }

    def _raise_fire(_event, _data):
        raise RuntimeError("fail")

    hass.bus.async_fire = _raise_fire
    controller._on_effective_mode_changed()


@pytest.mark.asyncio
async def test_poke_coordinator_handles_error():
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    class DummyCoordinator:
        data = {"k": "v"}

        def async_set_updated_data(self, _data):
            raise RuntimeError("fail")

    controller = module.DataSourceController(hass, entry, coordinator=DummyCoordinator())
    await controller._poke_coordinator()


@pytest.mark.asyncio
async def test_handle_local_event_updates_coordinator():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    class DummyStore:
        def apply_local_events(self, _pending):
            return True

        def get_snapshot(self):
            return SimpleNamespace(payload={"123": {"box_prms": {"mode": 1}}})

    class DummyCoordinator:
        def __init__(self):
            self.updated = None

        def async_set_updated_data(self, data):
            self.updated = data

    controller = module.DataSourceController(
        hass, entry, coordinator=DummyCoordinator(), telemetry_store=DummyStore()
    )
    controller._pending_local_entities = {"sensor.oig_local_123_ac_out"}
    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    controller._update_state = lambda: (False, False)
    await controller._handle_local_event()

    assert controller.coordinator.updated == {"123": {"box_prms": {"mode": 1}}}


@pytest.mark.asyncio
async def test_async_start_fallback_listeners(monkeypatch):
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    class DummyStore:
        def seed_from_existing_local_states(self):
            return True

        def get_snapshot(self):
            return SimpleNamespace(payload={"123": {"box_prms": {"mode": 1}}})

    class DummyCoordinator:
        def __init__(self):
            self.updated = None

        def async_set_updated_data(self, data):
            self.updated = data

    controller = module.DataSourceController(
        hass, entry, coordinator=DummyCoordinator(), telemetry_store=DummyStore()
    )

    monkeypatch.setattr(module, "_async_track_state_change_event", None)
    monkeypatch.setattr(module, "_async_track_time_interval", None)

    await controller.async_start()

    assert controller.coordinator.updated == {"123": {"box_prms": {"mode": 1}}}


def test_init_data_source_state_entry_options_error():
    class BadOptions:
        def get(self, _key, _default=None):
            if _key == "box_id":
                raise RuntimeError("boom")
            return _default

    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]
    hass = DummyHass(states)
    entry = SimpleNamespace(entry_id="entry1", options=BadOptions())

    state = module.init_data_source_state(hass, entry)

    assert state.configured_mode == module.DEFAULT_DATA_SOURCE_MODE


def test_init_data_source_state_local_stale_reason():
    now = dt_util.utcnow()
    old = now - timedelta(minutes=20)
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, old.isoformat(), last_updated=old),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=old),
    ]
    hass = DummyHass(states)
    entry = SimpleNamespace(
        entry_id="entry1",
        options={
            "data_source_mode": module.DATA_SOURCE_LOCAL_ONLY,
            "box_id": "123",
            "local_proxy_stale_minutes": 1,
        },
    )

    state = module.init_data_source_state(hass, entry)

    assert state.reason.startswith("local_stale_")


def test_init_data_source_state_proxy_box_missing():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")

    state = module.init_data_source_state(hass, entry)

    assert state.local_available is False
    assert state.reason == "proxy_box_id_missing"


def test_init_data_source_state_cloud_only_effective():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_CLOUD_ONLY, box_id="123")

    state = module.init_data_source_state(hass, entry)

    assert state.effective_mode == module.DATA_SOURCE_CLOUD_ONLY


@pytest.mark.asyncio
async def test_async_start_seed_error(monkeypatch):
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    class DummyStore:
        def seed_from_existing_local_states(self):
            raise RuntimeError("boom")

    controller = module.DataSourceController(
        hass, entry, coordinator=None, telemetry_store=DummyStore()
    )

    monkeypatch.setattr(module, "_async_track_state_change_event", None)
    monkeypatch.setattr(module, "_async_track_time_interval", None)

    await controller.async_start()


def test_on_any_state_change_state_read_error(monkeypatch):
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    monkeypatch.setattr(
        module,
        "get_data_source_state",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)


def test_on_any_state_change_entity_id_not_str():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)

    event = SimpleNamespace(data={"entity_id": None}, time_fired=now)
    controller._on_any_state_change(event)


def test_on_any_state_change_box_id_mismatch():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="999")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)

    assert not controller._pending_local_entities


def test_on_any_state_change_proxy_box_mismatch():
    now = dt_util.utcnow()
    states = [DummyState(module.PROXY_BOX_ID_ENTITY_ID, "123", last_updated=now)]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id=None)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_999_ac_out"},
        time_fired=now + timedelta(seconds=5),
    )
    controller._on_any_state_change(event)

    assert not controller._pending_local_entities


@pytest.mark.asyncio
async def test_async_start_with_event_helpers(monkeypatch):
    now = dt_util.utcnow()
    states = [DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now)]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    def _track_state(_hass, _entities, _cb):
        return lambda: None

    def _track_time(_hass, _cb, _interval):
        return lambda: None

    monkeypatch.setattr(module, "_async_track_state_change_event", _track_state)
    monkeypatch.setattr(module, "_async_track_time_interval", _track_time)

    controller = module.DataSourceController(hass, entry, coordinator=None)
    await controller.async_start()

    assert controller._unsubs


def test_on_proxy_change_triggers_mode_change():
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._update_state = lambda **_k: (False, True)
    controller._on_effective_mode_changed = Mock()

    controller._on_proxy_change(SimpleNamespace())

    assert controller._on_effective_mode_changed.called


def test_on_periodic_triggers_mode_change():
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._update_state = lambda **_k: (False, True)
    controller._on_effective_mode_changed = Mock()

    controller._on_periodic(None)

    assert controller._on_effective_mode_changed.called


@pytest.mark.asyncio
async def test_async_stop_unsub_errors():
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    def _bad_unsub():
        raise RuntimeError("boom")

    controller._unsubs = [_bad_unsub]

    await controller.async_stop()


def test_init_data_source_state_proxy_entity_dt_error():
    now = dt_util.utcnow()

    class BadState:
        def __init__(self, entity_id, state):
            self.entity_id = entity_id
            self.state = state
            self.last_changed = None
            self.attributes = {}

        @property
        def last_updated(self):
            raise RuntimeError("boom")

    states = [
        BadState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat()),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")

    state = module.init_data_source_state(hass, entry)

    assert state.effective_mode == module.DATA_SOURCE_CLOUD_ONLY


@pytest.mark.asyncio
async def test_async_start_fallback_listener_invokes_proxy_change(monkeypatch):
    now = dt_util.utcnow()
    states = [DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now)]

    class CaptureBus(DummyBus):
        def async_listen(self, _event, cb):
            self._callbacks = getattr(self, "_callbacks", [])
            self._callbacks.append(cb)
            return lambda: None

    hass = DummyHass(states)
    hass.bus = CaptureBus()
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)

    controller = module.DataSourceController(hass, entry, coordinator=None)
    monkeypatch.setattr(module, "_async_track_state_change_event", None)
    monkeypatch.setattr(module, "_async_track_time_interval", None)
    controller._on_proxy_change = Mock()

    await controller.async_start()

    event = SimpleNamespace(data={"entity_id": module.PROXY_LAST_DATA_ENTITY_ID})
    hass.bus._callbacks[0](event)

    assert controller._on_proxy_change.called


def test_on_any_state_change_entity_id_not_str_local():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(data={"entity_id": None}, time_fired=now)
    controller._on_any_state_change(event)


def test_on_any_state_change_wrong_prefix_local():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(data={"entity_id": "sensor.other"}, time_fired=now)
    controller._on_any_state_change(event)


def test_on_any_state_change_expected_box_id_error():
    class BadOptions:
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return default

    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = SimpleNamespace(entry_id="entry1", options=BadOptions())
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now,
    )
    controller._on_any_state_change(event)


def test_on_any_state_change_regex_no_match():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_bad"},
        time_fired=now,
    )
    controller._on_any_state_change(event)


def test_on_any_state_change_coerce_box_id_exception():
    class BadOptions:
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return module.DATA_SOURCE_LOCAL_ONLY if key == "data_source_mode" else default

    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = SimpleNamespace(entry_id="entry1", options=BadOptions())
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired=now,
    )
    controller._on_any_state_change(event)


def test_on_any_state_change_time_fired_error(monkeypatch):
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._schedule_debounced_poke = lambda: None

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    monkeypatch.setattr(module.dt_util, "as_utc", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    event = SimpleNamespace(
        data={"entity_id": "sensor.oig_local_123_ac_out"},
        time_fired="bad",
    )
    controller._on_any_state_change(event)


@pytest.mark.asyncio
async def test_handle_local_event_mode_changed():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._update_state = lambda: (False, True)
    controller._on_effective_mode_changed = Mock()

    hass.data[module.DOMAIN][entry.entry_id] = {
        "data_source_state": module.DataSourceState(
            configured_mode=module.DATA_SOURCE_LOCAL_ONLY,
            effective_mode=module.DATA_SOURCE_LOCAL_ONLY,
            local_available=True,
            last_local_data=now,
            reason="local_ok",
        )
    }

    await controller._handle_local_event()

    assert controller._on_effective_mode_changed.called


@pytest.mark.asyncio
async def test_handle_local_event_exception(monkeypatch):
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    monkeypatch.setattr(
        module,
        "get_data_source_state",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    await controller._handle_local_event()


def test_update_state_proxy_parse_failed():
    states = [DummyState(module.PROXY_LAST_DATA_ENTITY_ID, "bad", last_updated=None)]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    controller._update_state(force=True)


def test_update_state_proxy_entity_dt_exception():
    class BadState:
        def __init__(self, entity_id, state):
            self.entity_id = entity_id
            self.state = state
            self.last_changed = None
            self.attributes = {}

        @property
        def last_updated(self):
            raise RuntimeError("boom")

    now = dt_util.utcnow()
    states = [BadState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat())]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)

    controller._update_state(force=True)


def test_update_state_expected_box_error():
    class BadOptions:
        def get(self, key, default=None):
            if key == "box_id":
                raise RuntimeError("boom")
            return default

    hass = DummyHass([])
    entry = SimpleNamespace(entry_id="entry1", options=BadOptions())
    controller = module.DataSourceController(hass, entry, coordinator=None)

    controller._update_state(force=True)


def test_update_state_local_entities_candidate():
    now = dt_util.utcnow()
    hass = DummyHass([])
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY)
    controller = module.DataSourceController(hass, entry, coordinator=None)
    controller._last_local_entity_update = now

    controller._update_state(force=True)


def test_update_state_local_stale_reason():
    now = dt_util.utcnow()
    old = now - timedelta(minutes=20)
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, old.isoformat(), last_updated=old),
    ]
    hass = DummyHass(states)
    entry = SimpleNamespace(
        entry_id="entry1",
        options={"data_source_mode": module.DATA_SOURCE_LOCAL_ONLY, "local_proxy_stale_minutes": 1},
    )
    controller = module.DataSourceController(hass, entry, coordinator=None)

    controller._update_state(force=True)


def test_update_state_proxy_box_mismatch_reason():
    now = dt_util.utcnow()
    states = [
        DummyState(module.PROXY_LAST_DATA_ENTITY_ID, now.isoformat(), last_updated=now),
        DummyState(module.PROXY_BOX_ID_ENTITY_ID, "999", last_updated=now),
    ]
    hass = DummyHass(states)
    entry = _make_entry(module.DATA_SOURCE_LOCAL_ONLY, box_id="123")
    controller = module.DataSourceController(hass, entry, coordinator=None)

    controller._update_state(force=True)
