"""Tests for base_sensor and oig_cloud_sensor coverage."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.oig_cloud.coordinator import OigCloudDataUpdateCoordinator
from custom_components.oig_cloud.entities.base_sensor import (
    SHIELD_SENSOR_TYPES,
    _as_numeric_string,
    _get_sensor_definition,
    resolve_box_id,
)
from custom_components.oig_cloud.oig_cloud_sensor import OigCloudSensor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyCoordinator(OigCloudDataUpdateCoordinator):
    def __init__(
        self,
        box_id: str = "1234567890",
        data: dict[str, Any] | None = None,
        forced_box_id: Any = None,
        config_entry: Any = None,
        last_update_success: bool = True,
    ):
        self.forced_box_id = forced_box_id
        self.data = data or {box_id: {"some": "data", "queen": False}}
        self.config_entry = config_entry
        self.last_update_success = last_update_success

    def async_add_listener(self, *_args: Any, **_kwargs: Any) -> Any:
        return lambda: None


def _make_oig_sensor(sensor_type: str, **kwargs):
    coordinator = DummyCoordinator(**kwargs)
    return OigCloudSensor(coordinator, sensor_type)


# ---------------------------------------------------------------------------
# base_sensor: _get_sensor_definition
# ---------------------------------------------------------------------------


def test_get_sensor_definition_known():
    assert _get_sensor_definition("service_shield_status") == SHIELD_SENSOR_TYPES[
        "service_shield_status"
    ]


def test_get_sensor_definition_unknown():
    assert _get_sensor_definition("nonexistent") == {}


# ---------------------------------------------------------------------------
# base_sensor: _as_numeric_string
# ---------------------------------------------------------------------------


def test_as_numeric_string_int():
    assert _as_numeric_string(42) == "42"


def test_as_numeric_string_float():
    assert _as_numeric_string(42.7) == "42"


def test_as_numeric_string_str_digit():
    assert _as_numeric_string("123") == "123"


def test_as_numeric_string_str_non_digit():
    assert _as_numeric_string("abc") is None


def test_as_numeric_string_bool():
    assert _as_numeric_string(True) is None
    assert _as_numeric_string(False) is None


def test_as_numeric_string_none():
    assert _as_numeric_string(None) is None


# ---------------------------------------------------------------------------
# base_sensor: resolve_box_id
# ---------------------------------------------------------------------------


def test_resolve_box_id_forced():
    coordinator = DummyCoordinator(forced_box_id="999")
    assert resolve_box_id(coordinator) == "999"


def test_resolve_box_id_forced_non_numeric():
    coordinator = DummyCoordinator(forced_box_id="abc")
    # _as_numeric_string returns None for non-digit strings
    assert resolve_box_id(coordinator) == "1234567890"


def test_resolve_box_id_from_entry_options():
    entry = SimpleNamespace(options={"box_id": "555"}, data={})
    coordinator = DummyCoordinator(config_entry=entry, forced_box_id=None)
    assert resolve_box_id(coordinator) == "555"


def test_resolve_box_id_from_entry_data():
    entry = SimpleNamespace(options=None, data={"inverter_sn": "777"})
    coordinator = DummyCoordinator(config_entry=entry, forced_box_id=None)
    assert resolve_box_id(coordinator) == "777"


def test_resolve_box_id_from_data_keys():
    coordinator = DummyCoordinator(
        data={"888": {"x": 1}}, forced_box_id=None, config_entry=None
    )
    assert resolve_box_id(coordinator) == "888"


def test_resolve_box_id_unknown():
    coordinator = DummyCoordinator(
        data={}, forced_box_id=None, config_entry=None
    )
    coordinator.data = {}
    assert resolve_box_id(coordinator) == "unknown"


def test_resolve_box_id_entry_options_non_numeric():
    entry = SimpleNamespace(options={"box_id": "abc"}, data={})
    coordinator = DummyCoordinator(config_entry=entry, forced_box_id=None)
    assert resolve_box_id(coordinator) == "1234567890"


# ---------------------------------------------------------------------------
# oig_cloud_sensor: __init__
# ---------------------------------------------------------------------------


def test_oig_sensor_init():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor._sensor_type == "actual_aci_wr"
    assert sensor._box_id == "1234567890"
    assert sensor.entity_id == "sensor.oig_1234567890_actual_aci_wr"


def test_oig_sensor_init_non_string_type_raises():
    coordinator = DummyCoordinator()
    with pytest.raises(TypeError, match="sensor_type must be a string"):
        OigCloudSensor(coordinator, 123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# oig_cloud_sensor: available
# ---------------------------------------------------------------------------


def test_oig_sensor_available_no_data():
    sensor = _make_oig_sensor("actual_aci_wr", data={}, last_update_success=False)
    assert sensor.available is False


def test_oig_sensor_available_last_update_failed():
    sensor = _make_oig_sensor("actual_aci_wr", last_update_success=False)
    assert sensor.available is False


def test_oig_sensor_available_node_missing():
    sensor = _make_oig_sensor("actual_aci_wr", data={"1234567890": {}})
    assert sensor.available is False


def test_oig_sensor_available_node_present():
    sensor = _make_oig_sensor(
        "actual_aci_wr", data={"1234567890": {"actual": {"aci_wr": 100}}}
    )
    assert sensor.available is True


def test_oig_sensor_available_no_node_id():
    # sensor_type without node_id should be available if coordinator has data
    sensor = _make_oig_sensor("actual_aci_wtotal")
    assert sensor.available is True


# ---------------------------------------------------------------------------
# oig_cloud_sensor: entity_category
# ---------------------------------------------------------------------------


def test_oig_sensor_entity_category():
    sensor = _make_oig_sensor("device_lastcall")
    from homeassistant.const import EntityCategory
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC


def test_oig_sensor_entity_category_none():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.entity_category is None


# ---------------------------------------------------------------------------
# oig_cloud_sensor: unit_of_measurement
# ---------------------------------------------------------------------------


def test_oig_sensor_unit_of_measurement():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.unit_of_measurement == "W"


def test_oig_sensor_unit_of_measurement_none():
    sensor = _make_oig_sensor("device_lastcall")
    assert sensor.unit_of_measurement is None


# ---------------------------------------------------------------------------
# oig_cloud_sensor: unique_id
# ---------------------------------------------------------------------------


def test_oig_sensor_unique_id():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.unique_id == "oig_cloud_1234567890_actual_aci_wr"


# ---------------------------------------------------------------------------
# oig_cloud_sensor: device_info
# ---------------------------------------------------------------------------


def test_oig_sensor_device_info_home():
    sensor = _make_oig_sensor("actual_aci_wr")
    info = sensor.device_info
    assert info.get("name") == "ČEZ Battery Box Home 1234567890"
    assert info.get("manufacturer") == "OIG"
    assert info.get("model") == "ČEZ Battery Box Home"


def test_oig_sensor_device_info_queen():
    sensor = _make_oig_sensor(
        "actual_aci_wr", data={"1234567890": {"queen": True}}
    )
    info = sensor.device_info
    assert info.get("name") == "ČEZ Battery Box Queen 1234567890"
    assert info.get("model") == "ČEZ Battery Box Queen"


def test_oig_sensor_device_info_sw_version():
    sensor = _make_oig_sensor(
        "actual_aci_wr",
        data={"1234567890": {"box_prms": {"sw": "1.2.3"}}},
    )
    info = sensor.device_info
    assert info.get("sw_version") == "1.2.3"


# ---------------------------------------------------------------------------
# oig_cloud_sensor: _resolve_box_id
# ---------------------------------------------------------------------------


def test_oig_sensor_resolve_box_id_forced():
    sensor = _make_oig_sensor("actual_aci_wr", forced_box_id="999")
    assert sensor._resolve_box_id() == "999"


def test_oig_sensor_resolve_box_id_from_data():
    sensor = _make_oig_sensor("actual_aci_wr", data={"888": {}})
    assert sensor._resolve_box_id() == "888"


def test_oig_sensor_resolve_box_id_unknown():
    sensor = _make_oig_sensor("actual_aci_wr")
    sensor.coordinator.data = {}
    assert sensor._resolve_box_id() == "unknown"


# ---------------------------------------------------------------------------
# oig_cloud_sensor: extra_state_attributes
# ---------------------------------------------------------------------------


def test_oig_sensor_extra_state_attributes():
    sensor = _make_oig_sensor("actual_aci_wr")
    sensor._attr_extra_state_attributes = {"foo": "bar"}
    assert sensor.extra_state_attributes == {"foo": "bar"}


def test_oig_sensor_extra_state_attributes_none():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.extra_state_attributes is None


# ---------------------------------------------------------------------------
# oig_cloud_sensor: options
# ---------------------------------------------------------------------------


def test_oig_sensor_options():
    sensor = _make_oig_sensor("invertor_prms_to_grid")
    opts = sensor.options
    assert isinstance(opts, list)
    assert "Vypnuto / Off" in opts


def test_oig_sensor_options_none():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.options is None


# ---------------------------------------------------------------------------
# oig_cloud_sensor: name
# ---------------------------------------------------------------------------


def test_oig_sensor_name_cs():
    sensor = _make_oig_sensor("actual_aci_wr")
    sensor.hass = MagicMock()
    sensor.hass.config.language = "cs"
    assert sensor.name == "Síť - zátěž fáze 1 (live)"


def test_oig_sensor_name_en():
    sensor = _make_oig_sensor("actual_aci_wr")
    sensor.hass = MagicMock()
    sensor.hass.config.language = "en"
    assert sensor.name == "Grid Load Line 1 (live)"


# ---------------------------------------------------------------------------
# oig_cloud_sensor: device_class / state_class
# ---------------------------------------------------------------------------


def test_oig_sensor_device_class():
    sensor = _make_oig_sensor("actual_aci_wr")
    from homeassistant.components.sensor.const import SensorDeviceClass
    assert sensor.device_class == SensorDeviceClass.POWER


def test_oig_sensor_state_class():
    sensor = _make_oig_sensor("actual_aci_wr")
    from homeassistant.components.sensor.const import SensorStateClass
    assert sensor.state_class == SensorStateClass.MEASUREMENT


# ---------------------------------------------------------------------------
# oig_cloud_sensor: should_poll
# ---------------------------------------------------------------------------


def test_oig_sensor_should_poll():
    sensor = _make_oig_sensor("actual_aci_wr")
    assert sensor.should_poll is False


# ---------------------------------------------------------------------------
# oig_cloud_sensor: get_node_value
# ---------------------------------------------------------------------------


def test_oig_sensor_get_node_value():
    sensor = _make_oig_sensor(
        "actual_aci_wr",
        data={"1234567890": {"actual": {"aci_wr": 150}}},
    )
    assert sensor.get_node_value() == 150


def test_oig_sensor_get_node_value_no_data():
    sensor = _make_oig_sensor("actual_aci_wr", data={})
    assert sensor.get_node_value() is None


def test_oig_sensor_get_node_value_no_node_id():
    sensor = _make_oig_sensor("actual_aci_wtotal")
    assert sensor.get_node_value() is None


def test_oig_sensor_get_node_value_key_error():
    sensor = _make_oig_sensor(
        "actual_aci_wr",
        data={"1234567890": {"actual": {}}},
    )
    assert sensor.get_node_value() is None
