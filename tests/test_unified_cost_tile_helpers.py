from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as helpers,
)


class DummyPlansStore:
    def __init__(self, data=None):
        self._data = data

    async def async_load(self):
        return self._data


class DummyCoordinator:
    def __init__(self, spot_prices=None):
        self.data = {"spot_prices": spot_prices or {}}


class DummySensor:
    def __init__(self):
        self._mode_optimization_result = None
        self._plans_store = None
        self._daily_plans_archive = {}
        self.coordinator = None

    async def _build_day_timeline(self, *_args, **_kwargs):
        return None

    def _group_intervals_by_mode(self, intervals, _bucket):
        grouped = {}
        for interval in intervals:
            planned = interval.get("planned") or {}
            actual = interval.get("actual") or {}
            mode = planned.get("mode") or actual.get("mode") or "Unknown"
            grouped.setdefault(mode, []).append(interval)
        return [
            {
                "mode": mode,
                "count": len(items),
            }
            for mode, items in grouped.items()
        ]


def test_build_baseline_comparison_selects_best():
    sensor = DummySensor()
    sensor._mode_optimization_result = {
        "baselines": {
            "HOME_I": {"adjusted_total_cost": 120.0},
            "HOME_II": {"adjusted_total_cost": 110.0},
            "HOME_III": {"adjusted_total_cost": 130.0},
        }
    }

    result = helpers.build_baseline_comparison(sensor, hybrid_cost=100.0)

    assert result["best_baseline"] == "HOME_II"
    assert result["best_baseline_cost"] == 110.0
    assert result["savings"] == 10.0


def test_analyze_today_variance_no_completed():
    text = helpers.analyze_today_variance(
        sensor=None,
        intervals=[],
        plan_total=100.0,
        predicted_total=100.0,
    )

    assert "Den právě začal" in text


def test_analyze_today_variance_with_diffs():
    intervals = [
        {
            "planned": {"solar_kwh": 1.0, "load_kwh": 1.0},
            "actual": {"solar_kwh": 2.0, "load_kwh": 2.0},
        }
    ]

    text = helpers.analyze_today_variance(
        sensor=None,
        intervals=intervals,
        plan_total=100.0,
        predicted_total=120.0,
    )

    assert "Slunce" in text
    assert "Spotřeba" in text
    assert "+20" in text


@pytest.mark.asyncio
async def test_analyze_yesterday_performance_and_tomorrow_plan(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now", lambda: fixed_now)

    async def _timeline_for(date):
        return {
            "intervals": [
                {
                    "planned": {"solar_kwh": 1.0, "load_kwh": 2.0, "net_cost": 3.0},
                    "actual": {"solar_kwh": 1.5, "load_kwh": 1.0, "net_cost": 4.0},
                    "time": "2025-01-01T00:00:00",
                }
            ]
        }

    sensor._build_day_timeline = _timeline_for

    yesterday_text = await helpers.analyze_yesterday_performance(sensor)
    assert "Včera jsme plánovali" in yesterday_text

    tomorrow_text = await helpers.analyze_tomorrow_plan(sensor)
    assert "Zítra plánujeme" in tomorrow_text


@pytest.mark.asyncio
async def test_build_today_cost_data(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyPlansStore({})

    fixed_now = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now", lambda: fixed_now)

    intervals = [
        {
            "time": "2025-01-01T10:00:00+00:00",
            "planned": {"net_cost": 5.0, "mode": "HOME_II", "savings_vs_home_i": 1.0},
            "actual": {"net_cost": 6.0, "mode": "HOME_II", "savings": 0.5},
        },
        {
            "time": "2025-01-01T12:30:00+00:00",
            "planned": {"net_cost": 4.0, "mode": "HOME_UPS", "savings": 1.0},
            "duration_minutes": 60,
        },
        {
            "time": "2025-01-01T14:00:00+00:00",
            "planned": {"net_cost": 7.0, "mode": "HOME_III", "savings_vs_home_i": 2.0},
        },
    ]

    async def _timeline_for(date, *_args, **_kwargs):
        return {"intervals": intervals}

    sensor._build_day_timeline = _timeline_for
    sensor.coordinator = DummyCoordinator(
        spot_prices={
            "timeline": [
                {"time": "2025-01-01T09:00:00+00:00", "spot_price_czk": 1.5},
                {"time": "2025-01-02T09:00:00+00:00", "spot_price_czk": 2.0},
            ]
        }
    )

    data = await helpers.build_today_cost_data(sensor)

    assert data["plan_total_cost"] == 16.0
    assert data["actual_total_cost"] == 6.0
    assert data["completed_intervals"] == 1
    assert data["active_interval"] is not None
    assert data["spot_prices_today"]


def test_resolve_interval_cost_uses_net_cost():
    interval = {"planned": {"net_cost": 5.5}}
    assert helpers.resolve_interval_cost(interval, prefer_actual=False) == 5.5


def test_resolve_interval_cost_fallback_computation():
    interval = {
        "planned": {
            "grid_import_kwh": 2.0,
            "spot_price_czk": 3.0,
            "grid_export_kwh": 1.0,
            "export_price_czk": 1.0,
        }
    }
    assert helpers.resolve_interval_cost(interval, prefer_actual=False) == 5.0


@pytest.mark.asyncio
async def test_build_tomorrow_cost_data(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("custom_components.oig_cloud.battery_forecast.presentation.unified_cost_tile_helpers.dt_util.now", lambda: fixed_now)

    async def _timeline_for(date):
        return {
            "intervals": [
                {"planned": {"net_cost": 4.0, "mode": "HOME_II"}},
                {"planned": {"net_cost": 6.0, "mode": "HOME_II"}},
                {"planned": {"net_cost": 2.0, "mode": "HOME_UPS"}},
            ]
        }

    sensor._build_day_timeline = _timeline_for

    data = await helpers.build_tomorrow_cost_data(sensor)

    assert data["plan_total_cost"] == 12.0
    assert data["dominant_mode_name"] == "HOME_II"


def test_get_yesterday_cost_from_archive():
    sensor = DummySensor()
    yesterday = (dt_util.now().date() - timedelta(days=1)).strftime(helpers.DATE_FMT)
    sensor._daily_plans_archive = {
        yesterday: {
            "plan": [
                {"planned": {"net_cost": 3.0, "mode": "HOME_II"}},
            ],
            "actual": [
                {
                    "planned": {"net_cost": 3.0, "mode": "HOME_II"},
                    "actual": {"net_cost": 4.0, "mode": "HOME_II"},
                    "time": "2025-01-01T00:00:00",
                }
            ],
        }
    }

    data = helpers.get_yesterday_cost_from_archive(sensor, mode_names={})

    assert data["plan_total_cost"] == 3.0
    assert data["actual_total_cost"] == 4.0
    assert data["performance"] in {"better", "worse", "on_plan"}
