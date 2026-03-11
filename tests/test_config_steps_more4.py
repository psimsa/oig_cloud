from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config import steps as steps_module
from custom_components.oig_cloud.config.steps import ConfigFlow, WizardMixin


class DummyWizard(WizardMixin):
    def __init__(self, states=None) -> None:
        super().__init__()
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=states or (lambda _eid: None)),
            config=SimpleNamespace(latitude=50.0, longitude=14.0),
        )

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    async def async_step_wizard_welcome(self, user_input=None):
        return {"type": "welcome"}

    def _get_next_step(self, _current_step: str) -> str:
        return "wizard_summary"

    async def async_step_wizard_modules(self, user_input=None):
        return {"type": "modules"}

    def _get_modules_schema(self, *_a, **_k):
        return {}

    def _get_credentials_schema(self):
        return {}


class DummyConfigFlow(ConfigFlow):
    def __init__(self):
        super().__init__()
        self.hass = SimpleNamespace(
            config=SimpleNamespace(latitude=50.0, longitude=14.0),
            states=SimpleNamespace(get=lambda _eid: None),
        )

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}


@pytest.mark.asyncio
async def test_wizard_intervals_local_proxy_missing():
    flow = DummyWizard()
    result = await flow.async_step_wizard_intervals(
        {
            "standard_scan_interval": 60,
            "extended_scan_interval": 600,
            "data_source_mode": "local_only",
            "local_proxy_stale_minutes": 10,
            "local_event_debounce_ms": 300,
        }
    )
    assert result["type"] == "form"
    assert result["errors"]["data_source_mode"] == "local_proxy_missing"


@pytest.mark.asyncio
async def test_wizard_solar_validation_errors():
    flow = DummyWizard()
    flow._wizard_data = {
        "solar_forecast_string1_enabled": False,
        "solar_forecast_string2_enabled": False,
    }
    result = await flow.async_step_wizard_solar(
        {
            "solar_forecast_mode": "hourly",
            "solar_forecast_api_key": "",
            "solar_forecast_latitude": 200,
            "solar_forecast_longitude": 200,
            "solar_forecast_string1_enabled": False,
            "solar_forecast_string2_enabled": False,
        }
    )
    assert result["type"] == "form"
    assert result["errors"]["solar_forecast_mode"] == "api_key_required_for_frequent_updates"
    assert result["errors"]["solar_forecast_latitude"] == "invalid_latitude"
    assert result["errors"]["solar_forecast_longitude"] == "invalid_longitude"
    assert result["errors"]["base"] == "no_strings_enabled"


@pytest.mark.asyncio
async def test_wizard_solar_string_param_errors():
    flow = DummyWizard()
    flow._wizard_data = {
        "solar_forecast_string1_enabled": True,
        "solar_forecast_string2_enabled": True,
    }
    result = await flow.async_step_wizard_solar(
        {
            "solar_forecast_mode": "daily_optimized",
            "solar_forecast_api_key": "key",
            "solar_forecast_latitude": 50.0,
            "solar_forecast_longitude": 14.0,
            "solar_forecast_string1_enabled": True,
            "solar_forecast_string1_kwp": 99,
            "solar_forecast_string1_declination": 200,
            "solar_forecast_string1_azimuth": 999,
            "solar_forecast_string2_enabled": True,
            "solar_forecast_string2_kwp": 0,
            "solar_forecast_string2_declination": -1,
            "solar_forecast_string2_azimuth": -10,
        }
    )
    assert result["type"] == "form"
    errors = result["errors"]
    assert errors["solar_forecast_string1_kwp"] == "invalid_kwp"
    assert errors["solar_forecast_string1_declination"] == "invalid_declination"
    assert errors["solar_forecast_string1_azimuth"] == "invalid_azimuth"
    assert errors["solar_forecast_string2_kwp"] == "invalid_kwp"
    assert errors["solar_forecast_string2_declination"] == "invalid_declination"
    assert errors["solar_forecast_string2_azimuth"] == "invalid_azimuth"


@pytest.mark.asyncio
async def test_wizard_solar_initial_form():
    flow = DummyWizard()
    result = await flow.async_step_wizard_solar()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_solar"


@pytest.mark.asyncio
async def test_wizard_welcome_routes():
    flow = DummyWizard()
    async def _credentials(*_a, **_k):
        return {"type": "modules"}

    flow.async_step_wizard_credentials = _credentials
    result = await WizardMixin.async_step_wizard_welcome(flow, {})
    assert result["type"] == "modules"


@pytest.mark.asyncio
async def test_wizard_credentials_live_data_not_enabled(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.LiveDataNotEnabled

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "live_data_not_enabled"


@pytest.mark.asyncio
async def test_wizard_credentials_invalid_auth(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.InvalidAuth

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_wizard_credentials_cannot_connect(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.CannotConnect

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_wizard_credentials_unknown_error(monkeypatch):
    async def _raise(_hass, _data):
        raise RuntimeError("boom")

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyWizard()
    result = await flow.async_step_wizard_credentials(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "unknown"


@pytest.mark.asyncio
async def test_wizard_credentials_initial_form():
    flow = DummyWizard()
    result = await WizardMixin.async_step_wizard_credentials(flow)
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_wizard_modules_go_back():
    flow = DummyWizard()
    flow._step_history = ["wizard_welcome"]
    result = await WizardMixin.async_step_wizard_modules(flow, {"go_back": True})
    assert result["type"] == "welcome"


@pytest.mark.asyncio
async def test_wizard_modules_dashboard_requires_all():
    flow = DummyWizard()
    result = await WizardMixin.async_step_wizard_modules(
        flow,
        {
            "enable_dashboard": True,
            "enable_statistics": False,
            "enable_solar_forecast": False,
            "enable_battery_prediction": False,
            "enable_pricing": False,
            "enable_extended_sensors": False,
        }
    )
    assert result["errors"]["enable_dashboard"] == "dashboard_requires_all"


@pytest.mark.asyncio
async def test_wizard_solar_invalid_coordinates_format():
    flow = DummyWizard()
    flow._wizard_data = {
        "solar_forecast_string1_enabled": True,
        "solar_forecast_string2_enabled": False,
    }
    result = await flow.async_step_wizard_solar(
        {
            "solar_forecast_mode": "daily",
            "solar_forecast_api_key": "key",
            "solar_forecast_latitude": "bad",
            "solar_forecast_longitude": "bad",
            "solar_forecast_string1_enabled": True,
            "solar_forecast_string2_enabled": False,
        }
    )
    assert result["errors"]["base"] == "invalid_coordinates"


@pytest.mark.asyncio
async def test_wizard_solar_invalid_string_params_format():
    flow = DummyWizard()
    flow._wizard_data = {
        "solar_forecast_string1_enabled": True,
        "solar_forecast_string2_enabled": True,
    }
    result = await flow.async_step_wizard_solar(
        {
            "solar_forecast_mode": "daily",
            "solar_forecast_api_key": "key",
            "solar_forecast_latitude": 50.0,
            "solar_forecast_longitude": 14.0,
            "solar_forecast_string1_enabled": True,
            "solar_forecast_string1_kwp": "bad",
            "solar_forecast_string2_enabled": True,
            "solar_forecast_string2_kwp": "bad",
        }
    )
    assert result["errors"]["base"] in ("invalid_string1_params", "invalid_string2_params")


def test_migrate_old_pricing_data_fixed_dual():
    data = {
        "spot_pricing_model": "fixed",
        "spot_fixed_fee_mwh": 800.0,
        "dual_tariff_enabled": True,
    }
    migrated = WizardMixin._migrate_old_pricing_data(data)
    assert migrated["import_pricing_scenario"] == "spot_fixed_2tariff"
    assert migrated["import_spot_fixed_fee_mwh_vt"] == 800.0


def test_map_backend_to_frontend_weekend_same_inferred():
    backend_data = {
        "spot_pricing_model": "percentage",
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_vt_start_weekend": None,
        "tariff_nt_start_weekend": None,
        "tariff_weekend_same_as_weekday": None,
    }
    frontend = WizardMixin._map_backend_to_frontend(backend_data)
    assert frontend["tariff_weekend_same_as_weekday"] is True


def test_map_backend_to_frontend_weekend_same_computed_false():
    backend_data = {
        "spot_pricing_model": "percentage",
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_vt_start_weekend": "8",
        "tariff_nt_start_weekend": "20",
        "tariff_weekend_same_as_weekday": None,
    }
    frontend = WizardMixin._map_backend_to_frontend(backend_data)
    assert frontend["tariff_weekend_same_as_weekday"] is False


def test_get_defaults_non_reconfiguration():
    flow = DummyWizard()
    assert flow._get_defaults() == {}


def test_get_planner_mode_value():
    flow = DummyWizard()
    assert flow._get_planner_mode_value({}) == "hybrid"


def test_get_step_placeholders_fallback():
    flow = DummyWizard()
    placeholders = flow._get_step_placeholders("", current=2, total=5)
    assert placeholders["step"] == "Krok 2 z 5"


def test_get_current_step_number_options_flow():
    flow = DummyWizard()
    flow._step_history = ["wizard_welcome_reconfigure"]
    assert flow._get_current_step_number("wizard_modules") == 2


def test_get_next_step_unknown():
    flow = DummyWizard()
    assert WizardMixin._get_next_step(flow, "missing_step") == "wizard_summary"


def test_get_next_step_skips_to_summary():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_solar_forecast": False,
        "enable_battery_prediction": False,
        "enable_pricing": False,
        "enable_boiler": False,
    }
    assert WizardMixin._get_next_step(flow, "wizard_intervals") == "wizard_summary"


def test_get_next_step_from_summary_returns_summary():
    flow = DummyWizard()
    assert WizardMixin._get_next_step(flow, "wizard_summary") == "wizard_summary"


@pytest.mark.asyncio
async def test_wizard_intervals_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_modules", "wizard_intervals"]
    result = await flow.async_step_wizard_intervals({"go_back": True})
    assert result["type"] == "modules"


@pytest.mark.asyncio
async def test_wizard_intervals_too_long_errors():
    flow = DummyWizard()
    result = await flow.async_step_wizard_intervals(
        {
            "standard_scan_interval": 400,
            "extended_scan_interval": 4000,
            "data_source_mode": "cloud_only",
            "local_proxy_stale_minutes": 200,
            "local_event_debounce_ms": 6000,
        }
    )
    assert result["errors"]["standard_scan_interval"] == "interval_too_long"
    assert result["errors"]["extended_scan_interval"] == "extended_interval_too_long"
    assert result["errors"]["local_proxy_stale_minutes"] == "interval_too_long"
    assert result["errors"]["local_event_debounce_ms"] == "interval_too_long"


@pytest.mark.asyncio
async def test_wizard_solar_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_intervals", "wizard_solar"]
    result = await flow.async_step_wizard_solar({"go_back": True})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_intervals"


@pytest.mark.asyncio
async def test_wizard_battery_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_solar", "wizard_battery"]
    result = await flow.async_step_wizard_battery({"go_back": True})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_solar"


@pytest.mark.asyncio
async def test_wizard_battery_initial_form():
    flow = DummyWizard()
    result = await flow.async_step_wizard_battery()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_battery"


def test_battery_schema_uses_defaults():
    flow = DummyWizard()
    flow._wizard_data = {"min_capacity_percent": 30.0}
    schema = flow._get_battery_schema()
    assert "min_capacity_percent" in schema.schema


@pytest.mark.asyncio
async def test_wizard_summary_not_implemented():
    flow = DummyWizard()
    with pytest.raises(NotImplementedError):
        await WizardMixin.async_step_wizard_summary(flow)


@pytest.mark.asyncio
async def test_quick_setup_ote_api_warning(monkeypatch):
    async def _ok(_hass, _data):
        return {"title": "ok"}

    class DummyOteApi:
        async def get_spot_prices(self):
            return []

    module = types.ModuleType("custom_components.oig_cloud.config.api.ote_api")
    module.OteApi = DummyOteApi
    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.config.api.ote_api", module)
    monkeypatch.setattr(steps_module, "validate_input", _ok)

    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_quick_setup_live_data_not_enabled(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.LiveDataNotEnabled

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "live_data_not_enabled"


@pytest.mark.asyncio
async def test_quick_setup_invalid_auth(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.InvalidAuth

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_quick_setup_unknown_error(monkeypatch):
    async def _raise(_hass, _data):
        raise RuntimeError("boom")

    monkeypatch.setattr(steps_module, "validate_input", _raise)
    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            steps_module.CONF_USERNAME: "user",
            steps_module.CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )
    assert result["errors"]["base"] == "unknown"
