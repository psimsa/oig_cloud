from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as helpers,
)


class DummySensor:
    def __init__(self, intervals, timeline=None, plans_store=None):
        self._intervals = intervals
        self._plans_store = plans_store
        self.coordinator = type(
            "Coord", (), {"data": {"spot_prices": {"timeline": timeline or []}}}
        )()

    async def _build_day_timeline(self, *_args, **_kwargs):
        return {"intervals": self._intervals}

    def _group_intervals_by_mode(self, intervals, kind):
        return [{"mode": kind, "count": len(intervals)}]


def test_build_baseline_comparison_missing_data():
    sensor = SimpleNamespace()
    assert helpers.build_baseline_comparison(sensor, 10.0) == {}


def test_build_baseline_comparison_best_choice():
    sensor = SimpleNamespace(
        _mode_optimization_result={
            "baselines": {
                "HOME_I": {"adjusted_total_cost": 100},
                "HOME_II": {"adjusted_total_cost": 80},
            }
        }
    )
    result = helpers.build_baseline_comparison(sensor, 70.0)
    assert result["best_baseline"] == "HOME_II"
    assert result["savings"] == 10.0


def test_analyze_today_variance_no_completed():
    text = helpers.analyze_today_variance(None, [], 100.0, 120.0)
    assert "Den právě začal" in text


def test_analyze_today_variance_with_diffs():
    intervals = [
        {
            "planned": {"solar_kwh": 1, "load_kwh": 1},
            "actual": {"solar_kwh": 0, "load_kwh": 2},
        }
    ]
    text = helpers.analyze_today_variance(None, intervals, 100.0, 110.0)
    assert "MÉNĚ" in text
    assert "VĚTŠÍ" in text


@pytest.mark.asyncio
async def test_analyze_yesterday_performance_no_data(monkeypatch):
    sensor = DummySensor(intervals=[])

    async def _timeline(_d):
        return None

    sensor._build_day_timeline = _timeline
    text = await helpers.analyze_yesterday_performance(sensor)
    assert "Žádná data" in text


@pytest.mark.asyncio
async def test_analyze_tomorrow_plan_no_intervals():
    sensor = DummySensor(intervals=[])
    text = await helpers.analyze_tomorrow_plan(sensor)
    assert "Žádné intervaly" in text


@pytest.mark.asyncio
async def test_analyze_tomorrow_plan_with_charging(monkeypatch):
    intervals = [
        {
            "planned": {
                "solar_kwh": 16,
                "load_kwh": 5,
                "net_cost": 100,
                "mode": "HOME_UPS",
                "grid_charge_kwh": 1.0,
                "spot_price": 2.0,
                "battery_kwh": 6.0,
            }
        }
    ]
    sensor = DummySensor(intervals=intervals)
    text = await helpers.analyze_tomorrow_plan(sensor)
    assert "slunečno" in text
    assert "nabíjení" in text


@pytest.mark.asyncio
async def test_build_today_cost_data_no_intervals(monkeypatch):
    now = datetime(2025, 1, 1, 10, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(helpers.dt_util, "now", lambda: now)
    sensor = DummySensor(intervals=[])
    result = await helpers.build_today_cost_data(sensor)
    assert result["total_intervals"] == 0
    assert result["progress_pct"] == 0


@pytest.mark.asyncio
async def test_build_today_cost_data_spot_prices(monkeypatch):
    now = datetime(2025, 1, 1, 10, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(helpers.dt_util, "now", lambda: now)
    timeline = [
        {"time": now.isoformat(), "spot_price_czk": 3.5},
        {"time": (now - timedelta(days=1)).isoformat(), "spot_price_czk": 2.0},
    ]
    sensor = DummySensor(
        intervals=[{"time": now.isoformat(), "planned": {"net_cost": 5}}],
        timeline=timeline,
    )
    result = await helpers.build_today_cost_data(sensor)
    assert result["spot_prices_today"]
