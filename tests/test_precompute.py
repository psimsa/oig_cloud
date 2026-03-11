from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import (
    precompute as precompute_module,
)


class DummyStore:
    def __init__(self):
        self.saved = None

    async def async_save(self, data):
        self.saved = data


class DummySensor:
    def __init__(self):
        self._precomputed_store = DummyStore()
        self._timeline_data = [{"time": "t"}]
        self._data_hash = "hash"
        self._last_precompute_hash = None
        self._last_precompute_at = None
        self._precompute_interval = timedelta(seconds=60)
        self._precompute_task = None
        self._box_id = "123"
        self.hass = SimpleNamespace(
            async_create_task=lambda coro: coro,
        )

    async def build_unified_cost_tile(self):
        return {"today": {"plan_total_cost": 1.0}}


@pytest.mark.asyncio
async def test_precompute_ui_data_missing_store():
    sensor = DummySensor()
    sensor._precomputed_store = None

    await precompute_module.precompute_ui_data(sensor)

    assert sensor._last_precompute_at is None


@pytest.mark.asyncio
async def test_precompute_ui_data_success(monkeypatch):
    sensor = DummySensor()

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.precompute.detail_tabs_module.build_detail_tabs",
        lambda *_a, **_k: {"today": {"mode_blocks": [1]}},
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_send",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.precompute.dt_util.now",
        lambda: datetime(2025, 1, 1, 12, 0, 0),
    )

    await precompute_module.precompute_ui_data(sensor)

    assert sensor._precomputed_store.saved is not None
    assert sensor._last_precompute_hash == "hash"
    assert sensor._last_precompute_at is not None


def test_schedule_precompute_throttle(monkeypatch):
    sensor = DummySensor()
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor._last_precompute_at = fixed_now

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.precompute.dt_util.now",
        lambda: fixed_now,
    )

    precompute_module.schedule_precompute(sensor, force=False)

    assert sensor._precompute_task is None


def test_schedule_precompute_creates_task(monkeypatch):
    sensor = DummySensor()
    created = {"coro": None}

    def _create_task(coro):
        created["coro"] = coro
        if hasattr(coro, "close"):
            coro.close()
        return SimpleNamespace(done=lambda: False)

    sensor.hass = SimpleNamespace(async_create_task=_create_task)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.precompute.precompute_ui_data",
        lambda *_a, **_k: None,
    )

    precompute_module.schedule_precompute(sensor, force=True)

    assert created["coro"] is not None
    assert sensor._precompute_task is not None
