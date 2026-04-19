"""Tests for box_mode_extended computed sensor."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


class DummyCoordinator:
    def __init__(self):
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


def _make_sensor():
    coordinator = DummyCoordinator()
    return OigCloudComputedSensor(coordinator, "box_mode_extended")


def test_sensor_config_in_sensor_types():
    from custom_components.oig_cloud.sensors.SENSOR_TYPES_MISC import SENSOR_TYPES_MISC

    assert "box_mode_extended" in SENSOR_TYPES_MISC
    cfg = SENSOR_TYPES_MISC["box_mode_extended"]
    assert cfg["sensor_type_category"] == "computed"
    assert cfg["device_mapping"] == "main"
    assert cfg["local_entity_suffix"] == "tbl_box_mode_extended"


def test_unknown_when_raw_sensor_unavailable():
    sensor = _make_sensor()
    sensor.hass = DummyHass({})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"
    assert sensor._attr_extra_state_attributes["raw_app"] is None
    assert sensor._attr_extra_state_attributes["home_grid_v"] is False
    assert sensor._attr_extra_state_attributes["home_grid_vi"] is False
    assert sensor._attr_extra_state_attributes["flexibilita"] is False


def test_unknown_when_raw_sensor_unknown_string():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("unavailable")})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"


def test_unknown_when_raw_sensor_empty():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("")})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"


def test_raw_0_returns_none():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("0")})

    result = sensor._state_box_mode_extended()
    assert result == "none"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 0
    assert attrs["home_grid_v"] is False
    assert attrs["home_grid_vi"] is False
    assert attrs["flexibilita"] is False


def test_raw_1_returns_home_5():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("1")})

    result = sensor._state_box_mode_extended()
    assert result == "home_5"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 1
    assert attrs["home_grid_v"] is True
    assert attrs["home_grid_vi"] is False
    assert attrs["flexibilita"] is False


def test_raw_2_returns_home_6():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("2")})

    result = sensor._state_box_mode_extended()
    assert result == "home_6"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 2
    assert attrs["home_grid_v"] is False
    assert attrs["home_grid_vi"] is True
    assert attrs["flexibilita"] is False


def test_raw_3_returns_home_5_home_6():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("3")})

    result = sensor._state_box_mode_extended()
    assert result == "home_5_home_6"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 3
    assert attrs["home_grid_v"] is True
    assert attrs["home_grid_vi"] is True
    assert attrs["flexibilita"] is False


def test_raw_4_returns_flexibility():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("4")})

    result = sensor._state_box_mode_extended()
    assert result == "flexibility"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 4
    assert attrs["home_grid_v"] is False
    assert attrs["home_grid_vi"] is False
    assert attrs["flexibilita"] is True


def test_raw_5_returns_unknown():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("5")})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"


def test_raw_negative_returns_unknown():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("-1")})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"


def test_raw_999_returns_unknown():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("999")})

    result = sensor._state_box_mode_extended()
    assert result == "unknown"


def test_float_raw_value_is_converted():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_1234567890_box_prm2_app": DummyState("2.0")})

    result = sensor._state_box_mode_extended()
    assert result == "home_6"
    attrs = sensor._attr_extra_state_attributes
    assert attrs["raw_app"] == 2