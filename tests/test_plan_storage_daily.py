from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.storage import (
    plan_storage_daily as daily_module,
)


class DummyStore:
    def __init__(self):
        self.saved = None
        self.loaded = {}

    async def async_load(self):
        return self.loaded

    async def async_save(self, data):
        self.saved = data


class DummySensor:
    def __init__(self):
        self._daily_plan_state = None
        self._daily_plans_archive = {}
        self._plans_store = DummyStore()
        self._mode_optimization_result = None


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_keeps_existing(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {
        "date": "2025-01-02",
        "plan": [{"time": "2025-01-02T00:00:00"}],
        "actual": [],
    }

    fixed_now = datetime(2025, 1, 2, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)

    assert sensor._daily_plan_state["date"] == "2025-01-02"
    assert sensor._daily_plans_archive == {}


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_archives_and_builds(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {
        "date": "2025-01-01",
        "plan": [{"time": "2025-01-01T00:00:00"}],
        "actual": [{"time": "2025-01-01T00:00:00"}],
    }
    sensor._mode_optimization_result = {
        "optimal_timeline": [
            {
                "timestamp": "2025-01-02T00:00:00",
            },
            {
                "time": "2025-01-02T00:30:00",
                "timestamp": "2025-01-02T00:30:00",
            },
            {
                "time": "2025-01-02T01:00:00+00:00",
                "timestamp": "2025-01-02T01:00:00",
                "solar_kwh": 1.0,
                "load_kwh": 2.0,
                "battery_soc": 50.0,
                "battery_capacity_kwh": 5.0,
                "grid_import": 0.5,
                "grid_export": 0.1,
                "mode": 1,
                "mode_name": "Test",
                "spot_price": 2.0,
                "net_cost": 1.2,
            }
        ],
        "mode_recommendations": [
            {"mode": 1},
            {"from_time": "2025-01-02T02:00:00", "mode": 1},
            {"from_time": "2025-01-02T03:00:00+00:00", "mode": 1},
        ],
    }

    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)

    assert "2025-01-01" in sensor._daily_plans_archive
    assert sensor._daily_plan_state["date"] == "2025-01-02"
    assert sensor._daily_plan_state["plan"]
    assert sensor._plans_store.saved["daily_archive"]


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_baseline_creation(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = None
    fixed_now = datetime(2025, 1, 2, 0, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    called = {"exists": 0, "baseline": 0}

    async def _exists(_sensor, _date):
        called["exists"] += 1
        return False

    async def _baseline(_sensor, _date):
        called["baseline"] += 1
        return True

    monkeypatch.setattr(daily_module, "plan_exists_in_storage", _exists)
    monkeypatch.setattr(daily_module, "create_baseline_plan", _baseline)

    await daily_module.maybe_fix_daily_plan(sensor)

    assert called["exists"] == 1
    assert called["baseline"] == 1


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_baseline_failure(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 0, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    async def _exists(_sensor, _date):
        return False

    async def _baseline(_sensor, _date):
        return False

    monkeypatch.setattr(daily_module, "plan_exists_in_storage", _exists)
    monkeypatch.setattr(daily_module, "create_baseline_plan", _baseline)

    await daily_module.maybe_fix_daily_plan(sensor)


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_baseline_exists(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 2, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    async def _exists(_sensor, _date):
        return True

    monkeypatch.setattr(daily_module, "plan_exists_in_storage", _exists)
    await daily_module.maybe_fix_daily_plan(sensor)
    assert sensor._daily_plan_state["date"] == "2025-01-02"


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_missing_mode_result(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {"date": "2025-01-01", "plan": [], "actual": []}

    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)

    assert sensor._daily_plan_state["date"] == "2025-01-02"
    assert sensor._daily_plan_state["plan"] == []


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_archive_save_error(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {"date": "2025-01-01", "plan": [], "actual": []}

    class BrokenStore(DummyStore):
        async def async_save(self, data):
            raise RuntimeError("fail")

    sensor._plans_store = BrokenStore()

    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)
    assert "2025-01-01" in sensor._daily_plans_archive


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_invalid_times(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {"date": "2025-01-01", "plan": [], "actual": []}
    sensor._mode_optimization_result = {
        "optimal_timeline": [{"time": "bad"}],
        "mode_recommendations": [{"from_time": "bad"}],
    }

    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)
    assert sensor._daily_plan_state["date"] == "2025-01-02"


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_missing_attr(monkeypatch):
    class MinimalSensor:
        def __init__(self):
            self._daily_plans_archive = {}
            self._plans_store = DummyStore()
            self._mode_optimization_result = None

    sensor = MinimalSensor()
    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)
    assert sensor._daily_plan_state["date"] == "2025-01-02"


@pytest.mark.asyncio
async def test_maybe_fix_daily_plan_preserves_actual(monkeypatch):
    sensor = DummySensor()
    sensor._daily_plan_state = {"date": "2025-01-02", "plan": [], "actual": [{"a": 1}]}
    sensor._mode_optimization_result = {
        "optimal_timeline": [
            {
                "time": "2025-01-02T01:00:00+00:00",
                "timestamp": "2025-01-02T01:00:00",
            }
        ],
        "mode_recommendations": [],
    }

    fixed_now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.storage.plan_storage_daily.dt_util.now",
        lambda: fixed_now,
    )

    await daily_module.maybe_fix_daily_plan(sensor)
    assert sensor._daily_plan_state["actual"] == [{"a": 1}]
