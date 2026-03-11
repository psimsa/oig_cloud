from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import GridMode, OigCloudDataSensor


class DummyState:
    def __init__(self, state):
        self.state = state


class DummyStates:
    def __init__(self, data):
        self._data = data

    def get(self, entity_id):
        return self._data.get(entity_id)


class DummyCoordinator:
    def __init__(self, hass, data=None):
        self.hass = hass
        self.data = data or {}
        self.forced_box_id = "123"

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(monkeypatch, sensor_type, sensor_config, *, data=None, states=None):
    states = states or {}
    hass = SimpleNamespace(states=DummyStates(states))
    coordinator = DummyCoordinator(hass, data=data)

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {sensor_type: sensor_config},
    )

    sensor = OigCloudDataSensor(coordinator, sensor_type)
    sensor.hass = hass
    return sensor


def test_fallback_value_uses_last_state(monkeypatch):
    sensor = _make_sensor(monkeypatch, "simple", {})
    sensor._last_state = 42
    assert sensor._fallback_value() == 42


def test_fallback_value_restored_state(monkeypatch):
    sensor = _make_sensor(monkeypatch, "simple", {})
    sensor._restored_state = 7
    assert sensor._fallback_value() == 7


def test_fallback_value_energy_default(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "energy_sensor",
        {"device_class": "energy"},
    )
    assert sensor._fallback_value() == 0.0


def test_get_local_entity_id_for_config_prefers_existing_state(monkeypatch):
    states = {
        "switch.oig_local_123_temp": DummyState("1"),
    }
    sensor = _make_sensor(
        monkeypatch,
        "local_pref",
        {
            "local_entity_suffix": "temp",
            "local_entity_domains": ["sensor", "switch"],
        },
        states=states,
    )
    assert sensor._get_local_entity_id_for_config(sensor._sensor_config) == (
        "switch.oig_local_123_temp"
    )


def test_get_local_entity_id_for_config_default_domain(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "local_default",
        {"local_entity_suffix": "foo"},
    )
    assert sensor._get_local_entity_id_for_config(sensor._sensor_config) == (
        "sensor.oig_local_123_foo"
    )


def test_apply_local_value_map_and_coerce(monkeypatch):
    sensor = _make_sensor(monkeypatch, "local_map", {})
    assert sensor._apply_local_value_map("ON", {"local_value_map": {"on": 1}}) == 1
    assert sensor._apply_local_value_map("1.5", {}) == 1.5
    assert sensor._apply_local_value_map("2", {}) == 2
    assert sensor._apply_local_value_map("bad", {}) == "bad"


def test_get_extended_value_out_of_range(monkeypatch):
    data = {"extended_batt": {"items": [{"values": [1.0]}]}}
    sensor = _make_sensor(
        monkeypatch,
        "extended_battery_temperature",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor.state is None


def test_compute_fve_current_voltage_zero(monkeypatch):
    data = {"extended_fve": {"items": [{"values": [0.0, 0.0, 0.0, 5.0, 6.0]}]}}
    sensor = _make_sensor(
        monkeypatch,
        "extended_fve_current_1",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor.state == 0.0


def test_local_grid_mode_uses_local_values(monkeypatch):
    states = {
        "sensor.box_prms_crct": DummyState("1"),
        "sensor.invertor_prm1_p_max_feed_grid": DummyState("10000"),
    }
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {
            "invertor_prms_to_grid": {"node_id": "invertor_prms", "node_key": "to_grid"},
            "box_prms_crct": {"local_entity_id": "sensor.box_prms_crct"},
            "invertor_prm1_p_max_feed_grid": {
                "local_entity_id": "sensor.invertor_prm1_p_max_feed_grid"
            },
        },
    )
    hass = SimpleNamespace(states=DummyStates(states))
    coordinator = DummyCoordinator(hass, data={"123": {"invertor_prms": {"to_grid": 1}}})
    sensor = OigCloudDataSensor(coordinator, "invertor_prms_to_grid")
    sensor.hass = hass
    assert sensor._get_local_grid_mode(1, "cs") == GridMode.ON


def test_grid_mode_fallbacks_to_local(monkeypatch):
    states = {
        "sensor.box_prms_crct": DummyState("1"),
        "sensor.invertor_prm1_p_max_feed_grid": DummyState("0"),
    }
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {
            "invertor_prms_to_grid": {"node_id": "invertor_prms", "node_key": "to_grid"},
            "box_prms_crct": {"local_entity_id": "sensor.box_prms_crct"},
            "invertor_prm1_p_max_feed_grid": {
                "local_entity_id": "sensor.invertor_prm1_p_max_feed_grid"
            },
        },
    )
    hass = SimpleNamespace(states=DummyStates(states))
    coordinator = DummyCoordinator(hass, data={"123": {"invertor_prms": {"to_grid": 0}}})
    sensor = OigCloudDataSensor(coordinator, "invertor_prms_to_grid")
    sensor.hass = hass
    assert sensor.state == GridMode.OFF


def test_handle_coordinator_update_no_data(monkeypatch):
    sensor = _make_sensor(monkeypatch, "simple", {}, data=None)
    called = {"count": 0}

    def _write_state():
        called["count"] += 1

    sensor.async_write_ha_state = _write_state
    sensor._handle_coordinator_update()
    assert sensor._attr_available is False
    assert called["count"] == 1


def test_handle_coordinator_update_unchanged(monkeypatch):
    data = {"123": {"node": {"value": 10}}}
    sensor = _make_sensor(
        monkeypatch,
        "simple_value",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    sensor._last_state = 10
    sensor.async_write_ha_state = lambda *_args, **_kwargs: None
    sensor._handle_coordinator_update()


def test_notification_manager_missing(monkeypatch):
    sensor = _make_sensor(monkeypatch, "latest_notification", {})
    assert sensor.state is None
    assert sensor._warned_notification_manager_missing is True


def test_bypass_status_missing_manager(monkeypatch):
    sensor = _make_sensor(monkeypatch, "bypass_status", {})
    assert sensor.state is None


def test_notification_counts_and_attributes(monkeypatch):
    class DummyNotification:
        def __init__(self):
            self.id = "n1"
            self.type = "error"
            self.timestamp = SimpleNamespace(isoformat=lambda: "2025-01-01T00:00:00")
            self.device_id = "dev"
            self.severity = 2
            self.read = False

    class DummyNotificationManager:
        def __init__(self):
            self._notifications = [DummyNotification()]

        def get_latest_notification_message(self):
            return "latest"

        def get_latest_notification(self):
            return self._notifications[0]

        def get_bypass_status(self):
            return "ok"

        def get_notification_count(self, _kind):
            return 3

        def get_unread_count(self):
            return 2

    sensor = _make_sensor(monkeypatch, "notification_count_error", {})
    sensor.coordinator.notification_manager = DummyNotificationManager()
    assert sensor.state == 3
    attrs = sensor.extra_state_attributes
    assert attrs["total_notifications"] == 1

    sensor_warning = _make_sensor(monkeypatch, "notification_count_warning", {})
    sensor_warning.coordinator.notification_manager = DummyNotificationManager()
    assert sensor_warning.state == 3

    sensor_unread = _make_sensor(monkeypatch, "notification_count_unread", {})
    sensor_unread.coordinator.notification_manager = DummyNotificationManager()
    assert sensor_unread.state == 2


def test_latest_notification_attributes(monkeypatch):
    class DummyNotification:
        def __init__(self):
            self.id = "n1"
            self.type = "warning"
            self.timestamp = SimpleNamespace(isoformat=lambda: "2025-01-01T00:00:00")
            self.device_id = "dev"
            self.severity = 1
            self.read = True

    class DummyNotificationManager:
        def __init__(self):
            self._notifications = [DummyNotification()]

        def get_latest_notification_message(self):
            return "latest"

        def get_latest_notification(self):
            return self._notifications[0]

    sensor = _make_sensor(monkeypatch, "latest_notification", {})
    sensor.coordinator.notification_manager = DummyNotificationManager()
    assert sensor.state == "latest"
    attrs = sensor.extra_state_attributes
    assert attrs["notification_type"] == "warning"


def test_bypass_status_attributes(monkeypatch):
    class DummyNotificationManager:
        def get_bypass_status(self):
            return "on"

    sensor = _make_sensor(monkeypatch, "bypass_status", {})
    sensor.coordinator.notification_manager = DummyNotificationManager()
    assert sensor.state == "on"
    attrs = sensor.extra_state_attributes
    assert "last_check" in attrs


def test_special_state_mappings(monkeypatch):
    data = {"123": {"node": {"value": 1}}}
    sensor = _make_sensor(
        monkeypatch,
        "box_prms_mode",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    assert sensor.state == "Home 2"

    sensor_ssr = _make_sensor(
        monkeypatch,
        "ssr_mode",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    assert sensor_ssr.state == "Zapnuto/On"

    sensor_boiler = _make_sensor(
        monkeypatch,
        "boiler_manual_mode",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    assert sensor_boiler.state == "Manuální"

    sensor_onoff = _make_sensor(
        monkeypatch,
        "box_prms_crct",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    assert sensor_onoff.state == "Zapnuto"

    sensor_boiler_use = _make_sensor(
        monkeypatch,
        "boiler_is_use",
        {"node_id": "node", "node_key": "value"},
        data=data,
    )
    assert sensor_boiler_use.state == "Zapnuto"


def test_grid_mode_queen_changing(monkeypatch):
    sensor = _make_sensor(monkeypatch, "invertor_prms_to_grid", {})
    result = sensor._grid_mode_queen(1, 2, 0, "cs")
    assert result == "Probíhá změna"


def test_grid_mode_king_changing(monkeypatch):
    sensor = _make_sensor(monkeypatch, "invertor_prms_to_grid", {})
    result = sensor._grid_mode_king(1, 2, 5000, "cs")
    assert result == "Probíhá změna"


def test_grid_mode_missing_data(monkeypatch):
    sensor = _make_sensor(monkeypatch, "invertor_prms_to_grid", {})
    result = sensor._grid_mode({}, 1, "cs")
    assert result == "Vypnuto"


def test_get_local_value_unknown_state(monkeypatch):
    states = {"sensor.oig_local_123_temp": DummyState("unknown")}
    sensor = _make_sensor(
        monkeypatch,
        "local_unknown",
        {"local_entity_suffix": "temp"},
        states=states,
    )
    assert sensor._get_local_value() is None


def test_get_node_value_missing(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "missing_node",
        {"node_id": "missing", "node_key": "value"},
        data={"123": {}},
    )
    assert sensor.get_node_value() is None


def test_get_extended_value_for_sensor_types(monkeypatch):
    data = {
        "extended_grid": {"items": [{"values": [230.0, 5.0, 1.0, 2.0]}]},
        "extended_load": {"items": [{"values": [1.0, 2.0, 3.0]}]},
    }
    sensor_grid = _make_sensor(
        monkeypatch,
        "extended_grid_power",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor_grid.state == 5.0
    sensor_load = _make_sensor(
        monkeypatch,
        "extended_load_l2_power",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor_load.state == 2.0


def test_compute_fve_current_second_channel(monkeypatch):
    data = {"extended_fve": {"items": [{"values": [10.0, 5.0, 0.0, 0.0, 20.0]}]}}
    sensor = _make_sensor(
        monkeypatch,
        "extended_fve_current_2",
        {"sensor_type_category": "extended"},
        data=data,
    )
    assert sensor.state == 4.0


def test_get_extended_value_handles_missing(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "extended_battery_current",
        {"sensor_type_category": "extended"},
        data={},
    )
    assert sensor.state is None


@pytest.mark.asyncio
async def test_async_added_and_removed(monkeypatch):
    sensor = _make_sensor(monkeypatch, "simple", {})

    class DummyLastState:
        def __init__(self, state):
            self.state = state

    async def _last_state():
        return DummyLastState("12")

    sensor.async_get_last_state = _last_state
    await sensor.async_added_to_hass()
    assert sensor._restored_state == 12

    sensor._local_state_unsub = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    sensor._data_source_unsub = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    await sensor.async_will_remove_from_hass()


def test_state_handles_invalid_grid_value(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "invertor_prms_to_grid",
        {"node_id": "node", "node_key": "value"},
        data={"123": {"node": {"value": {"bad": "type"}}}},
    )
    assert sensor.state is None


def test_state_extended_import_error(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        "extended_battery_voltage",
        {"sensor_type_category": "extended", "node_id": "node", "node_key": "value"},
        data={"123": {"node": {"value": 1}}},
    )
    import builtins

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name.endswith("sensor_types"):
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    assert sensor.state == 1


def test_resolve_box_id_fallback(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    hass = SimpleNamespace(states=DummyStates({}))
    coordinator = DummyCoordinator(hass, data={})
    sensor = OigCloudDataSensor(coordinator, "simple")
    assert sensor.entity_id.startswith("sensor.oig_unknown_")
