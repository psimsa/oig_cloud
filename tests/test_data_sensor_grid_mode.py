from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor


class DummyCoordinator:
    def __init__(self, data):
        self.data = data
        self.last_update_success = True
        self.hass = SimpleNamespace()

    def async_add_listener(self, _listener):
        return lambda: None


def _build_sensor(data, sensor_type, sensor_config):
    coordinator = DummyCoordinator(data)
    sensor = OigCloudDataSensor(coordinator, sensor_type)
    sensor._sensor_config = sensor_config
    sensor._box_id = next(iter(data.keys()))
    return sensor


def test_grid_mode_limited_king():
    data = {
        "123": {
            "box_prms": {"crcte": 1},
            "invertor_prm1": {"p_max_feed_grid": 5000},
            "invertor_prms": {"to_grid": 1},
        }
    }
    sensor = _build_sensor(
        data,
        "invertor_prms_to_grid",
        {"node_id": "invertor_prms", "node_key": "to_grid"},
    )

    assert sensor.state == "Omezeno"


def test_grid_mode_off_when_disabled():
    data = {
        "123": {
            "box_prms": {"crcte": 0},
            "invertor_prm1": {"p_max_feed_grid": 15000},
            "invertor_prms": {"to_grid": 1},
        }
    }
    sensor = _build_sensor(
        data,
        "invertor_prms_to_grid",
        {"node_id": "invertor_prms", "node_key": "to_grid"},
    )

    assert sensor.state == "Vypnuto"


def test_grid_mode_queen_branch():
    data = {
        "123": {
            "queen": True,
            "box_prms": {"crcte": 1},
            "invertor_prm1": {"p_max_feed_grid": 0},
            "invertor_prms": {"to_grid": 0},
        }
    }
    sensor = _build_sensor(
        data,
        "invertor_prms_to_grid",
        {"node_id": "invertor_prms", "node_key": "to_grid"},
    )

    assert sensor.state == "Vypnuto"

