from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.presentation import (
    precompute as precompute_module,
    unified_cost_tile,
)


class DummyStore:
    def __init__(self):
        self.saved = None

    async def async_save(self, data):
        self.saved = data


class DummyHass:
    def __init__(self):
        self.created = []

    def async_create_task(self, coro):
        coro.close()
        self.created.append(True)
        return object()


class DummySensor:
    def __init__(self):
        self._precomputed_store = DummyStore()
        self._timeline_data = [{"time": "2025-01-01T00:00:00"}]
        self._data_hash = "hash"
        self._last_precompute_hash = None
        self._last_precompute_at = None
        self._precompute_interval = timedelta(minutes=15)
        self._precompute_task = None
        self._box_id = "123"
        self.hass = None

    async def build_unified_cost_tile(self):
        return {"today": {"plan_total_cost": 1.0}}


@pytest.mark.asyncio
async def test_precompute_ui_data_saves_payload(monkeypatch):
    sensor = DummySensor()

    async def _fake_detail_tabs(_sensor, plan="active"):
        return {"today": {"mode_blocks": [1]}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.detail_tabs.build_detail_tabs",
        _fake_detail_tabs,
    )

    await precompute_module.precompute_ui_data(sensor)

    assert sensor._precomputed_store.saved is not None
    assert sensor._precomputed_store.saved["timeline"] == sensor._timeline_data
    assert sensor._last_precompute_hash == "hash"
    assert sensor._last_precompute_at is not None


@pytest.mark.asyncio
async def test_precompute_ui_data_skips_without_store():
    sensor = DummySensor()
    sensor._precomputed_store = None

    await precompute_module.precompute_ui_data(sensor)

    assert sensor._last_precompute_at is None


@pytest.mark.asyncio
async def test_precompute_ui_data_handles_detail_tabs_error(monkeypatch):
    sensor = DummySensor()

    async def _fail_detail_tabs(_sensor, plan="active"):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.detail_tabs.build_detail_tabs",
        _fail_detail_tabs,
    )

    await precompute_module.precompute_ui_data(sensor)

    assert sensor._precomputed_store.saved is not None
    assert sensor._precomputed_store.saved["detail_tabs"] == {}


def test_schedule_precompute_skips_recent():
    sensor = DummySensor()
    sensor.hass = DummyHass()
    sensor._last_precompute_at = dt_util.now()

    precompute_module.schedule_precompute(sensor, force=False)
    assert sensor._precompute_task is None


def test_schedule_precompute_skips_running():
    sensor = DummySensor()
    sensor.hass = DummyHass()

    class DummyTask:
        def done(self):
            return False

    sensor._precompute_task = DummyTask()
    precompute_module.schedule_precompute(sensor, force=False)
    assert sensor._precompute_task is not None


def test_schedule_precompute_creates_task():
    sensor = DummySensor()
    sensor.hass = DummyHass()
    sensor._last_precompute_at = dt_util.now() - timedelta(minutes=30)

    precompute_module.schedule_precompute(sensor, force=False)
    assert sensor._precompute_task is not None


@pytest.mark.asyncio
async def test_build_unified_cost_tile_success(monkeypatch):
    async def _today(_sensor):
        return {"plan_total_cost": 2.0}

    async def _tomorrow(_sensor, mode_names=None):
        return {"plan_total_cost": 3.0}

    def _yesterday(_sensor, mode_names=None):
        return {"plan_total_cost": 1.0}

    monkeypatch.setattr(unified_cost_tile, "build_today_cost_data", _today)
    monkeypatch.setattr(unified_cost_tile, "build_tomorrow_cost_data", _tomorrow)
    monkeypatch.setattr(unified_cost_tile, "get_yesterday_cost_from_archive", _yesterday)

    result = await unified_cost_tile.build_unified_cost_tile(object())
    assert result["today"]["plan_total_cost"] == 2.0
    assert result["tomorrow"]["plan_total_cost"] == 3.0
    assert result["yesterday"]["plan_total_cost"] == 1.0


@pytest.mark.asyncio
async def test_build_unified_cost_tile_handles_error(monkeypatch):
    async def _fail(_sensor):
        raise RuntimeError("boom")

    monkeypatch.setattr(unified_cost_tile, "build_today_cost_data", _fail)
    monkeypatch.setattr(unified_cost_tile, "build_tomorrow_cost_data", _fail)
    monkeypatch.setattr(
        unified_cost_tile,
        "get_yesterday_cost_from_archive",
        lambda _sensor, mode_names=None: {},
    )

    result = await unified_cost_tile.build_unified_cost_tile(object())
    assert result["today"]["error"]
    assert result["tomorrow"]["error"]
