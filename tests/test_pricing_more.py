from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.data import pricing as module


class DummyConfigEntry:
    def __init__(self, options=None, data=None):
        self.options = options or {}
        self.data = data or {}


class DummyCoordinator:
    def __init__(self, config_entry, spot_data):
        self.config_entry = config_entry
        self.data = {"spot_prices": spot_data}


class DummyHass:
    def __init__(self, data=None):
        self.data = data or {}
        self.config = SimpleNamespace(path=lambda *parts: "/".join(parts))


class DummyEntity:
    def __init__(self, entity_id, spot_data):
        self.entity_id = entity_id
        self._spot_data_15min = spot_data


class DummyComponent:
    def __init__(self, entity=None, entities=None):
        self._entity = entity
        self.entities = entities or []

    def get_entity(self, entity_id):
        if self._entity and self._entity.entity_id == entity_id:
            return self._entity
        return None


class DummySensor:
    def __init__(self, options=None, spot_data=None, hass=None):
        self._config_entry = DummyConfigEntry(options=options or {})
        self.coordinator = DummyCoordinator(self._config_entry, spot_data or {})
        self._hass = hass
        self._box_id = "123"


def test_round_czk_half_up():
    assert module._round_czk(1.005) == 1.01


def test_calculate_commercial_price_percentage_and_fixed():
    config = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 10.0,
        "spot_negative_fee_percent": 5.0,
    }
    assert module._calculate_commercial_price(10.0, datetime.now(), config) == 11.0
    assert module._calculate_commercial_price(-10.0, datetime.now(), config) == -9.5

    config = {"spot_pricing_model": "fixed", "spot_fixed_fee_mwh": 500.0}
    assert module._calculate_commercial_price(1.0, datetime.now(), config) == 1.5


def test_get_distribution_fee_vt_nt():
    config = {
        "distribution_fee_vt_kwh": 1.5,
        "distribution_fee_nt_kwh": 1.0,
        "dual_tariff_enabled": True,
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
    }
    vt_time = datetime(2025, 1, 2, 10, 0, 0)
    nt_time = datetime(2025, 1, 2, 23, 0, 0)
    assert module._get_distribution_fee(vt_time, config) == 1.5
    assert module._get_distribution_fee(nt_time, config) == 1.0


@pytest.mark.asyncio
async def test_get_spot_price_timeline_invalid_timestamp():
    sensor = DummySensor(
        options={"spot_pricing_model": "percentage"},
        spot_data={"prices15m_czk_kwh": {"bad": 1.0, "2025-01-02T10:00:00": 2.0}},
    )
    timeline = await module.get_spot_price_timeline(sensor)
    assert len(timeline) == 1
    assert timeline[0]["time"] == "2025-01-02T10:00:00"


@pytest.mark.asyncio
async def test_get_export_price_timeline_direct_and_derived():
    sensor = DummySensor(
        options={"export_pricing_model": "percentage", "export_fee_percent": 10.0},
        spot_data={
            "export_prices15m_czk_kwh": {"2025-01-02T10:00:00": 1.5, "bad": 2.0}
        },
    )
    timeline = await module.get_export_price_timeline(sensor)
    assert timeline == [{"time": "2025-01-02T10:00:00", "price": 1.5}]

    sensor = DummySensor(
        options={"export_pricing_model": "percentage", "export_fee_percent": 10.0},
        spot_data={"prices15m_czk_kwh": {"2025-01-02T10:00:00": 2.0}},
    )
    timeline = await module.get_export_price_timeline(sensor)
    assert timeline == [{"time": "2025-01-02T10:00:00", "price": 1.8}]


def test_get_spot_data_from_price_sensor_component_entity():
    spot_payload = {"prices15m_czk_kwh": {"2025-01-02T10:00:00": 2.0}}
    entity = DummyEntity(
        "sensor.oig_123_spot_price_current_15min", spot_payload
    )
    hass = DummyHass(
        data={"entity_components": {"sensor": DummyComponent(entity=entity)}}
    )
    sensor = DummySensor(hass=hass)
    assert (
        module.get_spot_data_from_price_sensor(sensor, price_type="spot")
        == spot_payload
    )


def test_get_spot_data_from_price_sensor_component_entities_list():
    spot_payload = {"prices15m_czk_kwh": {"2025-01-02T10:00:00": 2.0}}
    entity = DummyEntity(
        "sensor.oig_123_spot_price_current_15min", spot_payload
    )
    hass = DummyHass(data={"sensor": DummyComponent(entities=[entity])})
    sensor = DummySensor(hass=hass)
    assert (
        module.get_spot_data_from_price_sensor(sensor, price_type="spot")
        == spot_payload
    )


def test_get_spot_data_from_price_sensor_missing():
    sensor = DummySensor(hass=DummyHass())
    assert module.get_spot_data_from_price_sensor(sensor, price_type="spot") is None


@pytest.mark.asyncio
async def test_get_spot_data_from_ote_cache_error(monkeypatch):
    sensor = DummySensor(hass=DummyHass())

    class DummyOte:
        def __init__(self, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(module, "OteApi", DummyOte)
    assert await module.get_spot_data_from_ote_cache(sensor) is None
