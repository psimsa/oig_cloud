from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.oig_cloud.battery_forecast.storage import plan_storage_baseline as module


class DummySensor:
    def __init__(self):
        self._plans_store = None
        self._timeline_data = []
        self._daily_plan_state = None


@pytest.mark.asyncio
async def test_create_baseline_plan_no_store():
    sensor = DummySensor()
    ok = await module.create_baseline_plan(sensor, "2025-01-01")
    assert ok is False


@pytest.mark.asyncio
async def test_ensure_plan_exists_already(monkeypatch):
    sensor = DummySensor()

    async def _exists(*_a, **_k):
        return True

    monkeypatch.setattr(module, "plan_exists_in_storage", _exists)
    ok = await module.ensure_plan_exists(sensor, "2025-01-01")
    assert ok is True


@pytest.mark.asyncio
async def test_ensure_plan_exists_not_today(monkeypatch):
    sensor = DummySensor()

    async def _exists(*_a, **_k):
        return False

    monkeypatch.setattr(module, "plan_exists_in_storage", _exists)
    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 2, 1, 0, 0))
    ok = await module.ensure_plan_exists(sensor, "2025-01-01")
    assert ok is False


@pytest.mark.asyncio
async def test_ensure_plan_exists_midnight(monkeypatch):
    sensor = DummySensor()

    async def _exists(*_a, **_k):
        return False

    async def _create(*_a, **_k):
        return True

    monkeypatch.setattr(module, "plan_exists_in_storage", _exists)
    monkeypatch.setattr(module, "create_baseline_plan", _create)
    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 0, 20, 0))
    ok = await module.ensure_plan_exists(sensor, "2025-01-01")
    assert ok is True
