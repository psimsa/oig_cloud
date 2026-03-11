from __future__ import annotations

import types

import pytest

from custom_components.oig_cloud.config import schema as schema_module
from custom_components.oig_cloud.config import steps as steps_module
from custom_components.oig_cloud.config import validation as validation_module


def test_sanitize_data_source_mode():
    mixin = steps_module.WizardMixin
    assert mixin._sanitize_data_source_mode(None) == "cloud_only"
    assert mixin._sanitize_data_source_mode("hybrid") == "local_only"
    assert mixin._sanitize_data_source_mode("cloud_only") == "cloud_only"


def test_migrate_old_pricing_data_percentage():
    data = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 5.0,
        "dual_tariff_enabled": True,
    }

    migrated = steps_module.WizardMixin._migrate_old_pricing_data(data)
    assert migrated["import_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["export_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["tariff_weekend_same_as_weekday"] is True


def test_map_pricing_to_backend_fixed_price():
    wizard_data = {
        "import_pricing_scenario": "fix_price",
        "fixed_price_vt_kwh": 4.5,
        "fixed_price_nt_kwh": 3.0,
        "export_pricing_scenario": "spot_fixed",
        "export_spot_fixed_fee_kwh": 0.15,
    }

    backend = steps_module.WizardMixin._map_pricing_to_backend(wizard_data)
    assert backend["spot_pricing_model"] == "fixed_prices"
    assert backend["fixed_commercial_price_vt"] == 4.5
    assert backend["fixed_commercial_price_nt"] == 3.0
    assert backend["export_pricing_model"] == "fixed"


def test_validate_tariff_hours(monkeypatch):
    ok, err = schema_module.validate_tariff_hours("6", "22,2")
    assert ok is True
    assert err is None

    ok, err = schema_module.validate_tariff_hours("x", "22")
    assert ok is False
    assert err == "invalid_hour_format"

    ok, err = schema_module.validate_tariff_hours("24", "22")
    assert ok is False
    assert err == "invalid_hour_range"

    ok, err = schema_module.validate_tariff_hours("", "", allow_single_tariff=False)
    assert ok is False
    assert err == "tariff_gaps"

    ok, err = schema_module.validate_tariff_hours("6", "", allow_single_tariff=True)
    assert ok is True
    assert err is None

    ok, err = schema_module.validate_tariff_hours("6", "12")
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_validate_input_ok(monkeypatch):
    class DummyApi:
        def __init__(self, *_args, **_kwargs):
            return None

        async def authenticate(self):
            return True

        async def get_stats(self):
            return {"box": {"actual": {}}}

    monkeypatch.setattr(validation_module, "OigCloudApi", DummyApi)

    result = await validation_module.validate_input(
        None, {"username": "u", "password": "p"}
    )
    assert result["title"] == validation_module.DEFAULT_NAME


@pytest.mark.asyncio
async def test_validate_input_live_data_missing(monkeypatch):
    class DummyApi:
        def __init__(self, *_args, **_kwargs):
            return None

        async def authenticate(self):
            return True

        async def get_stats(self):
            return {"box": {}}

    monkeypatch.setattr(validation_module, "OigCloudApi", DummyApi)

    with pytest.raises(validation_module.LiveDataNotEnabled):
        await validation_module.validate_input(
            None, {"username": "u", "password": "p"}
        )


@pytest.mark.asyncio
async def test_validate_solar_forecast_api_key_status(monkeypatch):
    class DummyResponse:
        def __init__(self, status):
            self.status = status

        async def text(self):
            return "err"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class DummySession:
        def __init__(self, status):
            self._status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return DummyResponse(self._status)

    monkeypatch.setattr(
        validation_module.aiohttp,
        "ClientSession",
        lambda: DummySession(200),
    )
    assert await validation_module.validate_solar_forecast_api_key("token") is True

    monkeypatch.setattr(
        validation_module.aiohttp,
        "ClientSession",
        lambda: DummySession(401),
    )
    assert await validation_module.validate_solar_forecast_api_key("token") is False
