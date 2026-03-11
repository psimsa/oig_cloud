from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import (
    GridMode,
    OigCloudDataSensor,
    _LANGS,
)


class DummyCoordinator:
    def __init__(self, data=None):
        self.data = data or {}
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(sensor_type="box_prms_mode", coordinator=None):
    coordinator = coordinator or DummyCoordinator()
    return OigCloudDataSensor(coordinator, sensor_type)


def test_get_mode_name_and_unknown():
    sensor = _make_sensor()
    assert sensor._get_mode_name(0, "cs") == "Home 1"
    assert sensor._get_mode_name(3, "cs") == "Home UPS"
    assert sensor._get_mode_name(99, "cs") == _LANGS["unknown"]["cs"]


def test_grid_mode_king_and_queen():
    sensor = _make_sensor("invertor_prms_to_grid")

    assert sensor._grid_mode_king(1, 0, 0, "cs") == GridMode.OFF
    assert sensor._grid_mode_king(1, 0, 100, "cs") == GridMode.OFF
    assert sensor._grid_mode_king(1, 1, 5000, "cs") == GridMode.LIMITED
    assert sensor._grid_mode_king(1, 1, 10000, "cs") == GridMode.ON

    assert sensor._grid_mode_queen(1, 0, 0, "cs") == GridMode.OFF
    assert sensor._grid_mode_queen(1, 0, 100, "cs") == GridMode.LIMITED
    assert sensor._grid_mode_queen(1, 1, 100, "cs") == GridMode.ON


def test_apply_local_value_map_and_coerce():
    sensor = _make_sensor("boiler_is_use")
    sensor._sensor_config = {"local_value_map": {"1": "Zapnuto"}}

    assert sensor._apply_local_value_map("1", sensor._sensor_config) == "Zapnuto"
    assert sensor._apply_local_value_map("missing", sensor._sensor_config) == "missing"
    assert sensor._coerce_number("123") == 123.0
    assert sensor._coerce_number("bad") == "bad"


def test_state_box_mode():
    coordinator = DummyCoordinator({"123": {}})
    sensor = _make_sensor("box_prms_mode", coordinator)
    sensor.get_node_value = lambda: 3

    assert sensor.state == "Home UPS"


def test_state_grid_mode_missing_data_uses_local(monkeypatch):
    coordinator = DummyCoordinator({"123": {}})
    sensor = _make_sensor("invertor_prms_to_grid", coordinator)
    sensor.get_node_value = lambda: 1

    monkeypatch.setattr(sensor, "_get_local_grid_mode", lambda *_a, **_k: "Omezeno")

    assert sensor.state == "Omezeno"


def test_state_latest_notification_without_manager():
    coordinator = DummyCoordinator({"123": {}})
    sensor = _make_sensor("latest_notification", coordinator)

    assert sensor.state is None


def test_extra_state_attributes_notification_manager():
    coordinator = DummyCoordinator({"123": {}})
    notification = SimpleNamespace(
        id="n1",
        type="info",
        timestamp=SimpleNamespace(isoformat=lambda: "2025-01-01T00:00:00"),
        device_id="123",
        severity="low",
        read=False,
    )

    notification_manager = SimpleNamespace(get_latest_notification=lambda: notification)
    coordinator.notification_manager = notification_manager

    sensor = _make_sensor("latest_notification", coordinator)
    attrs = sensor.extra_state_attributes

    assert attrs["notification_id"] == "n1"
    assert attrs["sensor_category"] == "notification"


def test_get_extended_value_and_compute_current():
    coordinator = DummyCoordinator(
        {
            "extended_fve": {
                "items": [
                    {"values": [50.0, 60.0, 0.0, 100.0, 120.0]},
                ]
            }
        }
    )
    sensor = _make_sensor("extended_fve_current_1", coordinator)

    assert sensor._compute_fve_current("extended_fve_current_1") == 2.0
