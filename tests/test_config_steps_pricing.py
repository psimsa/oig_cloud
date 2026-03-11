from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config.steps import WizardMixin


def test_sanitize_data_source_mode():
    assert WizardMixin._sanitize_data_source_mode(None) == "cloud_only"
    assert WizardMixin._sanitize_data_source_mode("hybrid") == "local_only"
    assert WizardMixin._sanitize_data_source_mode("local_only") == "local_only"


def test_migrate_old_pricing_data_percentage_dual():
    data = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 5.0,
        "dual_tariff_enabled": True,
        "export_pricing_model": "percentage",
        "export_fee_percent": 12.0,
    }

    migrated = WizardMixin._migrate_old_pricing_data(data)

    assert migrated["import_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["export_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["import_spot_positive_fee_percent_vt"] == 10.0
    assert migrated["import_spot_negative_fee_percent_nt"] == 5.0
    assert migrated["tariff_vt_start_weekday"] == "6"
    assert migrated["tariff_weekend_same_as_weekday"] is True


def test_migrate_old_pricing_data_fixed_prices_single():
    data = {
        "spot_pricing_model": "fixed_prices",
        "dual_tariff_enabled": False,
        "fixed_commercial_price_vt": 4.2,
        "export_pricing_model": "fixed",
        "export_fixed_fee_czk": 0.3,
    }

    migrated = WizardMixin._migrate_old_pricing_data(data)

    assert migrated["import_pricing_scenario"] == "fix_1tariff"
    assert migrated["import_fixed_price"] == 4.2
    assert migrated["export_pricing_scenario"] == "spot_fixed_1tariff"
    assert migrated["export_spot_fixed_fee_czk"] == 0.3


def test_map_pricing_to_backend():
    wizard_data = {
        "import_pricing_scenario": "spot_fixed",
        "spot_fixed_fee_kwh": 0.55,
        "export_pricing_scenario": "fix_price",
        "export_fixed_price_kwh": 2.6,
        "tariff_count": "dual",
        "distribution_fee_vt_kwh": 1.5,
        "distribution_fee_nt_kwh": 0.9,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
        "tariff_weekend_same_as_weekday": True,
        "vat_rate": 20.0,
    }

    backend = WizardMixin._map_pricing_to_backend(wizard_data)

    assert backend["spot_pricing_model"] == "fixed"
    assert backend["spot_fixed_fee_mwh"] == 550.0
    assert backend["export_pricing_model"] == "fixed_prices"
    assert backend["export_fixed_price"] == 2.6
    assert backend["dual_tariff_enabled"] is True
    assert backend["distribution_fee_nt_kwh"] == 0.9
    assert backend["tariff_vt_start_weekend"] == "6"
    assert backend["vat_rate"] == 20.0


def test_map_backend_to_frontend():
    backend_data = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.4,
        "fixed_commercial_price_nt": 3.1,
        "export_pricing_model": "fixed",
        "export_fixed_fee_czk": 0.25,
        "dual_tariff_enabled": True,
        "distribution_fee_vt_kwh": 1.4,
        "distribution_fee_nt_kwh": 0.8,
        "tariff_vt_start_weekday": "7",
        "tariff_nt_start_weekday": "21,2",
        "tariff_vt_start_weekend": "8",
        "tariff_nt_start_weekend": "23,1",
        "tariff_weekend_same_as_weekday": False,
        "vat_rate": 19.0,
    }

    frontend = WizardMixin._map_backend_to_frontend(backend_data)

    assert frontend["import_pricing_scenario"] == "fix_price"
    assert frontend["fixed_price_vt_kwh"] == 4.4
    assert frontend["fixed_price_nt_kwh"] == 3.1
    assert frontend["export_pricing_scenario"] == "spot_fixed"
    assert frontend["export_fixed_fee_czk"] == 0.25
    assert frontend["tariff_count"] == "dual"
    assert frontend["tariff_weekend_same_as_weekday"] is False
    assert frontend["vat_rate"] == 19.0


class DummyWizard(WizardMixin):
    def __init__(self):
        super().__init__()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    def _get_next_step(self, current_step: str) -> str:
        return "wizard_summary"


@pytest.mark.asyncio
async def test_pricing_import_scenario_switch():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "spot_percentage"}

    result = await flow.async_step_wizard_pricing_import(
        {"import_pricing_scenario": "fix_price"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_import"


@pytest.mark.asyncio
async def test_pricing_import_invalid_fee():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "spot_fixed"}

    result = await flow.async_step_wizard_pricing_import(
        {"import_pricing_scenario": "spot_fixed", "spot_fixed_fee_kwh": 20.0}
    )

    assert result["type"] == "form"
    assert result["errors"]["spot_fixed_fee_kwh"] == "invalid_fee"


@pytest.mark.asyncio
async def test_pricing_import_invalid_negative_fee():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_import(
        {
            "import_pricing_scenario": "spot_percentage",
            "spot_positive_fee_percent": 15.0,
            "spot_negative_fee_percent": 150.0,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["spot_negative_fee_percent"] == "invalid_percentage"


@pytest.mark.asyncio
async def test_pricing_import_invalid_fixed_price():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "fix_price"}
    result = await flow.async_step_wizard_pricing_import(
        {"import_pricing_scenario": "fix_price", "fixed_price_kwh": 50.0}
    )

    assert result["type"] == "form"
    assert result["errors"]["fixed_price_kwh"] == "invalid_price"


@pytest.mark.asyncio
async def test_pricing_import_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_battery", "wizard_pricing_import"]
    result = await flow.async_step_wizard_pricing_import({"go_back": True})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_battery"


@pytest.mark.asyncio
async def test_pricing_import_initial_form():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_import()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_import"


@pytest.mark.asyncio
async def test_pricing_export_invalid_price():
    flow = DummyWizard()
    flow._wizard_data = {"export_pricing_scenario": "fix_price"}

    result = await flow.async_step_wizard_pricing_export(
        {"export_pricing_scenario": "fix_price", "export_fixed_price_kwh": 20.0}
    )

    assert result["type"] == "form"
    assert result["errors"]["export_fixed_price_kwh"] == "invalid_price"


@pytest.mark.asyncio
async def test_pricing_export_invalid_percent():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_export(
        {"export_pricing_scenario": "spot_percentage", "export_fee_percent": 80.0}
    )

    assert result["type"] == "form"
    assert result["errors"]["export_fee_percent"] == "invalid_percentage"


@pytest.mark.asyncio
async def test_pricing_export_invalid_fixed_fee():
    flow = DummyWizard()
    flow._wizard_data = {"export_pricing_scenario": "spot_fixed"}
    result = await flow.async_step_wizard_pricing_export(
        {"export_pricing_scenario": "spot_fixed", "export_fixed_fee_czk": 10.0}
    )

    assert result["type"] == "form"
    assert result["errors"]["export_fixed_fee_czk"] == "invalid_fee"


@pytest.mark.asyncio
async def test_pricing_export_scenario_change():
    flow = DummyWizard()
    flow._wizard_data = {"export_pricing_scenario": "spot_percentage"}
    result = await flow.async_step_wizard_pricing_export(
        {"export_pricing_scenario": "spot_fixed"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_export"


@pytest.mark.asyncio
async def test_pricing_export_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_pricing_import", "wizard_pricing_export"]
    result = await flow.async_step_wizard_pricing_export({"go_back": True})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_import"


@pytest.mark.asyncio
async def test_pricing_export_initial_form():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_export()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_export"


def test_pricing_export_schema_for_scenarios():
    flow = DummyWizard()
    spot_schema = flow._get_pricing_export_schema({"export_pricing_scenario": "spot_percentage"})
    fixed_schema = flow._get_pricing_export_schema({"export_pricing_scenario": "spot_fixed"})
    price_schema = flow._get_pricing_export_schema({"export_pricing_scenario": "fix_price"})

    assert "export_fee_percent" in spot_schema.schema
    assert "export_fixed_fee_czk" in fixed_schema.schema
    assert "export_fixed_price_kwh" in price_schema.schema


def test_pricing_import_schema_defaults_from_wizard_data():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "spot_fixed"}
    schema = flow._get_pricing_import_schema()
    assert "spot_fixed_fee_kwh" in schema.schema


def test_pricing_export_schema_defaults_from_wizard_data():
    flow = DummyWizard()
    flow._wizard_data = {"export_pricing_scenario": "spot_percentage"}
    schema = flow._get_pricing_export_schema()
    assert "export_fee_percent" in schema.schema


@pytest.mark.asyncio
async def test_pricing_export_success():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_export(
        {"export_pricing_scenario": "spot_percentage", "export_fee_percent": 10.0}
    )

    assert result["type"] == "summary"


@pytest.mark.asyncio
async def test_pricing_import_success():
    flow = DummyWizard()
    flow._wizard_data = {"import_pricing_scenario": "fix_price"}

    result = await flow.async_step_wizard_pricing_import(
        {"import_pricing_scenario": "fix_price", "fixed_price_kwh": 4.5}
    )

    assert result["type"] == "summary"
