from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.oig_cloud.boiler import sensors as module
from custom_components.oig_cloud.boiler.models import BoilerPlan, BoilerProfile, BoilerSlot, EnergySource


class DummyCoordinator:
    def __init__(self, data):
        self.data = data

    def async_add_listener(self, *_a, **_k):
        return lambda: None


def test_boiler_sensor_base_metadata():
    coordinator = DummyCoordinator({})
    sensor = module.BoilerAvgTempSensor(coordinator)
    assert sensor.unique_id.endswith("avg_temp")
    assert sensor.device_info["model"] == "Boiler Control"


def test_current_source_sensor_mapping():
    coordinator = DummyCoordinator({"energy_tracking": {"current_source": "fve"}})
    sensor = module.BoilerCurrentSourceSensor(coordinator)
    assert sensor.native_value == "FVE"

    coordinator = DummyCoordinator({"energy_tracking": {"current_source": "unknown"}})
    sensor = module.BoilerCurrentSourceSensor(coordinator)
    assert sensor.native_value == "unknown"


def test_recommended_source_sensor_mapping():
    coordinator = DummyCoordinator({"recommended_source": None})
    sensor = module.BoilerRecommendedSourceSensor(coordinator)
    assert sensor.native_value is None

    coordinator = DummyCoordinator({"recommended_source": "grid"})
    sensor = module.BoilerRecommendedSourceSensor(coordinator)
    assert sensor.native_value == "Síť"


def test_charging_recommended_sensor_attributes():
    coordinator = DummyCoordinator({"charging_recommended": True, "current_slot": None})
    sensor = module.BoilerChargingRecommendedSensor(coordinator)
    assert sensor.native_value == "ano"
    assert sensor.extra_state_attributes == {}

    slot = BoilerSlot(
        start=datetime(2025, 1, 1, 0, 0),
        end=datetime(2025, 1, 1, 0, 15),
        avg_consumption_kwh=1.23456,
        confidence=0.456,
        recommended_source=EnergySource.GRID,
        spot_price_kwh=2.0,
        overflow_available=True,
    )
    coordinator = DummyCoordinator({"current_slot": slot})
    sensor = module.BoilerChargingRecommendedSensor(coordinator)
    attrs = sensor.extra_state_attributes
    assert attrs["consumption_kwh"] == 1.235
    assert attrs["confidence"] == 0.46


def test_plan_estimated_cost_sensor():
    coordinator = DummyCoordinator({"plan": None})
    sensor = module.BoilerPlanEstimatedCostSensor(coordinator)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}

    plan = BoilerPlan(
        created_at=datetime(2025, 1, 1),
        valid_until=datetime(2025, 1, 2),
        total_consumption_kwh=2.3456,
        estimated_cost_czk=12.3456,
        fve_kwh=1.234,
        grid_kwh=0.5,
        alt_kwh=0.1,
    )
    coordinator = DummyCoordinator({"plan": plan})
    sensor = module.BoilerPlanEstimatedCostSensor(coordinator)
    assert sensor.native_value == 12.35
    attrs = sensor.extra_state_attributes
    assert attrs["total_consumption_kwh"] == 2.35
    assert attrs["created_at"].startswith("2025-01-01")


def test_profile_confidence_sensor():
    coordinator = DummyCoordinator({"profile": None})
    sensor = module.BoilerProfileConfidenceSensor(coordinator)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}

    profile = BoilerProfile(
        category="test",
        hourly_avg={1: 0.1},
        confidence={1: 0.25, 2: 0.75},
        sample_count={1: 2, 2: 3},
        last_updated=datetime(2025, 1, 1),
    )
    coordinator = DummyCoordinator({"profile": profile})
    sensor = module.BoilerProfileConfidenceSensor(coordinator)
    assert sensor.native_value == 50.0
    attrs = sensor.extra_state_attributes
    assert attrs["hours_with_data"] == 1
    assert attrs["total_samples"] == 5


def test_get_boiler_sensors():
    sensors = module.get_boiler_sensors(DummyCoordinator({}))
    assert len(sensors) == 13
