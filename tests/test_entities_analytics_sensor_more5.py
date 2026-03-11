from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.analytics_sensor import OigCloudAnalyticsSensor


class DummyCoordinator:
    def __init__(self, data=None, last_update_success=True):
        self.data = data or {}
        self.last_update_success = last_update_success


def _make_sensor(sensor_type, options=None, data=None, ok=True):
    entry = SimpleNamespace(options={"enable_pricing": True, **(options or {})})
    return OigCloudAnalyticsSensor(
        DummyCoordinator(data=data, last_update_success=ok),
        sensor_type,
        entry,
        device_info={"id": "x"},
    )


def test_device_info_and_available():
    sensor = _make_sensor("current_tariff", {"enable_pricing": False})
    assert sensor.device_info == {"id": "x"}
    assert sensor.available is False

    sensor = _make_sensor("current_tariff", {}, ok=False)
    assert sensor.available is False


def test_calculate_current_tariff_yesterday_weekend(monkeypatch):
    options = {
        "dual_tariff_enabled": True,
        "tariff_nt_start_weekday": "",
        "tariff_vt_start_weekday": "",
        "tariff_nt_start_weekend": "0",
        "tariff_vt_start_weekend": "6",
    }
    sensor = _make_sensor("current_tariff", options)
    monday = datetime(2025, 1, 6, 1, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: monday,
    )
    assert sensor._calculate_current_tariff() in ("NT", "VT")


def test_fixed_price_value_variants(monkeypatch):
    options = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 3.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 0.5,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor("spot_price_current_czk_kwh", options, {"spot_prices": {}})
    assert sensor._get_fixed_price_value() is not None

    sensor = _make_sensor("spot_price_today_avg", options, {"spot_prices": {}})
    assert sensor._get_fixed_price_value() is not None

    sensor = _make_sensor("spot_price_today_max", options, {"spot_prices": {}})
    assert sensor._get_fixed_price_value() is not None

    sensor = _make_sensor("spot_price_tomorrow_avg", options, {"spot_prices": {}})
    assert sensor._get_fixed_price_value() is not None

    sensor = _make_sensor("spot_price_current_eur_mwh", options, {"spot_prices": {}})
    assert sensor._get_fixed_price_value() is None


def test_fixed_daily_average_dual_tariff(monkeypatch):
    options = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 2.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 1.0,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor("spot_price_today_avg", options, {"spot_prices": {}})
    monkeypatch.setattr(sensor, "_get_tariff_for_datetime", lambda _dt: "VT")
    avg = sensor._calculate_fixed_daily_average(datetime.now().date())
    assert avg == 5.0


def test_final_price_with_fees_variants(monkeypatch):
    options = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 10.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 1.0,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor("spot_price_today_avg", options, {"spot_prices": {}})
    assert sensor._final_price_with_fees(10.0) == 12.0
    assert sensor._final_price_with_fees(-10.0) == -8.0

    sensor._entry.options["spot_pricing_model"] = "fixed"
    sensor._entry.options["spot_fixed_fee_mwh"] = 1000.0
    assert sensor._final_price_with_fees(1.0) == 3.0


def test_today_extreme_price_and_tomorrow_avg(monkeypatch):
    now = datetime.now()
    key = now.strftime("%Y-%m-%dT%H:00:00")
    data = {
        "prices_czk_kwh": {"bad": 1.0, key: 2.0},
        "tomorrow_stats": {"avg_czk": 5.0},
    }
    sensor = _make_sensor("spot_price_today_min", {}, {"spot_prices": data})
    assert sensor._get_today_extreme_price(data, True) is not None
    assert sensor._get_today_extreme_price(data, False) is not None
    assert sensor._get_tomorrow_average_price(data) is not None


def test_extra_state_attributes_hourly_all_fixed(monkeypatch):
    options = {"spot_pricing_model": "fixed_prices"}
    data = {"spot_prices": {"prices_czk_kwh": {}}}
    sensor = _make_sensor("spot_price_hourly_all", options, data)
    monkeypatch.setattr(sensor, "_get_tariff_for_datetime", lambda _dt: "VT")
    attrs = sensor.extra_state_attributes
    assert "hourly_final_prices" in attrs
    assert attrs["hours_count"] > 0


def test_extra_state_attributes_hourly_all_dynamic(monkeypatch):
    now = datetime.now()
    key = now.strftime("%Y-%m-%dT%H:00:00")
    data = {"spot_prices": {"prices_czk_kwh": {key: 1.0}}}
    options = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 0.0,
        "distribution_fee_vt_kwh": 0.0,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor("spot_price_hourly_all", options, data)
    monkeypatch.setattr(sensor, "_get_tariff_for_datetime", lambda _dt: "VT")
    attrs = sensor.extra_state_attributes
    assert "date_range" in attrs
    assert "hourly_final_prices" in attrs
