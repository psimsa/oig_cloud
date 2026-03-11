from __future__ import annotations

from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.planning import (
    charging_helpers,
    charging_plan,
    charging_plan_adjustments,
    charging_plan_utils,
    interval_grouping,
    mode_guard,
    mode_recommendations,
)
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_UPS,
)


class DummyState:
    def __init__(self, state, last_changed):
        self.state = state
        self.last_changed = last_changed


class DummyStates:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class DummyHass:
    def __init__(self, states):
        self.states = DummyStates(states)


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options
        self.data = options
        self.entry_id = "entry-id"


class DummySensor:
    def __init__(self, options):
        self._config_entry = DummyConfigEntry(options)
        self._charging_metrics = None

    def _get_battery_efficiency(self):
        return 0.9


def _build_timeline_points(base_time, count):
    return [
        {
            "timestamp": (base_time + timedelta(minutes=15 * i)).isoformat(),
            "spot_price_czk": 2.0 + i,
            "battery_capacity_kwh": 1.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        }
        for i in range(count)
    ]


def test_enforce_min_mode_duration_replaces_short_block():
    modes = [0, 1, 0, 0]
    mode_names = {0: "Home 1", 1: "Home 2"}
    min_mode_duration = {"Home 2": 2}

    result = mode_guard.enforce_min_mode_duration(
        modes, mode_names=mode_names, min_mode_duration=min_mode_duration
    )

    assert result == [0, 0, 0, 0]


def test_enforce_min_mode_duration_empty():
    result = mode_guard.enforce_min_mode_duration(
        [], mode_names={}, min_mode_duration={}
    )
    assert result == []


def test_enforce_min_mode_duration_end_block_replacement():
    modes = [1, 2]
    mode_names = {1: "Home 1", 2: "Home 2"}
    min_mode_duration = {"Home 1": 2}
    result = mode_guard.enforce_min_mode_duration(
        modes, mode_names=mode_names, min_mode_duration=min_mode_duration
    )
    assert result == [2, 2]

    modes = [0, 1]
    mode_names = {0: "Home 1", 1: "Home 2"}
    min_mode_duration = {"Home 2": 2}
    result = mode_guard.enforce_min_mode_duration(
        modes, mode_names=mode_names, min_mode_duration=min_mode_duration
    )
    assert result == [0, 0]


def test_get_mode_guard_context_active():
    last_changed = dt_util.now() - timedelta(minutes=10)
    hass = DummyHass(
        {"sensor.oig_123_box_prms_mode": DummyState("Home 1", last_changed)}
    )

    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=hass,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 0,
    )

    assert mode == 0
    assert guard_until is not None
    assert guard_until > dt_util.now()


def test_get_mode_guard_context_missing_or_invalid():
    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=None,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 0,
    )
    assert mode is None
    assert guard_until is None

    hass = DummyHass({"sensor.oig_123_box_prms_mode": DummyState("unknown", None)})
    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=hass,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 1,
    )
    assert mode is None
    assert guard_until is None

    hass = DummyHass({"sensor.oig_123_box_prms_mode": DummyState("Home 1", "bad")})
    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=hass,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 2,
    )
    assert mode == 2
    assert guard_until is None


def test_get_mode_guard_context_expired_guard():
    last_changed = dt_util.now() - timedelta(minutes=31)
    hass = DummyHass(
        {"sensor.oig_123_box_prms_mode": DummyState("Home 1", last_changed)}
    )

    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=hass,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 0,
    )

    assert mode == 0
    assert guard_until is None


def test_get_mode_guard_context_naive_last_changed():
    last_changed = dt_util.now().replace(tzinfo=None)
    hass = DummyHass(
        {"sensor.oig_123_box_prms_mode": DummyState("Home 1", last_changed)}
    )

    mode, guard_until = mode_guard.get_mode_guard_context(
        hass=hass,
        box_id="123",
        mode_guard_minutes=30,
        get_current_mode=lambda: 0,
    )

    assert mode == 0
    assert guard_until is not None


def test_build_plan_lock():
    now = dt_util.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=15 * i)).isoformat()} for i in range(3)
    ]
    modes = [0, 1, 1]

    lock_until, lock_modes = mode_guard.build_plan_lock(
        now=now,
        spot_prices=spot_prices,
        modes=modes,
        mode_guard_minutes=30,
        plan_lock_until=None,
        plan_lock_modes=None,
    )

    assert lock_until is not None
    assert len(lock_modes) == 2


def test_build_plan_lock_reuse_and_fallback():
    now = dt_util.now()
    lock_until = now + timedelta(minutes=30)
    lock_modes = {"2025-01-01T00:00:00": 1}

    reused_until, reused_modes = mode_guard.build_plan_lock(
        now=now,
        spot_prices=[],
        modes=[],
        mode_guard_minutes=30,
        plan_lock_until=lock_until,
        plan_lock_modes=lock_modes,
    )
    assert reused_until == lock_until
    assert reused_modes == lock_modes

    lock_until, lock_modes = mode_guard.build_plan_lock(
        now=now,
        spot_prices=[{"time": None}],
        modes=[0],
        mode_guard_minutes=15,
        plan_lock_until=None,
        plan_lock_modes=None,
    )
    assert lock_until is not None
    assert lock_modes == {}


def test_build_plan_lock_modes_shorter_than_prices():
    now = dt_util.now()
    lock_until, lock_modes = mode_guard.build_plan_lock(
        now=now,
        spot_prices=[
            {"time": (now + timedelta(minutes=15 * i)).isoformat()} for i in range(3)
        ],
        modes=[1],
        mode_guard_minutes=30,
        plan_lock_until=None,
        plan_lock_modes=None,
    )
    assert len(lock_modes) == 1


def test_build_plan_lock_disabled():
    now = dt_util.now()
    lock_until, lock_modes = mode_guard.build_plan_lock(
        now=now,
        spot_prices=[],
        modes=[],
        mode_guard_minutes=0,
        plan_lock_until=None,
        plan_lock_modes=None,
    )
    assert lock_until is None
    assert lock_modes == {}


def test_apply_mode_guard_lock_and_exception():
    now = dt_util.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=15 * i)).isoformat()} for i in range(2)
    ]
    modes = [CBB_MODE_HOME_UPS, CBB_MODE_HOME_UPS]

    guarded, overrides, _ = mode_guard.apply_mode_guard(
        modes=modes,
        spot_prices=spot_prices,
        solar_kwh_list=[0.0, 0.0],
        load_forecast=[0.0, 0.0],
        current_capacity=5.0,
        max_capacity=10.0,
        hw_min_capacity=1.0,
        efficiency=1.0,
        home_charge_rate_kw=0.0,
        planning_min_kwh=0.5,
        lock_modes={spot_prices[0]["time"]: CBB_MODE_HOME_I},
        guard_until=now + timedelta(minutes=30),
    )

    assert guarded[0] == CBB_MODE_HOME_I
    assert overrides[0]["type"] == "guard_locked_plan"

    guarded, overrides, _ = mode_guard.apply_mode_guard(
        modes=modes,
        spot_prices=spot_prices,
        solar_kwh_list=[0.0, 0.0],
        load_forecast=[2.0, 2.0],
        current_capacity=1.0,
        max_capacity=10.0,
        hw_min_capacity=0.1,
        efficiency=1.0,
        home_charge_rate_kw=2.0,
        planning_min_kwh=0.5,
        lock_modes={spot_prices[0]["time"]: CBB_MODE_HOME_I},
        guard_until=now + timedelta(minutes=30),
    )

    assert overrides[0]["type"] == "guard_exception_soc"


def test_apply_mode_guard_noop_conditions():
    guarded, overrides, guard_until = mode_guard.apply_mode_guard(
        modes=[],
        spot_prices=[],
        solar_kwh_list=[],
        load_forecast=[],
        current_capacity=0.0,
        max_capacity=1.0,
        hw_min_capacity=0.0,
        efficiency=1.0,
        home_charge_rate_kw=0.0,
        planning_min_kwh=0.0,
        lock_modes={},
        guard_until=None,
    )
    assert guarded == []
    assert overrides == []
    assert guard_until is None


def test_apply_mode_guard_breaks_on_guard_until_and_bad_timestamp(monkeypatch):
    now = dt_util.now()
    called = {"sim": 0}

    def _simulate(*_a, **_k):
        called["sim"] += 1

        class Res:
            new_soc_kwh = 5.0

        return Res()

    monkeypatch.setattr(mode_guard, "simulate_interval", _simulate)

    guarded, overrides, guard_until = mode_guard.apply_mode_guard(
        modes=[CBB_MODE_HOME_UPS, CBB_MODE_HOME_UPS],
        spot_prices=[{"time": "bad"}],
        solar_kwh_list=[0.0],
        load_forecast=[0.0],
        current_capacity=5.0,
        max_capacity=10.0,
        hw_min_capacity=1.0,
        efficiency=1.0,
        home_charge_rate_kw=2.0,
        planning_min_kwh=2.0,
        lock_modes={"bad": CBB_MODE_HOME_I},
        guard_until=now,
    )

    assert guarded == [CBB_MODE_HOME_UPS, CBB_MODE_HOME_UPS]
    assert overrides == []
    assert guard_until == now
    assert called["sim"] == 0


def test_apply_mode_guard_breaks_on_spot_price_length(monkeypatch):
    now = dt_util.now()
    called = {"sim": 0}

    def _simulate(*_a, **_k):
        called["sim"] += 1

        class Res:
            new_soc_kwh = 5.0

        return Res()

    monkeypatch.setattr(mode_guard, "simulate_interval", _simulate)

    guarded, overrides, _ = mode_guard.apply_mode_guard(
        modes=[CBB_MODE_HOME_UPS, CBB_MODE_HOME_UPS],
        spot_prices=[{"time": (now + timedelta(minutes=15)).isoformat()}],
        solar_kwh_list=[0.0],
        load_forecast=[0.0],
        current_capacity=5.0,
        max_capacity=10.0,
        hw_min_capacity=1.0,
        efficiency=1.0,
        home_charge_rate_kw=2.0,
        planning_min_kwh=2.0,
        lock_modes={(now + timedelta(minutes=15)).isoformat(): CBB_MODE_HOME_UPS},
        guard_until=now + timedelta(minutes=30),
    )

    assert guarded == [CBB_MODE_HOME_UPS, CBB_MODE_HOME_UPS]
    assert overrides == []
    assert called["sim"] == 1


def test_apply_mode_guard_uses_log_rate_limited(monkeypatch):
    now = dt_util.now()
    spot_prices = [{"time": (now + timedelta(minutes=15 * i)).isoformat()} for i in range(1)]
    modes = [CBB_MODE_HOME_UPS]
    called = {"log": 0}

    def _simulate(*_a, **_k):
        class Res:
            new_soc_kwh = 10.0

        return Res()

    def _log(*_a, **_k):
        called["log"] += 1

    monkeypatch.setattr(mode_guard, "simulate_interval", _simulate)

    guarded, overrides, _ = mode_guard.apply_mode_guard(
        modes=modes,
        spot_prices=spot_prices,
        solar_kwh_list=[0.0],
        load_forecast=[0.0],
        current_capacity=5.0,
        max_capacity=10.0,
        hw_min_capacity=1.0,
        efficiency=1.0,
        home_charge_rate_kw=2.0,
        planning_min_kwh=2.0,
        lock_modes={spot_prices[0]["time"]: CBB_MODE_HOME_I},
        guard_until=now + timedelta(minutes=30),
        log_rate_limited=_log,
    )

    assert guarded[0] == CBB_MODE_HOME_I
    assert overrides
    assert called["log"] == 1


def test_apply_guard_reasons_to_timeline():
    timeline = [{"planner_reason": "base"}]
    overrides = [
        {
            "idx": 0,
            "type": "guard_locked_plan",
            "planned_mode": CBB_MODE_HOME_II,
            "forced_mode": CBB_MODE_HOME_I,
        }
    ]
    mode_guard.apply_guard_reasons_to_timeline(
        timeline,
        overrides,
        guard_until=dt_util.now() + timedelta(minutes=30),
        current_mode=CBB_MODE_HOME_I,
        mode_names={0: "Home 1", 1: "Home 2"},
    )

    assert "guard_reason" in timeline[0]
    assert "Stabilizace" in timeline[0]["planner_reason"]


def test_apply_guard_reasons_to_timeline_unknown_and_missing_label():
    timeline = [{"planner_reason": "base", "reason": "orig"}]
    overrides = [
        {
            "idx": 0,
            "type": "unknown",
            "planned_mode": 1,
            "forced_mode": 2,
        }
    ]
    mode_guard.apply_guard_reasons_to_timeline(
        timeline,
        overrides,
        guard_until=None,
        current_mode=None,
        mode_names={},
    )

    assert "Stabilizace" in timeline[0]["planner_reason"]
    assert timeline[0]["reason"] == "Stabilizace: držíme potvrzený plán."


def test_apply_guard_reasons_to_timeline_early_returns():
    mode_guard.apply_guard_reasons_to_timeline(
        [],
        overrides=[{"idx": 0}],
        guard_until=None,
        current_mode=None,
        mode_names={},
    )

    mode_guard.apply_guard_reasons_to_timeline(
        [{"planner_reason": "base"}],
        overrides=[],
        guard_until=None,
        current_mode=None,
        mode_names={},
    )


def test_apply_guard_reasons_to_timeline_idx_out_of_range():
    timeline = [{"planner_reason": "base"}]
    mode_guard.apply_guard_reasons_to_timeline(
        timeline,
        overrides=[{"idx": 2, "type": "guard_exception_soc"}],
        guard_until=None,
        current_mode=None,
        mode_names={},
    )
    assert timeline[0]["planner_reason"] == "base"


def test_apply_guard_reasons_to_timeline_exception_and_locked():
    timeline = [{}]
    overrides = [
        {
            "idx": 0,
            "type": "guard_exception_soc",
            "planned_mode": 1,
            "forced_mode": 1,
        }
    ]
    mode_guard.apply_guard_reasons_to_timeline(
        timeline,
        overrides,
        guard_until=None,
        current_mode=1,
        mode_names={1: "Home 2"},
    )
    assert "Výjimka guardu" in timeline[0]["planner_reason"]
    assert "reason" not in timeline[0]

    timeline = [{}]
    overrides = [
        {
            "idx": 0,
            "type": "guard_locked_plan",
            "planned_mode": 1,
            "forced_mode": 1,
        }
    ]
    mode_guard.apply_guard_reasons_to_timeline(
        timeline,
        overrides,
        guard_until=None,
        current_mode=None,
        mode_names={1: "Home 2"},
    )
    assert "Stabilizace" in timeline[0]["planner_reason"]


def test_get_candidate_intervals_filters_and_sorts():
    now = dt_util.now()
    timeline = [
        {"timestamp": (now - timedelta(minutes=15)).isoformat(), "spot_price_czk": 1},
        {"timestamp": (now + timedelta(minutes=15)).isoformat(), "spot_price_czk": 5},
        {"timestamp": (now + timedelta(minutes=30)).isoformat(), "spot_price_czk": 2},
        {"timestamp": (now + timedelta(minutes=45)).isoformat(), "spot_price_czk": 1},
    ]

    candidates = charging_plan_utils.get_candidate_intervals(
        timeline,
        max_charging_price=3.0,
        current_time=now,
        iso_tz_offset="+00:00",
    )

    assert [c["price"] for c in candidates] == [1, 2]


def test_get_candidate_intervals_default_now_and_invalid_timestamp(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.charging_plan_utils.dt_util.now",
        lambda: fixed_now,
    )

    timeline = [
        {"timestamp": "bad", "spot_price_czk": 1.0},
        {"timestamp": "2025-01-01T12:15:00", "spot_price_czk": 5.0},
    ]

    candidates = charging_plan_utils.get_candidate_intervals(
        timeline, max_charging_price=1.0
    )

    assert candidates == []


def test_simulate_forward_death_valley():
    timeline = [
        {
            "battery_capacity_kwh": 1.0,
            "spot_price_czk": 2.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
        {
            "battery_capacity_kwh": 0.0,
            "spot_price_czk": 2.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
    ]

    result = charging_plan_utils.simulate_forward(
        timeline=timeline,
        start_index=0,
        charge_now=True,
        charge_amount_kwh=1.0,
        horizon_hours=1,
        effective_minimum_kwh=1.5,
        efficiency=1.0,
    )

    assert result["charging_events"]
    assert result["total_charging_cost"] == 2.0
    assert result["death_valley_reached"] is True


def test_simulate_forward_start_index_out_of_range():
    result = charging_plan_utils.simulate_forward(
        timeline=[],
        start_index=1,
        charge_now=False,
        charge_amount_kwh=0.0,
        horizon_hours=1,
        effective_minimum_kwh=1.0,
        efficiency=1.0,
    )
    assert result["death_valley_reached"] is True


def test_calculate_minimum_charge_and_protection():
    assert charging_plan_utils.calculate_minimum_charge(3.0, 4.0, 1.0) == 1.0
    assert charging_plan_utils.calculate_minimum_charge(5.0, 4.0, 1.0) == 0

    now = dt_util.now()
    timeline = [
        {
            "timestamp": (now + timedelta(hours=1)).isoformat(),
            "consumption_kwh": 2.0,
        }
    ]
    required = charging_plan_utils.calculate_protection_requirement(
        timeline,
        max_capacity=10.0,
        config={
            "enable_blackout_protection": True,
            "blackout_protection_hours": 12,
            "blackout_target_soc_percent": 60.0,
            "enable_weather_risk": True,
            "weather_risk_level": "high",
            "weather_target_soc_percent": 50.0,
        },
        iso_tz_offset="+00:00",
    )

    assert required == 6.0


def test_calculate_protection_requirement_invalid_timestamp_returns_none(monkeypatch):
    now = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.charging_plan_utils.dt_util.now",
        lambda: now,
    )
    timeline = [{"timestamp": "bad", "consumption_kwh": 2.0}]
    required = charging_plan_utils.calculate_protection_requirement(
        timeline,
        max_capacity=10.0,
        config={
            "enable_blackout_protection": True,
            "blackout_target_soc_percent": 0.0,
        },
    )
    assert required is None


def test_recalculate_timeline_from_index_updates_soc_and_mode():
    timeline = [
        {
            "battery_capacity_kwh": 2.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 0.5,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
        {
            "battery_capacity_kwh": 2.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 0.5,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
    ]

    charging_plan_utils.recalculate_timeline_from_index(
        timeline,
        1,
        max_capacity=10.0,
        min_capacity=1.0,
        efficiency=1.0,
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert timeline[1]["battery_capacity_kwh"] == 1.5
    assert timeline[1]["mode"] == "Home 1"


def test_recalculate_timeline_from_index_solar_surplus():
    timeline = [
        {
            "battery_capacity_kwh": 1.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 0.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
        {
            "battery_capacity_kwh": 1.0,
            "solar_production_kwh": 2.0,
            "consumption_kwh": 1.0,
            "grid_charge_kwh": 0.0,
            "reason": "normal",
        },
    ]

    charging_plan_utils.recalculate_timeline_from_index(
        timeline,
        1,
        max_capacity=10.0,
        min_capacity=0.0,
        efficiency=1.0,
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert timeline[1]["battery_capacity_kwh"] == 2.0
    assert timeline[1]["mode"] == "Home 1"


def test_fix_minimum_capacity_violations_and_target_capacity():
    timeline = [
        {
            "battery_capacity_kwh": 5.0,
            "spot_price_czk": 1.0,
            "grid_charge_kwh": 0.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "reason": "normal",
        },
        {
            "battery_capacity_kwh": 1.0,
            "spot_price_czk": 5.0,
            "grid_charge_kwh": 0.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "reason": "normal",
        },
    ]

    charging_plan_adjustments.fix_minimum_capacity_violations(
        timeline=timeline,
        min_capacity=2.0,
        max_price=3.0,
        price_threshold=2.0,
        charging_power_kw=4.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert timeline[0]["grid_charge_kwh"] > 0
    assert timeline[0]["reason"] == "legacy_violation_fix"

    charging_plan_adjustments.ensure_target_capacity_at_end(
        timeline=timeline,
        target_capacity=6.0,
        max_price=3.0,
        price_threshold=2.0,
        charging_power_kw=4.0,
        max_capacity=10.0,
        min_capacity=1.0,
        efficiency=1.0,
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert timeline[0]["grid_charge_kwh"] > 0


def test_group_intervals_by_mode_completed_and_planned():
    intervals = [
        {
            "time": "2025-01-01T00:00:00",
            "actual": {"mode": 0, "net_cost": 1.0, "savings_vs_home_i": 0.1},
            "planned": {"mode": 0, "net_cost": 1.2, "savings_vs_home_i": 0.2},
        },
        {
            "time": "2025-01-01T00:15:00",
            "actual": {"mode": 0, "net_cost": 1.5, "savings_vs_home_i": 0.0},
            "planned": {"mode": 0, "net_cost": 1.2, "savings_vs_home_i": 0.2},
        },
        {
            "time": "2025-01-01T00:30:00",
            "planned": {"mode": 1, "net_cost": 2.0, "savings_vs_home_i": 0.0},
        },
    ]

    groups = interval_grouping.group_intervals_by_mode(
        intervals, "completed", {0: "Home 1", 1: "Home 2"}
    )

    assert len(groups) == 2
    assert groups[0]["interval_count"] == 2
    assert groups[0]["actual_cost"] == 2.5

    planned_groups = interval_grouping.group_intervals_by_mode(
        intervals, "planned", {0: "Home 1", 1: "Home 2"}
    )
    assert planned_groups[0]["planned_cost"] == 2.4


def test_group_intervals_by_mode_handles_unknowns_and_invalid_times():
    intervals = [
        None,
        {
            "time": "bad-time",
            "actual": {"mode": None, "net_cost": 1.0, "savings_vs_home_i": 0.1},
            "planned": {"mode": None, "net_cost": 0.0, "savings_vs_home_i": 0.0},
        },
        {
            "time": "2025-01-01T01:00:00",
            "actual": {"mode": 2, "net_cost": 2.0},
            "planned": {"mode": 3, "net_cost": 1.0},
        },
        {
            "time": "2025-01-01T01:15:00",
            "actual": {"mode": "  ", "net_cost": 0.5},
            "planned": {"mode": "Home", "net_cost": 0.5},
        },
    ]

    groups = interval_grouping.group_intervals_by_mode(intervals, "both", {})

    assert [group["mode"] for group in groups] == ["Unknown", "Mode 2", "Unknown"]
    assert groups[0]["start_time"] == "bad-time"
    assert groups[1]["end_time"] == "01:15"
    assert groups[0]["delta_pct"] == 0.0


def test_group_intervals_by_mode_empty_returns_empty():
    assert interval_grouping.group_intervals_by_mode([], "planned", {}) == []


def test_group_intervals_by_mode_completed_unknown_mode():
    intervals = [
        {"time": "2025-01-01T00:00:00", "actual": {}, "planned": {}},
    ]

    groups = interval_grouping.group_intervals_by_mode(intervals, "completed", {})

    assert groups[0]["mode"] == "Unknown"


def test_group_intervals_by_mode_both_uses_planned_when_actual_missing():
    intervals = [
        {"time": "2025-01-01T00:00:00", "planned": {"mode": 1, "net_cost": 1.0}},
    ]

    groups = interval_grouping.group_intervals_by_mode(intervals, "both", {1: "Home 2"})

    assert groups[0]["mode"] == "Home 2"


def test_create_mode_recommendations_split_midnight():
    now = datetime(2025, 1, 1, 22, 0, 0)
    timeline = [
        {
            "time": "2025-01-01T23:30:00",
            "mode": CBB_MODE_HOME_I,
            "mode_name": "Home 1",
            "net_cost": 1.0,
            "solar_kwh": 0.2,
            "load_kwh": 0.3,
            "spot_price": 2.0,
        },
        {
            "time": "2025-01-01T23:45:00",
            "mode": CBB_MODE_HOME_I,
            "mode_name": "Home 1",
            "net_cost": 1.1,
            "solar_kwh": 0.2,
            "load_kwh": 0.3,
            "spot_price": 2.0,
        },
        {
            "time": "2025-01-02T00:00:00",
            "mode": CBB_MODE_HOME_I,
            "mode_name": "Home 1",
            "net_cost": 1.2,
            "solar_kwh": 0.2,
            "load_kwh": 0.3,
            "spot_price": 2.0,
        },
    ]

    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        hours_ahead=48,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=2,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )

    assert len(recs) == 2
    assert recs[0]["intervals_count"] == 2
    assert recs[1]["intervals_count"] == 1


def test_charging_helpers_store_metrics(monkeypatch):
    def _fake_economic_plan(**_kwargs):
        return ([{"grid_charge_kwh": 1.0}], {"algorithm": "economic"})

    def _fake_smart_plan(**_kwargs):
        return ([{"grid_charge_kwh": 2.0}], {"algorithm": "smart"})

    monkeypatch.setattr(charging_plan, "economic_charging_plan", _fake_economic_plan)
    monkeypatch.setattr(charging_plan, "smart_charging_plan", _fake_smart_plan)

    sensor = DummySensor(
        {
            "min_capacity_percent": 20.0,
        }
    )

    timeline = [{"battery_capacity_kwh": 2.0}]

    result = charging_helpers.economic_charging_plan(
        sensor,
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        effective_minimum_kwh=1.0,
        target_capacity_kwh=2.0,
        max_charging_price=5.0,
        min_savings_margin=0.1,
        charging_power_kw=4.0,
        max_capacity=10.0,
        enable_blackout_protection=False,
        blackout_protection_hours=12,
        blackout_target_soc_percent=60.0,
        enable_weather_risk=False,
        weather_risk_level="low",
        weather_target_soc_percent=50.0,
        iso_tz_offset="+00:00",
    )

    assert result[0]["grid_charge_kwh"] == 1.0
    assert sensor._charging_metrics["algorithm"] == "economic"

    result = charging_helpers.smart_charging_plan(
        sensor,
        timeline=timeline,
        min_capacity=1.0,
        target_capacity=2.0,
        max_price=5.0,
        price_threshold=5.0,
        charging_power_kw=4.0,
        max_capacity=10.0,
    )

    assert result[0]["grid_charge_kwh"] == 2.0
    assert sensor._charging_metrics["algorithm"] == "smart"


def test_economic_charging_plan_death_valley():
    now = dt_util.now()
    timeline = _build_timeline_points(now + timedelta(hours=1), 3)

    timeline, metrics = charging_plan.economic_charging_plan(
        timeline_data=timeline,
        min_capacity_kwh=1.0,
        min_capacity_floor=0.5,
        effective_minimum_kwh=2.0,
        target_capacity_kwh=4.0,
        max_charging_price=10.0,
        min_savings_margin=0.5,
        charging_power_kw=4.0,
        max_capacity=10.0,
        enable_blackout_protection=True,
        blackout_protection_hours=12,
        blackout_target_soc_percent=60.0,
        enable_weather_risk=False,
        weather_risk_level="low",
        weather_target_soc_percent=50.0,
        target_reason="test",
        battery_efficiency=1.0,
        config={
            "enable_blackout_protection": True,
            "blackout_protection_hours": 12,
            "blackout_target_soc_percent": 60.0,
        },
        iso_tz_offset="+00:00",
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert metrics["algorithm"] == "economic"
    assert any(pt.get("grid_charge_kwh", 0) > 0 for pt in timeline)


def test_smart_charging_plan_adds_charge():
    timeline = [
        {
            "battery_capacity_kwh": 1.0,
            "spot_price_czk": 1.0,
            "grid_charge_kwh": 0.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "reason": "normal",
            "timestamp": "2025-01-01T00:00:00",
        },
        {
            "battery_capacity_kwh": 0.5,
            "spot_price_czk": 5.0,
            "grid_charge_kwh": 0.0,
            "solar_production_kwh": 0.0,
            "consumption_kwh": 1.0,
            "reason": "normal",
            "timestamp": "2025-01-01T00:15:00",
        },
    ]

    result, metrics = charging_plan.smart_charging_plan(
        timeline=timeline,
        min_capacity=1.0,
        target_capacity=2.0,
        max_price=5.0,
        price_threshold=5.0,
        charging_power_kw=4.0,
        max_capacity=10.0,
        efficiency=1.0,
        mode_label_home_ups="Home UPS",
        mode_label_home_i="Home 1",
    )

    assert metrics["target_capacity_kwh"] == 2.0
    assert any(pt.get("grid_charge_kwh", 0) > 0 for pt in result)
