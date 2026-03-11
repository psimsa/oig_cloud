from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config import steps as steps_module


class DummyConfigFlow(steps_module.ConfigFlow):
    def __init__(self):
        super().__init__()
        self.hass = SimpleNamespace()

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, title, data, options=None):
        return {"type": "create_entry", "title": title, "data": data, "options": options}

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}


@pytest.mark.asyncio
async def test_step_user_form():
    flow = DummyConfigFlow()
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_step_user_quick_setup():
    flow = DummyConfigFlow()
    result = await flow.async_step_user({"setup_type": "quick"})
    assert result["type"] == "form"
    assert result["step_id"] == "quick_setup"


@pytest.mark.asyncio
async def test_step_user_wizard():
    flow = DummyConfigFlow()
    result = await flow.async_step_user({"setup_type": "wizard"})
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_welcome"


@pytest.mark.asyncio
async def test_quick_setup_requires_live_data():
    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            "username": "demo",
            "password": "pass",
            "live_data_enabled": False,
        }
    )
    assert result["type"] == "form"
    assert result["errors"]["live_data_enabled"] == "live_data_not_confirmed"


@pytest.mark.asyncio
async def test_quick_setup_success(monkeypatch):
    async def _fake_validate_input(_hass, _data):
        return {"title": "OIG Cloud"}

    monkeypatch.setattr(steps_module, "validate_input", _fake_validate_input)

    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            "username": "demo",
            "password": "pass",
            "live_data_enabled": True,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"]["username"] == "demo"
    assert result["options"]["data_source_mode"] == "cloud_only"


@pytest.mark.asyncio
async def test_import_yaml_not_implemented():
    flow = DummyConfigFlow()
    result = await flow.async_step_import_yaml({})
    assert result["type"] == "abort"
    assert result["reason"] == "not_implemented"


@pytest.mark.asyncio
async def test_wizard_summary_creates_entry():
    flow = DummyConfigFlow()
    flow._wizard_data = {
        "username": "demo",
        "password": "pass",
        "enable_pricing": True,
        "enable_battery_prediction": True,
    }

    result = await flow.async_step_wizard_summary({})

    assert result["type"] == "create_entry"
    assert result["data"]["username"] == "demo"
    assert result["options"]["enable_pricing"] is True


@pytest.mark.asyncio
async def test_wizard_summary_back_button():
    flow = DummyConfigFlow()
    flow._step_history = ["wizard_summary"]
    result = await flow.async_step_wizard_summary({"go_back": True})
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_wizard_summary_form():
    flow = DummyConfigFlow()
    flow._wizard_data = {
        "username": "demo",
        "password": "pass",
    }
    result = await flow.async_step_wizard_summary()
    assert result["type"] == "form"
    assert "summary" in result["description_placeholders"]


def test_async_get_options_flow_handler():
    flow = DummyConfigFlow()
    handler = flow.async_get_options_flow(SimpleNamespace(options={}, data={}))
    assert handler is not None
