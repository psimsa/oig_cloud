from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.oig_cloud.battery_forecast.presentation import (
    detail_tabs_blocks as blocks_module,
)


def test_determine_block_status_fixed_tabs():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    interval = {"time": now.isoformat()}

    assert (
        blocks_module.determine_block_status(interval, interval, "yesterday", now)
        == "completed"
    )
    assert (
        blocks_module.determine_block_status(interval, interval, "tomorrow", now)
        == "planned"
    )


def test_determine_block_status_current_and_planned():
    now = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)
    current_start = {"time": datetime(2025, 1, 1, 12, 30).isoformat()}
    current_end = {"time": datetime(2025, 1, 1, 12, 30).isoformat()}
    planned_start = {"time": datetime(2025, 1, 1, 13, 0).isoformat()}

    assert (
        blocks_module.determine_block_status(current_start, current_end, "today", now)
        == "current"
    )
    assert (
        blocks_module.determine_block_status(planned_start, planned_start, "today", now)
        == "planned"
    )


def test_determine_block_status_invalid_time():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    interval = {"time": "bad"}
    assert (
        blocks_module.determine_block_status(interval, interval, "today", now)
        == "planned"
    )


def test_determine_block_status_missing_time():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    interval = {}
    assert (
        blocks_module.determine_block_status(interval, interval, "today", now)
        == "planned"
    )


def test_get_mode_from_intervals():
    intervals = [{"planned": {"mode": 2}}, {"planned": {"mode": "Home UPS"}}]
    mode_names = {2: "Home 3"}

    assert (
        blocks_module.get_mode_from_intervals(intervals, "planned", mode_names)
        == "Home 3"
    )

    intervals = [{"planned": {"mode": "Custom"}}]
    assert (
        blocks_module.get_mode_from_intervals(intervals, "planned", mode_names)
        == "Custom"
    )

    intervals = [{"planned": {"mode": None}}]
    assert blocks_module.get_mode_from_intervals(intervals, "planned", mode_names) is None


def test_summarize_block_reason_guard_exception():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "decision_metrics": {
                    "guard_active": True,
                    "guard_type": "guard_exception_soc",
                    "guard_planned_mode": "Home UPS",
                }
            }
        }
    ]
    block = {"mode_planned": "Home UPS"}

    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)

    assert "Výjimka guardu" in reason


def test_summarize_block_reason_price_band_hold():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "spot_price": 2.5,
                "decision_metrics": {
                    "planner_reason_code": "price_band_hold",
                    "future_ups_avg_price_czk": 3.0,
                    "spot_price_czk": 2.5,
                },
            }
        }
    ]
    block = {"mode_planned": "Home UPS"}

    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)

    assert "UPS držíme" in reason


def test_summarize_block_reason_price_band_hold_no_future():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "spot_price": 2.5,
                "decision_metrics": {
                    "planner_reason_code": "price_band_hold",
                },
            }
        }
    ]
    block = {"mode_planned": "Home UPS"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "cenovém pásmu" in reason


def test_summarize_block_reason_price_band_hold_no_price():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "decision_metrics": {
                    "planner_reason_code": "price_band_hold",
                },
            }
        }
    ]
    block = {"mode_planned": "Home UPS"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "cenovém pásmu" in reason


def test_summarize_block_reason_ups_charge():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "spot_price": 2.0,
            }
        }
    ]
    block = {"mode_planned": "Home UPS", "battery_kwh_start": 2.0, "battery_kwh_end": 2.5}

    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)

    assert "Nabíjíme ze sítě" in reason


def test_summarize_block_reason_guard_forced_mode():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "decision_metrics": {
                    "guard_active": True,
                    "guard_forced_mode": "Home 2",
                    "guard_until": "2025-01-01T12:00:00",
                }
            }
        }
    ]
    block = {"mode_planned": "Home 2"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "Stabilizace" in reason


def test_summarize_block_reason_guard_no_time():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "decision_metrics": {
                    "guard_active": True,
                    "guard_forced_mode": "Home 2",
                }
            }
        }
    ]
    block = {"mode_planned": "Home 2"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "60 min" in reason


def test_summarize_block_reason_dominant_other():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "spot_price": 2.0,
                "decision_metrics": {"planner_reason_code": "balancing_charge"},
            }
        }
    ]
    block = {"mode_planned": "Home 1"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "Balancování" in reason
    assert "Kč/kWh" in reason


def test_summarize_block_reason_ups_price_limit():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 3.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [
        {
            "planned": {
                "spot_price": 2.0,
                "decision_metrics": {
                    "grid_charge_kwh": 1.0,
                    "future_ups_avg_price_czk": 3.5,
                },
            }
        }
    ]
    block = {"mode_planned": "Home UPS", "battery_kwh_start": 1.0, "battery_kwh_end": 2.0}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "UPS" in reason

    group_intervals[0]["planned"]["spot_price"] = 5.0
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "vyšší cenu" in reason

    group_intervals = [{"planned": {}}]
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "UPS režim" in reason


def test_summarize_block_reason_ups_high_price_no_charge():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 3.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    group_intervals = [{"planned": {"spot_price": 5.0}}]
    block = {"mode_planned": "Home UPS"}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "vyšší cenu" in reason
    assert reason.endswith(".")


def test_summarize_block_reason_no_entries():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    assert blocks_module.summarize_block_reason(sensor, [], {}) is None


def test_summarize_block_reason_modes():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    base = {"planned": {"solar_kwh": 1.0, "consumption_kwh": 0.5}}

    block = {"mode_planned": "Home II"}
    group_intervals = [
        {
            "planned": {
                "decision_metrics": {
                    "home1_saving_czk": 1.2,
                    "recharge_cost_czk": 1.0,
                }
            }
        }
    ]
    assert "HOME II" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home 3"}
    group_intervals = [base]
    assert "maximalizujeme" in blocks_module.summarize_block_reason(sensor, group_intervals, block).lower()

    block = {"mode_planned": "Home I", "battery_kwh_start": 4.0, "battery_kwh_end": 3.0}
    group_intervals = [{"planned": {"spot_price": 5.0, "solar_kwh": 0.1, "consumption_kwh": 0.3}}]
    assert "Vybíjíme baterii" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home I", "battery_kwh_start": 3.0, "battery_kwh_end": 4.0}
    group_intervals = [{"planned": {"solar_kwh": 1.0, "consumption_kwh": 0.2}}]
    assert "Solár pokrývá spotřebu" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home I", "battery_kwh_start": 4.0, "battery_kwh_end": 3.0}
    group_intervals = [
        {"planned": {"spot_price": 5.0, "consumption_kwh": 0.5, "solar_kwh": 0.1, "decision_metrics": {"future_ups_avg_price_czk": 3.0}}}
    ]
    assert "UPS" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home II"}
    group_intervals = [{"planned": {"spot_price": 2.0}}]
    assert "HOME II" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home 3"}
    group_intervals = [{"planned": {"solar_kwh": 0.1, "consumption_kwh": 0.5}}]
    assert "Maximalizujeme" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Home I", "battery_kwh_start": 4.0, "battery_kwh_end": 3.0}
    group_intervals = [{"planned": {"spot_price": 2.0, "consumption_kwh": 0.5, "solar_kwh": 0.1}}]
    assert "Vybíjíme baterii" in blocks_module.summarize_block_reason(sensor, group_intervals, block)

    block = {"mode_planned": "Other"}
    group_intervals = [{"planned": {"decision_reason": "Custom reason"}}]
    assert blocks_module.summarize_block_reason(sensor, group_intervals, block) == "Custom reason"


def test_summarize_block_reason_no_reason():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.9,
    )
    block = {"mode_planned": "Other"}
    group_intervals = [{"planned": {"solar_kwh": 0.1, "consumption_kwh": 0.2}}]
    assert blocks_module.summarize_block_reason(sensor, group_intervals, block) is None


def test_summarize_block_reason_actual_only():
    sensor = SimpleNamespace(
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
        _get_battery_efficiency=lambda: 0.0,
    )
    group_intervals = [
        {
            "actual": {
                "spot_price": 2.0,
                "decision_metrics": {},
                "consumption_kwh": 0.5,
                "solar_kwh": 0.5,
            }
        }
    ]
    block = {"mode_historical": "Home UPS", "battery_kwh_start": 1.0, "battery_kwh_end": 1.5}
    reason = blocks_module.summarize_block_reason(sensor, group_intervals, block)
    assert "Nabíjíme ze sítě" in reason


def test_build_mode_blocks_for_tab():
    sensor = SimpleNamespace(
        _group_intervals_by_mode=lambda *_a, **_k: [
            {
                "mode": "Home 1",
                "intervals": [
                    {
                        "time": "2025-01-01T00:00:00",
                        "planned": {
                            "mode": 0,
                            "battery_soc": 50,
                            "battery_kwh": None,
                            "solar_kwh": 1.0,
                            "consumption_kwh": 0.5,
                            "grid_import_kwh": 0.2,
                            "grid_export": 0.1,
                            "spot_price": 2.0,
                        },
                        "actual": {
                            "mode": 0,
                            "battery_soc": 4.0,
                            "solar_kwh": 0.9,
                            "consumption_kwh": 0.4,
                            "grid_import": 0.3,
                            "grid_export_kwh": 0.0,
                        },
                    }
                ],
                "start_time": "2025-01-01T00:00:00",
                "end_time": "2025-01-01T00:15:00",
                "interval_count": 1,
                "actual_cost": 1.0,
                "planned_cost": 1.1,
                "delta": -0.1,
            }
        ],
        _get_total_battery_capacity=lambda: 10.0,
        _get_battery_efficiency=lambda: 0.9,
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
    )
    blocks = blocks_module.build_mode_blocks_for_tab(
        sensor,
        [{"time": "2025-01-01T00:00:00"}],
        "today",
        mode_names={0: "Home 1"},
    )
    assert blocks
    assert blocks[0]["battery_kwh_start"] >= 0.0
    assert blocks[0]["grid_import_planned_kwh"] >= 0.0


def test_build_mode_blocks_for_tab_empty():
    sensor = SimpleNamespace(_group_intervals_by_mode=lambda *_a, **_k: [])
    assert (
        blocks_module.build_mode_blocks_for_tab(
            sensor, [], "today", mode_names={}
        )
        == []
    )


def test_build_mode_blocks_for_tab_skips_empty_group():
    sensor = SimpleNamespace(
        _group_intervals_by_mode=lambda *_a, **_k: [{"intervals": []}],
        _get_total_battery_capacity=lambda: 0.0,
    )
    blocks = blocks_module.build_mode_blocks_for_tab(
        sensor,
        [{"time": "2025-01-01T00:00:00"}],
        "today",
        mode_names={},
    )
    assert blocks == []


def test_build_mode_blocks_for_tab_planned_only():
    sensor = SimpleNamespace(
        _group_intervals_by_mode=lambda *_a, **_k: [
            {
                "mode": "Home 1",
                "intervals": [
                    {
                        "time": "2025-01-02T00:00:00",
                        "planned": {
                            "mode": 0,
                            "battery_soc": 80,
                            "battery_kwh": None,
                            "solar_kwh": 1.0,
                            "consumption_kwh": 0.5,
                            "grid_import": 0.2,
                            "grid_export_kwh": 0.1,
                        },
                    }
                ],
                "start_time": "2025-01-02T00:00:00",
                "end_time": "2025-01-02T00:15:00",
                "interval_count": 1,
                "planned_cost": 1.1,
            }
        ],
        _get_total_battery_capacity=lambda: 10.0,
        _get_battery_efficiency=lambda: 0.9,
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
    )
    blocks = blocks_module.build_mode_blocks_for_tab(
        sensor,
        [{"time": "2025-01-02T00:00:00"}],
        "tomorrow",
        mode_names={0: "Home 1"},
    )
    assert blocks[0]["adherence_pct"] is None
    assert blocks[0]["battery_kwh_start"] > 0.0


def test_build_mode_blocks_for_tab_non_dict_payload():
    sensor = SimpleNamespace(
        _group_intervals_by_mode=lambda *_a, **_k: [
            {
                "mode": "Home 1",
                "intervals": [
                    {
                        "time": "2025-01-02T00:00:00",
                        "planned": "bad",
                    }
                ],
                "start_time": "2025-01-02T00:00:00",
                "end_time": "2025-01-02T00:15:00",
                "interval_count": 1,
                "planned_cost": 1.0,
            }
        ],
        _get_total_battery_capacity=lambda: 10.0,
        _get_battery_efficiency=lambda: 0.9,
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
    )
    blocks = blocks_module.build_mode_blocks_for_tab(
        sensor,
        [{"time": "2025-01-02T00:00:00"}],
        "tomorrow",
        mode_names={0: "Home 1"},
    )
    assert blocks[0]["battery_soc_start"] == 0.0
    assert blocks[0]["battery_kwh_start"] == 0.0


def test_build_mode_blocks_for_tab_completed_mismatch():
    sensor = SimpleNamespace(
        _group_intervals_by_mode=lambda *_a, **_k: [
            {
                "mode": "Home 1",
                "intervals": [
                    {
                        "time": "2025-01-01T00:00:00",
                        "planned": {"mode": 0, "battery_kwh": 1.0},
                        "actual": {"mode": 1, "battery_kwh": 2.0},
                    }
                ],
                "start_time": "2025-01-01T00:00:00",
                "end_time": "2025-01-01T00:15:00",
                "interval_count": 1,
                "actual_cost": 1.0,
                "planned_cost": 1.2,
                "delta": -0.2,
            }
        ],
        _get_total_battery_capacity=lambda: 10.0,
        _get_battery_efficiency=lambda: 0.9,
        _config_entry=SimpleNamespace(options={"max_ups_price_czk": 4.0}),
    )
    blocks = blocks_module.build_mode_blocks_for_tab(
        sensor,
        [{"time": "2025-01-01T00:00:00"}],
        "yesterday",
        mode_names={0: "Home 1", 1: "Home 2"},
    )
    assert blocks[0]["adherence_pct"] == 0
