from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.api import ha_rest_api as api_module
from custom_components.oig_cloud.const import CONF_AUTO_MODE_SWITCH, DOMAIN


class DummyRequest:
    def __init__(self, hass, query=None):
        self.app = {"hass": hass}
        self.query = query or {}


class DummyComponent:
    def __init__(self, entities):
        self.entities = entities


class DummyEntity:
    def __init__(self, entity_id):
        self.entity_id = entity_id


class DummyConfigEntries:
    def __init__(self, entries=None):
        self._entries = entries or []
        self.updated = []

    def async_entries(self, _domain):
        return self._entries

    def async_update_entry(self, entry, options=None):
        entry.options = options or {}
        self.updated.append(entry)

    def async_get_entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        return None


class DummyHass:
    def __init__(self, config_entries=None):
        self.data = {}
        self.config_entries = config_entries or DummyConfigEntries()


def test_transform_timeline_for_api():
    timeline = [
        {"solar_production_kwh": 1, "consumption_kwh": 2, "grid_charge_kwh": 3}
    ]
    transformed = api_module._transform_timeline_for_api(timeline)
    assert transformed[0]["solar_kwh"] == 1
    assert transformed[0]["load_kwh"] == 2
    assert "solar_production_kwh" not in transformed[0]
    assert "consumption_kwh" not in transformed[0]


def test_find_entry_for_box():
    entry = SimpleNamespace(entry_id="e1", options={})
    coordinator = SimpleNamespace(data={"123": {}})
    hass = DummyHass(config_entries=DummyConfigEntries([entry]))
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}
    assert api_module._find_entry_for_box(hass, "123") == entry

    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace()}}
    assert api_module._find_entry_for_box(hass, "123") is None


@pytest.mark.asyncio
async def test_battery_timeline_store_error_and_missing_entity(monkeypatch):
    class BadStore:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    hass.data["sensor"] = DummyComponent([])
    monkeypatch.setattr("homeassistant.helpers.storage.Store", BadStore)

    view = api_module.OIGCloudBatteryTimelineView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 503


@pytest.mark.asyncio
async def test_battery_timeline_timeline_hybrid(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return {"timeline_hybrid": [{"t": 1}]}

    hass = DummyHass()
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)
    view = api_module.OIGCloudBatteryTimelineView()
    response = await view.get(DummyRequest(hass, {"type": "active"}), "123")
    payload = json.loads(response.text)
    assert payload["active"] == [{"t": 1}]
    assert "baseline" not in payload


@pytest.mark.asyncio
async def test_battery_timeline_entity_precomputed_error(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return None

    class BadStore:
        async def async_load(self):
            raise RuntimeError("boom")

    entity = DummyEntity("sensor.oig_123_battery_forecast")
    entity._precomputed_store = BadStore()
    entity._timeline_data = [{"t": 2}]

    hass = DummyHass()
    hass.data["sensor"] = DummyComponent([entity])
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)

    view = api_module.OIGCloudBatteryTimelineView()
    response = await view.get(DummyRequest(hass, {"type": "active"}), "123")
    payload = json.loads(response.text)
    assert payload["active"] == [{"t": 2}]


@pytest.mark.asyncio
async def test_spot_prices_view_spot_ok():
    hass = DummyHass()
    entity = DummyEntity("sensor.oig_123_spot_price_current_15min")
    entity._spot_data_15min = {"prices15m_czk_kwh": {"t": 2.5}}
    hass.data["sensor"] = DummyComponent([entity])
    view = api_module.OIGCloudSpotPricesView()
    response = await view.get(DummyRequest(hass, {"type": "spot"}), "123")
    payload = json.loads(response.text)
    assert payload["intervals"][0]["price"] == 2.5


@pytest.mark.asyncio
async def test_spot_prices_view_exception():
    hass = DummyHass()
    entity = DummyEntity("sensor.oig_123_export_price_current_15min")
    entity._spot_data_15min = None
    hass.data["sensor"] = DummyComponent([entity])
    view = api_module.OIGCloudSpotPricesView()
    response = await view.get(DummyRequest(hass, {"type": "export"}), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_analytics_view_missing_component():
    hass = DummyHass()
    view = api_module.OIGCloudAnalyticsView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_analytics_view_exception():
    hass = DummyHass()
    entity = DummyEntity("sensor.oig_123_hourly_analytics")
    entity._hourly_prices = None
    hass.data["sensor"] = DummyComponent([entity])
    view = api_module.OIGCloudAnalyticsView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_consumption_profiles_view_exception():
    class BadEntity(DummyEntity):
        def get_current_prediction(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    hass.data["sensor"] = DummyComponent([BadEntity("sensor.oig_123_adaptive_load_profiles")])
    view = api_module.OIGCloudConsumptionProfilesView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_balancing_decisions_warning_path():
    class BadEntity(DummyEntity):
        async def _find_best_matching_balancing_pattern(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    hass.data["entity_components"] = {"sensor": DummyComponent([BadEntity("sensor.oig_123_battery_balancing")])}
    view = api_module.OIGCloudBalancingDecisionsView()
    view.hass = hass
    response = await view.get(DummyRequest(hass), "123")
    payload = json.loads(response.text)
    assert response.status == 200
    assert payload["current_prediction"] is None


@pytest.mark.asyncio
async def test_balancing_decisions_exception():
    view = api_module.OIGCloudBalancingDecisionsView()
    view.hass = SimpleNamespace(data=None)
    response = await view.get(DummyRequest(DummyHass()), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_unified_cost_tile_legacy_key(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return {"unified_cost_tile_hybrid": {"today": {"plan_total_cost": 1}}}

    hass = DummyHass()
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)
    view = api_module.OIGCloudUnifiedCostTileView()
    response = await view.get(DummyRequest(hass), "123")
    payload = json.loads(response.text)
    assert payload["today"]["plan_total_cost"] == 1


@pytest.mark.asyncio
async def test_unified_cost_tile_store_error_component_missing(monkeypatch):
    class BadStore:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    monkeypatch.setattr("homeassistant.helpers.storage.Store", BadStore)
    view = api_module.OIGCloudUnifiedCostTileView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 503


@pytest.mark.asyncio
async def test_unified_cost_tile_build_error(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return None

    class BadEntity(DummyEntity):
        async def build_unified_cost_tile(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    hass.data["sensor"] = DummyComponent([BadEntity("sensor.oig_123_battery_forecast")])
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)
    view = api_module.OIGCloudUnifiedCostTileView()
    response = await view.get(DummyRequest(hass), "123")
    assert response.status == 500


@pytest.mark.asyncio
async def test_detail_tabs_precomputed_hybrid_tab_all(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return {
                "detail_tabs_hybrid": {
                    "today": {"mode_blocks": []},
                    "yesterday": {"mode_blocks": []},
                    "tomorrow": {"mode_blocks": []},
                }
            }

    hass = DummyHass()
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)
    view = api_module.OIGCloudDetailTabsView()
    response = await view.get(DummyRequest(hass, {"tab": "invalid"}), "123")
    payload = json.loads(response.text)
    assert "today" in payload


@pytest.mark.asyncio
async def test_detail_tabs_entity_components_fallback(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return None

    class DetailEntity(DummyEntity):
        async def build_detail_tabs(self, tab=None, plan=None):
            return {"today": {"mode_blocks": []}}

    hass = DummyHass()
    hass.data["entity_components"] = "not-dict"
    hass.data["sensor"] = DummyComponent([DetailEntity("sensor.oig_123_battery_forecast")])
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)
    view = api_module.OIGCloudDetailTabsView()
    response = await view.get(DummyRequest(hass), "123")
    payload = json.loads(response.text)
    assert "today" in payload


@pytest.mark.asyncio
async def test_detail_tabs_precomputed_store_on_entity(monkeypatch):
    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return None

    class EntityStore:
        async def async_load(self):
            return {
                "detail_tabs": {
                    "today": {"mode_blocks": []},
                    "yesterday": {},
                    "tomorrow": {},
                },
                "last_update": "2025-01-01T00:00:00+00:00",
            }

    entity = DummyEntity("sensor.oig_123_battery_forecast")
    entity._precomputed_store = EntityStore()

    hass = DummyHass()
    hass.data["sensor"] = DummyComponent([entity])
    monkeypatch.setattr("homeassistant.helpers.storage.Store", Store)

    view = api_module.OIGCloudDetailTabsView()
    response = await view.get(DummyRequest(hass), "123")
    payload = json.loads(response.text)
    assert "today" in payload


@pytest.mark.asyncio
async def test_planner_settings_post_no_change():
    entry = SimpleNamespace(entry_id="e1", options={CONF_AUTO_MODE_SWITCH: True})
    coordinator = SimpleNamespace(data={"123": {}})
    hass = DummyHass(config_entries=DummyConfigEntries([entry]))
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    class JsonRequest(DummyRequest):
        async def json(self):
            return {}

    view = api_module.OIGCloudPlannerSettingsView()
    response = await view.post(JsonRequest(hass), "123")
    payload = json.loads(response.text)
    assert payload["updated"] is False


@pytest.mark.asyncio
async def test_planner_settings_entry_missing():
    hass = DummyHass()
    view = api_module.OIGCloudPlannerSettingsView()
    response = await view.post(DummyRequest(hass), "missing")
    assert response.status == 404
