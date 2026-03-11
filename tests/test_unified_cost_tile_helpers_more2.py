from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.presentation import (
    unified_cost_tile_helpers as helpers,
)


class DummySensor:
    def __init__(self):
        self._daily_plans_archive = {}

    def _group_intervals_by_mode(self, intervals, _kind):
        return [{"mode": (intervals[0].get("planned") or {}).get("mode", "Unknown")}]


def test_resolve_interval_cost_fallback_computed():
    interval = {
        "grid_import_kwh": 2,
        "grid_export_kwh": 1,
        "spot_price_czk": 5,
        "export_price_czk": 2,
    }
    assert helpers.resolve_interval_cost(interval) == 8.0


def test_resolve_interval_cost_invalid_payload():
    assert helpers.resolve_interval_cost(None) == 0.0
    assert helpers.resolve_interval_cost({"net_cost": "bad"}) == 0.0


def test_get_yesterday_cost_from_archive_empty():
    sensor = DummySensor()
    result = helpers.get_yesterday_cost_from_archive(sensor)
    assert result["note"] == "No archive data available"


def test_get_yesterday_cost_from_archive_with_data():
    sensor = DummySensor()
    yesterday = (helpers.dt_util.now().date() - helpers.timedelta(days=1)).strftime(
        helpers.DATE_FMT
    )
    sensor._daily_plans_archive = {
        yesterday: {
            "plan": [{"planned": {"net_cost": 2}}],
            "actual": [
                {
                    "planned": {"net_cost": 2, "mode": "HOME_I"},
                    "actual": {"net_cost": 3, "mode": "HOME_II"},
                    "time": "2025-01-01T00:00:00",
                }
            ],
        }
    }

    result = helpers.get_yesterday_cost_from_archive(sensor, mode_names={})
    assert result["plan_total_cost"] == 2.0
    assert result["actual_total_cost"] == 3.0
    assert result["top_variances"]
