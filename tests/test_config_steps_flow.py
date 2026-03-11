from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config.steps import WizardMixin


class DummyWizard(WizardMixin):
    def __init__(self):
        super().__init__()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    async def async_step_wizard_welcome(self, user_input=None):
        return {"type": "welcome"}


def test_total_steps_with_modules_and_summary():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_solar_forecast": True,
        "enable_battery_prediction": True,
        "enable_pricing": True,
        "enable_boiler": True,
    }
    assert flow._get_total_steps() == 11


def test_total_steps_options_flow_reconfigure():
    flow = DummyWizard()
    flow._step_history = ["wizard_welcome_reconfigure"]
    flow._wizard_data = {"enable_pricing": True}
    assert flow._get_total_steps() == 7


def test_current_step_number_pricing_flow():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_solar_forecast": True,
        "enable_battery_prediction": True,
        "enable_pricing": True,
        "enable_boiler": True,
    }
    assert flow._get_current_step_number("wizard_solar") == 5
    assert flow._get_current_step_number("wizard_battery") == 6
    assert flow._get_current_step_number("wizard_pricing_import") == 7
    assert flow._get_current_step_number("wizard_pricing_export") == 8
    assert flow._get_current_step_number("wizard_pricing_distribution") == 9
    assert flow._get_current_step_number("wizard_boiler") == 10
    assert flow._get_current_step_number("wizard_summary") == 11


def test_step_placeholders_progress_bar():
    flow = DummyWizard()
    flow._wizard_data = {"enable_pricing": False}
    placeholders = flow._get_step_placeholders("wizard_intervals")
    assert placeholders["step"].startswith("Krok")
    assert "progress" in placeholders
    assert len(placeholders["progress"]) == flow._get_total_steps()


def test_get_next_step_skips_disabled_modules():
    flow = DummyWizard()
    flow._wizard_data = {
        "enable_solar_forecast": False,
        "enable_battery_prediction": False,
        "enable_pricing": False,
        "enable_boiler": False,
    }
    assert flow._get_next_step("wizard_intervals") == "wizard_summary"

    flow._wizard_data["enable_pricing"] = True
    assert flow._get_next_step("wizard_battery") == "wizard_pricing_import"


@pytest.mark.asyncio
async def test_wizard_intervals_validation_errors():
    flow = DummyWizard()
    result = await flow.async_step_wizard_intervals(
        {
            "standard_scan_interval": 10,
            "extended_scan_interval": 100,
            "data_source_mode": "cloud_only",
            "local_proxy_stale_minutes": 0,
            "local_event_debounce_ms": -1,
        }
    )
    assert result["type"] == "form"
    errors = result.get("errors", {})
    assert errors.get("standard_scan_interval") == "interval_too_short"
    assert errors.get("extended_scan_interval") == "extended_interval_too_short"
    assert errors.get("local_proxy_stale_minutes") == "interval_too_short"
    assert errors.get("local_event_debounce_ms") == "interval_too_short"


@pytest.mark.asyncio
async def test_wizard_intervals_success_path():
    flow = DummyWizard()
    result = await flow.async_step_wizard_intervals(
        {
            "standard_scan_interval": 60,
            "extended_scan_interval": 600,
            "data_source_mode": "cloud_only",
            "local_proxy_stale_minutes": 10,
            "local_event_debounce_ms": 300,
        }
    )
    assert result["type"] == "summary"
    assert flow._wizard_data["standard_scan_interval"] == 60
    assert flow._wizard_data["data_source_mode"] == "cloud_only"
