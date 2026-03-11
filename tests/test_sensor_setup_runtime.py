from __future__ import annotations

from datetime import timedelta

from custom_components.oig_cloud.battery_forecast.sensors import (
    sensor_runtime,
    sensor_setup,
)


class DummyStore:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key


class DummyHass:
    def __init__(self):
        self.config = self

    def path(self, *_args):
        return "/tmp"


class DummyCoordinator:
    def __init__(self, hass):
        self.hass = hass


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options
        self.data = options
        self.entry_id = "entry-id"


class DummySensor:
    _GLOBAL_LOG_LAST_TS = {}


def test_initialize_sensor_sets_defaults(monkeypatch):
    monkeypatch.setattr(sensor_setup, "Store", DummyStore)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "box123",
    )

    sensor = DummySensor()
    coordinator = DummyCoordinator(DummyHass())
    config_entry = DummyConfigEntry({})

    sensor_setup.initialize_sensor(
        sensor,
        coordinator,
        "battery_load_median",
        config_entry,
        {},
        None,
        side_effects_enabled=True,
        auto_switch_startup_delay=timedelta(seconds=5),
    )

    assert sensor._box_id == "box123"
    assert sensor.entity_id == "sensor.oig_box123_battery_load_median"
    assert sensor._plans_store is not None
    assert sensor._precomputed_store is not None
    assert sensor._log_last_ts is sensor._GLOBAL_LOG_LAST_TS
    assert sensor._auto_switch_ready_at is not None


def test_log_rate_limited(monkeypatch):
    sensor = DummySensor()
    calls = []

    class DummyLogger:
        def info(self, msg, *args):
            calls.append((msg, args))

    monkeypatch.setattr(sensor_runtime.time, "time", lambda: 400.0)
    sensor_runtime.log_rate_limited(sensor, DummyLogger(), "key", "info", "one")
    sensor_runtime.log_rate_limited(sensor, DummyLogger(), "key", "info", "two")

    assert len(calls) == 1


def test_get_state_and_availability():
    sensor = DummySensor()
    sensor._timeline_data = [{"battery_soc": 5.4321}]

    assert sensor_runtime.get_state(sensor) == 5.43
    assert sensor_runtime.is_available(sensor) is True

    sensor._timeline_data = [{"battery_capacity_kwh": 2.345}]
    assert sensor_runtime.get_state(sensor) == 2.35
