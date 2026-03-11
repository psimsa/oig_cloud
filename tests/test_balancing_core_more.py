from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.balancing import core as core_module


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class DummyHass:
    def __init__(self, states=None):
        self.states = DummyStates(states or {})
        self.data = {}
        self.config = SimpleNamespace(path=lambda *_parts: "/tmp", config_dir="/tmp")

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make_manager(hass, options=None):
    entry = SimpleNamespace(options=options or {})
    return core_module.BalancingManager(hass, "123", "path", entry)


def test_days_and_hours_since_last_balancing(monkeypatch):
    hass = DummyHass()
    manager = _make_manager(hass, options={"balancing_cooldown_hours": 5})

    assert manager._get_days_since_last_balancing() == 99
    assert manager._get_hours_since_last_balancing() == 5.0

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    manager._last_balancing_ts = now - timedelta(days=2, hours=3)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)

    assert manager._get_days_since_last_balancing() == 2
    assert manager._get_hours_since_last_balancing() == pytest.approx(51.0)


@pytest.mark.asyncio
async def test_check_if_balancing_occurred_detects_completion(monkeypatch):
    hass = DummyHass()
    manager = _make_manager(hass)

    now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(core_module.dt_util, "now", lambda: now)
    monkeypatch.setattr(manager, "_get_holding_time_hours", lambda: 1)

    stats = [
        {"start": now - timedelta(hours=2), "max": 99.5},
        {"start": now - timedelta(hours=1), "max": 99.2},
        {"start": now, "max": 90.0},
    ]

    import homeassistant.components.recorder.statistics as stats_module

    monkeypatch.setattr(
        stats_module,
        "statistics_during_period",
        lambda *_a, **_k: {"sensor.oig_123_batt_bat_c": stats},
    )

    result, completion = await manager._check_if_balancing_occurred()

    assert result is True
    assert completion is not None


@pytest.mark.asyncio
async def test_check_natural_balancing_creates_plan(monkeypatch):
    hass = DummyHass()
    manager = _make_manager(hass)

    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    manager._forecast_sensor = SimpleNamespace(
        _hybrid_timeline=[
            {
                "battery_soc_kwh": 9.9,
                "timestamp": (base + timedelta(minutes=15 * idx)).isoformat(),
            }
            for idx in range(12)
        ]
    )

    monkeypatch.setattr(manager, "_get_battery_capacity_kwh", lambda: 10.0)
    monkeypatch.setattr(
        core_module, "create_natural_plan", lambda *_a, **_k: "plan"
    )

    plan = await manager._check_natural_balancing()

    assert plan == "plan"


def test_get_battery_capacity_kwh_wh_units():
    hass = DummyHass(
        states={
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState(
                "5000", {"unit_of_measurement": "Wh"}
            )
        }
    )
    manager = _make_manager(hass)

    assert manager._get_battery_capacity_kwh() == 5.0


@pytest.mark.asyncio
async def test_get_spot_prices_48h(monkeypatch):
    hass = DummyHass()
    manager = _make_manager(hass)
    manager._forecast_sensor = SimpleNamespace(
        _timeline_data=[
            {"timestamp": "2025-01-01T00:00:00", "spot_price_czk": 1.5},
            {"time": "bad", "spot_price": 2.0},
        ]
    )

    prices = await manager._get_spot_prices_48h()

    assert len(prices) == 1


@pytest.mark.asyncio
async def test_find_cheap_holding_window(monkeypatch):
    hass = DummyHass()
    manager = _make_manager(hass)

    base = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    prices = {
        base + timedelta(minutes=15 * i): price
        for i, price in enumerate([5.0, 4.0, 3.0, 2.0, 10.0])
    }

    async def _get_prices():
        return prices

    monkeypatch.setattr(manager, "_get_spot_prices_48h", _get_prices)
    monkeypatch.setattr(manager, "_get_holding_time_hours", lambda: 1)

    window = await manager._find_cheap_holding_window()

    assert window is not None
    assert window[0] == base
