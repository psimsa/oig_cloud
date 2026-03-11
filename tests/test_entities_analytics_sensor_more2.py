from datetime import datetime
from types import SimpleNamespace

from custom_components.oig_cloud.entities.analytics_sensor import OigCloudAnalyticsSensor


class DummyCoordinator:
    def __init__(self):
        self.data = {"spot_prices": {"prices_czk_kwh": {}}}
        self.forced_box_id = "123"
        self.hass = None
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(options, sensor_type):
    return OigCloudAnalyticsSensor(DummyCoordinator(), sensor_type, SimpleNamespace(options=options), {})


def test_get_current_spot_price_missing_returns_none():
    sensor = _make_sensor({"enable_pricing": True}, "spot_price_current_czk_kwh")
    assert sensor.state is None


def test_get_tariff_for_datetime_single():
    sensor = _make_sensor({"dual_tariff_enabled": False}, "current_tariff")
    assert sensor._get_tariff_for_datetime(datetime(2025, 1, 1, 10, 0, 0)) == "VT"
