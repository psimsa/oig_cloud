from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.const import DOMAIN
from custom_components.oig_cloud import sensor as sensor_module


class DummyCoordinator:
    def __init__(self):
        self.data = {"123": {}}
        self.forced_box_id = "123"

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntries:
    def __init__(self):
        self.updated = []

    def async_update_entry(self, entry, options=None):
        entry.options = options or {}
        self.updated.append(entry)


class DummyHass:
    def __init__(self, entry_id):
        self.data = {DOMAIN: {entry_id: {"coordinator": DummyCoordinator(), "statistics_enabled": True}}}
        self.config_entries = DummyConfigEntries()


class DummyEntry:
    def __init__(self, entry_id="entry1"):
        self.entry_id = entry_id
        self.options = {
            "enable_extended_sensors": True,
            "enable_pricing": True,
            "enable_battery_prediction": True,
            "enable_solar_forecast": True,
            "enable_chmu_warnings": True,
        }
        self.title = "OIG 123"


class DummySensor:
    def __init__(self, *args, **kwargs):
        self.entity_id = "sensor.oig_123_dummy"
        self.device_info = {"identifiers": {("oig_cloud", "123")}}
        self.unique_id = "dummy"


@pytest.mark.asyncio
async def test_sensor_async_setup_entry(monkeypatch):
    entry = DummyEntry()
    hass = DummyHass(entry.entry_id)

    fake_types = {
        "data_one": {"sensor_type_category": "data"},
        "computed_one": {"sensor_type_category": "computed"},
        "extended_one": {"sensor_type_category": "extended"},
        "statistics_one": {"sensor_type_category": "statistics"},
        "solar_one": {"sensor_type_category": "solar_forecast"},
        "shield_one": {"sensor_type_category": "shield"},
        "notification_one": {"sensor_type_category": "notification"},
        "battery_one": {"sensor_type_category": "battery_prediction"},
        "battery_balancing_one": {"sensor_type_category": "battery_balancing"},
        "grid_plan_one": {"sensor_type_category": "grid_charging_plan"},
        "battery_eff_one": {"sensor_type_category": "battery_efficiency"},
        "planner_status_one": {"sensor_type_category": "planner_status"},
        "adaptive_one": {"sensor_type_category": "adaptive_profiles"},
    }

    spot_types = {
        "spot_price_current_15min": {"sensor_type_category": "pricing"},
        "export_price_current_15min": {"sensor_type_category": "pricing"},
        "spot_price_current": {"sensor_type_category": "pricing"},
    }

    chmu_types = {"chmu_one": {"sensor_type_category": "chmu_warnings"}}

    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", fake_types)
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT.SENSOR_TYPES_SPOT",
        spot_types,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU.SENSOR_TYPES_CHMU",
        chmu_types,
    )
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_sensor.OigCloudDataSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.computed_sensor.OigCloudComputedSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.OigCloudStatisticsSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.OigCloudSolarForecastSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.shield_sensor.OigCloudShieldSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_sensor.OigCloudDataSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.analytics_sensor.OigCloudAnalyticsSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.pricing.spot_price_sensor.SpotPrice15MinSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.pricing.spot_price_sensor.ExportPrice15MinSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.OigCloudChmuSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.OigCloudBatteryForecastSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.battery_health_sensor.BatteryHealthSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.battery_balancing_sensor.OigCloudBatteryBalancingSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.grid_charging_sensor.OigCloudGridChargingPlanSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.efficiency_sensor.OigCloudBatteryEfficiencySensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.recommended_sensor.OigCloudPlannerRecommendedModeSensor",
        DummySensor,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.OigCloudAdaptiveLoadProfilesSensor",
        DummySensor,
    )

    added = []

    def _add_entities(entities, _update=False):
        added.extend(entities)

    await sensor_module.async_setup_entry(hass, entry, _add_entities)

    assert added
    assert entry.options.get("box_id") == "123"


@pytest.mark.asyncio
async def test_sensor_async_setup_entry_from_title(monkeypatch):
    entry = DummyEntry()
    entry.title = "OIG 987654"
    entry.options = {
        "enable_extended_sensors": False,
        "enable_pricing": False,
        "enable_battery_prediction": False,
        "enable_solar_forecast": False,
        "enable_chmu_warnings": False,
    }
    hass = DummyHass(entry.entry_id)

    import re

    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", {})
    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "unknown")
    monkeypatch.setattr(sensor_module, "OigCloudDataSourceSensor", DummySensor)
    monkeypatch.setattr(
        re,
        "search",
        lambda _pattern, _string: SimpleNamespace(group=lambda _i: "987654"),
    )

    added = []

    def _add_entities(entities, _update=False):
        added.extend(entities)

    await sensor_module.async_setup_entry(hass, entry, _add_entities)

    assert entry.options.get("box_id") == "987654"
    assert added


@pytest.mark.asyncio
async def test_sensor_async_setup_entry_no_box_id(monkeypatch):
    entry = DummyEntry()
    entry.title = "OIG"
    entry.options = {}
    hass = DummyHass(entry.entry_id)

    monkeypatch.setattr(sensor_module, "resolve_box_id", lambda _c: "unknown")

    added = []

    def _add_entities(entities, _update=False):
        added.extend(entities)

    await sensor_module.async_setup_entry(hass, entry, _add_entities)

    assert not added
