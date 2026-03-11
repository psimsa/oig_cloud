from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.analytics_sensor import OigCloudAnalyticsSensor


class DummyCoordinator:
    def __init__(self):
        self.data = {}
        self.forced_box_id = "123"
        self.hass = None
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(options, sensor_type="current_tariff"):
    coordinator = DummyCoordinator()
    entry = SimpleNamespace(options=options)
    device_info = {"identifiers": {("oig_cloud", "123")}}
    return OigCloudAnalyticsSensor(coordinator, sensor_type, entry, device_info)


def test_native_value_unavailable():
    sensor = _make_sensor({"enable_pricing": False}, sensor_type="spot_price_today_avg")
    assert sensor.native_value is None


def test_native_value_no_spot_prices():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_today_avg")
    sensor.coordinator.data = {}
    assert sensor.native_value is None


def test_calculate_current_tariff_fallback_yesterday(monkeypatch):
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
        }
    )

    fixed = datetime(2025, 1, 1, 1, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )

    assert sensor._calculate_current_tariff() == "NT"


def test_get_next_tariff_change_no_changes():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "",
            "tariff_nt_start_weekday": "",
        }
    )
    current = datetime(2025, 1, 1, 10, 0, 0)
    tariff, next_change = sensor._get_next_tariff_change(current, is_weekend=False)
    assert tariff == "NT"
    assert next_change == current + timedelta(hours=1)


def test_calculate_tariff_intervals_no_changes():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "",
            "tariff_nt_start_weekday": "",
        }
    )
    now = datetime(2025, 1, 1, 7, 0, 0)
    intervals = sensor._calculate_tariff_intervals(now)
    assert len(intervals["NT"]) == 2
    assert intervals["VT"] == []


def test_get_current_spot_price_eur_missing():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_current_eur_mwh")
    sensor.coordinator.data = {"spot_prices": {"prices_eur_mwh": {}}}
    assert sensor.state is None


def test_get_today_average_price_missing():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_today_avg")
    spot_data = {"today_stats": {}}
    assert sensor._get_today_average_price(spot_data) is None


def test_get_today_extreme_price_invalid_key():
    sensor = _make_sensor(
        {
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 0.0,
            "spot_negative_fee_percent": 0.0,
            "distribution_fee_vt_kwh": 0.0,
            "distribution_fee_nt_kwh": 0.0,
            "dual_tariff_enabled": False,
            "vat_rate": 0.0,
        },
        sensor_type="spot_price_today_min",
    )
    spot_data = {"prices_czk_kwh": {"bad": 1.0}}
    assert sensor._get_today_extreme_price(spot_data, find_min=True) is None


def test_get_tomorrow_average_price_missing():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_tomorrow_avg")
    assert sensor._get_tomorrow_average_price({}) is None


def test_get_spot_price_value_fixed_prices_eur():
    sensor = _make_sensor(
        {"spot_pricing_model": "fixed_prices"}, sensor_type="spot_price_current_eur_mwh"
    )
    assert sensor._get_spot_price_value({"prices_czk_kwh": {}}) is None


def test_extra_state_attributes_no_spot_prices():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_today_avg")
    sensor.coordinator.data = {}
    assert sensor.extra_state_attributes == {}


def test_available_pricing_enabled_success():
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_today_avg")
    sensor.coordinator.last_update_success = True
    assert sensor.available is True


@pytest.mark.asyncio
async def test_state_error_path(monkeypatch):
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="spot_price_today_avg")

    def _boom(_data):
        raise RuntimeError("fail")

    monkeypatch.setattr(sensor, "_get_spot_price_value", _boom)
    sensor.coordinator.data = {"spot_prices": {"prices_czk_kwh": {}}}
    assert sensor.state is None
