from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from custom_components.oig_cloud.battery_forecast.timeline import extended_summary


def test_aggregate_cost_by_day():
    timeline = [
        {"time": "2025-01-01T00:00:00", "net_cost": 1.0},
        {"time": "2025-01-01T12:00:00", "net_cost": 2.0},
        {"time": "bad", "net_cost": 5.0},
        {"net_cost": 3.0},
    ]
    costs = extended_summary.aggregate_cost_by_day(timeline)
    assert costs["2025-01-01"] == 3.0


def test_get_day_cost_from_timeline():
    timeline = [
        {"time": "2025-01-02T00:00:00", "net_cost": 1.5},
        {"time": "2025-01-03T00:00:00", "net_cost": 2.5},
    ]
    assert (
        extended_summary.get_day_cost_from_timeline(
            timeline, date(2025, 1, 2)
        )
        == 1.5
    )
    assert (
        extended_summary.get_day_cost_from_timeline(
            timeline, date(2025, 1, 4)
        )
        is None
    )
    assert extended_summary.get_day_cost_from_timeline([], date(2025, 1, 1)) is None

    timeline = [{"time": "", "net_cost": 1.0}, {"time": "bad", "net_cost": 2.0}]
    assert (
        extended_summary.get_day_cost_from_timeline(timeline, date(2025, 1, 1))
        is None
    )


def test_format_planned_data():
    planned = {
        "mode": 2,
        "mode_name": "HOME II",
        "battery_soc": 40.123,
        "load_kwh": 1.234,
        "grid_import_kwh": 0.5,
        "grid_export_kwh": 0.2,
        "spot_price_czk": 3.33,
        "net_cost": 1.1,
        "savings_vs_home_i": 0.5,
    }
    formatted = extended_summary.format_planned_data(planned)
    assert formatted["battery_kwh"] == 40.12
    assert formatted["consumption_kwh"] == 1.234
    assert formatted["grid_import"] == 0.5
    assert formatted["grid_export"] == 0.2
    assert formatted["spot_price"] == 3.33


def test_format_actual_data():
    actual = {"net_cost": 2.0, "savings_vs_home_i": 0.4}
    planned = {"savings_vs_home_i": 1.2}
    formatted = extended_summary.format_actual_data(actual, planned=planned)
    assert formatted["savings_vs_home_i"] == 0.4

    formatted = extended_summary.format_actual_data(actual={}, planned=planned)
    assert formatted is None

    formatted = extended_summary.format_actual_data({"net_cost": 1.0}, planned=planned)
    assert formatted["savings_vs_home_i"] == 1.2

    formatted = extended_summary.format_actual_data({"net_cost": 1.0}, planned=None)
    assert formatted["savings_vs_home_i"] == 0


def test_calculate_day_summary():
    intervals = [
        {"planned": {"net_cost": 2.0}, "actual": {"net_cost": 2.5}, "status": "historical"},
        {"planned": {"net_cost": 1.0}, "status": "future"},
    ]
    summary = extended_summary.calculate_day_summary(intervals)
    assert summary["planned_total_cost"] == 3.0
    assert summary["actual_total_cost"] == 2.5
    assert summary["delta_cost"] == -0.5
    assert summary["intervals_count"] == 2
    assert summary["historical_count"] == 1


def test_build_today_tile_summary():
    now = datetime(2025, 1, 2, 10, 7, tzinfo=timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    intervals = [
        {
            "time": (base - timedelta(minutes=15)).replace(tzinfo=None).isoformat(),
            "planned": {"net_cost": 1.0},
            "actual": {"net_cost": 1.2},
            "delta": {"net_cost": 0.2},
        },
        {
            "time": base.isoformat(),
            "planned": {"net_cost": 2.0},
        },
        {
            "time": "bad",
            "planned": {"net_cost": 0.0},
        },
    ]
    summary = extended_summary.build_today_tile_summary(None, intervals, now)
    assert summary["intervals_total"] == 3
    assert summary["intervals_historical"] == 1
    assert summary["confidence"] in {"low", "medium", "good", "high"}
    assert summary["mini_chart_data"]


def test_build_today_tile_summary_handles_missing_time_and_costs():
    now = datetime(2025, 1, 2, 10, 7, tzinfo=timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    intervals = [
        {"time": "", "planned": {"net_cost": 1.0}},
        {
            "time": (base - timedelta(minutes=30)).isoformat(),
            "planned": None,
            "actual": {"net_cost": 1.0},
        },
        {
            "time": (base - timedelta(minutes=15)).isoformat(),
            "planned": 1.0,
            "actual": {"net_cost": 0.5},
        },
        {
            "time": base.isoformat(),
            "planned": {"net_cost": 2.0},
        },
    ]
    summary = extended_summary.build_today_tile_summary(None, intervals, now)
    assert summary["intervals_total"] == 4
    assert summary["confidence"] == "good"


def test_build_today_tile_summary_confidence_low():
    now = datetime(2025, 1, 2, 10, 7, tzinfo=timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    intervals = [
        {"time": base.isoformat(), "planned": {"net_cost": 1.0}},
        {"time": (base + timedelta(minutes=15)).isoformat(), "planned": {"net_cost": 1.0}},
        {"time": (base + timedelta(minutes=30)).isoformat(), "planned": {"net_cost": 1.0}},
        {"time": (base + timedelta(minutes=45)).isoformat(), "planned": {"net_cost": 1.0}},
    ]
    summary = extended_summary.build_today_tile_summary(None, intervals, now)
    assert summary["confidence"] == "low"


def test_build_today_tile_summary_confidence_high():
    now = datetime(2025, 1, 2, 10, 7, tzinfo=timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    intervals = [
        {
            "time": (base - timedelta(minutes=45)).isoformat(),
            "planned": {"net_cost": 1.0},
            "actual": {"net_cost": 1.0},
        },
        {
            "time": (base - timedelta(minutes=30)).isoformat(),
            "planned": {"net_cost": 1.0},
            "actual": {"net_cost": 1.0},
        },
        {
            "time": (base - timedelta(minutes=15)).isoformat(),
            "planned": {"net_cost": 1.0},
            "actual": {"net_cost": 1.0},
        },
        {
            "time": base.isoformat(),
            "planned": {"net_cost": 1.0},
        },
    ]
    summary = extended_summary.build_today_tile_summary(None, intervals, now)
    assert summary["confidence"] == "high"


def test_get_empty_tile_summary():
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    summary = extended_summary.get_empty_tile_summary(now)
    assert summary["confidence"] == "none"


def test_build_today_tile_summary_empty():
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    summary = extended_summary.build_today_tile_summary(None, [], now)
    assert summary["intervals_total"] == 0
