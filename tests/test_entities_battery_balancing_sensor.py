from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.const import DOMAIN
from custom_components.oig_cloud.entities.battery_balancing_sensor import (
    OigCloudBatteryBalancingSensor,
    _format_hhmm,
    _parse_dt_local,
)


class DummyCoordinator:
    def __init__(self):
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyManager:
    def __init__(self, plan, attrs):
        self._plan = plan
        self._attrs = attrs

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


class DummyHass:
    def __init__(self, entry_id, manager):
        self.data = {DOMAIN: {entry_id: {"balancing_manager": manager}}}


def test_format_hhmm():
    assert _format_hhmm(timedelta(hours=2, minutes=5)) == "02:05"


def test_parse_dt_local():
    dt = _parse_dt_local("2025-01-01T10:00:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_balancing_sensor_update_from_manager(monkeypatch):
    now = datetime(2025, 1, 1, 10, 5, tzinfo=dt_util.UTC)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.battery_balancing_sensor.dt_util.now",
        lambda: now,
    )

    holding_start = now + timedelta(minutes=55)
    holding_end = now + timedelta(hours=2)

    plan = SimpleNamespace(
        holding_start=holding_start.isoformat(),
        holding_end=holding_end.isoformat(),
        intervals=[SimpleNamespace(ts=now.isoformat(), mode="home")],
        reason="unit-test",
        mode=SimpleNamespace(value="home_ups"),
        priority=SimpleNamespace(value="critical"),
    )

    manager_attrs = {
        "last_balancing_ts": now.isoformat(),
        "days_since_last": 1,
        "immediate_cost_czk": 10.0,
        "selected_cost_czk": 8.0,
        "cost_savings_czk": 2.0,
    }

    manager = DummyManager(plan, manager_attrs)
    hass = DummyHass("entry1", manager)

    coordinator = DummyCoordinator()
    config_entry = SimpleNamespace(entry_id="entry1", options={"balancing_enabled": True})
    sensor = OigCloudBatteryBalancingSensor(
        coordinator, "battery_balancing", config_entry, {"identifiers": {("oig", "123")}}, hass
    )

    sensor._update_from_manager()

    assert sensor.native_value == "critical"
    attrs = sensor.extra_state_attributes
    assert attrs["current_state"] == "charging"
    assert attrs["planned"]["mode"] == "home_ups"
    assert attrs["cost_savings_czk"] == 2.0
