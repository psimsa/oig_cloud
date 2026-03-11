from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.oig_cloud.battery_forecast.timeline import extended as module


class DummyStore:
    def __init__(self, data=None, fail=False):
        self._data = data or {}
        self._fail = fail

    async def async_load(self):
        if self._fail:
            raise RuntimeError("boom")
        return self._data


class DummySensor:
    def __init__(self, hass=True):
        self._hass = object() if hass else None
        self._plans_store = None
        self._baseline_repair_attempts = set()
        self._timeline_data = []
        self._mode_optimization_result = None
        self._daily_plan_state = None

    def _is_baseline_plan_invalid(self, plan):
        return bool(plan and plan.get("invalid"))

    async def _save_plan_to_storage(self, *_args, **_kwargs):
        return None

    async def _create_baseline_plan(self, *_args, **_kwargs):
        return True

    def _get_current_mode(self):
        return 1

    def _get_current_battery_soc_percent(self):
        return 55.0

    def _get_current_battery_capacity(self):
        return 5.5


@pytest.mark.asyncio
async def test_build_timeline_extended_storage_error(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore(fail=True)

    fixed_now = datetime(2025, 1, 2, 10, 0, 0)
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)

    async def _day(*_args, **_kwargs):
        return {"intervals": []}

    monkeypatch.setattr(module, "build_day_timeline", _day)
    monkeypatch.setattr(
        module, "build_today_tile_summary", lambda *_a, **_k: {"ok": True}
    )

    result = await module.build_timeline_extended(sensor)
    assert result["today_tile_summary"] == {"ok": True}


@pytest.mark.asyncio
async def test_build_day_timeline_historical_only(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 12, 0, 0)
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)
    monkeypatch.setattr(module.dt_util, "as_local", lambda dt: dt)

    day = fixed_now.date() - timedelta(days=1)
    date_str = day.strftime(module.DATE_FMT)
    storage_plans = {
        "detailed": {
            date_str: {
                "intervals": [
                    {"time": "00:00", "mode": 1, "mode_name": "HOME I"},
                ]
            }
        }
    }

    async def fake_modes(*_args, **_kwargs):
        return {f"{date_str}T00:00:00": {"mode": 1, "mode_name": "HOME I"}}

    async def fake_history(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module.history_module, "build_historical_modes_lookup", fake_modes)
    monkeypatch.setattr(module.history_module, "fetch_interval_from_history", fake_history)

    result = await module.build_day_timeline(sensor, day, storage_plans)
    assert result["date"] == date_str
    assert result["intervals"]


@pytest.mark.asyncio
async def test_build_day_timeline_mixed_with_repair(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 10, 7, 0)
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)
    monkeypatch.setattr(module.dt_util, "as_local", lambda dt: dt)

    date_str = fixed_now.strftime(module.DATE_FMT)
    sensor._plans_store = DummyStore(
        data={"detailed": {date_str: {"intervals": [], "invalid": True}}}
    )

    async def fake_modes(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(module.history_module, "build_historical_modes_lookup", fake_modes)

    sensor._daily_plan_state = {
        "date": date_str,
        "plan": [{"time": "09:45", "net_cost": 1.0}],
        "actual": [],
    }
    sensor._timeline_data = [
        {"time": f"{date_str}T10:15:00", "net_cost": 2.0},
        {"time": "bad"},
    ]

    result = await module.build_day_timeline(sensor, fixed_now.date(), {})
    assert result["date"] == date_str
    assert result["intervals"]


@pytest.mark.asyncio
async def test_build_day_timeline_planned_only(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 10, 0, 0)
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)
    monkeypatch.setattr(module.dt_util, "as_local", lambda dt: dt)

    sensor._mode_optimization_result = {
        "optimal_timeline": [
            {"time": "2025-01-03T00:00:00", "mode": 1},
            {"time": "bad"},
        ]
    }

    day = fixed_now.date() + timedelta(days=1)
    result = await module.build_day_timeline(sensor, day, {})
    assert result["intervals"]
