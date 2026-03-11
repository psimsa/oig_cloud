from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.balancing import core as core_module
from custom_components.oig_cloud.battery_forecast.balancing.plan import (
    BalancingMode,
    BalancingPlan,
    BalancingPriority,
)


class DummyStore:
    data = {}
    saved = None

    def __init__(self, *_args, **_kwargs):
        self.saved = None

    async def async_load(self):
        return DummyStore.data

    async def async_save(self, data):
        DummyStore.saved = data


class DummyEntry:
    def __init__(self, options=None):
        self.options = options or {}


def _make_plan(start: datetime, end: datetime) -> BalancingPlan:
    return BalancingPlan(
        mode=BalancingMode.NATURAL,
        created_at=start.isoformat(),
        reason="test",
        holding_start=start.isoformat(),
        holding_end=end.isoformat(),
        intervals=[],
        locked=False,
        priority=BalancingPriority.NORMAL,
        active=True,
    )


def _make_manager(options=None):
    return core_module.BalancingManager(
        SimpleNamespace(), "123", "path", DummyEntry(options=options)
    )


@pytest.mark.asyncio
async def test_check_balancing_requires_forecast_sensor(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", DummyEntry())

    result = await manager.check_balancing()
    assert result is None


@pytest.mark.asyncio
async def test_check_balancing_active_plan_holding(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", DummyEntry())
    manager._forecast_sensor = object()
    manager._active_plan = _make_plan(now - timedelta(hours=1), now + timedelta(hours=1))

    async def fake_check():
        return False, None

    monkeypatch.setattr(manager, "_check_if_balancing_occurred", fake_check)

    result = await manager.check_balancing()
    assert result == manager._active_plan


@pytest.mark.asyncio
async def test_check_balancing_force_creates_plan(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", DummyEntry())
    manager._forecast_sensor = object()

    async def fake_check():
        return False, None

    plan = _make_plan(now, now + timedelta(hours=3))

    async def fake_create():
        return plan

    async def fake_save():
        return None

    monkeypatch.setattr(manager, "_check_if_balancing_occurred", fake_check)
    monkeypatch.setattr(manager, "_create_forced_plan", fake_create)
    monkeypatch.setattr(manager, "_save_state", fake_save)

    result = await manager.check_balancing(force=True)
    assert result == plan


@pytest.mark.asyncio
async def test_check_balancing_natural_plan(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", DummyEntry())
    manager._forecast_sensor = object()

    async def fake_check():
        return False, None

    plan = _make_plan(now, now + timedelta(hours=3))

    async def fake_natural():
        return plan

    async def fake_save():
        return None

    monkeypatch.setattr(manager, "_check_if_balancing_occurred", fake_check)
    monkeypatch.setattr(manager, "_check_natural_balancing", fake_natural)
    monkeypatch.setattr(manager, "_save_state", fake_save)

    result = await manager.check_balancing()
    assert result == plan


@pytest.mark.asyncio
async def test_check_balancing_forced_by_cycle(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    now = datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    entry = DummyEntry(options={"balancing_cycle_days": 1})
    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", entry)
    manager._forecast_sensor = object()
    manager._last_balancing_ts = now - timedelta(days=2)

    async def fake_check():
        return False, None

    async def fake_natural():
        return None

    plan = _make_plan(now, now + timedelta(hours=3))

    async def fake_forced():
        return plan

    async def fake_save():
        return None

    monkeypatch.setattr(manager, "_check_if_balancing_occurred", fake_check)
    monkeypatch.setattr(manager, "_check_natural_balancing", fake_natural)
    monkeypatch.setattr(manager, "_create_forced_plan", fake_forced)
    monkeypatch.setattr(manager, "_save_state", fake_save)

    result = await manager.check_balancing()
    assert result == plan


@pytest.mark.asyncio
async def test_check_balancing_opportunistic(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    now = datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    entry = DummyEntry(options={"balancing_cooldown_hours": 1})
    manager = core_module.BalancingManager(SimpleNamespace(), "123", "path", entry)
    manager._forecast_sensor = object()
    manager._last_balancing_ts = now - timedelta(hours=5)

    async def fake_check():
        return False, None

    async def fake_natural():
        return None

    async def fake_forced():
        return None

    plan = _make_plan(now, now + timedelta(hours=3))

    async def fake_opportunistic():
        return plan

    async def fake_save():
        return None

    monkeypatch.setattr(manager, "_check_if_balancing_occurred", fake_check)
    monkeypatch.setattr(manager, "_check_natural_balancing", fake_natural)
    monkeypatch.setattr(manager, "_create_forced_plan", fake_forced)
    monkeypatch.setattr(manager, "_create_opportunistic_plan", fake_opportunistic)
    monkeypatch.setattr(manager, "_save_state", fake_save)

    result = await manager.check_balancing()
    assert result == plan


def test_balancing_config_helpers(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    manager = _make_manager(
        options={
            "balancing_hold_hours": 5,
            "balancing_interval_days": 10,
            "balancing_cooldown_hours": 12,
            "balancing_soc_threshold": 75,
            "cheap_window_percentile": "bad",
        }
    )

    assert manager._get_holding_time_hours() == 5
    assert manager._get_cycle_days() == 10
    assert manager._get_cooldown_hours() == 12
    assert manager._get_soc_threshold() == 75
    assert manager._get_cheap_window_percentile() == 30


@pytest.mark.asyncio
async def test_load_and_save_state(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    manager = _make_manager()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    plan = _make_plan(now, now + timedelta(hours=3))
    DummyStore.data = {
        "last_balancing_ts": now.isoformat(),
        "active_plan": plan.to_dict(),
    }

    await manager._load_state_safe()

    assert manager._last_balancing_ts == now
    assert manager._active_plan is not None

    async def _refresh():
        manager._refreshed = True

    manager._refreshed = False
    manager._coordinator = SimpleNamespace(async_request_refresh=_refresh)

    await manager._save_state()

    assert DummyStore.saved["last_balancing_ts"] == now.isoformat()
    assert manager._refreshed is True


def test_get_sensor_state_and_attributes(monkeypatch):
    monkeypatch.setattr(core_module, "Store", DummyStore)
    manager = _make_manager(options={"balancing_cycle_days": 7})

    assert manager.get_sensor_state() == "overdue"

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    plan = _make_plan(now, now + timedelta(hours=3))
    manager._active_plan = plan
    manager._last_balancing_ts = now
    manager._last_immediate_cost = 10.0

    attrs = manager.get_sensor_attributes()

    assert attrs["active_plan"] == plan.mode.value
    assert attrs["immediate_cost_czk"] == 10.0
