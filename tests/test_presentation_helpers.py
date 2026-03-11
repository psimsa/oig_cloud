from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.presentation import (
    detail_tabs,
    plan_tabs,
    state_attributes,
    unified_cost_tile_helpers,
)


class DummySensor:
    def __init__(self):
        self._last_update = dt_util.now()
        self._timeline_data = [
            {"battery_capacity_kwh": 5.0, "time": "2025-01-01T00:00:00"}
        ]
        self._data_hash = "hash"
        self._box_id = "123"
        self._charging_metrics = {"charging_metric": 1}
        self._consumption_summary = {"consumption_metric": 2}
        self._balancing_cost = 1.5
        self._active_charging_plan = {"requester": "test"}
        self._plan_status = "pending"
        self._mode_optimization_result = {
            "total_cost_48h": 100.0,
            "total_savings_48h": 10.0,
            "total_cost": 150.0,
            "optimal_modes": [0, 1, 3],
            "optimal_timeline": [{"boiler_charge": 0.2, "curtailed_loss": 0.1}],
            "baselines": {"HOME_I": {"adjusted_total_cost": 120.0}},
            "best_baseline": "HOME_I",
            "hybrid_cost": 110.0,
            "best_baseline_cost": 120.0,
            "savings_vs_best": 10.0,
            "savings_percentage": 8.3,
            "alternatives": {"HOME_II": {"adjusted_total_cost": 130.0}},
        }
        self._baseline_timeline = [{"time": "2025-01-01T00:00:00"}]

    def _get_max_battery_capacity(self):
        return 10.0

    def _get_min_battery_capacity(self):
        return 2.0


def test_build_extra_state_attributes():
    sensor = DummySensor()
    attrs = state_attributes.build_extra_state_attributes(
        sensor, debug_expose_baseline_timeline=True
    )

    assert attrs["current_battery_kwh"] == 5.0
    assert attrs["max_capacity_kwh"] == 10.0
    assert attrs["plan_status"] == "pending"
    assert "timeline_data" in attrs
    assert attrs["mode_optimization"]["best_baseline"] == "HOME_I"


def test_build_extra_state_attributes_uses_balancing_snapshot():
    sensor = DummySensor()
    sensor._balancing_plan_snapshot = {"requester": "balancing"}
    attrs = state_attributes.build_extra_state_attributes(
        sensor, debug_expose_baseline_timeline=False
    )
    assert "active_plan_data" in attrs


def test_calculate_data_hash():
    assert state_attributes.calculate_data_hash([]) == "empty"
    value = state_attributes.calculate_data_hash([{"time": "2025-01-01T00:00:00"}])
    assert len(value) == 64


def test_build_baseline_comparison():
    sensor = DummySensor()
    result = unified_cost_tile_helpers.build_baseline_comparison(sensor, hybrid_cost=90)

    assert result["best_baseline"] == "HOME_I"
    assert result["hybrid_cost"] == 90


def test_analyze_today_variance_text():
    intervals = [
        {
            "planned": {"solar_kwh": 1.0, "load_kwh": 1.0},
            "actual": {"solar_kwh": 0.0, "load_kwh": 2.0},
        }
    ]
    text = unified_cost_tile_helpers.analyze_today_variance(
        None, intervals, plan_total=10, predicted_total=15
    )

    assert "Slunce" in text
    assert "Spotřeba" in text


@pytest.mark.asyncio
async def test_analyze_yesterday_performance():
    class DummySensorForYesterday(DummySensor):
        async def _build_day_timeline(self, _date):
            return {
                "intervals": [
                    {
                        "planned": {"solar_kwh": 1.0, "load_kwh": 1.0, "net_cost": 5},
                        "actual": {"solar_kwh": 0.0, "load_kwh": 2.0, "net_cost": 8},
                    }
                ]
            }

    sensor = DummySensorForYesterday()
    text = await unified_cost_tile_helpers.analyze_yesterday_performance(sensor)

    assert "Včera" in text


def test_decorate_plan_tabs_adds_metadata_and_comparison():
    primary_tabs = {
        "today": {
            "date": "2025-01-01",
            "mode_blocks": [{"status": "planned"}],
            "summary": {},
            "intervals": [],
        }
    }
    secondary_tabs = {
        "today": {
            "mode_blocks": [{"status": "current"}, {"status": "planned"}],
        }
    }

    result = plan_tabs.decorate_plan_tabs(
        primary_tabs, secondary_tabs, "hybrid", "legacy"
    )

    assert result["today"]["metadata"]["active_plan"] == "hybrid"
    assert result["today"]["comparison"]["plan"] == "legacy"


@pytest.mark.asyncio
async def test_build_hybrid_detail_tabs_empty():
    class DummySensorForTabs:
        async def build_timeline_extended(self):
            return {"today": {"date": "2025-01-01", "intervals": []}}

        def _decorate_plan_tabs(self, *, primary_tabs, secondary_tabs, primary_plan, secondary_plan):
            return primary_tabs

    sensor = DummySensorForTabs()
    result = await detail_tabs.build_detail_tabs(sensor, tab="today")

    assert result["today"]["summary"]["total_cost"] == 0.0
