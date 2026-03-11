from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config import steps as steps_module
from custom_components.oig_cloud.config.steps import ConfigFlow, WizardMixin


class DummyWizard(WizardMixin):
    def __init__(self) -> None:
        super().__init__()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    async def async_step_wizard_welcome(self, user_input=None):
        return {"type": "welcome"}

    def _get_next_step(self, _current_step: str) -> str:
        return "wizard_summary"


def test_sanitize_data_source_mode_variants():
    assert WizardMixin._sanitize_data_source_mode("hybrid") == "local_only"
    assert WizardMixin._sanitize_data_source_mode(None) == "cloud_only"
    assert WizardMixin._sanitize_data_source_mode("local_only") == "local_only"


def test_config_flow_sanitize_mode_override():
    assert ConfigFlow._sanitize_data_source_mode("hybrid") == "local_only"
    assert ConfigFlow._sanitize_data_source_mode(None) == "cloud_only"


@pytest.mark.asyncio
async def test_pricing_distribution_tariff_change_rerender(monkeypatch):
    flow = DummyWizard()
    flow._wizard_data = {"tariff_count": "single"}

    monkeypatch.setattr(steps_module, "validate_tariff_hours", lambda *_a, **_k: (True, None))

    result = await flow.async_step_wizard_pricing_distribution(
        {"tariff_count": "dual"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "wizard_pricing_distribution"


@pytest.mark.asyncio
async def test_pricing_distribution_invalid_fees_and_vat(monkeypatch):
    flow = DummyWizard()
    flow._wizard_data = {"tariff_count": "dual", "import_pricing_scenario": "fix_price"}

    monkeypatch.setattr(steps_module, "validate_tariff_hours", lambda *_a, **_k: (True, None))

    result = await flow.async_step_wizard_pricing_distribution(
        {
            "tariff_count": "dual",
            "distribution_fee_vt_kwh": 11.0,
            "distribution_fee_nt_kwh": -1.0,
            "fixed_price_vt_kwh": 0.0,
            "fixed_price_nt_kwh": 50.0,
            "tariff_vt_start_weekday": "6",
            "tariff_nt_start_weekday": "22,2",
            "tariff_weekend_same_as_weekday": True,
            "vat_rate": 40.0,
        }
    )

    assert result["type"] == "form"
    errors = result["errors"]
    assert errors["distribution_fee_vt_kwh"] == "invalid_distribution_fee"
    assert errors["distribution_fee_nt_kwh"] == "invalid_distribution_fee"
    assert errors["fixed_price_vt_kwh"] == "invalid_price"
    assert errors["fixed_price_nt_kwh"] == "invalid_price"
    assert errors["vat_rate"] == "invalid_vat"

