from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.balancing import core as module
from unittest.mock import AsyncMock

from custom_components.oig_cloud.battery_forecast.balancing.plan import (
    BalancingMode,
    BalancingPlan,
)
from custom_components.oig_cloud.const import HOME_UPS


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class DummyHass:
    def __init__(self, states=None):
        self.states = DummyStates(states or {})
        self.data = {}
        self.config = SimpleNamespace(path=lambda *_a: "/tmp", config_dir="/tmp")

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class DummyEntry:
    def __init__(self, options=None):
        self.options = options or {}


def _make_manager(options=None, states=None):
    hass = DummyHass(states)
    entry = DummyEntry(options)
    return module.BalancingManager(hass, "123", "path", entry)


class _BrokenOptions:
    def get(self, *_a, **_k):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_async_setup_and_load_errors(monkeypatch):
    mgr = _make_manager()

    async def _load():
        raise RuntimeError("boom")

    mgr._store = SimpleNamespace(async_load=_load)
    await mgr._load_state_safe()
    assert mgr._last_balancing_ts is None

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(mgr, "_load_state_safe", _raise)
    with pytest.raises(RuntimeError):
        await mgr.async_setup()


def test_get_cooldown_hours_invalid_config():
    mgr = _make_manager({"balancing_cooldown_hours": "bad"})
    assert mgr._get_cooldown_hours() >= 24


def test_set_coordinator():
    mgr = _make_manager()
    coord = object()
    mgr.set_coordinator(coord)
    assert mgr._coordinator is coord


@pytest.mark.asyncio
async def test_async_setup_success(monkeypatch):
    mgr = _make_manager()

    async def _load():
        return None

    monkeypatch.setattr(mgr, "_load_state_safe", _load)
    await mgr.async_setup()


@pytest.mark.asyncio
async def test_save_state_coordinator_error(monkeypatch):
    mgr = _make_manager()
    mgr._active_plan = None
    mgr._last_balancing_ts = datetime.now(timezone.utc)
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    class DummyCoordinator:
        async def async_request_refresh(self):
            raise RuntimeError("boom")

    mgr.set_coordinator(DummyCoordinator())
    await mgr._save_state()


@pytest.mark.asyncio
async def test_save_state_coordinator_success():
    mgr = _make_manager()
    mgr._active_plan = None
    mgr._last_balancing_ts = datetime.now(timezone.utc)
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    coord = SimpleNamespace(async_request_refresh=AsyncMock())
    mgr.set_coordinator(coord)
    await mgr._save_state()
    coord.async_request_refresh.assert_awaited()


@pytest.mark.asyncio
async def test_load_state_with_data():
    mgr = _make_manager()
    now = datetime.now(timezone.utc)
    plan = BalancingPlan(
        mode=BalancingMode.OPPORTUNISTIC,
        created_at=now.isoformat(),
        reason="loaded",
        holding_start=now.isoformat(),
        holding_end=(now + timedelta(hours=1)).isoformat(),
        intervals=[],
    )
    mgr._store = SimpleNamespace(
        async_load=AsyncMock(
            return_value={
                "last_balancing_ts": now.isoformat(),
                "active_plan": plan.to_dict(),
            }
        )
    )

    await mgr._load_state_safe()
    assert mgr._last_balancing_ts == now
    assert mgr._active_plan is not None


def test_get_cheap_window_percentile_exception():
    mgr = _make_manager()
    mgr._config_entry.options = _BrokenOptions()
    assert mgr._get_cheap_window_percentile() == 30


@pytest.mark.asyncio
async def test_load_state_safe_error(monkeypatch):
    mgr = _make_manager()

    async def _load():
        raise RuntimeError("boom")

    mgr._store = SimpleNamespace(async_load=_load)
    await mgr._load_state_safe()


@pytest.mark.asyncio
async def test_check_balancing_no_forecast_sensor():
    mgr = _make_manager()
    assert await mgr.check_balancing() is None


@pytest.mark.asyncio
async def test_check_balancing_detects_completion(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (True, datetime.now(timezone.utc))

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)
    assert await mgr.check_balancing() is None


@pytest.mark.asyncio
async def test_check_balancing_active_plan_paths(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())
    monkeypatch.setattr(mgr, "_save_state", AsyncMock())
    mgr._last_balancing_ts = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    plan = BalancingPlan(
        mode=BalancingMode.OPPORTUNISTIC,
        created_at=now.isoformat(),
        reason="x",
        holding_start=now.isoformat(),
        holding_end=(now + timedelta(hours=1)).isoformat(),
        intervals=[],
    )
    mgr._active_plan = plan

    async def _check():
        return (False, None)

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)

    result = await mgr.check_balancing()
    assert result == plan

    plan.holding_start = (now - timedelta(hours=2)).isoformat()
    plan.holding_end = (now - timedelta(hours=1)).isoformat()
    mgr._store = SimpleNamespace(async_save=lambda *_a, **_k: None)
    result = await mgr.check_balancing()
    assert result is None

    # Ensure no forced plan when expired by keeping last balancing fresh.
    mgr._last_balancing_ts = datetime.now(timezone.utc)
    mgr._active_plan = plan
    plan.holding_start = (now - timedelta(hours=2)).isoformat()
    plan.holding_end = (now - timedelta(hours=1)).isoformat()
    result = await mgr.check_balancing()
    assert result is None


@pytest.mark.asyncio
async def test_check_balancing_active_plan_future_deadline(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (False, None)

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)

    now = datetime.now()
    plan = BalancingPlan(
        mode=BalancingMode.OPPORTUNISTIC,
        created_at=now.isoformat(),
        reason="future",
        holding_start=(now + timedelta(hours=1)).isoformat(),
        holding_end=(now + timedelta(hours=2)).isoformat(),
        intervals=[],
    )
    mgr._active_plan = plan
    result = await mgr.check_balancing()
    assert result == plan


@pytest.mark.asyncio
async def test_check_balancing_cycle_forced(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (False, None)

    async def _natural():
        return None

    async def _forced():
        now = datetime.now(timezone.utc)
        return BalancingPlan(
            mode=BalancingMode.FORCED,
            created_at=now.isoformat(),
            reason="forced",
            holding_start=now.isoformat(),
            holding_end=(now + timedelta(hours=3)).isoformat(),
            intervals=[],
        )

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)
    monkeypatch.setattr(mgr, "_check_natural_balancing", _natural)
    monkeypatch.setattr(mgr, "_create_forced_plan", _forced)
    monkeypatch.setattr(mgr, "_get_days_since_last_balancing", lambda: 10)
    monkeypatch.setattr(mgr, "_get_cycle_days", lambda: 5)

    result = await mgr.check_balancing()
    assert isinstance(result, BalancingPlan)

@pytest.mark.asyncio
async def test_check_balancing_force_and_natural(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (False, None)

    async def _forced():
        now = datetime.now(timezone.utc)
        return BalancingPlan(
            mode=BalancingMode.FORCED,
            created_at=now.isoformat(),
            reason="forced",
            holding_start=now.isoformat(),
            holding_end=(now + timedelta(hours=3)).isoformat(),
            intervals=[],
        )

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)
    monkeypatch.setattr(mgr, "_create_forced_plan", _forced)
    result = await mgr.check_balancing(force=True)
    assert isinstance(result, BalancingPlan)

    mgr2 = _make_manager()
    mgr2._forecast_sensor = object()
    mgr2._store = SimpleNamespace(async_save=AsyncMock())
    monkeypatch.setattr(mgr2, "_check_if_balancing_occurred", _check)

    async def _natural():
        now = datetime.now(timezone.utc)
        return BalancingPlan(
            mode=BalancingMode.NATURAL,
            created_at=now.isoformat(),
            reason="natural",
            holding_start=now.isoformat(),
            holding_end=(now + timedelta(hours=3)).isoformat(),
            intervals=[],
        )

    monkeypatch.setattr(mgr2, "_check_natural_balancing", _natural)
    result = await mgr2.check_balancing()
    assert isinstance(result, BalancingPlan)


@pytest.mark.asyncio
async def test_check_balancing_opportunistic(monkeypatch):
    mgr = _make_manager({"balancing_cooldown_hours": 1})
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (False, None)

    async def _natural():
        return None

    async def _opp():
        now = datetime.now(timezone.utc)
        return BalancingPlan(
            mode=BalancingMode.OPPORTUNISTIC,
            created_at=now.isoformat(),
            reason="opp",
            holding_start=now.isoformat(),
            holding_end=(now + timedelta(hours=3)).isoformat(),
            intervals=[],
        )

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)
    monkeypatch.setattr(mgr, "_check_natural_balancing", _natural)
    monkeypatch.setattr(mgr, "_create_opportunistic_plan", _opp)
    mgr._last_balancing_ts = datetime.now(timezone.utc) - timedelta(hours=30)

    result = await mgr.check_balancing()
    assert isinstance(result, BalancingPlan)


@pytest.mark.asyncio
async def test_force_plan_failure(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = object()
    mgr._store = SimpleNamespace(async_save=AsyncMock())

    async def _check():
        return (False, None)

    async def _forced():
        return None

    monkeypatch.setattr(mgr, "_check_if_balancing_occurred", _check)
    monkeypatch.setattr(mgr, "_create_forced_plan", _forced)
    assert await mgr.check_balancing(force=True) is None


def test_get_days_and_hours_since_last():
    mgr = _make_manager()
    assert mgr._get_days_since_last_balancing() == 99
    assert mgr._get_hours_since_last_balancing() >= 24

    mgr._last_balancing_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    assert mgr._get_hours_since_last_balancing() >= 2


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_stats_paths(monkeypatch):
    mgr = _make_manager()

    def _stats(_hass, *_a, **_k):
        return {
            "sensor.oig_123_batt_bat_c": [
                {"start": datetime.now(timezone.utc) - timedelta(hours=3), "max": 99},
                {"start": datetime.now(timezone.utc) - timedelta(hours=2), "max": 99},
                {"start": datetime.now(timezone.utc) - timedelta(hours=1), "max": 99},
            ]
        }

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)

    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is True
    assert completion is not None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_varied_starts(monkeypatch):
    mgr = _make_manager()
    now = datetime.now(timezone.utc)
    stats = {
        "sensor.oig_123_batt_bat_c": [
            {"start": None, "mean": 99},
            {"start": now.timestamp(), "mean": 99},
            {"start": now.isoformat(), "mean": 99},
            {"start": "bad", "mean": 99},
            {"start": now, "mean": 98},
        ]
    }

    def _stats(_hass, *_a, **_k):
        return stats

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_recent_and_invalid_type(monkeypatch):
    mgr = _make_manager()
    mgr._last_balancing_ts = datetime.now(timezone.utc)

    stats = {
        "sensor.oig_123_batt_bat_c": [
            {"start": object(), "mean": 99},
        ]
    }

    def _stats(_hass, *_a, **_k):
        return stats

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_runtime_error(monkeypatch):
    mgr = _make_manager()

    def _stats(_hass, *_a, **_k):
        raise RuntimeError("database connection has not been established")

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_runtime_error_other(monkeypatch):
    mgr = _make_manager()

    def _stats(_hass, *_a, **_k):
        raise RuntimeError("boom")

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_exception(monkeypatch):
    mgr = _make_manager()

    def _stats(_hass, *_a, **_k):
        raise ValueError("boom")

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_no_stats(monkeypatch):
    mgr = _make_manager()

    def _stats(_hass, *_a, **_k):
        return {}

    from homeassistant.components.recorder import statistics as rec_stats

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    occurred, completion = await mgr._check_if_balancing_occurred()
    assert occurred is False
    assert completion is None


@pytest.mark.asyncio
async def test_check_natural_balancing_paths(monkeypatch):
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    mgr._forecast_sensor = SimpleNamespace(
        _hybrid_timeline=[
            {"timestamp": (datetime.now() + timedelta(minutes=15 * i)).isoformat(), "battery_soc_kwh": 10}
            for i in range(12)
        ]
    )

    plan = await mgr._check_natural_balancing()
    assert plan is not None

    mgr._forecast_sensor = SimpleNamespace(_hybrid_timeline=[])
    assert await mgr._check_natural_balancing() is None

    mgr = _make_manager()
    mgr._forecast_sensor = SimpleNamespace(_hybrid_timeline=[{"timestamp": datetime.now().isoformat(), "battery_soc_kwh": 0}])
    assert await mgr._check_natural_balancing() is None


@pytest.mark.asyncio
async def test_check_natural_balancing_resets_window():
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    now = datetime.now()
    mgr._forecast_sensor = SimpleNamespace(
        _hybrid_timeline=[
            {"timestamp": (now + timedelta(minutes=15 * i)).isoformat(), "battery_soc_kwh": 10}
            for i in range(2)
        ]
        + [
            {"timestamp": (now + timedelta(minutes=30)).isoformat(), "battery_soc_kwh": 0}
        ]
    )
    assert await mgr._check_natural_balancing() is None

@pytest.mark.asyncio
async def test_create_opportunistic_plan_paths(monkeypatch):
    mgr = _make_manager(
        states={
            "sensor.oig_123_batt_bat_c": DummyState("90"),
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState("10"),
        }
    )
    mgr._forecast_sensor = SimpleNamespace(_timeline_data=[])

    async def _prices():
        return {}

    monkeypatch.setattr(mgr, "_get_spot_prices_48h", _prices)
    plan = await mgr._create_opportunistic_plan()
    assert plan is not None

    mgr = _make_manager(states={"sensor.oig_123_batt_bat_c": DummyState("50")})
    assert await mgr._create_opportunistic_plan() is None

    mgr = _make_manager(states={"sensor.oig_123_batt_bat_c": DummyState("90")})
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", _prices)
    monkeypatch.setattr(mgr, "_get_current_soc_percent", AsyncMock(return_value=None))
    assert await mgr._create_opportunistic_plan() is None


@pytest.mark.asyncio
async def test_create_opportunistic_plan_with_prices_immediate(monkeypatch):
    mgr = _make_manager(states={"sensor.oig_123_batt_bat_c": DummyState("90")})

    now = datetime.now()
    prices = {
        now + timedelta(minutes=15 * i + 60): 1.0 for i in range(16)
    }

    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    monkeypatch.setattr(mgr, "_get_current_soc_percent", AsyncMock(return_value=90.0))
    monkeypatch.setattr(mgr, "_calculate_immediate_balancing_cost", AsyncMock(return_value=1.0))
    monkeypatch.setattr(mgr, "_calculate_total_balancing_cost", AsyncMock(return_value=10.0))

    plan = await mgr._create_opportunistic_plan()
    assert plan is not None
    assert mgr._last_immediate_cost == 1.0
    assert mgr._last_selected_cost == 1.0
    assert mgr._last_cost_savings == 0.0


@pytest.mark.asyncio
async def test_create_opportunistic_plan_with_prices_delayed(monkeypatch):
    mgr = _make_manager(states={"sensor.oig_123_batt_bat_c": DummyState("90")})

    now = datetime.now()
    prices = {
        now + timedelta(minutes=15 * i + 60): 1.0 for i in range(16)
    }

    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    monkeypatch.setattr(mgr, "_get_current_soc_percent", AsyncMock(return_value=90.0))
    monkeypatch.setattr(mgr, "_calculate_immediate_balancing_cost", AsyncMock(return_value=10.0))
    monkeypatch.setattr(mgr, "_calculate_total_balancing_cost", AsyncMock(return_value=1.0))

    plan = await mgr._create_opportunistic_plan()
    assert plan is not None
    assert mgr._last_selected_cost == 1.0
    assert mgr._last_cost_savings == 9.0


@pytest.mark.asyncio
async def test_create_opportunistic_plan_skips_past_and_expensive(monkeypatch):
    mgr = _make_manager(
        options={"cheap_window_percentile": 0},
        states={"sensor.oig_123_batt_bat_c": DummyState("90")},
    )

    now = datetime.now()
    prices = {
        now + timedelta(minutes=15 * i - 15): (1.0 if i == 0 else 10.0)
        for i in range(16)
    }

    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    monkeypatch.setattr(mgr, "_get_current_soc_percent", AsyncMock(return_value=90.0))
    monkeypatch.setattr(mgr, "_calculate_immediate_balancing_cost", AsyncMock(return_value=1.0))
    monkeypatch.setattr(mgr, "_calculate_total_balancing_cost", AsyncMock(return_value=0.5))

    plan = await mgr._create_opportunistic_plan()
    assert plan is not None
    assert mgr._last_selected_cost == 1.0


@pytest.mark.asyncio
async def test_create_forced_plan(monkeypatch):
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    mgr._forecast_sensor = SimpleNamespace(_timeline_data=[])
    plan = await mgr._create_forced_plan()
    assert plan is not None


def test_plan_helpers():
    mgr = _make_manager()
    intervals = mgr._plan_ups_charging(datetime.now(), 100.0, 100.0)
    assert intervals == []

    intervals = mgr._create_holding_intervals(
        datetime.now(), datetime.now() + timedelta(minutes=30), mode=HOME_UPS
    )
    assert intervals


@pytest.mark.asyncio
async def test_cost_helpers(monkeypatch):
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    mgr._forecast_sensor = SimpleNamespace(
        _timeline_data=[
            {"timestamp": datetime.now().isoformat(), "spot_price_czk": 1.0}
        ]
    )
    cost = await mgr._calculate_immediate_balancing_cost(50)
    assert cost > 0

    cost = await mgr._calculate_total_balancing_cost(datetime.now(), 50)
    assert cost > 0


@pytest.mark.asyncio
async def test_calculate_immediate_cost_missing_price(monkeypatch):
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    now = datetime.now()
    prices = {
        now + timedelta(hours=2): 2.0,
        now + timedelta(hours=3): 3.0,
    }
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    assert await mgr._calculate_immediate_balancing_cost(50) == 999.0


@pytest.mark.asyncio
async def test_calculate_immediate_cost_missing_capacity(monkeypatch):
    mgr = _make_manager()
    now = datetime.now()
    prices = {now + timedelta(minutes=30): 2.0}
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    assert await mgr._calculate_immediate_balancing_cost(50) == 999.0


@pytest.mark.asyncio
async def test_calculate_total_cost_missing_capacity():
    mgr = _make_manager()
    cost = await mgr._calculate_total_balancing_cost(datetime.now() + timedelta(hours=1), 50)
    assert cost == 999.0


@pytest.mark.asyncio
async def test_calculate_total_cost_timeline_branches(monkeypatch):
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("10")}
    )
    now = datetime.now()
    mgr._forecast_sensor = SimpleNamespace(
        _timeline_data=[
            {"timestamp": None, "grid_import": 1.0},
            SimpleNamespace(ts=(now + timedelta(minutes=30)).isoformat(), grid_consumption_kwh=1.0),
            SimpleNamespace(ts="bad", grid_import="bad"),
        ]
    )
    prices = {now + timedelta(minutes=15): 2.0}
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))

    cost = await mgr._calculate_total_balancing_cost(now + timedelta(hours=1), 50)
    assert cost > 0


@pytest.mark.asyncio
async def test_cost_helpers_no_prices(monkeypatch):
    mgr = _make_manager()
    mgr._forecast_sensor = SimpleNamespace(_timeline_data=[])
    cost = await mgr._calculate_immediate_balancing_cost(50)
    assert cost == 999.0


@pytest.mark.asyncio
async def test_find_cheap_holding_window_no_prices(monkeypatch):
    mgr = _make_manager()
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value={}))
    assert await mgr._find_cheap_holding_window() is None


@pytest.mark.asyncio
async def test_find_cheap_holding_window_insufficient_intervals(monkeypatch):
    mgr = _make_manager()
    now = datetime.now()
    prices = {
        now + timedelta(minutes=15 * i): 1.0 for i in range(4)
    }
    monkeypatch.setattr(mgr, "_get_spot_prices_48h", AsyncMock(return_value=prices))
    assert await mgr._find_cheap_holding_window() is None


@pytest.mark.asyncio
async def test_find_cheap_holding_window():
    mgr = _make_manager()
    mgr._forecast_sensor = SimpleNamespace(
        _timeline_data=[
            {"timestamp": (datetime.now() + timedelta(minutes=15 * i)).isoformat(), "spot_price_czk": 1.0}
            for i in range(16)
        ]
    )
    window = await mgr._find_cheap_holding_window()
    assert window is not None


@pytest.mark.asyncio
async def test_get_hybrid_timeline_no_sensor():
    mgr = _make_manager()
    assert mgr._get_hybrid_timeline() is None


@pytest.mark.asyncio
async def test_get_current_soc_percent_invalid():
    mgr = _make_manager(
        states={"sensor.oig_123_batt_bat_c": DummyState("bad")}
    )
    assert await mgr._get_current_soc_percent() is None


def test_get_battery_capacity_conversions():
    mgr = _make_manager(
        states={
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState(
                "2000", {"unit_of_measurement": "Wh"}
            )
        }
    )
    assert mgr._get_battery_capacity_kwh() == 2.0

    mgr = _make_manager(
        states={
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState("2000")
        }
    )
    assert mgr._get_battery_capacity_kwh() == 2.0


def test_get_battery_capacity_invalid():
    mgr = _make_manager(
        states={"sensor.oig_123_installed_battery_capacity_kwh": DummyState("bad")}
    )
    assert mgr._get_battery_capacity_kwh() is None


@pytest.mark.asyncio
async def test_get_spot_prices_no_forecast_sensor():
    mgr = _make_manager()
    assert await mgr._get_spot_prices_48h() == {}


def test_sensor_state_and_attributes():
    mgr = _make_manager()
    assert mgr.get_sensor_state() == "overdue"
    attrs = mgr.get_sensor_attributes()
    assert attrs["active_plan"] is None


def test_get_active_plan_and_sensor_states():
    mgr = _make_manager()
    mgr._last_balancing_ts = datetime.now(timezone.utc)

    def _days():
        return 1

    def _cycle():
        return 7

    mgr._get_days_since_last_balancing = _days
    mgr._get_cycle_days = _cycle
    assert mgr.get_sensor_state() == "idle"

    plan = BalancingPlan(
        mode=BalancingMode.OPPORTUNISTIC,
        created_at=datetime.now(timezone.utc).isoformat(),
        reason="active",
        holding_start=datetime.now(timezone.utc).isoformat(),
        holding_end=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        intervals=[],
    )
    mgr._active_plan = plan
    assert mgr.get_active_plan() == plan
    assert mgr.get_sensor_state() == "opportunistic"
