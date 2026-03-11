from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.statistics_sensor import (
    OigCloudStatisticsSensor,
)


class DummyHass:
    def __init__(self):
        self.states = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _install_sensor_types(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("custom_components.oig_cloud.sensor_types")
    module.SENSOR_TYPES = {
        "stats_sensor": {
            "name": "Stats",
            "unit": "kWh",
            "device_class": "energy",
            "state_class": "measurement",
            "entity_category": None,
        }
    }
    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.sensor_types", module)


def _make_sensor(monkeypatch: pytest.MonkeyPatch):
    _install_sensor_types(monkeypatch)
    coordinator = SimpleNamespace()
    sensor = OigCloudStatisticsSensor(coordinator, "stats_sensor", device_info={})
    sensor.hass = DummyHass()
    return sensor


def test_is_correct_day_type(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._day_type = "weekday"
    saturday = datetime(2025, 1, 4)
    monday = datetime(2025, 1, 6)
    assert sensor._is_correct_day_type(saturday) is False
    assert sensor._is_correct_day_type(monday) is True


@pytest.mark.asyncio
async def test_calculate_interval_statistics_without_range(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._time_range = None
    assert await sensor._calculate_interval_statistics_from_history() is None


@pytest.mark.asyncio
async def test_calculate_interval_statistics_no_history(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._time_range = (8, 10)
    sensor._max_age_days = 1

    def _history(_hass, _start, _end, _entity_id):
        return {}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history,
    )

    assert await sensor._calculate_interval_statistics_from_history() is None


@pytest.mark.asyncio
async def test_calculate_interval_statistics_with_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._time_range = (6, 8)
    sensor._max_age_days = 2

    class DummyState:
        def __init__(self, state, last_updated):
            self.state = state
            self.last_updated = last_updated

    end_time = datetime.now()
    day0 = end_time.replace(hour=6, minute=30, second=0, microsecond=0)
    day1 = (end_time - timedelta(days=1)).replace(
        hour=6, minute=45, second=0, microsecond=0
    )

    def _history(_hass, _start, _end, entity_id):
        return {
            entity_id: [
                DummyState("100", day0),
                DummyState("200", day0 + timedelta(minutes=15)),
                DummyState("150", day1),
            ]
        }

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history,
    )

    result = await sensor._calculate_interval_statistics_from_history()
    assert result == 150.0
