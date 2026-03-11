from __future__ import annotations

import pytest

from custom_components.oig_cloud.config.steps import (
    CONF_SOLAR_FORECAST_STRING1_ENABLED,
    CONF_SOLAR_FORECAST_STRING1_KWP,
    WizardMixin,
)


class DummyWizard(WizardMixin):
    def __init__(self):
        super().__init__()
        self.config_entry = None

    async def async_step_wizard_welcome(self, user_input=None):
        return {"type": "form", "step_id": "wizard_welcome"}

    async def async_step_prev(self, user_input=None):
        return {"type": "form", "step_id": "prev"}


def test_migrate_old_pricing_data_empty_and_passthrough():
    assert WizardMixin._migrate_old_pricing_data({}) == {}
    data = {"import_pricing_scenario": "spot_percentage"}
    assert WizardMixin._migrate_old_pricing_data(data) == data


def test_migrate_old_pricing_data_fixed_models():
    data = {"spot_pricing_model": "fixed", "dual_tariff_enabled": False}
    migrated = WizardMixin._migrate_old_pricing_data(data)
    assert migrated["import_pricing_scenario"] == "spot_fixed_1tariff"
    assert migrated["import_spot_fixed_fee_mwh"] == 500.0

    data = {"spot_pricing_model": "fixed_prices", "dual_tariff_enabled": True}
    migrated = WizardMixin._migrate_old_pricing_data(data)
    assert migrated["import_pricing_scenario"] == "fix_2tariff"
    assert migrated["import_fixed_price_vt"] == 4.50
    assert migrated["import_fixed_price_nt"] == 3.20


def test_map_backend_to_frontend_weekend_same_defaults():
    backend = {
        "spot_pricing_model": "fixed",
        "spot_fixed_fee_mwh": 500.0,
        "export_pricing_model": "fixed_prices",
        "export_fixed_price": 2.5,
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
    }
    frontend = WizardMixin._map_backend_to_frontend(backend)
    assert frontend["import_pricing_scenario"] == "spot_fixed"
    assert frontend["export_pricing_scenario"] == "fix_price"
    assert frontend["tariff_weekend_same_as_weekday"] is True


def test_get_defaults_reconfiguration():
    flow = DummyWizard()
    flow.config_entry = type("Entry", (), {"options": {"spot_pricing_model": "fixed"}})()
    defaults = flow._get_defaults()
    assert defaults["import_pricing_scenario"] == "spot_fixed_1tariff"


@pytest.mark.asyncio
async def test_handle_back_button_returns_previous():
    flow = DummyWizard()
    flow._step_history = ["prev", "wizard_credentials"]
    result = await flow._handle_back_button("wizard_credentials")
    assert result["step_id"] == "prev"


@pytest.mark.asyncio
async def test_handle_back_button_no_history_returns_welcome():
    flow = DummyWizard()
    result = await flow._handle_back_button("wizard_credentials")
    assert result["step_id"] == "wizard_welcome"


def test_generate_summary_all_sections():
    flow = DummyWizard()
    flow._wizard_data = {
        "username": "user",
        "standard_scan_interval": 10,
        "extended_scan_interval": 20,
        "enable_statistics": True,
        "enable_solar_forecast": True,
        "solar_forecast_mode": "hourly",
        CONF_SOLAR_FORECAST_STRING1_ENABLED: True,
        CONF_SOLAR_FORECAST_STRING1_KWP: 3.5,
        "solar_forecast_string2_enabled": True,
        "solar_forecast_string2_kwp": 5,
        "enable_battery_prediction": True,
        "min_capacity_percent": 10,
        "target_capacity_percent": 90,
        "max_ups_price_czk": 12.5,
        "enable_pricing": True,
        "spot_pricing_model": "fixed_prices",
        "vat_rate": 15.0,
        "enable_extended_sensors": True,
        "enable_dashboard": True,
    }
    summary = flow._generate_summary()
    assert "Uživatel: user" in summary
    assert "Solární předpověď" in summary
    assert "DPH: 15.0%" in summary
    assert "Interaktivní dashboard" in summary
