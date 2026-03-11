from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.timeline import extended as module


class DummyStore:
    def __init__(self, data=None, raise_error: bool = False):
        self._data = data or {}
        self._raise_error = raise_error

    async def async_load(self):
        if self._raise_error:
            raise RuntimeError("boom")
        return self._data


class DummySensor:
    def __init__(self):
        self._plans_store = None
        self._hass = None
        self._daily_plan_state = None
        self._timeline_data = []
        self._baseline_repair_attempts = set()
        self._mode_optimization_result = None

    def _is_baseline_plan_invalid(self, _plan):
        return False

    async def _save_plan_to_storage(self, *_a, **_k):
        return None

    async def _create_baseline_plan(self, *_a, **_k):
        return False

    def _get_current_mode(self):
        return 0

    def _get_current_battery_soc_percent(self):
        return 55.5

    def _get_current_battery_capacity(self):
        return 8.0


@pytest.mark.asyncio
async def test_build_timeline_extended_storage_error(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore(raise_error=True)

    async def _fake_day(*_a, **_k):
        return {"intervals": []}

    monkeypatch.setattr(module, "build_day_timeline", _fake_day)
    data = await module.build_timeline_extended(sensor)
    assert "today_tile_summary" in data


@pytest.mark.asyncio
async def test_build_day_timeline_historical_archive_save_error(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore()
    sensor._hass = SimpleNamespace()

    async def _save(*_a, **_k):
        raise RuntimeError("boom")

    sensor._save_plan_to_storage = _save

    monkeypatch.setattr(
        module.history_module,
        "build_historical_modes_lookup",
        lambda *_a, **_k: {"2025-01-01T00:00:00": {"mode": 1, "mode_name": "Home 1"}},
    )
    monkeypatch.setattr(
        module.history_module,
        "fetch_interval_from_history",
        lambda *_a, **_k: None,
    )

    storage_plans = {
        "daily_archive": {
            "2025-01-01": {"plan": [{"time": "bad"}]}
        }
    }
    day = dt_util.as_local(datetime(2025, 1, 1)).date()
    data = await module.build_day_timeline(sensor, day, storage_plans)
    assert data["date"] == "2025-01-01"


@pytest.mark.asyncio
async def test_build_day_timeline_historical_archive_invalid(monkeypatch):
    sensor = DummySensor()
    sensor._hass = SimpleNamespace()
    sensor._is_baseline_plan_invalid = lambda *_a, **_k: True

    monkeypatch.setattr(
        module.history_module,
        "build_historical_modes_lookup",
        lambda *_a, **_k: {},
    )

    storage_plans = {
        "daily_archive": {
            "2025-01-01": {"plan": [{"time": "00:00"}]}
        }
    }
    day = dt_util.as_local(datetime(2025, 1, 1)).date()
    data = await module.build_day_timeline(sensor, day, storage_plans)
    assert data["intervals"]


@pytest.mark.asyncio
async def test_build_day_timeline_mixed_repair_and_parse_errors(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore(raise_error=True)
    sensor._hass = SimpleNamespace()
    sensor._daily_plan_state = {
        "date": "2025-01-02",
        "plan": [],
        "actual": [{"time": "00:00"}, {"time": "bad"}],
    }
    sensor._timeline_data = [{"time": "bad"}, {"time": "2025-01-03T00:00:00"}]

    async def _create(*_a, **_k):
        raise RuntimeError("boom")

    sensor._create_baseline_plan = _create

    monkeypatch.setattr(
        module.history_module,
        "build_historical_modes_lookup",
        lambda *_a, **_k: {"2025-01-02T00:00:00": {"mode": 1, "mode_name": "Home 1"}},
    )
    monkeypatch.setattr(
        module.history_module,
        "fetch_interval_from_history",
        lambda *_a, **_k: None,
    )

    fixed_now = dt_util.as_local(datetime(2025, 1, 2, 0, 5, 0))
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)

    data = await module.build_day_timeline(sensor, fixed_now.date(), {})
    assert data["intervals"]


@pytest.mark.asyncio
async def test_build_day_timeline_mixed_repair_reload_error(monkeypatch):
    sensor = DummySensor()
    sensor._plans_store = DummyStore(raise_error=True)
    sensor._hass = SimpleNamespace()

    async def _create(*_a, **_k):
        return True

    sensor._create_baseline_plan = _create

    monkeypatch.setattr(
        module.history_module,
        "build_historical_modes_lookup",
        lambda *_a, **_k: {},
    )

    fixed_now = dt_util.as_local(datetime(2025, 1, 2, 0, 5, 0))
    monkeypatch.setattr(module.dt_util, "now", lambda: fixed_now)

    data = await module.build_day_timeline(sensor, fixed_now.date(), {})
    assert isinstance(data["intervals"], list)


@pytest.mark.asyncio
async def test_build_day_timeline_planned_only(monkeypatch):
    sensor = DummySensor()
    day = dt_util.as_local(datetime(2025, 1, 3)).date()
    sensor._mode_optimization_result = {
        "optimal_timeline": [
            {"time": ""},
            {"time": "bad"},
            {"time": "2025-01-03T00:00:00", "mode": 1},
        ]
    }

    data = await module.build_day_timeline(sensor, day, {})
    assert data["intervals"]
