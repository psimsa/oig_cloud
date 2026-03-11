from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as helpers,
)


class DummyStore:
    def __init__(self, raise_error: bool = False):
        self._raise_error = raise_error

    async def async_load(self):
        if self._raise_error:
            raise RuntimeError("boom")
        return {}


class DummySensor:
    def __init__(self):
        self._mode_optimization_result = None
        self._plans_store = None
        self._daily_plans_archive = {}
        self.coordinator = None

    async def _build_day_timeline(self, *_a, **_k):
        return {}

    def _group_intervals_by_mode(self, intervals, *_a, **_k):
        return [{"mode": "Home", "interval_count": len(intervals)}]


def test_build_baseline_comparison_empty_and_missing_modes():
    sensor = DummySensor()
    assert helpers.build_baseline_comparison(sensor, 10.0) == {}

    sensor._mode_optimization_result = {"baselines": {}}
    assert helpers.build_baseline_comparison(sensor, 10.0) == {}

    sensor._mode_optimization_result = {"baselines": {"OTHER": {"adjusted_total_cost": 5}}}
    assert helpers.build_baseline_comparison(sensor, 10.0) == {}


def test_analyze_today_variance_small_cost_and_solar_impact():
    intervals = [
        {
            "planned": {"solar_kwh": 0.0, "load_kwh": 1.0},
            "actual": {"solar_kwh": 1.0, "load_kwh": 1.0},
        }
    ]
    text = helpers.analyze_today_variance(None, intervals, plan_total=10.0, predicted_total=10.4)
    assert "přesně dle plánu" in text
    assert "solární výroba" in text


@pytest.mark.asyncio
async def test_analyze_yesterday_performance_on_plan(monkeypatch):
    sensor = DummySensor()

    async def _timeline(_day, *_a, **_k):
        return {
            "intervals": [
                {"planned": {"net_cost": 10, "solar_kwh": 1, "load_kwh": 1}},
                {"actual": {"net_cost": 10, "solar_kwh": 1, "load_kwh": 1}},
            ]
        }

    sensor._build_day_timeline = _timeline

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: datetime(2025, 1, 2),
    )

    text = await helpers.analyze_yesterday_performance(sensor)
    assert "přesně dle plánu" in text


@pytest.mark.asyncio
async def test_analyze_tomorrow_plan_no_timeline():
    sensor = DummySensor()
    text = await helpers.analyze_tomorrow_plan(sensor)
    assert "Žádný plán" in text


@pytest.mark.asyncio
async def test_build_today_cost_data_storage_error_and_filters(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore(raise_error=True)
    sensor.coordinator = SimpleNamespace(
        data={
            "spot_prices": {
                "timeline": [
                    {"time": "", "spot_price_czk": 1.0},
                    {"time": "2025-01-01T12:00:00", "spot_price_czk": 2.0},
                ]
            }
        }
    )

    fixed_now = dt_util.as_local(datetime(2025, 1, 1, 12, 7, 0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: fixed_now,
    )

    async def _timeline(_day, *_a, **_k):
        return None

    sensor._build_day_timeline = _timeline

    data = await helpers.build_today_cost_data(sensor)
    assert data["spot_prices_today"]


@pytest.mark.asyncio
async def test_build_today_cost_data_interval_paths(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore()

    fixed_now = dt_util.as_local(datetime(2025, 1, 1, 12, 0, 0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: fixed_now,
    )

    past_time = (fixed_now - timedelta(minutes=15)).isoformat()
    active_time = fixed_now.isoformat()
    future_time = (fixed_now + timedelta(minutes=15)).isoformat()
    too_late = (fixed_now + timedelta(days=1)).isoformat()

    async def _timeline(_day, *_a, **_k):
        return {
            "intervals": [
                {"planned": {}},
                {"time": too_late, "planned": {}},
                {"time": past_time, "planned": {"net_cost": 1}, "actual": {"net_cost": 5}},
                {
                    "time": active_time,
                    "planned": {"net_cost": 10, "savings": 2},
                    "actual": {"net_cost": -1, "savings": 3},
                    "duration_minutes": 60,
                },
                {"time": future_time, "planned": {"net_cost": 2}},
            ]
        }

    sensor._build_day_timeline = _timeline

    data = await helpers.build_today_cost_data(sensor)
    assert data["performance"] in {"better", "worse", "on_plan"}
    assert data["active_interval"]["performance"] == "better"


@pytest.mark.asyncio
async def test_build_today_cost_data_confidence_high_and_worse(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore()

    fixed_now = dt_util.as_local(datetime(2025, 1, 1, 12, 0, 0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: fixed_now,
    )

    base = fixed_now - timedelta(minutes=15)
    intervals = []
    for i in range(50):
        interval_time = (base - timedelta(minutes=15 * i)).isoformat()
        intervals.append(
            {
                "time": interval_time,
                "planned": {"net_cost": 1, "mode": "Home 1"},
                "actual": {"net_cost": 5, "mode": "Home 1"},
            }
        )

    async def _timeline(_day, *_a, **_k):
        return {"intervals": intervals}

    sensor._build_day_timeline = _timeline

    data = await helpers.build_today_cost_data(sensor)
    assert data["performance"] == "worse"
    assert data["eod_prediction"]["confidence"] == "high"


def test_get_yesterday_cost_from_archive_branches(monkeypatch):
    sensor = DummySensor()
    yesterday = (datetime(2025, 1, 2).date() - timedelta(days=1)).strftime("%Y-%m-%d")
    sensor._daily_plans_archive[yesterday] = {
        "plan": [{"planned": {"net_cost": 10}}],
        "actual": [
            {"time": "t", "planned": {"net_cost": 10, "mode": 1}, "actual": {"net_cost": 5, "mode": None}},
        ],
    }

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: dt_util.as_local(datetime(2025, 1, 2)),
    )

    data = helpers.get_yesterday_cost_from_archive(sensor, mode_names={1: "Home 1"})
    assert data["performance_icon"] == "✅"
    assert data["mode_groups"]

    sensor._daily_plans_archive[yesterday] = {
        "plan": [],
        "actual": [],
    }
    data = helpers.get_yesterday_cost_from_archive(sensor, mode_names={})
    assert data["performance_icon"] == "⚪"

    sensor._daily_plans_archive[yesterday] = {
        "plan": [{"planned": {"net_cost": 10}}],
        "actual": [{"time": "t", "planned": {"net_cost": 10}, "actual": {"net_cost": 10}}],
    }
    data = helpers.get_yesterday_cost_from_archive(sensor, mode_names={})
    assert data["performance_icon"] == "⚪"


def test_resolve_interval_cost_edge_cases():
    assert helpers.resolve_interval_cost(None) == 0.0
    assert helpers.resolve_interval_cost(["bad"]) == 0.0

    interval = {"actual": {"grid_import": "bad", "spot_price": 1}}
    assert helpers.resolve_interval_cost(interval) == 0.0


@pytest.mark.asyncio
async def test_build_tomorrow_cost_data_distribution(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: dt_util.as_local(datetime(2025, 1, 1)),
    )

    async def _timeline(_day, *_a, **_k):
        return {
            "intervals": [
                {"planned": {"mode": 1, "net_cost": 1}},
                {"planned": {"mode": None, "net_cost": 2}},
            ]
        }

    sensor._build_day_timeline = _timeline
    data = await helpers.build_tomorrow_cost_data(sensor, mode_names={1: "Home 1"})
    assert data["mode_distribution"]["Home 1"] == 1
    assert data["mode_distribution"]["Unknown"] == 1


@pytest.mark.asyncio
async def test_build_tomorrow_cost_data_empty_and_no_modes(monkeypatch):
    sensor = DummySensor()
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now",
        lambda: dt_util.as_local(datetime(2025, 1, 1)),
    )

    async def _timeline_empty(_day, *_a, **_k):
        return {"intervals": []}

    sensor._build_day_timeline = _timeline_empty
    data = await helpers.build_tomorrow_cost_data(sensor)
    assert data["plan_total_cost"] == 0.0

    async def _timeline_none(_day, *_a, **_k):
        return {"intervals": [{"planned": {"mode": "Unknown"}}]}

    sensor._build_day_timeline = _timeline_none
    data = await helpers.build_tomorrow_cost_data(sensor)
    assert data["dominant_mode_name"] == "Unknown"
