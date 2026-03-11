from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.const import DOMAIN
from custom_components.oig_cloud.entities import battery_balancing_sensor as module
from custom_components.oig_cloud.entities.battery_balancing_sensor import (
    OigCloudBatteryBalancingSensor,
    _format_hhmm,
    _parse_dt_local,
)


class DummyCoordinator:
    def __init__(self, hass=None):
        self.hass = hass

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, entry_id="entry1", options=None):
        self.entry_id = entry_id
        self.options = options or {}


class DummyPlan:
    def __init__(self, holding_start, holding_end, mode="forced", priority="critical"):
        self.holding_start = (
            holding_start.isoformat()
            if isinstance(holding_start, datetime)
            else holding_start
        )
        self.holding_end = (
            holding_end.isoformat()
            if isinstance(holding_end, datetime)
            else holding_end
        )
        self.mode = SimpleNamespace(value=mode)
        self.priority = SimpleNamespace(value=priority)
        self.reason = "test"
        self.intervals = []


class DummyManager:
    def __init__(self, attrs=None, plan=None):
        self._attrs = attrs or {}
        self._plan = plan

    def get_sensor_attributes(self):
        return self._attrs

    def get_active_plan(self):
        return self._plan

    def _get_cycle_days(self):
        return 7

    def _get_holding_time_hours(self):
        return 3

    def _get_soc_threshold(self):
        return 80


def _make_sensor(hass, options=None):
    coordinator = DummyCoordinator(hass)
    entry = DummyConfigEntry(options=options)
    return OigCloudBatteryBalancingSensor(coordinator, "battery_balancing", entry, {}, hass)


def test_format_hhmm():
    assert _format_hhmm(timedelta(hours=2, minutes=5)) == "02:05"


def test_parse_dt_local_invalid():
    assert _parse_dt_local("bad") is None


def test_update_from_manager_disabled(hass, monkeypatch):
    manager = DummyManager(attrs={"days_since_last": 1})
    hass.data[DOMAIN] = {"entry1": {"balancing_manager": manager}}
    sensor = _make_sensor(hass, options={"balancing_enabled": False})
    sensor._update_from_manager()
    assert sensor.native_value == "disabled"


def test_update_from_manager_active_plan_balancing(hass, monkeypatch):
    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=module.dt_util.DEFAULT_TIME_ZONE)
    plan = DummyPlan(
        holding_start=now - timedelta(minutes=15),
        holding_end=now + timedelta(minutes=15),
    )
    manager = DummyManager(
        attrs={"days_since_last": 1, "last_balancing_ts": now.isoformat()},
        plan=plan,
    )
    hass.data[DOMAIN] = {"entry1": {"balancing_manager": manager}}
    sensor = _make_sensor(hass, options={"balancing_enabled": True})
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.battery_balancing_sensor.dt_util.now",
        lambda: now,
    )
    sensor._update_from_manager()
    assert sensor.native_value == "critical"
    assert sensor.extra_state_attributes["current_state"] == "balancing"


def test_update_from_manager_overdue(hass):
    manager = DummyManager(attrs={"days_since_last": 10})
    hass.data[DOMAIN] = {"entry1": {"balancing_manager": manager}}
    sensor = _make_sensor(hass)
    sensor._update_from_manager()
    assert sensor.native_value == "overdue"


@pytest.mark.asyncio
async def test_async_added_to_hass_restores(hass, monkeypatch):
    sensor = _make_sensor(hass)
    sensor.hass = hass

    old_state = SimpleNamespace(
        state="ok",
        attributes={
            "last_balancing": "2025-01-01T00:00:00",
            "days_since_last": "3",
            "planned": {"k": 1},
            "cost_immediate_czk": 1.2,
            "cost_selected_czk": 2.3,
            "cost_savings_czk": 3.4,
        },
    )
    async def _get_state():
        return old_state

    sensor.async_get_last_state = _get_state
    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=module.dt_util.DEFAULT_TIME_ZONE)
    plan = DummyPlan(now + timedelta(minutes=15), now + timedelta(minutes=45))
    hass.data[DOMAIN] = {
        "entry1": {
            "balancing_manager": DummyManager(
                attrs={"days_since_last": 1, "last_balancing_ts": now.isoformat()},
                plan=plan,
            )
        }
    }

    await sensor.async_added_to_hass()
    assert sensor.native_value == "critical"
    assert sensor.extra_state_attributes["planned"] is not None
