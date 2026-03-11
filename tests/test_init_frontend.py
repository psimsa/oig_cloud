from __future__ import annotations

from types import SimpleNamespace

import pytest

import custom_components.oig_cloud as init_module
from custom_components.oig_cloud.const import DOMAIN


class DummyHttp:
    def __init__(self):
        self.paths = None

    async def async_register_static_paths(self, paths):
        self.paths = paths


class DummyConfig:
    def path(self, value):
        return f"/tmp/{value}"


class DummyStates:
    def async_entity_ids(self):
        return ["sensor.oig_123_remaining_usable_capacity"]

    def get(self, _entity_id):
        return None


class DummyHass:
    def __init__(self):
        self.data = {}
        self.http = DummyHttp()
        self.config = DummyConfig()
        self.states = DummyStates()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.mark.asyncio
async def test_register_static_paths():
    hass = DummyHass()
    await init_module._register_static_paths(hass)
    assert hass.http.paths


@pytest.mark.asyncio
async def test_setup_frontend_panel_registers(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={"box_id": "123"})
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace(data={"123": {}})}}

    def _read_manifest(_path):
        return '{"version": "1.2.3"}'

    monkeypatch.setattr(init_module, "_read_manifest_file", _read_manifest)
    import time as time_module
    monkeypatch.setattr(time_module, "time", lambda: 42)

    recorded = {}

    def _remove_panel(_hass, panel_id, warn_if_unknown=False):
        recorded["removed"] = panel_id

    def _register_panel(hass, component_name, **kwargs):
        recorded["registered"] = {
            "component": component_name,
            "frontend_url_path": kwargs.get("frontend_url_path"),
            "config": kwargs.get("config"),
        }

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_remove_panel", _remove_panel)
    monkeypatch.setattr(frontend, "async_register_built_in_panel", _register_panel)

    await init_module._setup_frontend_panel(hass, entry)

    assert "registered" in recorded
    assert "oig_cloud_dashboard_entry1" in recorded["registered"]["frontend_url_path"]


@pytest.mark.asyncio
async def test_setup_frontend_panel_resolves_box_id_and_handles_errors(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry2", options={"box_id": "abc"})
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace(data={"456": {}})}}

    def _read_manifest(_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(init_module, "_read_manifest_file", _read_manifest)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "456",
    )

    import homeassistant.components.frontend as frontend

    def _remove_panel(_hass, _panel_id, warn_if_unknown=False):
        raise RuntimeError("remove failed")

    monkeypatch.setattr(frontend, "async_remove_panel", _remove_panel)
    monkeypatch.setattr(frontend, "async_register_built_in_panel", lambda *_a, **_k: None)

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_setup_frontend_panel_missing_register(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})
    hass.data[DOMAIN] = {entry.entry_id: {}}

    monkeypatch.delattr(
        "homeassistant.components.frontend.async_register_built_in_panel",
        raising=False,
    )
    monkeypatch.setattr(
        "homeassistant.components.frontend.async_remove_panel",
        lambda *_a, **_k: None,
    )

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_setup_frontend_panel_noncallable_register(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})
    hass.data[DOMAIN] = {entry.entry_id: {}}

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_register_built_in_panel", 123)

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_setup_frontend_panel_resolve_box_id_error(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace(data={"123": {}})}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_register_built_in_panel", lambda *_a, **_k: None)
    monkeypatch.setattr(frontend, "async_remove_panel", lambda *_a, **_k: None)

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_setup_frontend_panel_entity_checks(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(
        entry_id="entry1",
        options={"box_id": "123", "enable_solar_forecast": True, "enable_battery_prediction": True},
    )
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace(data={"123": {}})}}

    def _read_manifest(_path):
        return '{"version": "1.2.3"}'

    monkeypatch.setattr(init_module, "_read_manifest_file", _read_manifest)

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_register_built_in_panel", lambda *_a, **_k: None)
    monkeypatch.setattr(frontend, "async_remove_panel", lambda *_a, **_k: None)

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_setup_frontend_panel_options_get_raises(monkeypatch):
    class Options:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options=Options())
    hass.data[DOMAIN] = {entry.entry_id: {}}

    await init_module._setup_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_no_method(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})

    monkeypatch.delattr("homeassistant.components.frontend.async_remove_panel", raising=False)

    await init_module._remove_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_success(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_remove_panel", lambda *_a, **_k: None)

    await init_module._remove_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_exception(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})

    def _remove_panel(_hass, _panel_id, warn_if_unknown=False):
        raise RuntimeError("boom")

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_remove_panel", _remove_panel)

    await init_module._remove_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_outer_exception():
    class BadEntry:
        @property
        def entry_id(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    entry = BadEntry()

    await init_module._remove_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_value_error(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})

    def _remove_panel(_hass, _panel_id, warn_if_unknown=False):
        raise ValueError("other error")

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_remove_panel", _remove_panel)

    await init_module._remove_frontend_panel(hass, entry)


@pytest.mark.asyncio
async def test_remove_frontend_panel_unknown(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", options={})

    def _remove_panel(_hass, _panel_id, warn_if_unknown=False):
        raise ValueError("unknown panel")

    import homeassistant.components.frontend as frontend

    monkeypatch.setattr(frontend, "async_remove_panel", _remove_panel)

    await init_module._remove_frontend_panel(hass, entry)
