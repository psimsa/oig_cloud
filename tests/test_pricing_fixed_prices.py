from datetime import datetime

import pytest

from custom_components.oig_cloud.battery_forecast.data.pricing import (
    calculate_final_spot_price, get_spot_price_timeline)


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options
        self.data = {}


class DummyCoordinator:
    def __init__(self, config_entry, spot_data):
        self.config_entry = config_entry
        self.data = {"spot_prices": spot_data}


class DummySensor:
    def __init__(self, options, spot_data):
        self._config_entry = DummyConfigEntry(options)
        self.coordinator = DummyCoordinator(self._config_entry, spot_data)
        self._hass = None
        self._box_id = "2206237016"


def _fixed_options():
    return {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 3.0,
        "distribution_fee_vt_kwh": 1.0,
        "distribution_fee_nt_kwh": 0.5,
        "vat_rate": 21.0,
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_weekend_same_as_weekday": True,
        "tariff_vt_start_weekend": "6",
        "tariff_nt_start_weekend": "22,2",
    }


def test_calculate_final_spot_price_fixed_prices():
    options = _fixed_options()
    sensor = DummySensor(options, spot_data={"prices15m_czk_kwh": {}})

    vt_time = datetime.fromisoformat("2025-01-02T10:00:00")
    nt_time = datetime.fromisoformat("2025-01-02T23:00:00")

    vt_price = calculate_final_spot_price(sensor, 1.0, vt_time)
    nt_price = calculate_final_spot_price(sensor, 1.0, nt_time)

    assert vt_price == 6.05
    assert nt_price == 4.24


@pytest.mark.asyncio
async def test_get_spot_price_timeline_fixed_prices():
    options = _fixed_options()
    spot_data = {
        "prices15m_czk_kwh": {
            "2025-01-02T10:00:00": 1.23,
            "2025-01-02T23:00:00": 2.34,
        }
    }
    sensor = DummySensor(options, spot_data=spot_data)

    timeline = await get_spot_price_timeline(sensor)
    prices = {row["time"]: row["price"] for row in timeline}

    assert prices["2025-01-02T10:00:00"] == 6.05
    assert prices["2025-01-02T23:00:00"] == 4.24
