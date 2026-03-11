from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.timeline import extended as extended_module


class DummyStore:
    def __init__(self, payload):
        self._payload = payload

    async def async_load(self):
        return self._payload

    async def async_save(self, payload):
        self._payload = payload


class DummySensor:
    def __init__(self, *, hass=None, plans_store=None):
        self._hass = hass
        self._plans_store = plans_store
        self._baseline_repair_attempts = set()
        self._daily_plan_state = None
        self._timeline_data = []
        self._mode_optimization_result = None

    def _is_baseline_plan_invalid(self, plan):
        return bool(plan and plan.get("invalid"))

    async def _save_plan_to_storage(self, _date_str, _intervals, _meta):
        return None

    async def _create_baseline_plan(self, _date_str):
        return True

    def _get_current_mode(self):
        return 0

    def _get_current_battery_soc_percent(self):
        return 55.0

    def _get_current_battery_capacity(self):
        return 5.5


@pytest.mark.asyncio
async def test_build_day_timeline_historical_with_storage(monkeypatch):
    sensor = DummySensor(hass=None, plans_store=None)
    target_day = date.today() - timedelta(days=1)
    date_str = target_day.strftime(extended_module.DATE_FMT)
    planned = [
        {
            "time": f"{date_str}T00:00:00",
            "mode": 0,
            "mode_name": "Home 1",
            "consumption_kwh": 1.2,
            "solar_kwh": 0.4,
            "battery_soc": 55.0,
            "net_cost": 2.0,
        }
    ]
    storage_plans = {"detailed": {date_str: {"intervals": planned}}}

    result = await extended_module.build_day_timeline(
        sensor, target_day, storage_plans
    )

    assert result["date"] == date_str
    assert result["intervals"]
    assert result["summary"]["intervals_count"] == len(result["intervals"])


@pytest.mark.asyncio
async def test_build_day_timeline_mixed_rebuild(monkeypatch):
    today = date.today()
    date_str = today.strftime(extended_module.DATE_FMT)
    storage_plans = {"detailed": {date_str: {"intervals": [], "invalid": True}}}
    sensor = DummySensor(hass=SimpleNamespace(), plans_store=None)
    sensor._daily_plan_state = {
        "date": date_str,
        "plan": [
            {
                "time": f"{date_str}T00:00:00",
                "mode": 0,
                "mode_name": "Home 1",
                "consumption_kwh": 1.0,
                "solar_kwh": 0.2,
                "battery_soc": 50.0,
                "net_cost": 1.5,
            }
        ],
    }
    sensor._timeline_data = [
        {
            "time": f"{date_str}T23:45:00",
            "mode": 0,
            "mode_name": "Home 1",
            "consumption_kwh": 0.8,
            "solar_kwh": 0.1,
            "battery_soc": 48.0,
            "net_cost": 1.2,
        }
    ]

    fixed_now = datetime.combine(today, datetime.min.time()) + timedelta(hours=1)
    monkeypatch.setattr(extended_module.dt_util, "now", lambda: fixed_now)
    monkeypatch.setattr(extended_module.dt_util, "as_local", lambda dt: dt)


    async def _mock_build_modes(*_args, **_kwargs):
        ts = dt_util.as_local(datetime.combine(today, datetime.min.time()))
        key = ts.strftime(extended_module.DATETIME_FMT)
        return {key: {"mode": 0, "mode_name": "Home 1"}}

    async def _mock_fetch_interval(*_args, **_kwargs):
        return {
            "consumption_kwh": 1.1,
            "solar_kwh": 0.3,
            "battery_soc": 52.0,
            "grid_import": 0.4,
            "grid_export": 0.0,
            "net_cost": 1.7,
        }

    monkeypatch.setattr(
        extended_module.history_module,
        "build_historical_modes_lookup",
        _mock_build_modes,
    )
    monkeypatch.setattr(
        extended_module.history_module,
        "fetch_interval_from_history",
        _mock_fetch_interval,
    )

    result = await extended_module.build_day_timeline(
        sensor, today, storage_plans, mode_names={0: "Home 1"}
    )

    assert result["date"] == date_str
    assert result["intervals"]
    assert result["summary"]["intervals_count"] == len(result["intervals"])


@pytest.mark.asyncio
async def test_build_day_timeline_planned_only():
    sensor = DummySensor(hass=None, plans_store=None)
    target_day = date.today() + timedelta(days=1)
    date_str = target_day.strftime(extended_module.DATE_FMT)
    sensor._mode_optimization_result = {
        "optimal_timeline": [
            {
                "time": f"{date_str}T00:00:00",
                "mode": 0,
                "mode_name": "Home 1",
                "consumption_kwh": 1.0,
                "solar_kwh": 0.0,
                "battery_soc": 50.0,
                "net_cost": 1.2,
            }
        ]
    }

    result = await extended_module.build_day_timeline(
        sensor, target_day, {}, mode_names={0: "Home 1"}
    )

    assert result["date"] == date_str
    assert result["intervals"]
    assert result["intervals"][0]["status"] == "planned"
