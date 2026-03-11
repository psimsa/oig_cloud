import pytest

from custom_components.oig_cloud.config.steps import WizardMixin


class DummyWizard(WizardMixin):
    def __init__(self):
        super().__init__()
        self._wizard_data = {}

    async def async_step_wizard_welcome(self):
        return {"type": "welcome"}

    async def async_step_step1(self):
        return {"type": "step1"}


@pytest.mark.asyncio
async def test_handle_back_button_history():
    wizard = DummyWizard()
    wizard._step_history = ["step1", "step2"]
    result = await wizard._handle_back_button("step2")
    assert result["type"] == "step1"


def test_generate_summary_variants():
    wizard = DummyWizard()
    wizard._wizard_data = {
        "username": "user",
        "standard_scan_interval": 10,
        "extended_scan_interval": 20,
        "enable_statistics": True,
        "enable_solar_forecast": True,
        "solar_forecast_mode": "hourly",
        "solar_forecast_string2_enabled": True,
        "solar_forecast_string2_kwp": 3,
        "enable_battery_prediction": True,
        "min_capacity_percent": 10,
        "target_capacity_percent": 90,
        "max_ups_price_czk": 9.9,
        "enable_pricing": True,
        "spot_pricing_model": "fixed",
        "vat_rate": 10.0,
        "enable_extended_sensors": False,
        "enable_dashboard": False,
    }
    summary = wizard._generate_summary()
    assert "Přihlášení" in summary
    assert "Solární předpověď" in summary
