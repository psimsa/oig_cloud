from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.services import get_box_id_from_device
from custom_components.oig_cloud.const import DOMAIN


class DummyCoordinator:
    def __init__(self, data=None, entry=None):
        self.data = data or {}
        self.config_entry = entry


class DummyDevice:
    def __init__(self, identifiers):
        self.identifiers = identifiers


class DummyDeviceRegistry:
    def __init__(self, device=None):
        self._device = device

    def async_get(self, _device_id):
        return self._device


def _make_hass(entry, coordinator, device=None):
    class DummyConfigEntries:
        def async_get_entry(self, _entry_id):
            return entry

    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: {"coordinator": coordinator}}},
        config_entries=DummyConfigEntries(),
    )

    if device is not None:
        device_registry = DummyDeviceRegistry(device)
    else:
        device_registry = DummyDeviceRegistry(None)

    return hass, device_registry


def test_get_box_id_from_entry_option(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={"box_id": "123"}, data={})
    coordinator = DummyCoordinator(data={"999": {}}, entry=entry)
    hass, device_registry = _make_hass(entry, coordinator)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, None, entry.entry_id) == "123"


def test_get_box_id_from_coordinator_data(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    coordinator = DummyCoordinator(data={"456": {}}, entry=entry)
    hass, device_registry = _make_hass(entry, coordinator)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, None, entry.entry_id) == "456"


def test_get_box_id_from_device_identifier(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    coordinator = DummyCoordinator(data={}, entry=entry)
    device = DummyDevice(identifiers={(DOMAIN, "2206237016_shield")})
    hass, device_registry = _make_hass(entry, coordinator, device)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, "device-id", entry.entry_id) == "2206237016"


def test_get_box_id_device_missing(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={"box_id": "777"}, data={})
    coordinator = DummyCoordinator(data={}, entry=entry)
    hass, device_registry = _make_hass(entry, coordinator, device=None)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, "missing", entry.entry_id) == "777"


def test_get_box_id_from_entry_data_inverter_sn(monkeypatch):
    entry = SimpleNamespace(
        entry_id="entry", options={}, data={"inverter_sn": "123456"}
    )
    coordinator = DummyCoordinator(data={}, entry=entry)
    hass, device_registry = _make_hass(entry, coordinator)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, None, entry.entry_id) == "123456"


def test_get_box_id_from_device_identifier_missing_domain(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    coordinator = DummyCoordinator(data={"999": {}}, entry=entry)
    device = DummyDevice(identifiers={("other", "abc")})
    hass, device_registry = _make_hass(entry, coordinator, device)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, "device-id", entry.entry_id) == "999"


def test_get_box_id_none_when_unavailable(monkeypatch):
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    coordinator = DummyCoordinator(data={}, entry=entry)
    hass, device_registry = _make_hass(entry, coordinator)

    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: device_registry,
    )

    assert get_box_id_from_device(hass, None, entry.entry_id) is None
