from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as module,
)


def test_analyze_today_variance_no_completed():
    text = module.analyze_today_variance(None, [], 100.0, 120.0)
    assert "žádná data" in text.lower()


def test_analyze_today_variance_diffs():
    intervals = [
        {
            "planned": {"solar_kwh": 1.0, "load_kwh": 1.0},
            "actual": {"solar_kwh": 2.0, "load_kwh": 0.0},
        }
    ]
    text = module.analyze_today_variance(None, intervals, 100.0, 110.0)
    assert "slunce" in text.lower()


@pytest.mark.asyncio
async def test_analyze_yesterday_performance_no_data():
    async def _timeline(_day):
        return None

    sensor = SimpleNamespace(_build_day_timeline=_timeline)
    text = await module.analyze_yesterday_performance(sensor)
    assert "žádná data" in text.lower()


@pytest.mark.asyncio
async def test_analyze_yesterday_performance_empty_intervals():
    async def _timeline(_day):
        return {"intervals": []}

    sensor = SimpleNamespace(_build_day_timeline=_timeline)
    text = await module.analyze_yesterday_performance(sensor)
    assert "žádné intervaly" in text.lower()
