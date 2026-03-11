from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, data):
        self._data = data

    def get(self, entity_id):
        return self._data.get(entity_id)

    def async_all(self):
        return [SimpleNamespace(entity_id=eid) for eid in self._data.keys()]


class DummyCoordinator:
    def __init__(self, hass, data=None):
        self.hass = hass
        self.data = data or {}
        self.forced_box_id = "123"

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyNotification:
    def __init__(self):
        self.id = "n1"
        self.type = "error"
        self.timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.device_id = "dev"
        self.severity = "high"
        self.read = False


class DummyNotificationManager:
    def __init__(self):
        self._notifications = [DummyNotification()]

    def get_latest_notification_message(self):
        return "hello"

    def get_latest_notification(self):
        return self._notifications[0]

    def get_bypass_status(self):
        return "ok"

    def get_notification_count(self, _kind):
        return 2

    def get_unread_count(self):
        return 1


def _make_sensor(monkeypatch, sensor_type, sensor_config, data=None, states=None):
    states = states or {}
    hass = SimpleNamespace(states=DummyStates(states))
    coordinator = DummyCoordinator(hass, data=data)

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {sensor_type: sensor_config},
    )

    sensor = OigCloudDataSensor(coordinator, sensor_type)
    sensor.hass = hass
    return sensor, coordinator


def test_notification_state_and_attributes(monkeypatch):
    sensor, coordinator = _make_sensor(
        monkeypatch,
        "latest_notification",
        {"name_cs": "Notifikace"},
    )
    coordinator.notification_manager = DummyNotificationManager()

    assert sensor.state == "hello"
    attrs = sensor.extra_state_attributes
    assert attrs["notification_id"] == "n1"
    assert attrs["notification_type"] == "error"


def test_extended_values_and_fve_current(monkeypatch):
    data = {
        "extended_batt": {"items": [{"values": [51.2, 10.0, 80.0, 25.0]}]},
        "extended_fve": {"items": [{"values": [100.0, 120.0, 0.0, 500.0, 600.0]}]},
    }
    sensor, _ = _make_sensor(
        monkeypatch,
        "extended_battery_voltage",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor.state == 51.2

    sensor_current, _ = _make_sensor(
        monkeypatch,
        "extended_fve_current_1",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor_current.state == 5.0


def test_grid_mode_king_and_queen(monkeypatch):
    data = {
        "123": {
            "box_prms": {"crct": 1},
            "invertor_prm1": {"p_max_feed_grid": 20000},
            "invertor_prms": {"to_grid": 1},
        }
    }
    sensor, _ = _make_sensor(
        monkeypatch,
        "invertor_prms_to_grid",
        {"node_id": "invertor_prms", "node_key": "to_grid"},
        data=data,
    )
    assert sensor.state == "Zapnuto"

    data["123"]["queen"] = True
    data["123"]["invertor_prm1"]["p_max_feed_grid"] = 0
    data["123"]["invertor_prms"]["to_grid"] = 0
    assert sensor.state == "Vypnuto"


def test_local_entity_value_mapping(monkeypatch):
    states = {"sensor.oig_local_123_temp": DummyState("ON")}
    sensor, _ = _make_sensor(
        monkeypatch,
        "local_value_test",
        {
            "local_entity_suffix": "temp",
            "local_entity_domains": ["sensor"],
            "local_value_map": {"on": 1},
        },
        data={},
        states=states,
    )
    assert sensor._get_local_value() == 1


def test_handle_coordinator_update(monkeypatch):
    data = {"123": {"node": {"value": 10}}}
    sensor, _ = _make_sensor(
        monkeypatch,
        "simple_value",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )

    called = {"count": 0}

    def _write_state():
        called["count"] += 1

    sensor.async_write_ha_state = _write_state

    sensor._handle_coordinator_update()

    assert sensor._last_state == 10
    assert called["count"] == 1
