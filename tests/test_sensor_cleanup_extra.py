from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud import sensor as sensor_module


class DummyDevice:
    def __init__(self, name, device_id, identifiers):
        self.name = name
        self.id = device_id
        self.identifiers = identifiers


class DummyDeviceRegistry:
    def __init__(self):
        self.removed = []

    def async_remove_device(self, device_id):
        self.removed.append(device_id)


class DummyEntityRegistry:
    def __init__(self):
        self.removed = []

    def async_remove(self, entity_id):
        self.removed.append(entity_id)


def test_get_device_info_for_sensor():
    sensor_config = {"device_mapping": "analytics"}
    main_info = {"name": "main"}
    analytics_info = {"name": "analytics"}
    shield_info = {"name": "shield"}

    info = sensor_module.get_device_info_for_sensor(
        sensor_config, "123", main_info, analytics_info, shield_info
    )

    assert info["name"] == "analytics"


@pytest.mark.asyncio
async def test_cleanup_removed_devices(monkeypatch):
    device_reg = DummyDeviceRegistry()
    entity_reg = DummyEntityRegistry()
    coordinator = SimpleNamespace(data={"123": {}})

    devices = [
        DummyDevice("box123", "dev1", {("oig_cloud", "123")}),
        DummyDevice("box999", "dev2", {("oig_cloud", "999")}),
        DummyDevice("shield", "dev3", {("oig_cloud", "123_shield")}),
    ]

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_entries_for_config_entry",
        lambda _reg, _entry_id: devices,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, _device_id: [SimpleNamespace(entity_id="sensor.test")],
    )

    entry = SimpleNamespace(entry_id="entry")
    removed = await sensor_module._cleanup_removed_devices(
        device_reg, entity_reg, entry, coordinator
    )

    assert removed == 1
    assert "dev2" in device_reg.removed
    assert "sensor.test" in entity_reg.removed


@pytest.mark.asyncio
async def test_cleanup_empty_devices_internal(monkeypatch):
    device_reg = DummyDeviceRegistry()
    entity_reg = DummyEntityRegistry()
    devices = [
        DummyDevice("empty", "dev1", {("oig_cloud", "123")}),
        DummyDevice("with_entities", "dev2", {("oig_cloud", "456")}),
    ]

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_entries_for_config_entry",
        lambda _reg, _entry_id: devices,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, device_id: []
        if device_id == "dev1"
        else [SimpleNamespace(entity_id="sensor.ok")],
    )

    entry = SimpleNamespace(entry_id="entry")
    removed = await sensor_module._cleanup_empty_devices_internal(
        device_reg, entity_reg, entry
    )

    assert removed == 1
    assert "dev1" in device_reg.removed


@pytest.mark.asyncio
async def test_cleanup_all_orphaned_entities(monkeypatch):
    hass = SimpleNamespace()
    entry = SimpleNamespace(entry_id="entry")

    async def _cleanup_renamed(*_a, **_k):
        return 2

    async def _cleanup_removed(*_a, **_k):
        return 1

    async def _cleanup_empty(*_a, **_k):
        return 3

    monkeypatch.setattr(sensor_module, "_cleanup_renamed_sensors", _cleanup_renamed)
    monkeypatch.setattr(sensor_module, "_cleanup_removed_devices", _cleanup_removed)
    monkeypatch.setattr(
        sensor_module, "_cleanup_empty_devices_internal", _cleanup_empty
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: DummyEntityRegistry(),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: DummyDeviceRegistry(),
    )

    total = await sensor_module._cleanup_all_orphaned_entities(
        hass, entry, coordinator=SimpleNamespace(), expected_sensor_types=set()
    )

    assert total == 6
