from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.balancing import helpers


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummySensor:
    def __init__(self):
        self._balancing_plan_snapshot = None
        self._active_charging_plan = None
        self._hass = None
        self._box_id = "123"


def test_update_balancing_plan_snapshot_sets_active():
    sensor = DummySensor()
    plan = {"requester": "BalancingManager"}
    helpers.update_balancing_plan_snapshot(sensor, plan)
    assert sensor._balancing_plan_snapshot == plan
    assert sensor._active_charging_plan == plan


def test_update_balancing_plan_snapshot_clears_on_balancing():
    sensor = DummySensor()
    sensor._active_charging_plan = {"requester": "balancing_manager"}
    helpers.update_balancing_plan_snapshot(sensor, None)
    assert sensor._active_charging_plan is None


def test_get_balancing_plan():
    sensor = DummySensor()
    planned = {"reason": "manual", "holding_start": "a", "holding_end": "b"}
    state = SimpleNamespace(attributes={"planned": planned})
    sensor._hass = SimpleNamespace(
        states=DummyStates({"sensor.oig_123_battery_balancing": state})
    )

    result = helpers.get_balancing_plan(sensor)
    assert result == planned


def test_get_balancing_plan_no_hass():
    sensor = DummySensor()
    assert helpers.get_balancing_plan(sensor) is None


def test_get_balancing_plan_no_state():
    sensor = DummySensor()
    sensor._hass = SimpleNamespace(states=DummyStates({}))
    assert helpers.get_balancing_plan(sensor) is None


def test_get_balancing_plan_no_planned():
    sensor = DummySensor()
    state = SimpleNamespace(attributes={})
    sensor._hass = SimpleNamespace(
        states=DummyStates({"sensor.oig_123_battery_balancing": state})
    )
    assert helpers.get_balancing_plan(sensor) is None


def test_get_balancing_plan_empty_planned():
    sensor = DummySensor()
    state = SimpleNamespace(attributes={"planned": None})
    sensor._hass = SimpleNamespace(
        states=DummyStates({"sensor.oig_123_battery_balancing": state})
    )
    assert helpers.get_balancing_plan(sensor) is None


def test_update_balancing_plan_snapshot_empty_requester():
    sensor = DummySensor()
    sensor._active_charging_plan = {"requester": None}
    helpers.update_balancing_plan_snapshot(sensor, {"requester": "X"})
    assert sensor._active_charging_plan["requester"] is None


@pytest.mark.asyncio
async def test_plan_balancing_success():
    sensor = DummySensor()
    start = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=45)

    result = await helpers.plan_balancing(sensor, start, end, 80.0, "test")
    assert result["can_do"] is True
    assert len(result["charging_intervals"]) == 3


@pytest.mark.asyncio
async def test_plan_balancing_error(monkeypatch):
    sensor = DummySensor()
    start = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(helpers, "timedelta", _boom)
    result = await helpers.plan_balancing(sensor, start, end, 80.0, "test")
    assert result["can_do"] is False
