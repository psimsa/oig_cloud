from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

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


def _spot_data_for_now():
    now = datetime.now()
    hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
    return {
        "prices_czk_kwh": {hour_key: 2.0},
        "prices_eur_mwh": {hour_key: 80.0},
        "today_stats": {"avg_czk": 2.5},
        "tomorrow_stats": {"avg_czk": 3.0},
        "eur_czk_rate": 25.5,
    }


def test_dynamic_spot_price_paths():
    options = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "distribution_fee_vt_kwh": 1.0,
        "dual_tariff_enabled": False,
        "vat_rate": 0.0,
    }
    spot_data = _spot_data_for_now()

    sensor = _make_sensor("spot_price_current_czk_kwh", options, {"spot_prices": spot_data})
    assert sensor.native_value is not None

    sensor = _make_sensor("spot_price_current_eur_mwh", options, {"spot_prices": spot_data})
    assert sensor.native_value == 80.0

    sensor = _make_sensor("spot_price_today_avg", options, {"spot_prices": spot_data})
    assert sensor.native_value is not None

    sensor = _make_sensor("spot_price_today_min", options, {"spot_prices": spot_data})
    assert sensor.native_value is not None

    sensor = _make_sensor("spot_price_today_max", options, {"spot_prices": spot_data})
    assert sensor.native_value is not None

    sensor = _make_sensor("spot_price_tomorrow_avg", options, {"spot_prices": spot_data})
    assert sensor.native_value is not None

    sensor = _make_sensor("eur_czk_exchange_rate", options, {"spot_prices": spot_data})
    assert sensor.native_value == 25.5


def test_fixed_price_paths_dual_tariff():
    options = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 2.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 0.5,
        "dual_tariff_enabled": True,
        "vat_rate": 0.0,
    }

    sensor = _make_sensor("spot_price_today_min", options, {"spot_prices": {"x": 1}})
    assert sensor.native_value == 2.5

    sensor = _make_sensor("spot_price_today_max", options, {"spot_prices": {"x": 1}})
    assert sensor.native_value == 5.0

    sensor = _make_sensor("spot_price_current_eur_mwh", options, {"spot_prices": {"x": 1}})
    assert sensor.native_value is None


def test_current_tariff_and_extra_attributes():
    options = {
        "dual_tariff_enabled": False,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
    }
    sensor = _make_sensor("current_tariff", options, {"spot_prices": {}})

    assert sensor.native_value == "VT"
    attrs = sensor.extra_state_attributes
    assert attrs["tariff_type"] == "Jednotarifní"
    assert attrs["next_tariff"] == "VT"


def test_next_tariff_change_weekend():
    options = {
        "dual_tariff_enabled": True,
        "tariff_nt_start_weekend": "0",
        "tariff_vt_start_weekend": "6",
    }
    sensor = _make_sensor("current_tariff", options, {"spot_prices": {}})
    saturday = datetime.now() + timedelta(days=(5 - datetime.now().weekday()) % 7)
    next_tariff, next_time = sensor._get_next_tariff_change(saturday, True)
    assert next_tariff in ("VT", "NT")
    assert isinstance(next_time, datetime)
