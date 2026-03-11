from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.oig_cloud.entities.analytics_sensor import (
    OigCloudAnalyticsSensor,
)


class DummyCoordinator:
    def __init__(self, data=None):
        self.data = data or {}
        self.last_update_success = True


def _make_sensor(sensor_type: str, options: dict, data: dict | None = None):
    entry = SimpleNamespace(options={"enable_pricing": True, **options})
    coordinator = DummyCoordinator(data=data)
    return OigCloudAnalyticsSensor(coordinator, sensor_type, entry, device_info={})


def test_parse_tariff_times_invalid():
    sensor = _make_sensor("current_tariff", {}, {"spot_prices": {}})
    assert sensor._parse_tariff_times("bad,") == []


def test_get_spot_price_value_no_data():
    sensor = _make_sensor("spot_price_current_czk_kwh", {}, {})
    assert sensor._get_spot_price_value({}) is None


def test_get_next_tariff_change_no_dual():
    options = {"dual_tariff_enabled": False}
    sensor = _make_sensor("current_tariff", options, {"spot_prices": {}})
    now = datetime.now()
    tariff, next_time = sensor._get_next_tariff_change(now, False)
    assert tariff == "VT"
    assert next_time > now


def test_fixed_price_hourly_all():
    options = {"spot_pricing_model": "fixed_prices"}
    sensor = _make_sensor("spot_price_hourly_all", options, {"spot_prices": {"x": 1}})
    assert sensor.native_value is not None


def test_fixed_price_today_min_single_tariff():
    options = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "distribution_fee_vt_kwh": 1.0,
        "dual_tariff_enabled": False,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor("spot_price_today_min", options, {"spot_prices": {"x": 1}})
    assert sensor.native_value == 5.0


def test_current_tariff_yesterday_fallback(monkeypatch):
    options = {
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "",
        "tariff_nt_start_weekday": "22",
    }
    sensor = _make_sensor("current_tariff", options, {"spot_prices": {}})
    monkeypatch.setattr(sensor, "_parse_tariff_times", lambda _s: [])
    assert sensor._calculate_current_tariff() in ("VT", "NT")
