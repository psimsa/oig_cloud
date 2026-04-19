"""Tests for box_prm2_app raw sensor."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor


class DummyCoordinator:
    def __init__(self, data=None):
        self.data = data or {}
        self.forced_box_id = "1234567890"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyState:
    def __init__(self, state, last_updated=None, last_changed=None):
        self.state = state
        self.last_updated = last_updated
        self.last_changed = last_changed or last_updated


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, mapping):
        self.states = DummyStates(mapping)


def _make_sensor(sensor_type="box_prm2_app", coordinator=None):
    coordinator = coordinator or DummyCoordinator()
    return OigCloudDataSensor(coordinator, sensor_type)


def test_sensor_config_has_correct_definition():
    from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOX import SENSOR_TYPES_BOX

    assert "box_prm2_app" in SENSOR_TYPES_BOX
    cfg = SENSOR_TYPES_BOX["box_prm2_app"]
    assert cfg["node_id"] == "box_prm2"
    assert cfg["node_key"] == "app"
    assert cfg["local_entity_suffix"] == "tbl_box_prm2_app"
    assert cfg["sensor_type_category"] == "data"
    assert cfg["device_mapping"] == "main"


def test_sensor_entity_id_format():
    sensor = _make_sensor()
    assert sensor.entity_id == "sensor.oig_1234567890_box_prm2_app"


def test_sensor_renders_raw_integer_not_label():
    coordinator = DummyCoordinator()
    coordinator.data = {
        "1234567890": {
            "box_prm2": {"app": 3},
        }
    }
    sensor = _make_sensor(coordinator=coordinator)

    class FakeNode:
        def get_value(self):
            return 3

    sensor._node = FakeNode()
    sensor._resolve_box_id = lambda _: "1234567890"

    state = sensor.state
    assert state == 3
    assert isinstance(state, (int, float))


def test_special_state_not_handled_for_box_prm2_app():
    coordinator = DummyCoordinator()
    sensor = _make_sensor(coordinator=coordinator)
    result = sensor._get_special_state(0, {})
    from custom_components.oig_cloud.entities.data_sensor import _STATE_NOT_HANDLED

    assert result is _STATE_NOT_HANDLED


def test_no_label_mapping_in_special_state():
    coordinator = DummyCoordinator()
    coordinator.data = {
        "1234567890": {
            "box_prm2": {"app": 1},
        }
    }
    sensor = _make_sensor(coordinator=coordinator)

    class FakeNode:
        def get_value(self):
            return 1

    sensor._node = FakeNode()
    sensor._resolve_box_id = lambda _: "1234567890"

    state = sensor.state
    assert state == 1