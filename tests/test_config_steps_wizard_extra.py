from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config import steps as steps_module
from custom_components.oig_cloud.config.steps import (
    CONF_PASSWORD,
    CONF_USERNAME,
    WizardMixin,
)


class DummyWizard(WizardMixin):
    def __init__(self):
        super().__init__()
        self.hass = SimpleNamespace(
            config=SimpleNamespace(latitude=50.0, longitude=14.0),
            states=SimpleNamespace(get=lambda _eid: None),
        )

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}


@pytest.mark.asyncio
async def test_wizard_credentials_missing_fields():
    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {CONF_USERNAME: "", CONF_PASSWORD: "", "live_data_enabled": False}
    )
    assert result["type"] == "form"
    errors = result["errors"]
    assert errors[CONF_USERNAME] == "required"
    assert errors[CONF_PASSWORD] == "required"
    assert errors["live_data_enabled"] == "live_data_not_confirmed"


@pytest.mark.asyncio
async def test_wizard_credentials_go_back(monkeypatch):
    flow = DummyWizard()
    flow._step_history = ["wizard_welcome"]

    result = await flow.async_step_wizard_credentials({"go_back": True})

    assert result["step_id"] == "wizard_welcome"


@pytest.mark.asyncio
async def test_wizard_credentials_validate_errors(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.InvalidAuth

    monkeypatch.setattr(steps_module, "validate_input", _raise)

    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )

    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_wizard_credentials_success(monkeypatch):
    async def _ok(_hass, _data):
        return {"title": "ok"}

    monkeypatch.setattr(steps_module, "validate_input", _ok)

    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )

    assert result["step_id"] == "wizard_modules"
    assert flow._wizard_data[CONF_USERNAME] == "user"


@pytest.mark.asyncio
async def test_wizard_modules_requires_solar_and_extended():
    flow = DummyWizard()
    result = await flow.async_step_wizard_modules(
        {
            "enable_battery_prediction": True,
            "enable_solar_forecast": False,
            "enable_extended_sensors": False,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["enable_battery_prediction"] == "requires_solar_forecast"
    assert result["errors"]["enable_extended_sensors"] == "required_for_battery"


@pytest.mark.asyncio
async def test_wizard_modules_dashboard_requires_modules():
    flow = DummyWizard()
    result = await flow.async_step_wizard_modules(
        {
            "enable_dashboard": True,
            "enable_statistics": False,
            "enable_solar_forecast": False,
            "enable_battery_prediction": False,
            "enable_pricing": False,
            "enable_extended_sensors": False,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["enable_dashboard"] == "dashboard_requires_all"
    assert "Statistiky" in flow._wizard_data["_missing_for_dashboard"]


@pytest.mark.asyncio
async def test_wizard_modules_success_moves_forward():
    flow = DummyWizard()
    result = await flow.async_step_wizard_modules(
        {
            "enable_solar_forecast": False,
            "enable_battery_prediction": False,
            "enable_pricing": False,
            "enable_boiler": False,
            "enable_dashboard": False,
            "enable_extended_sensors": True,
        }
    )

    assert result["step_id"] == "wizard_intervals"


@pytest.mark.asyncio
async def test_wizard_solar_toggle_expands_form():
    flow = DummyWizard()
    flow._wizard_data = {steps_module.CONF_SOLAR_FORECAST_STRING1_ENABLED: True}

    result = await flow.async_step_wizard_solar(
        {
            steps_module.CONF_SOLAR_FORECAST_STRING1_ENABLED: False,
            "solar_forecast_string2_enabled": True,
        }
    )

    assert result["step_id"] == "wizard_solar"


@pytest.mark.asyncio
async def test_wizard_solar_validation_errors():
    flow = DummyWizard()
    flow._wizard_data = {
        steps_module.CONF_SOLAR_FORECAST_STRING1_ENABLED: False,
        "solar_forecast_string2_enabled": False,
    }
    result = await flow.async_step_wizard_solar(
        {
            "solar_forecast_mode": "hourly",
            steps_module.CONF_SOLAR_FORECAST_LATITUDE: 200,
            steps_module.CONF_SOLAR_FORECAST_LONGITUDE: 14.0,
            steps_module.CONF_SOLAR_FORECAST_STRING1_ENABLED: False,
            "solar_forecast_string2_enabled": False,
        }
    )

    assert result["errors"]["solar_forecast_mode"] == "api_key_required_for_frequent_updates"
    assert result["errors"][steps_module.CONF_SOLAR_FORECAST_LATITUDE] == "invalid_latitude"
    assert result["errors"]["base"] == "no_strings_enabled"


@pytest.mark.asyncio
async def test_wizard_solar_success():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_battery_prediction": False,
        "enable_pricing": False,
        "enable_boiler": False,
    }
    result = await flow.async_step_wizard_solar(
        {
            steps_module.CONF_SOLAR_FORECAST_API_KEY: "key",
            "solar_forecast_mode": "daily",
            steps_module.CONF_SOLAR_FORECAST_LATITUDE: 50.0,
            steps_module.CONF_SOLAR_FORECAST_LONGITUDE: 14.0,
            steps_module.CONF_SOLAR_FORECAST_STRING1_ENABLED: True,
            steps_module.CONF_SOLAR_FORECAST_STRING1_KWP: 5.0,
            steps_module.CONF_SOLAR_FORECAST_STRING1_DECLINATION: 35,
            steps_module.CONF_SOLAR_FORECAST_STRING1_AZIMUTH: 0,
            "solar_forecast_string2_enabled": False,
        }
    )

    assert result["type"] == "summary"


@pytest.mark.asyncio
async def test_wizard_battery_validation_errors():
    flow = DummyWizard()
    result = await flow.async_step_wizard_battery(
        {
            "min_capacity_percent": 80,
            "target_capacity_percent": 60,
            "max_ups_price_czk": 0.5,
        }
    )

    assert result["errors"]["min_capacity_percent"] == "min_must_be_less_than_target"
    assert result["errors"]["max_ups_price_czk"] == "invalid_price"


@pytest.mark.asyncio
async def test_wizard_battery_success():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_pricing": False,
        "enable_boiler": False,
    }
    result = await flow.async_step_wizard_battery(
        {
            "min_capacity_percent": 20,
            "target_capacity_percent": 80,
            "max_ups_price_czk": 10.0,
        }
    )

    assert result["type"] == "summary"


@pytest.mark.asyncio
async def test_wizard_pricing_import_scenario_change():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "spot_percentage"}
    result = await flow.async_step_wizard_pricing_import(
        {"import_pricing_scenario": "spot_fixed"}
    )
    assert result["step_id"] == "wizard_pricing_import"


@pytest.mark.asyncio
async def test_wizard_pricing_import_validation_error():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_import(
        {
            "import_pricing_scenario": "spot_percentage",
            "spot_positive_fee_percent": 150.0,
            "spot_negative_fee_percent": 5.0,
        }
    )
    assert result["errors"]["spot_positive_fee_percent"] == "invalid_percentage"


@pytest.mark.asyncio
async def test_wizard_pricing_distribution_validation(monkeypatch):
    flow = DummyWizard()
    flow._wizard_data = {
        "import_pricing_scenario": "fix_price",
        "fixed_price_kwh": 4.5,
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": True,
    }

    monkeypatch.setattr(steps_module, "validate_tariff_hours", lambda *_a, **_k: (False, "overlap"))

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "distribution_fee_vt_kwh": 15.0,
            "distribution_fee_nt_kwh": 0.5,
            "fixed_price_vt_kwh": 30.0,
            "fixed_price_nt_kwh": 30.0,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "tariff_weekend_same_as_weekday": True,
            "vat_rate": 40.0,
        }
    )

    assert result["errors"]["distribution_fee_vt_kwh"] == "invalid_distribution_fee"
    assert result["errors"]["fixed_price_vt_kwh"] == "invalid_price"
    assert result["errors"]["tariff_vt_start_weekday"] == "overlap"
    assert result["errors"]["vat_rate"] == "invalid_vat"
