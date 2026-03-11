from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config.steps import ConfigFlow


class DummyState:
    def __init__(self, state):
        self.state = state


class DummyStates:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def get(self, entity_id):
        value = self._mapping.get(entity_id)
        return DummyState(value) if value is not None else None


class DummyConfigFlow(ConfigFlow):
    def __init__(self, states=None):
        super().__init__()
        self.hass = SimpleNamespace(
            config=SimpleNamespace(latitude=50.0, longitude=14.0),
            states=DummyStates(states),
        )

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}


def test_get_total_steps_with_modules():
    flow = DummyConfigFlow()
    flow._wizard_data = {
        "enable_solar_forecast": True,
        "enable_battery_prediction": True,
        "enable_pricing": True,
        "enable_boiler": True,
    }

    assert flow._get_total_steps() == 11


def test_get_total_steps_options_flow():
    flow = DummyConfigFlow()
    flow._step_history = ["wizard_welcome_reconfigure"]
    flow._wizard_data = {}

    assert flow._get_total_steps() == 4


def test_get_step_placeholders_progress():
    flow = DummyConfigFlow()
    flow._wizard_data = {"enable_pricing": True}

    placeholders = flow._get_step_placeholders("wizard_pricing_export")

    assert "Krok" in placeholders["step"]
    assert "info" in placeholders
    assert "▓" in placeholders["progress"]


def test_get_next_step_skips_disabled():
    flow = DummyConfigFlow()
    flow._wizard_data = {
        "enable_solar_forecast": False,
        "enable_battery_prediction": False,
        "enable_pricing": False,
        "enable_boiler": False,
    }

    assert flow._get_next_step("wizard_modules") == "wizard_intervals"


@pytest.mark.asyncio
async def test_wizard_modules_requires_dependencies():
    flow = DummyConfigFlow()

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
async def test_wizard_modules_dashboard_requires_all():
    flow = DummyConfigFlow()

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
    assert "Statistiky" in flow._wizard_data.get("_missing_for_dashboard", [])


@pytest.mark.asyncio
async def test_wizard_intervals_validation_errors():
    flow = DummyConfigFlow(states={})

    result = await flow.async_step_wizard_intervals(
        {
            "standard_scan_interval": 10,
            "extended_scan_interval": 120,
            "data_source_mode": "local_only",
            "local_proxy_stale_minutes": 0,
            "local_event_debounce_ms": 6000,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["standard_scan_interval"] == "interval_too_short"
    assert result["errors"]["extended_scan_interval"] == "extended_interval_too_short"
    assert result["errors"]["local_proxy_stale_minutes"] == "interval_too_short"
    assert result["errors"]["local_event_debounce_ms"] == "interval_too_long"
    assert result["errors"]["data_source_mode"] == "local_proxy_missing"


@pytest.mark.asyncio
async def test_wizard_credentials_back_button(monkeypatch):
    flow = DummyConfigFlow()

    async def _back(_step):
        return {"type": "form", "step_id": "wizard_welcome"}

    monkeypatch.setattr(flow, "_handle_back_button", _back)

    result = await flow.async_step_wizard_credentials({"go_back": True})

    assert result["step_id"] == "wizard_welcome"
