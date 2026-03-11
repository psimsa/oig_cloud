from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import analytics_sensor as module


class DummyCoordinator:
    def __init__(self, data=None):
        self.data = data or {}
        self.last_update_success = True
        self.hass = SimpleNamespace()


def _make_sensor(monkeypatch, sensor_type, options=None, data=None):
    options = options or {}
    entry = SimpleNamespace(options=options)
    coord = DummyCoordinator(data=data)
    monkeypatch.setattr(module, "resolve_box_id", lambda *_a, **_k: "123")
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT.SENSOR_TYPES_SPOT",
        {sensor_type: {"name_cs": "Senzor"}},
    )
    sensor = module.OigCloudAnalyticsSensor(coord, sensor_type, entry, {"identifiers": set()})
    return sensor


def test_device_info_property(monkeypatch):
    sensor = _make_sensor(monkeypatch, "spot_price_current_czk_kwh")
    assert sensor.device_info is not None


def test_calculate_current_tariff_yesterday(monkeypatch):
    options = {
        "dual_tariff_enabled": True,
        "tariff_nt_start_weekday": "2",
        "tariff_vt_start_weekday": "3",
        "tariff_nt_start_weekend": "0",
        "tariff_vt_start_weekend": "1",
    }
    sensor = _make_sensor(monkeypatch, "current_tariff", options)
    now = datetime(2025, 1, 6, 1, 0, 0)  # Monday, yesterday was weekend
    monkeypatch.setattr(module.dt_util, "now", lambda: now)
    assert sensor._calculate_current_tariff() in ("NT", "VT")


def test_get_next_tariff_change_disabled(monkeypatch):
    sensor = _make_sensor(monkeypatch, "current_tariff", {"dual_tariff_enabled": False})
    current = datetime(2025, 1, 1, 10, 0, 0)
    tariff, next_change = sensor._get_next_tariff_change(current, False)
    assert tariff == "VT"
    assert next_change > current


def test_calculate_tariff_intervals_no_changes(monkeypatch):
    options = {
        "dual_tariff_enabled": True,
        "tariff_nt_start_weekday": "",
        "tariff_vt_start_weekday": "",
        "tariff_nt_start_weekend": "",
        "tariff_vt_start_weekend": "",
    }
    sensor = _make_sensor(monkeypatch, "current_tariff", options)
    intervals = sensor._calculate_tariff_intervals(datetime(2025, 1, 1, 0, 0, 0))
    assert intervals["NT"]


def test_get_tariff_for_datetime_disabled(monkeypatch):
    sensor = _make_sensor(monkeypatch, "current_tariff", {"dual_tariff_enabled": False})
    assert sensor._get_tariff_for_datetime(datetime(2025, 1, 1, 0, 0, 0)) == "VT"


def test_get_spot_price_value_empty(monkeypatch):
    sensor = _make_sensor(monkeypatch, "spot_price_today_avg")
    assert sensor._get_spot_price_value({}) is None


def test_fixed_price_value_variants(monkeypatch):
    options = {"spot_pricing_model": "fixed_prices", "dual_tariff_enabled": True}
    sensor = _make_sensor(monkeypatch, "spot_price_current_czk_kwh", options)
    assert sensor._get_fixed_price_value() is not None

    sensor = _make_sensor(monkeypatch, "spot_price_current_eur_mwh", options)
    assert sensor._get_fixed_price_value() is None


def test_calculate_fixed_daily_average_single_tariff(monkeypatch):
    options = {"dual_tariff_enabled": False}
    sensor = _make_sensor(monkeypatch, "spot_price_today_avg", options)
    value = sensor._calculate_fixed_daily_average(datetime(2025, 1, 1).date())
    assert value > 0


def test_get_dynamic_spot_price_value_unknown(monkeypatch):
    sensor = _make_sensor(monkeypatch, "unknown_sensor")
    assert sensor._get_dynamic_spot_price_value({"prices_czk_kwh": {}}) is None


def test_final_price_with_fees_fixed_model(monkeypatch):
    options = {"spot_pricing_model": "fixed", "dual_tariff_enabled": True}
    sensor = _make_sensor(monkeypatch, "spot_price_today_avg", options)
    assert sensor._final_price_with_fees(1.0) is not None


def test_get_today_extreme_price_invalid_key(monkeypatch):
    sensor = _make_sensor(monkeypatch, "spot_price_today_min")
    assert sensor._get_today_extreme_price({"prices_czk_kwh": {"bad": 1.0}}, True) is None


def test_extra_state_attributes_hourly_fixed_and_percentage(monkeypatch):
    options = {
        "enable_pricing": True,
        "spot_pricing_model": "fixed_prices",
        "dual_tariff_enabled": True,
    }
    sensor = _make_sensor(
        monkeypatch,
        "spot_price_hourly_all",
        options,
        data={"spot_prices": {"prices_czk_kwh": {}}},
    )
    attrs = sensor.extra_state_attributes
    assert "hourly_final_prices" in attrs

    options = {
        "enable_pricing": True,
        "spot_pricing_model": "percentage",
        "dual_tariff_enabled": True,
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 5.0,
    }
    sensor = _make_sensor(
        monkeypatch,
        "spot_price_hourly_all",
        options,
        data={
            "spot_prices": {
                "prices_czk_kwh": {
                    "bad": 1.0,
                    datetime.now().strftime("%Y-%m-%dT%H:00:00"): -1.0,
                }
            }
        },
    )
    attrs = sensor.extra_state_attributes
    assert "hourly_final_prices" in attrs


def test_extra_state_attributes_pricing_details(monkeypatch):
    class WeirdType:
        def __eq__(self, other):
            return other == "spot_price_hourly_all"

        def __contains__(self, item):
            return item == "czk"

        def __repr__(self):
            return "spot_price_hourly_all"

    options = {
        "enable_pricing": True,
        "spot_pricing_model": "fixed",
        "dual_tariff_enabled": True,
    }
    sensor = _make_sensor(
        monkeypatch,
        "spot_price_hourly_all",
        options,
        data={"spot_prices": {"prices_czk_kwh": {"2025-01-01T00:00:00": 1.0}}},
    )
    sensor._sensor_type = WeirdType()
    attrs = sensor.extra_state_attributes
    assert attrs.get("pricing_model")


def test_state_unavailable(monkeypatch):
    options = {"enable_pricing": False}
    sensor = _make_sensor(monkeypatch, "spot_price_today_avg", options)
    assert sensor.state is None
