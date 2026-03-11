from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.oig_cloud.battery_forecast.storage import (
    plan_storage_baseline as module,
)


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
        self._plans_store = DummyStore()
        self._timeline_data = []
        self._daily_plan_state = None


def _valid_intervals():
    return [{"time": f"{i // 4:02d}:{(i % 4) * 15:02d}", "consumption_kwh": 0.1} for i in range(96)]


def test_is_baseline_plan_invalid_low_consumption():
    intervals = [{"consumption_kwh": 0.0} for _ in range(96)]
    intervals[0]["consumption_kwh"] = 0.1
    assert module.is_baseline_plan_invalid({"intervals": intervals}) is True


@pytest.mark.asyncio
async def test_create_baseline_plan_daily_plan_state(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = []
    sensor._daily_plan_state = {"date": "2025-01-01", "plan": _valid_intervals()}

    async def _save(_sensor, date_str, intervals, meta):
        return True

    monkeypatch.setattr(module, "save_plan_to_storage", _save)
    ok = await module.create_baseline_plan(sensor, "2025-01-01")
    assert ok is True


@pytest.mark.asyncio
async def test_create_baseline_plan_no_fallback(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = []
    sensor._plans_store = DummyStore(data={}, raise_error=True)

    called = {"save": False}

    async def _save(*_a, **_k):
        called["save"] = True
        return True

    monkeypatch.setattr(module, "save_plan_to_storage", _save)
    ok = await module.create_baseline_plan(sensor, "2025-01-01")
    assert ok is False
    assert called["save"] is False


@pytest.mark.asyncio
async def test_create_baseline_plan_history_and_save_fail(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = [
        {"time": ""},
        {"timestamp": "2025-01-01T00:15:00"},
        {"time": "2025-01-01Tbad"},
    ]

    calls = {"history": 0}

    async def _fetch(*_a, **_k):
        calls["history"] += 1
        if calls["history"] == 1:
            return {
                "solar_kwh": 1.0,
                "consumption_kwh": 2.0,
                "battery_soc": 55.0,
                "battery_kwh": 8.0,
                "grid_import_kwh": 0.2,
                "grid_export_kwh": 0.1,
                "mode": 1,
                "mode_name": "HOME I",
                "spot_price": 2.0,
                "net_cost": 0.5,
            }
        return None

    async def _save(*_a, **_k):
        return False

    monkeypatch.setattr(module.history_module, "fetch_interval_from_history", _fetch)
    monkeypatch.setattr(module, "save_plan_to_storage", _save)

    ok = await module.create_baseline_plan(sensor, "2025-01-01")
    assert ok is False


@pytest.mark.asyncio
async def test_create_baseline_plan_exception(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = [{"time": "00:00"}]

    async def _fetch(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(module.history_module, "fetch_interval_from_history", _fetch)
    ok = await module.create_baseline_plan(sensor, "2025-01-01")
    assert ok is False


@pytest.mark.asyncio
async def test_ensure_plan_exists_retry_and_emergency(monkeypatch):
    sensor = DummySensor()

    async def _exists(*_a, **_k):
        return False

    async def _create(*_a, **_k):
        return True

    monkeypatch.setattr(module, "plan_exists_in_storage", _exists)
    monkeypatch.setattr(module, "create_baseline_plan", _create)
    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 6, 5, 0))
    assert await module.ensure_plan_exists(sensor, "2025-01-01") is True

    async def _create_fail(*_a, **_k):
        return False

    monkeypatch.setattr(module, "create_baseline_plan", _create_fail)
    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 13, 0, 0))
    assert await module.ensure_plan_exists(sensor, "2025-01-01") is False
