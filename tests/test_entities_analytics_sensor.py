from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.oig_cloud.entities.analytics_sensor import (
    OigCloudAnalyticsSensor,
)


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


def test_parse_tariff_times():
    sensor = _make_sensor({})
    assert sensor._parse_tariff_times("22,2") == [22, 2]
    assert sensor._parse_tariff_times("") == []
    assert sensor._parse_tariff_times("bad") == []


def test_calculate_current_tariff_single(monkeypatch):
    sensor = _make_sensor({"dual_tariff_enabled": False})

    fixed = datetime(2025, 1, 1, 7, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )

    assert sensor._calculate_current_tariff() == "VT"


def test_calculate_current_tariff_weekday(monkeypatch):
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
        }
    )

    fixed = datetime(2025, 1, 1, 7, 0, 0)  # Wednesday
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )

    assert sensor._calculate_current_tariff() == "VT"


def test_calculate_current_tariff_weekend(monkeypatch):
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekend": "8",
            "tariff_nt_start_weekend": "0",
        }
    )

    fixed = datetime(2025, 1, 4, 1, 0, 0)  # Saturday
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )

    assert sensor._calculate_current_tariff() == "NT"


def test_get_next_tariff_change():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
        }
    )

    current = datetime(2025, 1, 1, 7, 0, 0)
    tariff, next_change = sensor._get_next_tariff_change(current, is_weekend=False)

    assert tariff == "NT"
    assert next_change.hour == 22


def test_calculate_tariff_intervals_single_tariff():
    sensor = _make_sensor({"dual_tariff_enabled": False})
    now = datetime(2025, 1, 1, 7, 0, 0)

    intervals = sensor._calculate_tariff_intervals(now)

    assert intervals["NT"] == []
    assert len(intervals["VT"]) == 2


def test_get_tariff_for_datetime_weekend():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekend": "8",
            "tariff_nt_start_weekend": "0",
        }
    )
    assert sensor._get_tariff_for_datetime(datetime(2025, 1, 4, 1, 0, 0)) == "NT"
    assert sensor._get_tariff_for_datetime(datetime(2025, 1, 4, 9, 0, 0)) == "VT"


def test_final_price_with_fees_percentage():
    sensor = _make_sensor(
        {
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 10.0,
            "spot_negative_fee_percent": 5.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "vat_rate": 0.0,
        },
        sensor_type="spot_price_today_avg",
    )
    price = sensor._final_price_with_fees(
        2.0, target_datetime=datetime(2025, 1, 1, 8, 0, 0)
    )
    assert price == 3.2


def test_final_price_with_fees_fixed():
    sensor = _make_sensor(
        {
            "spot_pricing_model": "fixed",
            "spot_fixed_fee_mwh": 500.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "vat_rate": 0.0,
        },
        sensor_type="spot_price_today_avg",
    )
    price = sensor._final_price_with_fees(
        2.0, target_datetime=datetime(2025, 1, 1, 8, 0, 0)
    )
    assert price == 3.5


def test_get_today_extreme_price(monkeypatch):
    from custom_components.oig_cloud.entities import analytics_sensor as sensor_module

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(sensor_module, "datetime", FixedDatetime)

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
    spot_data = {
        "prices_czk_kwh": {
            "2025-01-01T00:00:00": 1.0,
            "2025-01-01T12:00:00": 2.0,
            "2025-01-02T00:00:00": 5.0,
        }
    }
    assert sensor._get_today_extreme_price(spot_data, find_min=True) == 1.0
    assert sensor._get_today_extreme_price(spot_data, find_min=False) == 2.0


def test_dynamic_spot_exchange_rate():
    sensor = _make_sensor(
        {"spot_pricing_model": "percentage"},
        sensor_type="eur_czk_exchange_rate",
    )
    value = sensor._get_dynamic_spot_price_value({"eur_czk_rate": 24.12345})
    assert value == 24.1234


def test_calculate_fixed_final_price_for_datetime():
    sensor = _make_sensor(
        {
            "fixed_commercial_price_vt": 4.0,
            "fixed_commercial_price_nt": 2.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "dual_tariff_enabled": False,
            "vat_rate": 10.0,
        },
        sensor_type="spot_price_current_czk_kwh",
    )
    price = sensor._calculate_fixed_final_price_for_datetime(
        datetime(2025, 1, 1, 8, 0, 0)
    )
    assert price == 5.5


def test_get_spot_price_value_empty_data():
    sensor = _make_sensor(
        {"spot_pricing_model": "percentage"}, sensor_type="spot_price_today_avg"
    )
    assert sensor._get_spot_price_value({}) is None


def test_get_fixed_price_value_min_max():
    options = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 2.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 0.5,
        "dual_tariff_enabled": True,
        "vat_rate": 0.0,
    }

    sensor_min = _make_sensor(options, sensor_type="spot_price_today_min")
    sensor_max = _make_sensor(options, sensor_type="spot_price_today_max")

    assert sensor_min._get_fixed_price_value() == 2.5
    assert sensor_max._get_fixed_price_value() == 5.0


def test_calculate_fixed_daily_average_dual_tariff():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "fixed_commercial_price_vt": 4.0,
            "fixed_commercial_price_nt": 2.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "vat_rate": 0.0,
        },
        sensor_type="spot_price_today_avg",
    )

    avg = sensor._calculate_fixed_daily_average(datetime(2025, 1, 1).date())
    assert avg == 4.17


def test_get_next_tariff_change_single_tariff():
    sensor = _make_sensor({"dual_tariff_enabled": False})
    current = datetime(2025, 1, 1, 10, 0, 0)
    tariff, next_change = sensor._get_next_tariff_change(current, is_weekend=False)
    assert tariff == "VT"
    assert (next_change - current).days >= 364


def test_calculate_tariff_intervals_dual_tariff_weekend():
    sensor = _make_sensor(
        {
            "dual_tariff_enabled": True,
            "tariff_vt_start_weekend": "8",
            "tariff_nt_start_weekend": "0",
        }
    )
    now = datetime(2025, 1, 4, 7, 0, 0)
    intervals = sensor._calculate_tariff_intervals(now)

    assert intervals["NT"]
    assert intervals["VT"]


def test_available_pricing_disabled():
    sensor = _make_sensor({"enable_pricing": False}, sensor_type="spot_price_today_avg")
    assert sensor.available is False


def test_state_current_tariff_and_spot_price(monkeypatch):
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="current_tariff")
    fixed = datetime(2025, 1, 1, 7, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )
    assert sensor.state == "VT"

    sensor = _make_sensor(
        {
            "enable_pricing": True,
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 0.0,
            "spot_negative_fee_percent": 0.0,
            "distribution_fee_vt_kwh": 0.0,
            "distribution_fee_nt_kwh": 0.0,
            "dual_tariff_enabled": False,
            "vat_rate": 0.0,
        },
        sensor_type="spot_price_current_czk_kwh",
    )
    fixed_now = datetime(2025, 1, 1, 10, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.datetime",
        FixedDatetime,
    )
    sensor.coordinator.data = {
        "spot_prices": {
            "prices_czk_kwh": {"2025-01-01T10:00:00": 2.5}
        }
    }
    assert sensor.state == 2.5


def test_extra_state_attributes_current_tariff(monkeypatch):
    sensor = _make_sensor({"enable_pricing": True}, sensor_type="current_tariff")
    fixed = datetime(2025, 1, 1, 7, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.dt_util.now",
        lambda: fixed,
    )
    attrs = sensor.extra_state_attributes
    assert attrs["current_tariff"] in ("VT", "NT")
    assert "nt_intervals" in attrs
    assert "vt_intervals" in attrs


def test_extra_state_attributes_hourly_fixed_prices(monkeypatch):
    options = {
        "enable_pricing": True,
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 2.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 0.5,
        "dual_tariff_enabled": True,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor(options, sensor_type="spot_price_hourly_all")
    sensor.coordinator.data = {"spot_prices": {"prices_czk_kwh": {}}}

    fixed_now = datetime(2025, 1, 1, 10, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.datetime",
        FixedDatetime,
    )

    attrs = sensor.extra_state_attributes
    assert attrs["hours_count"] == 48
    assert attrs["date_range"]["start"] == "2025-01-01"
    assert attrs["date_range"]["end"] == "2025-01-02"
    assert "hourly_final_prices" in attrs


def test_extra_state_attributes_hourly_dynamic(monkeypatch):
    options = {
        "enable_pricing": True,
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 0.0,
        "spot_negative_fee_percent": 0.0,
        "distribution_fee_vt_kwh": 0.0,
        "distribution_fee_nt_kwh": 0.0,
        "dual_tariff_enabled": False,
        "vat_rate": 0.0,
    }
    sensor = _make_sensor(options, sensor_type="spot_price_hourly_all")
    sensor.coordinator.data = {
        "spot_prices": {
            "prices_czk_kwh": {
                "2025-01-01T00:00:00": 1.0,
                "2025-01-02T01:00:00": 2.0,
            }
        }
    }

    attrs = sensor.extra_state_attributes
    assert attrs["hours_count"] == 2
    assert attrs["date_range"]["start"] == "2025-01-01"
    assert attrs["date_range"]["end"] == "2025-01-02"
