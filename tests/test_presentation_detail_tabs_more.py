from __future__ import annotations

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import detail_tabs


class DummySensor:
    def __init__(self, timeline):
        self._timeline = timeline

    async def build_timeline_extended(self):
        return self._timeline

    def _decorate_plan_tabs(self, *, primary_tabs, secondary_tabs, primary_plan, secondary_plan):
        return {
            "primary": primary_tabs,
            "secondary": secondary_tabs,
            "primary_plan": primary_plan,
            "secondary_plan": secondary_plan,
        }


@pytest.mark.asyncio
async def test_build_hybrid_detail_tabs_invalid_tab_warns():
    sensor = DummySensor({"today": {"intervals": [], "date": "2025-01-01"}})
    result = await detail_tabs.build_hybrid_detail_tabs(sensor, tab="invalid")
    assert "today" in result


@pytest.mark.asyncio
async def test_build_hybrid_detail_tabs_calls_build_timeline():
    sensor = DummySensor({"today": {"intervals": [], "date": "2025-01-01"}})
    result = await detail_tabs.build_hybrid_detail_tabs(sensor, tab="today", timeline_extended=None)
    assert result["today"]["intervals"] == []


@pytest.mark.asyncio
async def test_build_hybrid_detail_tabs_with_intervals(monkeypatch):
    sensor = DummySensor({"today": {"intervals": [{"time": "t"}], "date": "2025-01-01"}})

    monkeypatch.setattr(detail_tabs, "build_mode_blocks_for_tab", lambda *_a, **_k: [{"mode": "Home"}])
    monkeypatch.setattr(detail_tabs, "calculate_tab_summary", lambda *_a, **_k: {"total_cost": 1.0})

    result = await detail_tabs.build_hybrid_detail_tabs(sensor, tab="today")
    assert result["today"]["mode_blocks"]


@pytest.mark.asyncio
async def test_build_detail_tabs_decorates():
    sensor = DummySensor({"today": {"intervals": [], "date": "2025-01-01"}})
    result = await detail_tabs.build_detail_tabs(sensor)
    assert result["primary_plan"] == "hybrid"
