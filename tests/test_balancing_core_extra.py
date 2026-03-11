from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.balancing.core import (
    BalancingManager,
    MIN_MODE_DURATION,
)
from custom_components.oig_cloud.battery_forecast.balancing.plan import (
    BalancingMode,
    BalancingPlan,
)
from custom_components.oig_cloud.const import HOME_UPS


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, states=None):
        self.states = DummyStates(states or {})
        self.data = {}

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


def _make_manager(hass, options=None):
    options = options or {}
    entry = SimpleNamespace(options=options)
    return BalancingManager(hass, "123", "/tmp/balancing.json", entry)


class DummyStore:
    def __init__(self, *_args, **_kwargs):
        self.saved = None
        self.loaded = None

    async def async_load(self):
        return self.loaded

    async def async_save(self, data):
        self.saved = data


@pytest.fixture(autouse=True)
def _patch_store(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.balancing.core.Store",
        DummyStore,
    )


def test_config_helpers_default_and_overrides():
    manager = _make_manager(
        DummyHass(),
        options={
            "balancing_hold_hours": 4,
            "balancing_interval_days": 10,
            "balancing_cooldown_hours": 48,
            "balancing_soc_threshold": 85,
            "cheap_window_percentile": 25,
        },
    )
    assert manager._get_holding_time_hours() == 4
    assert manager._get_cycle_days() == 10
    assert manager._get_cooldown_hours() == 48
    assert manager._get_soc_threshold() == 85
    assert manager._get_cheap_window_percentile() == 25


def test_plan_ups_charging_and_holding_intervals():
    manager = _make_manager(DummyHass())
    target_time = datetime(2025, 1, 1, 10, 0, 0)

    intervals = manager._plan_ups_charging(
        target_time=target_time,
        current_soc_percent=95.0,
        target_soc_percent=100.0,
    )
    assert len(intervals) == MIN_MODE_DURATION
    assert intervals[0].mode == HOME_UPS

    holding = manager._create_holding_intervals(
        target_time, target_time + timedelta(hours=1)
    )
    assert len(holding) == 4
    assert holding[0].mode == HOME_UPS


@pytest.mark.asyncio
async def test_get_battery_capacity_kwh_handles_units():
    hass = DummyHass(
        {
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState(
                "15000", {"unit_of_measurement": "Wh"}
            )
        }
    )
    manager = _make_manager(hass)
    assert manager._get_battery_capacity_kwh() == 15.0


@pytest.mark.asyncio
async def test_get_spot_prices_48h_parses_timeline():
    manager = _make_manager(DummyHass())
    manager.set_forecast_sensor(
        SimpleNamespace(
            _timeline_data=[
                {
                    "timestamp": "2025-01-01T00:00:00",
                    "spot_price_czk": 2.0,
                },
                {
                    "time": "2025-01-01T00:15:00",
                    "spot_price": 2.5,
                },
                {"timestamp": None},
            ]
        )
    )

    prices = await manager._get_spot_prices_48h()
    assert len(prices) == 2


@pytest.mark.asyncio
async def test_calculate_immediate_balancing_cost(monkeypatch):
    now = datetime(2025, 1, 1, 0, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return now

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.balancing.core.datetime",
        FixedDatetime,
    )

    hass = DummyHass(
        {
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState("10"),
        }
    )
    manager = _make_manager(hass)
    manager.set_forecast_sensor(
        SimpleNamespace(
            _timeline_data=[
                {"timestamp": "2025-01-01T00:00:00", "spot_price_czk": 2.0},
                {"timestamp": "2025-01-01T00:15:00", "spot_price_czk": 3.0},
            ]
        )
    )

    cost = await manager._calculate_immediate_balancing_cost(50.0)
    assert cost == 10.0


@pytest.mark.asyncio
async def test_calculate_total_balancing_cost(monkeypatch):
    now = datetime(2025, 1, 1, 0, 0, 0)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return now

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.balancing.core.datetime",
        FixedDatetime,
    )

    hass = DummyHass(
        {
            "sensor.oig_123_installed_battery_capacity_kwh": DummyState("10"),
        }
    )
    manager = _make_manager(hass)

    timeline = []
    for i in range(4):
        timeline.append(
            {
                "timestamp": (now + timedelta(minutes=15 * i)).isoformat(),
                "spot_price_czk": 2.0,
                "grid_consumption_kwh": 0.1,
            }
        )
    for i in range(12):
        timeline.append(
            {
                "timestamp": (now + timedelta(hours=1, minutes=15 * i)).isoformat(),
                "spot_price_czk": 1.0,
                "grid_consumption_kwh": 0.0,
            }
        )

    manager.set_forecast_sensor(SimpleNamespace(_timeline_data=timeline))

    total_cost = await manager._calculate_total_balancing_cost(
        window_start=now + timedelta(hours=1),
        current_soc_percent=50.0,
    )

    assert total_cost == pytest.approx(5.95, rel=1e-2)


@pytest.mark.asyncio
async def test_find_cheap_holding_window(monkeypatch):
    manager = _make_manager(DummyHass(), options={"balancing_hold_hours": 1})
    start = datetime(2025, 1, 1, 0, 0, 0)

    timeline = []
    prices = [5.0, 1.0, 1.0, 1.0, 5.0, 5.0]
    for i, price in enumerate(prices):
        timeline.append(
            {
                "timestamp": (start + timedelta(minutes=15 * i)).isoformat(),
                "spot_price_czk": price,
            }
        )

    manager.set_forecast_sensor(SimpleNamespace(_timeline_data=timeline))
    window = await manager._find_cheap_holding_window()

    assert window is not None
    holding_start, _ = window
    assert holding_start == start


@pytest.mark.asyncio
async def test_get_current_soc_percent_and_sensor_state():
    hass = DummyHass(
        {
            "sensor.oig_123_batt_bat_c": DummyState("80"),
        }
    )
    manager = _make_manager(hass)
    assert await manager._get_current_soc_percent() == 80.0

    manager._last_balancing_ts = None
    assert manager.get_sensor_state() == "overdue"

    start = datetime(2025, 1, 1, 0, 0, 0)
    plan = BalancingPlan(
        mode=BalancingMode.NATURAL,
        created_at=start.isoformat(),
        reason="natural",
        holding_start=start.isoformat(),
        holding_end=(start + timedelta(hours=1)).isoformat(),
    )
    manager._active_plan = plan
    attrs = manager.get_sensor_attributes()
    assert attrs["active_plan"] == "natural"
