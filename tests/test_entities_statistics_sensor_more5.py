from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.statistics_sensor import OigCloudStatisticsSensor


class DummyCoordinator:
    def __init__(self):
        self.data = {"123": {}}
        self.config_entry = SimpleNamespace(options=SimpleNamespace(enable_statistics=True))

    def async_add_listener(self, *_a, **_k):
        return lambda: None


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


def _install_sensor_types(monkeypatch):
    module = types.ModuleType("custom_components.oig_cloud.sensor_types")
    module.SENSOR_TYPES = {
        "stats_bad": {
            "name": "Stats",
            "unit": "kWh",
            "device_class": "not_real",
            "state_class": "not_real",
            "entity_category": None,
        },
        "battery_load_median": {
            "name": "Median",
            "unit": "W",
        },
    }
    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.sensor_types", module)


def test_init_invalid_device_and_state_class(monkeypatch):
    _install_sensor_types(monkeypatch)
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "stats_bad", device_info={})
    assert sensor._attr_device_class == "not_real"
    assert sensor._attr_state_class == "not_real"


@pytest.mark.asyncio
async def test_async_added_to_hass_time_range(monkeypatch):
    _install_sensor_types(monkeypatch)
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "stats_bad", device_info={})
    sensor._time_range = (6, 8)
    def _create_task(coro):
        coro.close()
        return None

    sensor.hass = SimpleNamespace(async_create_task=_create_task)

    called = {"interval": False, "change": False}

    def _track_interval(_hass, _cb, _delta):
        called["interval"] = True
        return None

    def _track_change(_hass, _cb, **_k):
        called["change"] = True
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.async_track_time_interval",
        _track_interval,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change",
        _track_change,
    )
    async def _load():
        return None

    monkeypatch.setattr(sensor, "_load_statistics_data", _load)

    await sensor.async_added_to_hass()
    assert called["change"] is True


def test_calculate_statistics_value_fallback_to_all_data(monkeypatch):
    _install_sensor_types(monkeypatch)
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "battery_load_median", device_info={})
    now = datetime.now()
    sensor._sampling_minutes = 1
    sensor._sampling_data = [
        (now - timedelta(minutes=10), 1.0),
        (now - timedelta(minutes=5), 3.0),
    ]
    assert sensor._calculate_statistics_value() == 2.0


def test_get_actual_load_value_invalid_state(monkeypatch):
    _install_sensor_types(monkeypatch)
    coordinator = DummyCoordinator()
    sensor = OigCloudStatisticsSensor(coordinator, "battery_load_median", device_info={})
    sensor.hass = SimpleNamespace(states=DummyStates({"sensor.oig_123_actual_aco_p": SimpleNamespace(state="bad")}))
    assert sensor._get_actual_load_value() is None
