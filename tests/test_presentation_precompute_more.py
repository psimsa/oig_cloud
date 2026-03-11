from __future__ import annotations

import pytest

from custom_components.oig_cloud.battery_forecast.presentation import precompute


class DummyHass:
    def __init__(self):
        self.created = []

    def async_create_task(self, coro):
        self.created.append(coro)
        return coro


class DummyStore:
    async def async_load(self):
        return None

    async def async_save(self, _data):
        return None


class DummySensor:
    def __init__(self):
        self.hass = None
        self._precomputed_store = None
        self._precompute_interval = None
        self._last_precompute_at = None
        self._precompute_task = None
        self._box_id = "123"


@pytest.mark.asyncio
async def test_precompute_ui_data_handles_exception(monkeypatch):
    sensor = DummySensor()
    sensor.hass = DummyHass()
    sensor._precomputed_store = DummyStore()

    async def _boom(*_a, **_k):
        raise RuntimeError("fail")

    monkeypatch.setattr(precompute.detail_tabs_module, "build_detail_tabs", _boom)
    await precompute.precompute_ui_data(sensor)
    assert sensor._last_precompute_at is not None


def test_schedule_precompute_missing_hass_or_store():
    sensor = DummySensor()
    precompute.schedule_precompute(sensor)

    sensor.hass = DummyHass()
    precompute.schedule_precompute(sensor)


@pytest.mark.asyncio
async def test_schedule_precompute_runner_clears_task(monkeypatch):
    sensor = DummySensor()
    sensor.hass = DummyHass()
    sensor._precomputed_store = DummyStore()
    sensor._precompute_interval = 0

    async def _noop(_sensor):
        return None

    monkeypatch.setattr(precompute, "precompute_ui_data", _noop)
    precompute.schedule_precompute(sensor, force=True)
    assert sensor._precompute_task is not None
    await sensor._precompute_task
    assert sensor._precompute_task is None
