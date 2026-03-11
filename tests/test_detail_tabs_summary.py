from __future__ import annotations

from custom_components.oig_cloud.battery_forecast.presentation import (
    detail_tabs_summary as summary_module,
)


def test_default_metrics_summary():
    metrics = summary_module.default_metrics_summary()
    assert metrics["cost"]["unit"] == "Kč"
    assert metrics["solar"]["unit"] == "kWh"
    assert metrics["consumption"]["unit"] == "kWh"
    assert metrics["grid"]["unit"] == "kWh"


def test_aggregate_interval_metrics():
    intervals = [
        {
            "planned": {"net_cost": 1.25, "solar_kwh": 2.0, "consumption_kwh": 3.0},
            "actual": {"net_cost": 1.5, "solar_kwh": 1.8, "consumption_kwh": 2.9},
        },
        {
            "planned": {
                "net_cost": 1.0,
                "solar_kwh": 0.1,
                "consumption_kwh": 0.2,
                "grid_import_kwh": 0.3,
                "grid_export_kwh": 0.0,
            },
        },
        {
            "planned": {
                "net_cost": 2.0,
                "solar_kwh": 0.5,
                "consumption_kwh": 1.0,
                "grid_import": 1.0,
                "grid_export": 0.2,
            },
            "actual": {
                "grid_import_kwh": 0.8,
                "grid_export_kwh": 0.1,
            },
        },
    ]

    metrics = summary_module.aggregate_interval_metrics(intervals)

    assert metrics["cost"]["plan"] == 4.25
    assert metrics["cost"]["actual"] == 4.5
    assert metrics["cost"]["has_actual"] is True
    assert metrics["grid"]["plan"] == 1.1
    assert metrics["grid"]["actual"] == 1.0


def test_calculate_tab_summary_empty():
    summary = summary_module.calculate_tab_summary(None, [], [])
    assert summary["total_cost"] == 0.0
    assert summary["overall_adherence"] == 100
    assert summary["mode_switches"] == 0
    assert summary["metrics"]["cost"]["plan"] == 0.0


def test_calculate_tab_summary_with_blocks():
    mode_blocks = [
        {"status": "completed", "adherence_pct": 100, "cost_historical": 1.2},
        {"status": "planned", "adherence_pct": 80, "cost_planned": 2.3},
    ]
    summary = summary_module.calculate_tab_summary(None, mode_blocks, [])

    assert summary["total_cost"] == 3.5
    assert summary["overall_adherence"] == 50.0
    assert summary["mode_switches"] == 1
    assert summary["completed_summary"]["count"] == 1
    assert summary["planned_summary"]["count"] == 1
