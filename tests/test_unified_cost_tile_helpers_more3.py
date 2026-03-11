from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as helpers,
)


class DummySensor:
    def __init__(self, intervals):
        self._plans_store = None
        self.coordinator = type(
            "Coord",
            (),
            {"data": {"spot_prices": {"timeline": []}}},
        )()
        self._intervals = intervals

    async def _build_day_timeline(self, *_args, **_kwargs):
        return {"intervals": self._intervals}

    def _group_intervals_by_mode(self, intervals, kind):
        return [{"mode": kind, "count": len(intervals)}]


@pytest.mark.asyncio
async def test_build_today_cost_data_active_interval(monkeypatch):
    now = datetime(2025, 1, 1, 10, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(helpers.dt_util, "now", lambda: now)

    def _time(hour):
        return datetime(2025, 1, 1, hour, 0, tzinfo=timezone.utc).isoformat()

    intervals = [
        {
            "time": _time(9),
            "planned": {"net_cost": 5, "mode": "HOME_I", "savings_vs_home_i": 1},
            "actual": {"net_cost": 4, "savings_vs_home_i": 2},
        },
        {
            "time": _time(10),
            "planned": {"net_cost": 6, "mode": "HOME_II", "savings": 1},
            "actual": {"net_cost": 3, "savings": 2},
            "duration_minutes": 60,
        },
        {
            "time": _time(11),
            "planned": {"net_cost": 5, "mode": "HOME_III", "savings_vs_home_i": 1},
        },
    ]
    sensor = DummySensor(intervals)

    result = await helpers.build_today_cost_data(sensor)
    assert result["active_interval"] is not None
    assert result["performance_class"] in ("better", "on_plan", "worse")
