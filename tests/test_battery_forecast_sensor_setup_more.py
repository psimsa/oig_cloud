from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.sensors import sensor_setup


class DummySensor:
    _GLOBAL_LOG_LAST_TS = {}


class DummyCoordinator:
    def __init__(self, hass=None):
        self.hass = hass


class DummyEntry:
    def __init__(self):
        self.options = {}
        self.data = {}


def test_initialize_sensor_without_hass(monkeypatch):
    sensor = DummySensor()
    coordinator = DummyCoordinator(None)
    entry = DummyEntry()

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.sensor_setup.resolve_box_id",
        lambda _coord: "unknown",
        raising=False,
    )

    sensor_setup.initialize_sensor(
        sensor,
        coordinator,
        "battery_load_median",
        entry,
        {},
        None,
        side_effects_enabled=True,
        auto_switch_startup_delay=timedelta(seconds=1),
    )

    assert sensor._plans_store is None
    assert sensor._precomputed_store is None


def test_initialize_sensor_resolve_box_id_exception(monkeypatch):
    sensor = DummySensor()
    coordinator = DummyCoordinator(
        SimpleNamespace(
            data={},
            config=SimpleNamespace(path=lambda *_a: "/tmp", config_dir="/tmp"),
        )
    )
    entry = DummyEntry()

    def _boom(_coord):
        raise RuntimeError("fail")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        _boom,
        raising=False,
    )

    sensor_setup.initialize_sensor(
        sensor,
        coordinator,
        "battery_load_median",
        entry,
        {},
        coordinator.hass,
        side_effects_enabled=False,
        auto_switch_startup_delay=timedelta(seconds=1),
    )

    assert sensor._box_id == "unknown"
