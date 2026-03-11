from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.storage import plan_storage_baseline as module


class DummyStore:
    def __init__(self, data=None):
        self._data = data or {}
        self.saved = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self.saved = data


class DummySensor:
    def __init__(self):
        self._plans_store = DummyStore()
        self._timeline_data = []
        self._daily_plan_state = None


def test_is_baseline_plan_invalid():
    assert module.is_baseline_plan_invalid(None) is True
    assert module.is_baseline_plan_invalid({"intervals": []}) is True
    assert (
        module.is_baseline_plan_invalid(
            {"intervals": [{"consumption_kwh": 0.0}] * 100, "filled_intervals": "00:00-23:45"}
        )
        is True
    )
    assert (
        module.is_baseline_plan_invalid(
            {"intervals": [{"consumption_kwh": 0.1}] * 100, "filled_intervals": None}
        )
        is False
    )


@pytest.mark.asyncio
async def test_create_baseline_plan_with_hybrid_timeline(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = [
        {
            "time": "00:00",
            "solar_kwh": 0.1,
            "load_kwh": 0.2,
            "battery_soc": 50.0,
            "battery_capacity_kwh": 7.68,
            "grid_import": 0.1,
            "grid_export": 0.0,
            "mode": 2,
            "mode_name": "HOME III",
            "spot_price": 3.0,
            "net_cost": 0.2,
        },
        {
            "time": "00:15",
            "solar_kwh": 0.1,
            "load_kwh": 0.2,
            "battery_soc": 50.0,
            "battery_capacity_kwh": 7.68,
            "grid_import": 0.1,
            "grid_export": 0.0,
            "mode": 2,
            "mode_name": "HOME III",
            "spot_price": 3.0,
            "net_cost": 0.2,
        },
    ]

    async def fake_fetch(*_args, **_kwargs):
        return None

    captured = {}

    async def fake_save(_sensor, date_str, intervals, meta):
        captured["date"] = date_str
        captured["intervals"] = intervals
        captured["meta"] = meta
        return True

    monkeypatch.setattr(module.history_module, "fetch_interval_from_history", fake_fetch)
    monkeypatch.setattr(module, "save_plan_to_storage", fake_save)

    ok = await module.create_baseline_plan(sensor, "2025-01-01")

    assert ok is True
    assert captured["date"] == "2025-01-01"
    assert len(captured["intervals"]) == 96
    assert captured["meta"]["baseline"] is True


@pytest.mark.asyncio
async def test_create_baseline_plan_from_storage_fallback(monkeypatch):
    sensor = DummySensor()
    sensor._timeline_data = []
    fallback_intervals = [
        {
            "time": f"{i // 4:02d}:{(i % 4) * 15:02d}",
            "consumption_kwh": 0.1,
        }
        for i in range(96)
    ]
    sensor._plans_store = DummyStore(
        {
            "daily_archive": {
                "2025-01-01": {"plan": fallback_intervals}
            }
        }
    )

    captured = {}

    async def fake_save(_sensor, date_str, intervals, meta):
        captured["intervals"] = intervals
        captured["meta"] = meta
        return True

    monkeypatch.setattr(module, "save_plan_to_storage", fake_save)

    ok = await module.create_baseline_plan(sensor, "2025-01-01")

    assert ok is True
    assert captured["meta"]["baseline"] is True
    assert captured["intervals"][0]["time"] == "00:00"


@pytest.mark.asyncio
async def test_ensure_plan_exists(monkeypatch):
    sensor = DummySensor()

    async def fake_exists(_sensor, _date):
        return False

    async def fake_create(_sensor, _date):
        return True

    monkeypatch.setattr(module, "plan_exists_in_storage", fake_exists)
    monkeypatch.setattr(module, "create_baseline_plan", fake_create)
    monkeypatch.setattr(
        module.dt_util,
        "now",
        lambda: datetime(2025, 1, 1, 0, 20, 0),
    )

    ok = await module.ensure_plan_exists(sensor, "2025-01-01")
    assert ok is True
