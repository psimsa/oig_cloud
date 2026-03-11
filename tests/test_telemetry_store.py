from __future__ import annotations

from datetime import datetime, timezone

from custom_components.oig_cloud.core import telemetry_store as store_module


class DummyState:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state
        self.last_updated = datetime.now(timezone.utc)


class DummyStates:
    def __init__(self, states=None):
        self._states = states or {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_all(self, domain):
        prefix = f"{domain}."
        return [
            state
            for entity_id, state in self._states.items()
            if entity_id.startswith(prefix)
        ]


class DummyHass:
    def __init__(self, states):
        self.states = states


class DummyApplier:
    def __init__(self, box_id):
        self.box_id = box_id
        self.applied = []

    def apply_state(self, payload, entity_id, state, last_updated):
        self.applied.append((entity_id, state))
        payload.setdefault(self.box_id, {})
        return True


def test_set_cloud_payload_adds_box_id(monkeypatch):
    monkeypatch.setattr(store_module, "LocalUpdateApplier", DummyApplier)
    hass = DummyHass(DummyStates())
    store = store_module.TelemetryStore(hass, box_id="123")

    store.set_cloud_payload({"foo": 1})

    assert "123" in store._payload
    assert store._updated_at is not None


def test_apply_local_events_updates_payload(monkeypatch):
    monkeypatch.setattr(store_module, "LocalUpdateApplier", DummyApplier)
    states = DummyStates(
        {
            "sensor.oig_local_123_a": DummyState("sensor.oig_local_123_a", "on"),
            "binary_sensor.oig_local_123_b": DummyState(
                "binary_sensor.oig_local_123_b", "off"
            ),
        }
    )
    hass = DummyHass(states)
    store = store_module.TelemetryStore(hass, box_id="123")

    changed = store.apply_local_events(
        ["sensor.oig_local_123_a", "binary_sensor.oig_local_123_b"]
    )

    assert changed is True
    assert store._updated_at is not None


def test_seed_from_existing_local_states(monkeypatch):
    monkeypatch.setattr(store_module, "LocalUpdateApplier", DummyApplier)
    states = DummyStates(
        {
            "sensor.oig_local_123_a": DummyState("sensor.oig_local_123_a", "1"),
            "binary_sensor.oig_local_123_b": DummyState(
                "binary_sensor.oig_local_123_b", "0"
            ),
            "sensor.other": DummyState("sensor.other", "x"),
        }
    )
    hass = DummyHass(states)
    store = store_module.TelemetryStore(hass, box_id="123")

    captured = {}

    def _apply(entity_ids):
        captured["ids"] = list(entity_ids)
        return True

    store.apply_local_events = _apply

    assert store.seed_from_existing_local_states() is True
    assert sorted(captured["ids"]) == [
        "binary_sensor.oig_local_123_b",
        "sensor.oig_local_123_a",
    ]
