from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.boiler.api_views import (
    BoilerPlanView,
    BoilerProfileView,
    register_boiler_api_views,
)
from custom_components.oig_cloud.boiler.coordinator import BoilerCoordinator
from custom_components.oig_cloud.boiler.models import (
    BoilerPlan,
    BoilerProfile,
    BoilerSlot,
    EnergySource,
)
from custom_components.oig_cloud.boiler.planner import BoilerPlanner
from custom_components.oig_cloud.boiler.profiler import (
    BoilerProfiler,
    _get_profile_category,
)
from custom_components.oig_cloud.boiler.sensors import (
    BoilerChargingRecommendedSensor,
    BoilerPlanEstimatedCostSensor,
    BoilerProfileConfidenceSensor,
    BoilerRecommendedSourceSensor,
    BoilerUpperZoneTempSensor,
    get_boiler_sensors,
)
from custom_components.oig_cloud.boiler.utils import (
    calculate_energy_to_heat,
    calculate_stratified_temp,
    estimate_residual_energy,
    validate_temperature_sensor,
)
from custom_components.oig_cloud.const import (
    CONF_BOILER_ALT_ENERGY_SENSOR,
    CONF_BOILER_SPOT_PRICE_SENSOR,
    CONF_BOILER_TEMP_SENSOR_POSITION,
    CONF_BOILER_TEMP_SENSOR_TOP,
    CONF_BOILER_TWO_ZONE_SPLIT_RATIO,
    CONF_BOILER_VOLUME_L,
    DOMAIN,
)


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyHttp:
    def __init__(self):
        self.views = []

    def register_view(self, view):
        self.views.append(view)


def _response_json(response):
    text = response.text
    if text is None:
        text = response.body.decode("utf-8")
    return json.loads(text)


def test_boiler_utils_stratified_temp_simple_avg():
    upper, lower = calculate_stratified_temp(
        measured_temp=50.0, sensor_position="top", mode="simple_avg"
    )
    assert upper == 50.0
    assert lower == 50.0


def test_boiler_utils_stratified_temp_two_zone():
    upper, lower = calculate_stratified_temp(
        measured_temp=50.0,
        sensor_position="top",
        mode="two_zone",
        split_ratio=0.5,
        boiler_height_m=1.0,
    )
    assert upper > lower


def test_boiler_utils_energy_and_residual():
    assert calculate_energy_to_heat(100, 60, 60) == 0.0
    assert calculate_energy_to_heat(100, 20, 60) > 0.0
    assert estimate_residual_energy(10.0, 6.0, 5.0) == 0.0


def test_boiler_utils_validate_temperature_sensor():
    assert validate_temperature_sensor(None, "sensor.temp") is None
    assert validate_temperature_sensor(DummyState("bad"), "sensor.temp") is None
    assert validate_temperature_sensor(DummyState("200"), "sensor.temp") is None
    assert validate_temperature_sensor(DummyState("25.5"), "sensor.temp") == 25.5


def test_boiler_models_profile_and_plan():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    slot = BoilerSlot(
        start=now,
        end=now + timedelta(minutes=15),
        avg_consumption_kwh=0.5,
        confidence=0.9,
        recommended_source=EnergySource.GRID,
    )
    plan = BoilerPlan(created_at=now, valid_until=now + timedelta(days=1), slots=[slot])
    assert plan.get_current_slot(now) == slot
    assert plan.get_current_slot(now + timedelta(days=2)) is None

    profile = BoilerProfile(category="workday_winter")
    assert profile.get_consumption(10) == (0.0, 0.0)


@pytest.mark.asyncio
async def test_boiler_profiler_update_profiles(monkeypatch, hass):
    profiler = BoilerProfiler(hass, "sensor.boiler_energy", lookback_days=1)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    history_data = [
        {"timestamp": now - timedelta(hours=1), "value_wh": 1000},
        {"timestamp": now, "value_wh": 2000},
    ]

    async def _fetch_history(_start, _end):
        return history_data

    monkeypatch.setattr(profiler, "_fetch_history", _fetch_history)

    profiles = await profiler.async_update_profiles()
    assert profiles
    category = _get_profile_category(now)
    assert profiles[category].hourly_avg


def test_boiler_profiler_get_profile_for_datetime_low_confidence():
    profiler = BoilerProfiler(SimpleNamespace(), "sensor.boiler_energy")
    category = _get_profile_category(datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc))
    profiler._profiles[category] = BoilerProfile(
        category=category,
        hourly_avg={12: 0.5},
        confidence={12: 0.1},
        sample_count={12: 1},
    )
    assert profiler.get_profile_for_datetime(datetime(2025, 1, 2, 12, 0)) is None


@pytest.mark.asyncio
async def test_boiler_profiler_fetch_history_handles_instance(monkeypatch, hass):
    profiler = BoilerProfiler(hass, "sensor.boiler_energy")

    class DummyInstance:
        async def async_add_executor_job(self, _func, *_args):
            return {
                "sensor.boiler_energy": [
                    SimpleNamespace(
                        last_updated=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
                        state="1000",
                    ),
                    SimpleNamespace(
                        last_updated=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
                        state="bad",
                    ),
                ]
            }

    monkeypatch.setattr(
        "custom_components.oig_cloud.boiler.profiler.get_instance",
        lambda _hass: DummyInstance(),
    )

    data = await profiler._fetch_history(
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc),
    )

    assert data == [
        {
            "timestamp": datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
            "value_wh": 1000.0,
        }
    ]


def test_boiler_planner_spot_price_and_recommendations():
    planner = BoilerPlanner(SimpleNamespace(), has_alternative=True, alt_cost_kwh=2.0)
    now = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)
    prices = {
        now.replace(minute=0): 5.0,
        now + timedelta(hours=1): 7.0,
    }

    assert planner._get_spot_price(now, prices) == 5.0
    assert planner._get_spot_price(now + timedelta(hours=2), prices) == 6.0
    assert planner._get_spot_price(now, {}) is None

    assert planner._recommend_source(True, 10.0, 2.0) == EnergySource.FVE
    assert planner._recommend_source(False, None, 2.0) == EnergySource.ALTERNATIVE
    assert planner._recommend_source(False, 10.0, 2.0) == EnergySource.ALTERNATIVE
    assert planner._recommend_source(False, 10.0, 12.0) == EnergySource.GRID


@pytest.mark.asyncio
async def test_boiler_planner_create_plan_and_overflow_windows(monkeypatch):
    planner = BoilerPlanner(SimpleNamespace(), has_alternative=False)
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    profile = BoilerProfile(category="workday_winter", hourly_avg={0: 1.0}, confidence={0: 1.0})
    spot_prices = {now: 3.0}

    overflow_windows = [
        {"start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat(), "soc": 100.0},
        {"start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat(), "soc": 50.0},
    ]
    windows = await planner.async_get_overflow_windows({"overflow_windows": overflow_windows})

    plan = await planner.async_create_plan(
        profile=profile,
        spot_prices=spot_prices,
        overflow_windows=windows,
    )
    assert plan.slots
    assert plan.total_consumption_kwh > 0.0


@pytest.mark.asyncio
async def test_boiler_coordinator_helpers(hass):
    config = {
        CONF_BOILER_TEMP_SENSOR_TOP: "sensor.boiler_top",
        CONF_BOILER_TEMP_SENSOR_POSITION: "top",
        CONF_BOILER_TWO_ZONE_SPLIT_RATIO: 0.5,
        CONF_BOILER_VOLUME_L: 100.0,
        CONF_BOILER_ALT_ENERGY_SENSOR: "sensor.alt_energy",
    }
    coordinator = BoilerCoordinator(hass, config)

    hass.states.async_set("sensor.boiler_top", "50")
    hass.states.async_set("sensor.alt_energy", "500", {"unit_of_measurement": "Wh"})
    hass.states.async_set("sensor.oig_2206237016_boiler_day_w", "1000")
    hass.states.async_set("sensor.oig_2206237016_boiler_manual_mode", "Zapnuto")

    temps = await coordinator._read_temperatures()
    energy_state = coordinator._calculate_energy_state(temps)
    tracking = await coordinator._track_energy_sources()

    assert temps["upper_zone"] is not None
    assert energy_state["energy_needed_kwh"] >= 0.0
    assert tracking["current_source"] == EnergySource.FVE.value
    assert tracking["alt_kwh"] == 0.5


@pytest.mark.asyncio
async def test_boiler_coordinator_spot_prices_and_overflow(hass):
    config = {CONF_BOILER_SPOT_PRICE_SENSOR: "sensor.spot_prices"}
    coordinator = BoilerCoordinator(hass, config)

    hass.states.async_set(
        "sensor.spot_prices",
        "ok",
        {
            "prices": [
                {
                    "datetime": "2025-01-01T10:00:00+00:00",
                    "price": 3.5,
                }
            ]
        },
    )

    prices = await coordinator._get_spot_prices()
    assert list(prices.values()) == [3.5]

    hass.data[DOMAIN] = {"battery_forecast_coordinator": SimpleNamespace(data=None)}
    windows = await coordinator._get_overflow_windows()
    assert windows == []


@pytest.mark.asyncio
async def test_boiler_sensors_and_api_views():
    coordinator = SimpleNamespace(
        data={
            "temperatures": {"upper_zone": 55.0},
            "energy_state": {"avg_temp": 50.0, "energy_needed_kwh": 2.5},
            "energy_tracking": {"current_source": "grid", "total_kwh": 1.2},
            "charging_recommended": True,
            "recommended_source": "fve",
        },
        async_add_listener=lambda _cb: lambda: None,
        last_update_success=True,
    )
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    slot = BoilerSlot(
        start=now,
        end=now + timedelta(minutes=15),
        avg_consumption_kwh=0.5,
        confidence=0.9,
        recommended_source=EnergySource.FVE,
        spot_price_kwh=3.0,
        overflow_available=True,
    )
    plan = BoilerPlan(
        created_at=now,
        valid_until=now + timedelta(days=1),
        slots=[slot],
        total_consumption_kwh=1.0,
        estimated_cost_czk=3.0,
        fve_kwh=1.0,
        grid_kwh=0.0,
        alt_kwh=0.0,
    )
    profile = BoilerProfile(
        category="workday_winter",
        hourly_avg={12: 0.5},
        confidence={12: 0.5},
        sample_count={12: 2},
        last_updated=now,
    )
    coordinator.data["plan"] = plan
    coordinator.data["profile"] = profile
    coordinator.data["current_slot"] = slot

    assert BoilerUpperZoneTempSensor(coordinator).native_value == 55.0
    assert BoilerRecommendedSourceSensor(coordinator).native_value == "FVE"
    assert BoilerChargingRecommendedSensor(coordinator).native_value == "ano"
    assert BoilerPlanEstimatedCostSensor(coordinator).native_value == 3.0
    assert BoilerProfileConfidenceSensor(coordinator).native_value == 50.0

    sensors = get_boiler_sensors(coordinator)
    assert len(sensors) == 13

    hass = SimpleNamespace(
        data={DOMAIN: {"entry1": {"boiler_coordinator": SimpleNamespace(profiler=SimpleNamespace(get_all_profiles=lambda: {"workday_winter": profile}), _current_profile=profile, _current_plan=plan)}}},
        http=DummyHttp(),
    )

    register_boiler_api_views(hass)
    assert len(hass.http.views) == 2

    profile_view = BoilerProfileView(hass)
    response = await profile_view.get(None, "entry1")
    payload = _response_json(response)
    assert payload["current_category"] == "workday_winter"

    plan_view = BoilerPlanView(hass)
    response = await plan_view.get(None, "entry1")
    payload = _response_json(response)
    assert payload["total_consumption_kwh"] == 1.0
