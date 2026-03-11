from __future__ import annotations

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import unified_cost_tile


class DummySensor:
    def __init__(self):
        self._box_id = "123"


@pytest.mark.asyncio
async def test_build_unified_cost_tile_yesterday_error(monkeypatch):
    sensor = DummySensor()

    async def _today(_sensor):
        return {"plan_total_cost": 1.0}

    async def _tomorrow(_sensor, mode_names=None):
        return {"plan_total_cost": 2.0}

    def _yesterday(_sensor, mode_names=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(unified_cost_tile, "build_today_cost_data", _today)
    monkeypatch.setattr(unified_cost_tile, "build_tomorrow_cost_data", _tomorrow)
    monkeypatch.setattr(unified_cost_tile, "get_yesterday_cost_from_archive", _yesterday)

    result = await unified_cost_tile.build_unified_cost_tile(sensor)
    assert result["yesterday"]["error"] == "boom"
