from __future__ import annotations

from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.oig_cloud.config.steps import WizardMixin


def _schema_keys(schema: vol.Schema) -> set[str]:
    return {getattr(key, "schema", key) for key in schema.schema}


class DummyWizard(WizardMixin):
    def __init__(self) -> None:
        super().__init__()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    def _get_next_step(self, current_step: str) -> str:
        return "wizard_summary"


def test_pricing_distribution_schema_weekend_fields():
    flow = DummyWizard()
    flow._wizard_data = {
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": False,
        "import_pricing_scenario": "fix_price",
        "fixed_price_kwh": 4.5,
    }

    schema = flow._get_pricing_distribution_schema()
    keys = _schema_keys(schema)

    assert "tariff_vt_start_weekend" in keys
    assert "tariff_nt_start_weekend" in keys
    assert "fixed_price_vt_kwh" in keys
    assert "fixed_price_nt_kwh" in keys


@pytest.mark.asyncio
async def test_pricing_distribution_weekend_toggle_rerender():
    flow = DummyWizard()
    flow._wizard_data = {
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": True,
    }

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "tariff_weekend_same_as_weekday": False,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_distribution"


@pytest.mark.asyncio
async def test_pricing_distribution_initial_form():
    flow = DummyWizard()
    result = await flow.async_step_wizard_pricing_distribution()

    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_distribution"


@pytest.mark.asyncio
async def test_pricing_distribution_invalid_hours():
    flow = DummyWizard()
    flow._wizard_data = {
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": True,
    }

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "tariff_weekend_same_as_weekday": True,
            "tariff_vt_start_weekday": "bad",
            "tariff_nt_start_weekday": "22,2",
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["tariff_vt_start_weekday"] == "invalid_hour_format"


@pytest.mark.asyncio
async def test_pricing_distribution_invalid_weekend_hours():
    flow = DummyWizard()
    flow._wizard_data = {
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": False,
    }

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "tariff_weekend_same_as_weekday": False,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "tariff_vt_start_weekend": "bad",
            "tariff_nt_start_weekend": "0",
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["tariff_vt_start_weekend"] == "invalid_hour_format"


@pytest.mark.asyncio
async def test_pricing_distribution_back_button():
    flow = DummyWizard()
    flow._step_history = ["wizard_pricing_export", "wizard_pricing_distribution"]
    result = await flow.async_step_wizard_pricing_distribution({"go_back": True})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_export"


def test_pricing_distribution_schema_weekend_diff_defaults():
    flow = DummyWizard()
    schema = flow._get_pricing_distribution_schema(
        {
            "tariff_count": "dual",
            "tariff_weekend_same_as_weekday": None,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "tariff_vt_start_weekend": "8",
            "tariff_nt_start_weekend": "20",
        }
    )
    keys = _schema_keys(schema)
    assert "tariff_weekend_same_as_weekday" in keys


@pytest.mark.asyncio
async def test_pricing_distribution_success_weekend_custom():
    flow = DummyWizard()
    flow._wizard_data = {
        "tariff_count": "dual",
        "tariff_weekend_same_as_weekday": False,
        "import_pricing_scenario": "fix_price",
        "fixed_price_kwh": 4.5,
    }

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "tariff_weekend_same_as_weekday": False,
            "distribution_fee_vt_kwh": 1.1,
            "distribution_fee_nt_kwh": 0.8,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "tariff_vt_start_weekend": "8",
            "tariff_nt_start_weekend": "20",
            "fixed_price_vt_kwh": 4.2,
            "fixed_price_nt_kwh": 3.8,
            "vat_rate": 21.0,
        }
    )

    assert result["type"] == "summary"
    assert flow._wizard_data["tariff_vt_start_weekend"] == "8"
    assert flow._wizard_data["tariff_nt_start_weekend"] == "20"
