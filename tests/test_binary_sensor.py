from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud import binary_sensor as bs_module
from custom_components.oig_cloud.binary_sensor_types import BINARY_SENSOR_TYPES
from custom_components.oig_cloud.const import DOMAIN


class DummyHass:
    def __init__(self, language="cs"):
        self.config = SimpleNamespace(language=language)
        self.data = {}


class DummyCoordinator:
    def __init__(self, hass, data):
        self.hass = hass
        self.data = data

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyApi:
    async def get_stats(self):
        return {
            "123": {
                "tbl": {"flag": 1, "flag2": 0},
            }
        }


class DummyDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_method, update_interval):
        self.hass = hass
        self.data = None
        self._update_method = update_method

    async def async_config_entry_first_refresh(self):
        self.data = await self._update_method()


def test_binary_sensor_types_present():
    assert "chmu_warning_active" in BINARY_SENSOR_TYPES


@pytest.mark.asyncio
async def test_binary_sensor_basic(monkeypatch):
    monkeypatch.setattr(
        bs_module,
        "BINARY_SENSOR_TYPES",
        {
            "warn": {
                "name": "Warning",
                "name_cs": "Varovani",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag",
            }
        },
    )

    hass = DummyHass(language="cs")
    coordinator = DummyCoordinator(hass, {"123": {"tbl": {"flag": 1}}})
    sensor = bs_module.OigCloudBinarySensor(coordinator, "warn")
    sensor.hass = hass

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    await sensor.async_added_to_hass()

    assert sensor.name == "Varovani"
    assert sensor.unique_id == "oig_cloud_123_warn"
    assert sensor.is_on is True
    assert sensor.device_class is None
    assert sensor.should_poll is False


@pytest.mark.asyncio
async def test_async_setup_entry_creates_entities(monkeypatch):
    monkeypatch.setattr(bs_module, "DataUpdateCoordinator", DummyDataUpdateCoordinator)
    monkeypatch.setattr(
        bs_module,
        "BINARY_SENSOR_TYPES",
        {
            "warn": {
                "name": "Warning",
                "name_cs": "Varovani",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag",
            },
            "warn2": {
                "name": "Warning2",
                "name_cs": "Varovani2",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag2",
            },
        },
    )

    hass = DummyHass(language="en")
    entry = SimpleNamespace(entry_id="entry")
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "api": DummyApi(),
            "standard_scan_interval": 30,
        }
    }

    added = {}

    def _add_entities(entities):
        added["entities"] = entities

    await bs_module.async_setup_entry(hass, entry, _add_entities)

    assert len(added["entities"]) == 2
    assert all(isinstance(ent, bs_module.OigCloudBinarySensor) for ent in added["entities"])


@pytest.mark.asyncio
async def test_binary_sensor_name_unique_and_errors(monkeypatch):
    monkeypatch.setattr(
        bs_module,
        "BINARY_SENSOR_TYPES",
        {
            "warn": {
                "name": "Warning",
                "name_cs": "Varovani",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag",
            }
        },
    )

    hass = DummyHass(language="en")
    coordinator = DummyCoordinator(hass, {"123": {"tbl": {"flag": 0}}})
    sensor = bs_module.OigCloudBinarySensor(coordinator, "warn")
    sensor.hass = hass

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )
    await sensor.async_added_to_hass()

    assert sensor.name == "Warning"
    assert sensor.is_on is False

    # Missing box id/data returns None.
    sensor._box_id = None
    assert sensor.unique_id is None
    assert sensor.is_on is None

    # Error in coordinator data returns None.
    sensor._box_id = "123"
    sensor.coordinator.data = {"123": {"tbl": {}}}
    assert sensor.is_on is None


@pytest.mark.asyncio
async def test_binary_sensor_device_info_variants(monkeypatch):
    monkeypatch.setattr(
        bs_module,
        "BINARY_SENSOR_TYPES",
        {
            "warn": {
                "name": "Warning",
                "name_cs": "Varovani",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag",
            }
        },
    )

    hass = DummyHass(language="en")
    coordinator = DummyCoordinator(hass, {"123": {"tbl": {"flag": 1}, "queen": True}})
    sensor = bs_module.OigCloudBinarySensor(coordinator, "warn")
    sensor.hass = hass

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )
    await sensor.async_added_to_hass()

    info = sensor.device_info
    assert info["model"].endswith("Queen")

    # No box id returns None.
    sensor._box_id = None
    assert sensor.device_info is None

    # Coordinator data failure returns None.
    sensor._box_id = "123"
    sensor.coordinator.data = None
    assert sensor.device_info is None


@pytest.mark.asyncio
async def test_binary_sensor_added_to_hass_error(monkeypatch):
    monkeypatch.setattr(
        bs_module,
        "BINARY_SENSOR_TYPES",
        {
            "warn": {
                "name": "Warning",
                "name_cs": "Varovani",
                "device_class": None,
                "node_id": "tbl",
                "node_key": "flag",
            }
        },
    )

    hass = DummyHass(language="en")
    coordinator = DummyCoordinator(hass, {})
    sensor = bs_module.OigCloudBinarySensor(coordinator, "warn")
    sensor.hass = hass

    def _boom(_coord):
        raise RuntimeError("bad resolve")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        _boom,
    )

    await sensor.async_added_to_hass()
    assert sensor.unique_id is None
