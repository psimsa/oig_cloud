from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.config.steps import OigCloudOptionsFlowHandler
from custom_components.oig_cloud.const import CONF_USERNAME


class DummyConfigEntries:
    def __init__(self):
        self.updated = []
        self.reloaded = []

    def async_update_entry(self, entry, options=None):
        self.updated.append((entry, options))

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class DummyHass:
    def __init__(self):
        self.config_entries = DummyConfigEntries()


class DummyOptionsFlow(OigCloudOptionsFlowHandler):
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    async def async_step_wizard_modules(self, user_input=None):
        return {"type": "modules"}


@pytest.mark.asyncio
async def test_options_flow_welcome_reconfigure():
    entry = SimpleNamespace(entry_id="entry1", data={CONF_USERNAME: "demo"}, options={})
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()

    result = await flow.async_step_wizard_welcome_reconfigure()
    assert result["type"] == "form"

    result = await flow.async_step_wizard_welcome_reconfigure({})
    assert result["type"] == "modules"


@pytest.mark.asyncio
async def test_options_flow_init_redirect():
    entry = SimpleNamespace(entry_id="entry1", data={CONF_USERNAME: "demo"}, options={})
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()

    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_welcome_reconfigure"


@pytest.mark.asyncio
async def test_options_flow_summary_updates_entry():
    entry = SimpleNamespace(
        entry_id="entry1",
        data={CONF_USERNAME: "demo"},
        options={"enable_statistics": True},
    )
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()

    result = await flow.async_step_wizard_summary({})

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert flow.hass.config_entries.updated
    assert flow.hass.config_entries.reloaded == ["entry1"]


@pytest.mark.asyncio
async def test_options_flow_summary_back_button():
    entry = SimpleNamespace(
        entry_id="entry1",
        data={CONF_USERNAME: "demo"},
        options={"enable_statistics": True},
    )
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()
    flow._step_history = ["wizard_modules", "wizard_summary"]

    result = await flow.async_step_wizard_summary({"go_back": True})
    assert result["type"] == "modules"


@pytest.mark.asyncio
async def test_options_flow_summary_form():
    entry = SimpleNamespace(
        entry_id="entry1",
        data={CONF_USERNAME: "demo"},
        options={"enable_statistics": True},
    )
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()
    flow._wizard_data = {
        "enable_statistics": True,
        "enable_solar_forecast": False,
        "enable_battery_prediction": False,
        "enable_pricing": False,
        "enable_extended_sensors": False,
        "enable_dashboard": False,
        "standard_scan_interval": 30,
        "extended_scan_interval": 300,
    }

    result = await flow.async_step_wizard_summary()

    assert result["type"] == "form"
    assert "summary" in result["description_placeholders"]


@pytest.mark.asyncio
async def test_options_flow_summary_exception(monkeypatch):
    entry = SimpleNamespace(
        entry_id="entry1",
        data={CONF_USERNAME: "demo"},
        options={"enable_statistics": True},
    )
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()

    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(flow.hass.config_entries, "async_update_entry", _raise)

    with pytest.raises(RuntimeError):
        await flow.async_step_wizard_summary({})


@pytest.mark.asyncio
async def test_options_flow_summary_flags():
    entry = SimpleNamespace(
        entry_id="entry1",
        data={CONF_USERNAME: "demo"},
        options={"enable_statistics": True},
    )
    flow = DummyOptionsFlow(entry)
    flow.hass = DummyHass()
    flow._wizard_data = {
        "enable_statistics": True,
        "enable_solar_forecast": True,
        "enable_battery_prediction": True,
        "enable_pricing": True,
        "enable_extended_sensors": True,
        "enable_dashboard": True,
        "standard_scan_interval": 30,
        "extended_scan_interval": 300,
    }

    result = await flow.async_step_wizard_summary()
    summary = result["description_placeholders"]["summary"]
    assert "Statistiky a analýzy" in summary
    assert "Solární předpověď" in summary
    assert "Predikce baterie" in summary
    assert "Cenové senzory" in summary
    assert "Rozšířené senzory" in summary
    assert "Webový dashboard" in summary
