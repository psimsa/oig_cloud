from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.oig_cloud.battery_forecast.sensors.ha_sensor import (
    CBB_MODE_HOME_UPS,
    OigCloudBatteryForecastSensor,
)


class DummyCoordinator:
    def __init__(self):
        self.data = {}
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self):
        self.options = {}
        self.data = {}


def _make_sensor(monkeypatch):
    def _init_sensor(
        sensor,
        *_args,
        **_kwargs,
    ):
        sensor._device_info = {}
        sensor._config_entry = DummyConfigEntry()
        sensor._box_id = "123"

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.sensor_setup_module.initialize_sensor",
        _init_sensor,
    )
    coordinator = DummyCoordinator()
    return OigCloudBatteryForecastSensor(coordinator, "battery_forecast", DummyConfigEntry(), {})


@pytest.mark.asyncio
async def test_async_added_and_removed(monkeypatch, hass):
    sensor = _make_sensor(monkeypatch)
    sensor.hass = hass

    async def _base_added(self):
        return None

    async def _lifecycle(_sensor):
        _sensor._lifecycle_called = True

    def _handle_remove(_sensor):
        _sensor._removed_called = True

    monkeypatch.setattr(CoordinatorEntity, "async_added_to_hass", _base_added)
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.sensor_lifecycle_module.async_added_to_hass",
        _lifecycle,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.sensor_runtime_module.handle_will_remove",
        _handle_remove,
    )

    await sensor.async_added_to_hass()
    assert sensor._hass is hass
    assert getattr(sensor, "_lifecycle_called", False) is True

    await sensor.async_will_remove_from_hass()
    assert getattr(sensor, "_removed_called", False) is True


def test_create_mode_recommendations(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    def _create(optimal_timeline, **kwargs):
        return [{"mode": kwargs["mode_home_ups"]}]

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.mode_recommendations_module.create_mode_recommendations",
        _create,
    )
    result = sensor._create_mode_recommendations([{"mode": 1}])
    assert result == [{"mode": CBB_MODE_HOME_UPS}]


def test_update_balancing_plan_snapshot(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"plan": None}

    def _update(_sensor, plan):
        called["plan"] = plan

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.balancing_helpers_module.update_balancing_plan_snapshot",
        _update,
    )
    sensor._update_balancing_plan_snapshot({"ok": True})
    assert called["plan"] == {"ok": True}


def test_group_intervals_by_mode(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    def _group(intervals, **_kwargs):
        return [{"count": len(intervals)}]

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.interval_grouping_module.group_intervals_by_mode",
        _group,
    )
    result = sensor._group_intervals_by_mode([{"time": "t"}])
    assert result == [{"count": 1}]


def test_build_strategy_balancing_plan_branches(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    spot_prices = [
        {"time": "2025-01-01T00:00:00"},
        {"time": "2025-01-01T00:15:00"},
    ]

    assert sensor._build_strategy_balancing_plan(spot_prices, None) is None
    assert sensor._build_strategy_balancing_plan(spot_prices, {"active": False}) is None

    plan = {
        "active": True,
        "intervals": [{"ts": "2025-01-01T00:00:00", "mode": CBB_MODE_HOME_UPS}],
        "holding_start": "2025-01-01T00:00:00",
        "holding_end": "2025-01-01T00:30:00",
    }
    result = sensor._build_strategy_balancing_plan(spot_prices, plan)
    assert result is not None
    assert 0 in result.charging_intervals
    assert result.holding_intervals


def test_build_strategy_balancing_plan_legacy(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    spot_prices = [{"time": "2025-01-01T00:00:00"}]
    plan = {"active": True, "charging_intervals": ["2025-01-01T00:00:00"]}
    result = sensor._build_strategy_balancing_plan(spot_prices, plan)
    assert result is not None
