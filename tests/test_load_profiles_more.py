from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.data import load_profiles


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, mapping):
        self.states = DummyStates(mapping)


class DummySensor:
    def __init__(self, hass):
        self._hass = hass
        self._box_id = "123"


def test_get_load_avg_sensors_no_hass():
    sensor = DummySensor(None)
    assert load_profiles.get_load_avg_sensors(sensor) == {}


def test_get_load_avg_sensors_invalid_state(monkeypatch):
    sensor = DummySensor(DummyHass({}))

    class DummyStats:
        data = {
            "load_avg_x": {"time_range": (0, 24), "day_type": "weekday"},
        }

        @classmethod
        def items(cls):
            return cls.data.items()

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        DummyStats,
        raising=False,
    )
    assert load_profiles.get_load_avg_sensors(sensor) == {}


def test_get_load_avg_sensors_unavailable_and_bad(monkeypatch):
    sensor = DummySensor(
        DummyHass(
            {
                "sensor.oig_123_load_avg_x": SimpleNamespace(state="unavailable"),
                "sensor.oig_123_load_avg_y": SimpleNamespace(state="bad"),
            }
        )
    )

    class DummyStats:
        data = {
            "load_avg_x": {"time_range": (0, 24), "day_type": "weekday"},
            "load_avg_y": {"time_range": (0, 24), "day_type": "weekday"},
        }

        @classmethod
        def items(cls):
            return cls.data.items()

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        DummyStats,
        raising=False,
    )
    assert load_profiles.get_load_avg_sensors(sensor) == {}


def test_get_load_avg_sensors_skips_missing_config(monkeypatch):
    sensor = DummySensor(DummyHass({}))

    class DummyStats:
        data = {
            "load_avg_x": {"day_type": "weekday"},
            "load_avg_y": {"time_range": (0, 24)},
        }

        @classmethod
        def items(cls):
            return cls.data.items()

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        DummyStats,
        raising=False,
    )
    assert load_profiles.get_load_avg_sensors(sensor) == {}


def test_get_load_avg_sensors_valid(monkeypatch):
    sensor = DummySensor(
        DummyHass({"sensor.oig_123_load_avg_x": SimpleNamespace(state="100")})
    )

    class DummyStats:
        data = {
            "load_avg_x": {"time_range": (0, 24), "day_type": "weekday"},
        }

        @classmethod
        def items(cls):
            return cls.data.items()

    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        DummyStats,
        raising=False,
    )

    result = load_profiles.get_load_avg_sensors(sensor)
    assert result["sensor.oig_123_load_avg_x"]["value"] == 100.0
