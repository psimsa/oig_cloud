from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.sensors import sensor_runtime


class DummyLogger:
    def __init__(self):
        self.calls = []

    def info(self, msg, *args):
        self.calls.append((msg, args))


class DummySensor:
    def __init__(self):
        self._log_last_ts = {}
        self._timeline_data = []
        self._config_entry = None


def test_log_rate_limited_non_callable_logger():
    sensor = DummySensor()
    logger = SimpleNamespace()
    sensor_runtime.log_rate_limited(sensor, logger, "k", "info", "msg")


def test_get_config_options_and_data():
    sensor = DummySensor()
    sensor._config_entry = SimpleNamespace(options={"a": 1}, data={"b": 2})
    assert sensor_runtime.get_config(sensor) == {"a": 1}

    sensor._config_entry = SimpleNamespace(options={}, data={"b": 2})
    assert sensor_runtime.get_config(sensor) == {"b": 2}

    sensor._config_entry = None
    assert sensor_runtime.get_config(sensor) == {}


def test_get_state_uses_capacity_when_soc_missing():
    sensor = DummySensor()
    sensor._timeline_data = [{"battery_soc": None, "battery_capacity_kwh": 2.345}]
    assert sensor_runtime.get_state(sensor) == 2.35

    sensor._timeline_data = None
    assert sensor_runtime.get_state(sensor) == 0


def test_is_available_uses_parent_property(monkeypatch):
    sensor = DummySensor()

    class DummyEntity:
        @property
        def available(self):
            return False

    monkeypatch.setattr(sensor_runtime, "CoordinatorEntity", DummyEntity)
    assert sensor_runtime.is_available(sensor) is False


def test_handle_coordinator_update_calls_parent(monkeypatch):
    sensor = DummySensor()
    called = {}

    class DummyEntity:
        @staticmethod
        def _handle_coordinator_update(_sensor):
            called["ok"] = True

    monkeypatch.setattr(sensor_runtime, "CoordinatorEntity", DummyEntity)
    sensor_runtime.handle_coordinator_update(sensor)
    assert called["ok"] is True


def test_is_available_defaults_true(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = None

    class DummyEntity:
        available = None

    monkeypatch.setattr(sensor_runtime, "CoordinatorEntity", DummyEntity)
    assert sensor_runtime.is_available(sensor) is True


def test_handle_will_remove_calls_helpers(monkeypatch):
    sensor = DummySensor()
    called = {"cancel": False, "stop": False}

    monkeypatch.setattr(
        sensor_runtime.auto_switch_module,
        "cancel_auto_switch_schedule",
        lambda _sensor: called.__setitem__("cancel", True),
    )
    monkeypatch.setattr(
        sensor_runtime.auto_switch_module,
        "stop_auto_switch_watchdog",
        lambda _sensor: called.__setitem__("stop", True),
    )

    sensor_runtime.handle_will_remove(sensor)
    assert called["cancel"] is True
    assert called["stop"] is True
