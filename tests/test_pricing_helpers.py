from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.data import pricing as pricing_module


class DummyConfigEntry:
    def __init__(self, options=None, data=None):
        self.options = options or {}
        self.data = data or {}


class DummyCoordinator:
    def __init__(self, config_entry=None, spot_data=None):
        self.config_entry = config_entry or DummyConfigEntry()
        self.data = {"spot_prices": spot_data or {}}


class DummySensor:
    def __init__(self, options=None, spot_data=None, hass=None):
        self._config_entry = DummyConfigEntry(options or {})
        self.coordinator = DummyCoordinator(self._config_entry, spot_data or {})
        self._hass = hass
        self._box_id = "123"


class DummyComponent:
    def __init__(self, entities=None):
        self.entities = entities or []

    def get_entity(self, entity_id):
        return next((e for e in self.entities if e.entity_id == entity_id), None)


class DummyEntity:
    def __init__(self, entity_id, spot_data):
        self.entity_id = entity_id
        self._spot_data_15min = spot_data


class DummyHass:
    def __init__(self, data=None):
        self.data = data or {}
        self.config = SimpleNamespace(path=lambda *_args: "/tmp/cache.json")


def test_round_czk():
    assert pricing_module._round_czk(1.234) == 1.23
    assert pricing_module._round_czk(1.235) == 1.24


def test_calculate_commercial_price_percentage():
    config = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 5.0,
    }
    assert pricing_module._calculate_commercial_price(10.0, datetime.now(), config) == 11.0
    assert pricing_module._calculate_commercial_price(-10.0, datetime.now(), config) == -9.5


def test_calculate_commercial_price_fixed_prices(monkeypatch):
    config = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.0,
        "fixed_commercial_price_nt": 3.0,
    }
    monkeypatch.setattr(pricing_module, "get_tariff_for_datetime", lambda *_a, **_k: "VT")
    assert pricing_module._calculate_commercial_price(1.0, datetime.now(), config) == 4.0
    monkeypatch.setattr(pricing_module, "get_tariff_for_datetime", lambda *_a, **_k: "NT")
    assert pricing_module._calculate_commercial_price(1.0, datetime.now(), config) == 3.0


def test_calculate_commercial_price_fixed_fee():
    config = {"spot_pricing_model": "fixed_fee", "spot_fixed_fee_mwh": 100.0}
    assert pricing_module._calculate_commercial_price(1.0, datetime.now(), config) == 1.1


def test_get_distribution_fee(monkeypatch):
    config = {"distribution_fee_vt_kwh": 1.2, "distribution_fee_nt_kwh": 0.8}
    monkeypatch.setattr(pricing_module, "get_tariff_for_datetime", lambda *_a, **_k: "VT")
    assert pricing_module._get_distribution_fee(datetime.now(), config) == 1.2
    monkeypatch.setattr(pricing_module, "get_tariff_for_datetime", lambda *_a, **_k: "NT")
    assert pricing_module._get_distribution_fee(datetime.now(), config) == 0.8


@pytest.mark.asyncio
async def test_resolve_spot_data_fallbacks(monkeypatch):
    sensor = DummySensor(options={}, spot_data={})
    sensor.coordinator = None

    monkeypatch.setattr(pricing_module, "get_spot_data_from_price_sensor", lambda *_a, **_k: {"prices15m_czk_kwh": {"t": 1}})
    result = await pricing_module._resolve_spot_data(sensor, price_type="spot")
    assert result["prices15m_czk_kwh"]["t"] == 1

    sensor._hass = DummyHass()
    monkeypatch.setattr(pricing_module, "get_spot_data_from_price_sensor", lambda *_a, **_k: {})
    async def fake_cache(*_args, **_kwargs):
        return {"prices15m_czk_kwh": {"t": 2}}

    monkeypatch.setattr(pricing_module, "get_spot_data_from_ote_cache", fake_cache)
    result = await pricing_module._resolve_spot_data(sensor, price_type="spot")
    assert result["prices15m_czk_kwh"]["t"] == 2

    called = {"count": 0}

    def fake_price_sensor(*_args, **_kwargs):
        called["count"] += 1
        return {}

    monkeypatch.setattr(pricing_module, "get_spot_data_from_price_sensor", fake_price_sensor)
    sensor._hass = None
    result = await pricing_module._resolve_spot_data(
        sensor, price_type="export", fallback_to_spot=True
    )
    assert result == {}
    assert called["count"] >= 2


def test_get_prices_dict_and_resolve():
    sensor = DummySensor()
    spot_data = {"prices15m_czk_kwh": {"t": 1}}
    prices = pricing_module._get_prices_dict(spot_data, key="prices15m_czk_kwh", sensor=sensor, fallback_type="spot")
    assert prices == {"t": 1}


@pytest.mark.asyncio
async def test_resolve_prices_dict_uses_cache(monkeypatch):
    sensor = DummySensor(hass=DummyHass())
    spot_data = {}
    monkeypatch.setattr(pricing_module, "_get_prices_dict", lambda *_a, **_k: {})
    async def fake_cache(*_args, **_kwargs):
        return {"prices15m_czk_kwh": {"t": 3}}

    monkeypatch.setattr(pricing_module, "get_spot_data_from_ote_cache", fake_cache)
    prices = await pricing_module._resolve_prices_dict(sensor, spot_data, key="prices15m_czk_kwh", fallback_type="spot")
    assert prices == {"t": 3}


def test_get_export_config():
    entry = DummyConfigEntry(options={"export_pricing_model": "fixed_prices"})
    coordinator = DummyCoordinator(entry, {})
    sensor = DummySensor()
    sensor.coordinator = coordinator
    assert pricing_module._get_export_config(sensor)["export_pricing_model"] == "fixed_prices"


def test_get_sensor_component_and_find_entity():
    entity = DummyEntity("sensor.oig_123_spot_price_current_15min", {"prices15m_czk_kwh": {"t": 1}})
    component = DummyComponent([entity])
    hass = DummyHass(data={"entity_components": {"sensor": component}})
    assert pricing_module._get_sensor_component(hass) is component
    assert pricing_module._find_entity(component, entity.entity_id) is entity
    assert pricing_module._find_entity(component, "missing") is None

    hass = DummyHass(data={"sensor": component})
    assert pricing_module._get_sensor_component(hass) is component

    hass = DummyHass(data="bad")
    assert pricing_module._get_sensor_component(hass) is None

    class ListComponent:
        def __init__(self, entities):
            self.entities = entities

    ent = DummyEntity("sensor.oig_123_spot_price_current_15min", {})
    assert pricing_module._find_entity(ListComponent([ent]), ent.entity_id) is ent
    assert pricing_module._find_entity(None, ent.entity_id) is None


def test_derive_export_prices():
    spot_prices = {"t": 10.0}
    config = {"export_pricing_model": "percentage", "export_fee_percent": 10.0}
    assert pricing_module._derive_export_prices(spot_prices, config)["t"] == 9.0
    config = {"export_pricing_model": "fixed_prices", "export_fixed_price": 2.5}
    assert pricing_module._derive_export_prices(spot_prices, config)["t"] == 2.5
    config = {"export_pricing_model": "floor", "export_fee_percent": 3.0}
    assert pricing_module._derive_export_prices(spot_prices, config)["t"] == 7.0


@pytest.mark.asyncio
async def test_get_spot_price_timeline_invalid_timestamp(monkeypatch):
    sensor = DummySensor(options={}, spot_data={"prices15m_czk_kwh": {"bad": 1.0}})
    async def fake_resolve(*_args, **_kwargs):
        return sensor.coordinator.data["spot_prices"]

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    timeline = await pricing_module.get_spot_price_timeline(sensor)
    assert timeline == []


@pytest.mark.asyncio
async def test_get_spot_price_timeline_missing_data(monkeypatch):
    sensor = DummySensor()

    async def fake_resolve(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    timeline = await pricing_module.get_spot_price_timeline(sensor)
    assert timeline == []


@pytest.mark.asyncio
async def test_get_spot_price_timeline_missing_prices(monkeypatch):
    sensor = DummySensor()

    async def fake_resolve(*_args, **_kwargs):
        return {"prices15m_czk_kwh": {}}

    async def fake_prices(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    monkeypatch.setattr(pricing_module, "_resolve_prices_dict", fake_prices)
    timeline = await pricing_module.get_spot_price_timeline(sensor)
    assert timeline == []


@pytest.mark.asyncio
async def test_get_export_price_timeline_derives(monkeypatch):
    sensor = DummySensor(options={}, spot_data={"prices15m_czk_kwh": {"2025-01-01T00:00:00": 1.0}})
    async def fake_resolve(*_args, **_kwargs):
        return sensor.coordinator.data["spot_prices"]

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    timeline = await pricing_module.get_export_price_timeline(sensor)
    assert timeline[0]["price"] > 0


@pytest.mark.asyncio
async def test_get_export_price_timeline_no_spot(monkeypatch):
    sensor = DummySensor()

    async def fake_resolve(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    timeline = await pricing_module.get_export_price_timeline(sensor)
    assert timeline == []


@pytest.mark.asyncio
async def test_get_export_price_timeline_missing_prices(monkeypatch):
    sensor = DummySensor()

    async def fake_resolve(*_args, **_kwargs):
        return {"prices15m_czk_kwh": {}}

    async def fake_prices(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    monkeypatch.setattr(pricing_module, "_resolve_prices_dict", fake_prices)
    timeline = await pricing_module.get_export_price_timeline(sensor)
    assert timeline == []


@pytest.mark.asyncio
async def test_get_export_price_timeline_invalid_timestamp(monkeypatch):
    sensor = DummySensor()

    async def fake_resolve(*_args, **_kwargs):
        return {"export_prices15m_czk_kwh": {"bad": 1.0}}

    async def fake_prices(*_args, **_kwargs):
        return {"bad": 1.0}

    monkeypatch.setattr(pricing_module, "_resolve_spot_data", fake_resolve)
    monkeypatch.setattr(pricing_module, "_resolve_prices_dict", fake_prices)
    timeline = await pricing_module.get_export_price_timeline(sensor)
    assert timeline == []


def test_get_spot_data_from_price_sensor():
    entity = DummyEntity("sensor.oig_123_spot_price_current_15min", {"prices15m_czk_kwh": {"t": 1}})
    export_entity = DummyEntity("sensor.oig_123_export_price_current_15min", {"prices15m_czk_kwh": {"t": 1}})
    component = DummyComponent([entity, export_entity])
    hass = DummyHass(data={"entity_components": {"sensor": component}})
    sensor = DummySensor(hass=hass)
    assert pricing_module.get_spot_data_from_price_sensor(sensor, price_type="spot") == {"prices15m_czk_kwh": {"t": 1}}

    sensor._hass = None
    assert pricing_module.get_spot_data_from_price_sensor(sensor, price_type="spot") is None

    sensor = DummySensor(hass=hass)
    assert pricing_module.get_spot_data_from_price_sensor(sensor, price_type="export") == {"prices15m_czk_kwh": {"t": 1}}

    empty_component = DummyComponent([])
    sensor = DummySensor(hass=DummyHass(data={"entity_components": {"sensor": empty_component}}))
    assert pricing_module.get_spot_data_from_price_sensor(sensor, price_type="spot") is None


def test_get_spot_data_from_price_sensor_exception(monkeypatch):
    sensor = DummySensor(hass=DummyHass())

    def boom(_hass):
        raise RuntimeError("boom")

    monkeypatch.setattr(pricing_module, "_get_sensor_component", boom)
    assert pricing_module.get_spot_data_from_price_sensor(sensor, price_type="spot") is None


@pytest.mark.asyncio
async def test_get_spot_data_from_ote_cache(monkeypatch):
    sensor = DummySensor(hass=DummyHass())

    class DummyOte:
        def __init__(self, cache_path=None):
            self.closed = False

        async def async_load_cached_spot_prices(self):
            return None

        async def get_spot_prices(self):
            return {"prices15m_czk_kwh": {"t": 1}}

        async def close(self):
            self.closed = True

    monkeypatch.setattr(pricing_module, "OteApi", DummyOte)
    data = await pricing_module.get_spot_data_from_ote_cache(sensor)
    assert data["prices15m_czk_kwh"]["t"] == 1


@pytest.mark.asyncio
async def test_get_spot_data_from_ote_cache_no_hass():
    sensor = DummySensor(hass=None)
    data = await pricing_module.get_spot_data_from_ote_cache(sensor)
    assert data is None


@pytest.mark.asyncio
async def test_get_spot_data_from_ote_cache_exception(monkeypatch):
    sensor = DummySensor(hass=DummyHass())

    class BoomOte:
        def __init__(self, cache_path=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(pricing_module, "OteApi", BoomOte)
    data = await pricing_module.get_spot_data_from_ote_cache(sensor)
    assert data is None
