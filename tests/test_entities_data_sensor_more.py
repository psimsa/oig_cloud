from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.entities.data_sensor import OigCloudDataSensor


class DummyCoordinator:
    def __init__(self, data):
        self.data = data


def _make_sensor(sensor_type, data):
    return OigCloudDataSensor(DummyCoordinator(data), sensor_type, extended=True)


def test_extended_value_lookup_and_mode_name():
    data = {
        "extended_batt": {"items": [{"values": [48.5, 10.0, 80.0, 25.0]}]},
        "extended_fve": {"items": [{"values": [100.0, 200.0, 0.0, 400.0, 800.0]}]},
    }
    sensor = _make_sensor("extended_battery_voltage", data)
    assert sensor._get_extended_value_for_sensor() == 48.5

    sensor = _make_sensor("extended_fve_current_1", data)
    assert sensor._get_extended_value_for_sensor() == 4.0

    assert sensor._get_mode_name(3, "en") == "Home UPS"
    assert sensor._get_mode_name(9, "en") == "Unknown"


def test_extended_value_missing_data():
    sensor = _make_sensor("extended_battery_voltage", {})
    assert sensor._get_extended_value_for_sensor() is None

    sensor = _make_sensor("extended_fve_current_2", {"extended_fve": {"items": []}})
    assert sensor._get_extended_value_for_sensor() == 0.0
