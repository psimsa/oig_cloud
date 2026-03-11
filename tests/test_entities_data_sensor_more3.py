from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor, _LANGS


class DummyCoordinator:
    def __init__(self, data=None):
        self.data = data or {}
        self.forced_box_id = "123"
        self.hass = None
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyHass:
    def __init__(self):
        self.states = SimpleNamespace(get=lambda _eid: None)


def _make_sensor(sensor_type="invertor_prms_to_grid", coordinator=None):
    coordinator = coordinator or DummyCoordinator()
    sensor = OigCloudDataSensor(coordinator, sensor_type)
    sensor.hass = DummyHass()
    return sensor


def test_fallback_value_prefers_last_state():
    sensor = _make_sensor("box_prms_mode")
    sensor._last_state = "Home 1"
    assert sensor._fallback_value() == "Home 1"


def test_local_entity_id_suffix_and_domains(monkeypatch):
    sensor = _make_sensor("box_prms_mode")
    sensor._box_id = "abc"
    config = {
        "local_entity_suffix": "foo",
        "local_entity_domains": ["sensor", "binary_sensor"],
    }
    entity_id = sensor._get_local_entity_id_for_config(config)
    assert entity_id == "sensor.oig_local_abc_foo"


def test_apply_local_value_map_numeric_conversion():
    sensor = _make_sensor("box_prms_mode")
    config = {"local_value_map": {"on": "1"}}
    assert sensor._apply_local_value_map("on", config) == "1"
    assert sensor._apply_local_value_map("2", {}) == 2


def test_get_local_grid_mode_failure():
    sensor = _make_sensor("invertor_prms_to_grid")
    assert sensor._get_local_grid_mode("bad", "cs") == _LANGS["unknown"]["cs"]


def test_get_node_value_missing_node_key():
    coordinator = DummyCoordinator({"123": {"node": {"val": 1}}})
    sensor = _make_sensor("box_prms_mode", coordinator)
    sensor._sensor_config = {"node_id": "node"}
    assert sensor.get_node_value() is None


def test_init_handles_sensor_types_import_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _raise(name, *args, **kwargs):
        if name.endswith("sensor_types"):
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raise)
    sensor = _make_sensor("box_prms_mode")
    assert sensor._sensor_config == {}


def test_get_extended_value_unknown_mapping(caplog):
    coordinator = DummyCoordinator(
        {
            "extended_grid": {
                "items": [{"values": [1, 2, 3, 4]}],
            }
        }
    )
    sensor = _make_sensor("extended_grid_unknown", coordinator)
    value = sensor._get_extended_value("extended_grid", "extended_grid_unknown")
    assert value is None


def test_get_extended_value_index_out_of_range():
    coordinator = DummyCoordinator(
        {
            "extended_grid": {
                "items": [{"values": [1]}],
            }
        }
    )
    sensor = _make_sensor("extended_grid_voltage", coordinator)
    value = sensor._get_extended_value("extended_grid", "extended_grid_consumption")
    assert value is None


@pytest.mark.asyncio
async def test_async_added_to_hass_restore_exception(monkeypatch):
    sensor = _make_sensor("box_prms_mode")

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "async_get_last_state", _raise)
    await sensor.async_added_to_hass()
    assert sensor._restored_state is None


@pytest.mark.asyncio
async def test_async_will_remove_from_hass_unsub_errors(monkeypatch):
    sensor = _make_sensor("box_prms_mode")

    def _raise():
        raise RuntimeError("boom")

    sensor._local_state_unsub = _raise
    sensor._data_source_unsub = _raise
    await sensor.async_will_remove_from_hass()


def test_device_info_unknown_box():
    sensor = _make_sensor("box_prms_mode")
    sensor._box_id = "unknown"
    assert sensor.device_info is None


def test_available_and_should_poll():
    sensor = _make_sensor("box_prms_mode")
    assert sensor.available is True
    assert sensor.should_poll is False


@pytest.mark.asyncio
async def test_async_update_noop():
    sensor = _make_sensor("box_prms_mode")
    await sensor.async_update()


def test_state_notification_count_manager_missing():
    coordinator = DummyCoordinator({"123": {"node": {"val": 1}}})
    sensor = _make_sensor("notification_count_error", coordinator)
    assert sensor.state is None

    sensor = _make_sensor("notification_count_warning", coordinator)
    assert sensor.state is None

    sensor = _make_sensor("notification_count_unread", coordinator)
    assert sensor.state is None


def test_state_coordinator_missing_data_fallback():
    coordinator = DummyCoordinator(None)
    sensor = _make_sensor("box_prms_mode", coordinator)
    sensor._last_state = "fallback"
    assert sensor.state == "fallback"


def test_state_raw_value_none_fallback():
    coordinator = DummyCoordinator({"123": {"node": {"val": 1}}})
    sensor = _make_sensor("box_prms_mode", coordinator)
    sensor._sensor_config = {"node_id": "node", "node_key": "missing"}
    sensor._restored_state = "restored"
    assert sensor.state == "restored"


def test_state_exception_fallback(monkeypatch):
    coordinator = DummyCoordinator({"123": {"node": {"val": 1}}})
    sensor = _make_sensor("box_prms_mode", coordinator)
    monkeypatch.setattr(sensor, "get_node_value", lambda: 1 / 0)
    assert sensor.state is None


def test_get_extended_value_for_sensor_type_routes():
    coordinator = DummyCoordinator(
        {"extended_fve": {"items": [{"values": [10, 20, 0, 100, 200]}]}}
    )
    sensor = _make_sensor("extended_fve_current_1", coordinator)
    assert sensor._get_extended_value_for_sensor() == 10.0

    sensor = _make_sensor("extended_unknown", coordinator)
    assert sensor._get_extended_value_for_sensor() is None


def test_get_extended_value_missing_data():
    coordinator = DummyCoordinator({})
    sensor = _make_sensor("extended_grid_voltage", coordinator)
    assert sensor._get_extended_value("extended_grid", "extended_grid_voltage") is None

    coordinator = DummyCoordinator({"extended_grid": {"items": []}})
    sensor = _make_sensor("extended_grid_voltage", coordinator)
    assert sensor._get_extended_value("extended_grid", "extended_grid_voltage") is None


def test_get_extended_value_error(monkeypatch):
    coordinator = DummyCoordinator({"extended_grid": {"items": "bad"}})
    sensor = _make_sensor("extended_grid_voltage", coordinator)
    assert sensor._get_extended_value("extended_grid", "extended_grid_voltage") is None


def test_compute_fve_current_variants():
    sensor = _make_sensor("extended_fve_current_1", DummyCoordinator(None))
    assert sensor._compute_fve_current("extended_fve_current_1") is None

    coordinator = DummyCoordinator({"extended_fve": {"items": []}})
    sensor = _make_sensor("extended_fve_current_1", coordinator)
    assert sensor._compute_fve_current("extended_fve_current_1") == 0.0

    coordinator = DummyCoordinator({"extended_fve": {"items": [{"values": [0, 0, 0]}]}})
    sensor = _make_sensor("extended_fve_current_3", coordinator)
    assert sensor._compute_fve_current("extended_fve_current_3") is None

    coordinator = DummyCoordinator(
        {"extended_fve": {"items": [{"values": [0, 0, 0, 100, 0]}]}}
    )
    sensor = _make_sensor("extended_fve_current_1", coordinator)
    assert sensor._compute_fve_current("extended_fve_current_1") == 0.0


def test_compute_fve_current_exception():
    coordinator = DummyCoordinator({"extended_fve": {"items": [{"values": ["bad"]}]}})
    sensor = _make_sensor("extended_fve_current_1", coordinator)
    assert sensor._compute_fve_current("extended_fve_current_1") is None


def test_mode_name_variants():
    sensor = _make_sensor("box_prms_mode")
    assert sensor._get_mode_name(2, "cs") == "Home 3"
    assert sensor._get_mode_name(4, "cs") == "Home 5"
    assert sensor._get_mode_name(5, "cs") == "Home 6"


def test_grid_mode_missing_fields(monkeypatch):
    coordinator = DummyCoordinator({"123": {}})
    sensor = _make_sensor("invertor_prms_to_grid", coordinator)
    monkeypatch.setattr(sensor, "_get_local_grid_mode", lambda *_a, **_k: _LANGS["unknown"]["cs"])
    assert sensor._grid_mode({}, 1, "cs") == _LANGS["unknown"]["cs"]


def test_grid_mode_exception():
    sensor = _make_sensor("invertor_prms_to_grid")
    pv_data = {
        "box_prms": {"crcte": "1"},
        "invertor_prm1": {"p_max_feed_grid": "1000"},
    }
    assert sensor._grid_mode(pv_data, "bad", "cs") == _LANGS["unknown"]["cs"]


def test_on_off_and_mode_names():
    sensor = _make_sensor("box_prms_mode")
    assert sensor._get_ssrmode_name(0, "cs") == "Vypnuto/Off"
    assert sensor._get_ssrmode_name(1, "cs") == "Zapnuto/On"
    assert sensor._get_boiler_mode_name(0, "cs") == "CBB"
    assert sensor._get_boiler_mode_name(1, "cs").startswith("Manu")
    assert sensor._get_on_off_name(0, "cs") == _LANGS["off"]["cs"]
    assert sensor._get_on_off_name(1, "cs") == _LANGS["on"]["cs"]


def test_local_entity_id_for_config_domains():
    sensor = _make_sensor("box_prms_mode")
    sensor._box_id = "123"
    sensor.hass.states.get = lambda _eid: None
    assert (
        sensor._get_local_entity_id_for_config(
            {"local_entity_suffix": "x", "local_entity_domains": "sensor"}
        )
        == "sensor.oig_local_123_x"
    )
    assert (
        sensor._get_local_entity_id_for_config(
            {"local_entity_suffix": "x", "local_entity_domains": []}
        )
        == "sensor.oig_local_123_x"
    )


def test_coerce_number_non_string():
    sensor = _make_sensor("box_prms_mode")
    assert sensor._coerce_number(5) == 5


def test_apply_local_value_map_none():
    sensor = _make_sensor("box_prms_mode")
    assert sensor._apply_local_value_map(None, {}) is None


def test_get_local_value_missing_entity():
    sensor = _make_sensor("box_prms_mode")
    sensor._sensor_config = {}
    assert sensor._get_local_value() is None


def test_get_local_value_for_sensor_type_missing(monkeypatch):
    sensor = _make_sensor("box_prms_mode")

    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "_get_local_entity_id_for_config", lambda _cfg: None)
    assert sensor._get_local_value_for_sensor_type("missing") is None

    monkeypatch.setattr(sensor, "_get_local_entity_id_for_config", _raise)
    assert sensor._get_local_value_for_sensor_type("missing") is None


def test_get_local_value_for_sensor_type_unavailable(monkeypatch):
    sensor = _make_sensor("box_prms_mode")
    sensor.hass.states.get = lambda _eid: SimpleNamespace(state="unknown")
    monkeypatch.setattr(sensor, "_get_local_entity_id_for_config", lambda _cfg: "sensor.oig_local_123_x")
    assert sensor._get_local_value_for_sensor_type("box_prms_mode") is None


def test_get_node_value_missing_data():
    coordinator = DummyCoordinator(None)
    sensor = _make_sensor("box_prms_mode", coordinator)
    assert sensor.get_node_value() is None


def test_get_node_value_exception():
    coordinator = DummyCoordinator({"123": {"node": {"val": 1}}})
    sensor = _make_sensor("box_prms_mode", coordinator)
    sensor._sensor_config = {"node_id": "node", "node_key": []}
    assert sensor.get_node_value() is None
