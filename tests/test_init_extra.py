from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import custom_components.oig_cloud as init_module
from custom_components.oig_cloud.const import DOMAIN


class DummyDevice:
    def __init__(self, device_id, name):
        self.id = device_id
        self.name = name


class DummyDeviceRegistry:
    def __init__(self, devices):
        self.devices = devices
        self.removed = []

    def async_remove_device(self, device_id):
        self.removed.append(device_id)


class DummyEntityRegistry:
    def __init__(self, entities_by_device):
        self.entities_by_device = entities_by_device


class DummyConfigEntries:
    def __init__(self):
        self.updated = []
        self.reloaded = []
        self.unloaded = []

    def async_update_entry(self, entry, options=None):
        entry.options = options or {}
        self.updated.append(entry)

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry, platforms))
        return True

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class DummyHass:
    def __init__(self):
        self.data = {DOMAIN: {}}
        self.config_entries = DummyConfigEntries()

    def async_create_task(self, coro):
        coro.close()
        return object()


@pytest.mark.asyncio
async def test_setup_telemetry_success(monkeypatch):
    hass = SimpleNamespace(data={"core.uuid": "abc"})
    handler = object()

    monkeypatch.setattr(
        "custom_components.oig_cloud.shared.logging.setup_simple_telemetry",
        lambda *_a, **_k: handler,
    )

    await init_module._setup_telemetry(hass, "user@example.com")

    assert hass.data[DOMAIN]["telemetry"] is handler


@pytest.mark.asyncio
async def test_setup_telemetry_no_handler(monkeypatch):
    hass = SimpleNamespace(data={"core.uuid": "abc"})

    monkeypatch.setattr(
        "custom_components.oig_cloud.shared.logging.setup_simple_telemetry",
        lambda *_a, **_k: None,
    )

    await init_module._setup_telemetry(hass, "user@example.com")

    assert DOMAIN not in hass.data or "telemetry" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_setup_telemetry_exception(monkeypatch):
    hass = SimpleNamespace(data={"core.uuid": "abc"})

    def _raise(*_a, **_k):
        raise RuntimeError("fail")

    monkeypatch.setattr(
        "custom_components.oig_cloud.shared.logging.setup_simple_telemetry", _raise
    )

    await init_module._setup_telemetry(hass, "user@example.com")

    assert DOMAIN not in hass.data or "telemetry" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup(monkeypatch):
    hass = SimpleNamespace(data={})
    called = {"static": 0}

    async def fake_register(_hass):
        called["static"] += 1

    monkeypatch.setattr(init_module, "_register_static_paths", fake_register)

    result = await init_module.async_setup(hass, {})

    assert result is True
    assert called["static"] == 1
    assert DOMAIN in hass.data


@pytest.mark.asyncio
async def test_cleanup_unused_devices(monkeypatch):
    devices = [
        DummyDevice("dev1", "OIG Cloud Home"),
        DummyDevice("dev2", "Random Device"),
        DummyDevice("dev3", "ServiceShield"),
    ]
    device_registry = DummyDeviceRegistry(devices)
    entity_registry = DummyEntityRegistry({"dev2": []})

    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="entry1")

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_entries_for_config_entry",
        lambda _reg, _entry_id: devices,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, device_id: entity_registry.entities_by_device.get(device_id, []),
    )

    await init_module._cleanup_unused_devices(hass, entry)

    assert "dev2" in device_registry.removed
    assert "dev1" not in device_registry.removed
    assert "dev3" not in device_registry.removed


@pytest.mark.asyncio
async def test_cleanup_unused_devices_regex_and_remove_error(monkeypatch):
    devices = [
        DummyDevice("dev1", "OIG Test Statistics"),
        DummyDevice("dev2", "Another Device"),
    ]
    device_registry = DummyDeviceRegistry(devices)
    entity_registry = DummyEntityRegistry({"dev1": [], "dev2": []})

    def _remove_device(device_id):
        if device_id == "dev2":
            raise RuntimeError("boom")
        device_registry.removed.append(device_id)

    device_registry.async_remove_device = _remove_device

    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="entry1")

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_entries_for_config_entry",
        lambda _reg, _entry_id: devices,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, device_id: entity_registry.entities_by_device.get(device_id, []),
    )

    await init_module._cleanup_unused_devices(hass, entry)

    assert "dev1" in device_registry.removed


@pytest.mark.asyncio
async def test_cleanup_unused_devices_none_removed(monkeypatch):
    devices = [DummyDevice("dev1", "OIG Cloud Home")]
    device_registry = DummyDeviceRegistry(devices)
    entity_registry = DummyEntityRegistry({"dev1": ["entity"]})

    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="entry1")

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: entity_registry,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_entries_for_config_entry",
        lambda _reg, _entry_id: devices,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, device_id: entity_registry.entities_by_device.get(device_id, []),
    )

    await init_module._cleanup_unused_devices(hass, entry)

    assert device_registry.removed == []


@pytest.mark.asyncio
async def test_async_remove_config_entry_device(monkeypatch):
    device_entry = SimpleNamespace(
        id="dev1", identifiers={(DOMAIN, "123")}
    )
    hass = SimpleNamespace()

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda *_a, **_k: [],
    )

    allowed = await init_module.async_remove_config_entry_device(
        hass, SimpleNamespace(), device_entry
    )

    assert allowed is True

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda *_a, **_k: [SimpleNamespace(entity_id="sensor.test")],
    )

    denied = await init_module.async_remove_config_entry_device(
        hass, SimpleNamespace(), device_entry
    )

    assert denied is False


@pytest.mark.asyncio
async def test_async_remove_config_entry_device_exception(monkeypatch):
    device_entry = SimpleNamespace(id="dev1", identifiers={(DOMAIN, "123")})
    hass = SimpleNamespace()

    def boom(_hass):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        boom,
    )

    allowed = await init_module.async_remove_config_entry_device(
        hass, SimpleNamespace(), device_entry
    )

    assert allowed is False


@pytest.mark.asyncio
async def test_async_unload_entry(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1")
    called = {"remove": 0, "stop": 0, "close": 0}

    async def fake_remove(_hass, _entry):
        called["remove"] += 1

    class DummyController:
        async def async_stop(self):
            called["stop"] += 1

    class DummySession:
        async def close(self):
            called["close"] += 1

    hass.data[DOMAIN][entry.entry_id] = {
        "data_source_controller": DummyController(),
        "session_manager": DummySession(),
    }

    monkeypatch.setattr(init_module, "_remove_frontend_panel", fake_remove)
    result = await init_module.async_unload_entry(hass, entry)

    assert result is True
    assert called["remove"] == 1
    assert called["stop"] == 1
    assert called["close"] == 1
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_handles_stop_error(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1")

    async def fake_remove(_hass, _entry):
        return None

    class DummyController:
        async def async_stop(self):
            raise RuntimeError("boom")

    class DummySession:
        async def close(self):
            return None

    hass.data[DOMAIN][entry.entry_id] = {
        "data_source_controller": DummyController(),
        "session_manager": DummySession(),
    }

    monkeypatch.setattr(init_module, "_remove_frontend_panel", fake_remove)

    result = await init_module.async_unload_entry(hass, entry)

    assert result is True
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_reload_entry(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry1", hass=hass)
    called = {"unload": 0, "setup": 0}

    async def fake_unload(_hass, _entry):
        called["unload"] += 1
        return True

    async def fake_setup(_hass, _entry):
        called["setup"] += 1
        return True

    monkeypatch.setattr(init_module, "async_unload_entry", fake_unload)
    monkeypatch.setattr(init_module, "async_setup_entry", fake_setup)

    await init_module.async_reload_entry(entry)

    assert called["unload"] == 1
    assert called["setup"] == 1


@pytest.mark.asyncio
async def test_async_update_options_disabled(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(
        entry_id="entry1",
        options={"enable_dashboard": False},
    )
    hass.data[DOMAIN][entry.entry_id] = {"config": {}}
    called = {"remove": 0}

    async def fake_remove(_hass, _entry):
        called["remove"] += 1

    monkeypatch.setattr(init_module, "_remove_frontend_panel", fake_remove)

    await init_module.async_update_options(hass, entry)
    assert called["remove"] == 1


@pytest.mark.asyncio
async def test_async_update_options_enable_dashboard(monkeypatch):
    class Options(dict):
        def get(self, key, default=None):
            if key == "enable_dashboard":
                return False
            return super().get(key, default)

    hass = DummyHass()
    entry = SimpleNamespace(
        entry_id="entry1",
        options=Options({"enable_dashboard": True}),
    )
    hass.data[DOMAIN][entry.entry_id] = {"config": {}}
    called = {"setup": 0}

    async def fake_setup(_hass, _entry):
        called["setup"] += 1

    monkeypatch.setattr(init_module, "_setup_frontend_panel", fake_setup)

    await init_module.async_update_options(hass, entry)

    assert called["setup"] == 1
    assert hass.data[DOMAIN][entry.entry_id]["dashboard_enabled"] is True
    assert hass.data[DOMAIN][entry.entry_id]["config"]["enable_dashboard"] is True


@pytest.mark.asyncio
async def test_async_update_options_needs_reload(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(
        entry_id="entry1",
        options={"enable_dashboard": False, "_needs_reload": True},
    )
    hass.data[DOMAIN][entry.entry_id] = {"config": {}}
    hass.async_create_task = lambda coro: asyncio.create_task(coro)

    async def fake_remove(_hass, _entry):
        return None

    monkeypatch.setattr(init_module, "_remove_frontend_panel", fake_remove)

    await init_module.async_update_options(hass, entry)

    await asyncio.sleep(0)
    assert hass.config_entries.reloaded == ["entry1"]


@pytest.mark.asyncio
async def test_async_update_options_disable_dashboard_change(monkeypatch):
    class Options(dict):
        def get(self, key, default=None):
            if key == "enable_dashboard":
                return True
            return super().get(key, default)

    hass = DummyHass()
    entry = SimpleNamespace(
        entry_id="entry1",
        options=Options({"enable_dashboard": False}),
    )
    hass.data[DOMAIN][entry.entry_id] = {"config": {}}
    called = {"remove": 0}

    async def fake_remove(_hass, _entry):
        called["remove"] += 1

    monkeypatch.setattr(init_module, "_remove_frontend_panel", fake_remove)

    await init_module.async_update_options(hass, entry)

    assert called["remove"] == 1


@pytest.mark.asyncio
async def test_cleanup_unused_devices_exception(monkeypatch):
    entry = SimpleNamespace(entry_id="entry1")
    hass = SimpleNamespace()

    def boom(_hass):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        boom,
    )

    await init_module._cleanup_unused_devices(hass, entry)
