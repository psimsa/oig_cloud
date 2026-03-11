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


def test_fixed_prices_hourly_all_current_value(monkeypatch):
    sensor = _make_sensor({"enable_pricing": True, "spot_pricing_model": "fixed_prices"}, "spot_price_hourly_all")
    fixed_now = datetime(2025, 1, 1, 10, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.datetime",
        type("FixedDatetime", (datetime,), {"now": classmethod(lambda cls, tz=None: fixed_now)}),
    )
    assert sensor.native_value is not None
