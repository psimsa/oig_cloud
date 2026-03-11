from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config import steps as steps_module
from custom_components.oig_cloud.config.steps import (
    CONF_PASSWORD,
    CONF_USERNAME,
    ConfigFlow,
)


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
async def test_async_step_user_routes():
    flow = DummyConfigFlow()

    result = await flow.async_step_user({"setup_type": "wizard"})
    assert result["step_id"] == "wizard_welcome"

    result = await flow.async_step_user({"setup_type": "quick"})
    assert result["step_id"] == "quick_setup"

    result = await flow.async_step_user({"setup_type": "import"})
    assert result["type"] == "abort"


@pytest.mark.asyncio
async def test_quick_setup_live_data_required():
    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            "live_data_enabled": False,
        }
    )

    assert result["type"] == "form"
    assert result["errors"]["live_data_enabled"] == "live_data_not_confirmed"


@pytest.mark.asyncio
async def test_quick_setup_validate_input_error(monkeypatch):
    async def _raise(_hass, _data):
        raise steps_module.CannotConnect

    monkeypatch.setattr(steps_module, "validate_input", _raise)

    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )

    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_quick_setup_success(monkeypatch):
    async def _ok(_hass, _data):
        return {"title": "ok"}

    monkeypatch.setattr(steps_module, "validate_input", _ok)

    flow = DummyConfigFlow()
    result = await flow.async_step_quick_setup(
        {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            "live_data_enabled": True,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_USERNAME] == "user"
