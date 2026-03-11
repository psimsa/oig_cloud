from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.oig_cloud.battery_forecast.sensors.ha_sensor import (
    OigCloudBatteryForecastSensor,
)


def _setup_sensor(monkeypatch):
    def _init_sensor(self, coordinator, sensor_type, config_entry, device_info, hass, **_kwargs):
        self._device_info = device_info
        self._config_entry = config_entry
        self._hass = hass
        self.hass = hass
        self._box_id = "123"
        self.coordinator = coordinator

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.sensor_setup.initialize_sensor",
        _init_sensor,
    )

    coordinator = SimpleNamespace()
    config_entry = SimpleNamespace(options={})
    device_info = {"identifiers": {"oig", "123"}}
    hass = SimpleNamespace()

    return OigCloudBatteryForecastSensor(
        coordinator, "planner", config_entry, device_info, hass=hass, side_effects_enabled=False
    )


def test_sensor_proxy_properties(monkeypatch):
    sensor = _setup_sensor(monkeypatch)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.sensor_runtime.get_state",
        lambda *_a, **_k: 1.5,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.sensor_runtime.is_available",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.state_attributes.build_extra_state_attributes",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.presentation.state_attributes.calculate_data_hash",
        lambda *_a, **_k: "hash",
    )

    assert sensor.state == 1.5
    assert sensor.available is True
    assert sensor.extra_state_attributes == {"ok": True}
    assert sensor._calculate_data_hash([]) == "hash"


@pytest.mark.asyncio
async def test_sensor_async_update_proxy(monkeypatch):
    sensor = _setup_sensor(monkeypatch)

    update_called = {"count": 0}

    async def _forecast_update(_sensor):
        update_called["count"] += 1

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.async_update",
        _forecast_update,
    )
    monkeypatch.setattr(CoordinatorEntity, "async_update", AsyncMock())

    await sensor.async_update()

    assert update_called["count"] == 1


def test_sensor_analysis_proxies(monkeypatch):
    sensor = _setup_sensor(monkeypatch)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.simulate_interval",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.calculate_interval_cost",
        lambda *_a, **_k: {"cost": 1},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.calculate_fixed_mode_cost",
        lambda *_a, **_k: 2.0,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.calculate_mode_baselines",
        lambda *_a, **_k: {"home1": {"cost": 1}},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.calculate_do_nothing_cost",
        lambda *_a, **_k: 3.0,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.scenario_analysis.calculate_full_ups_cost",
        lambda *_a, **_k: 4.0,
    )

    assert sensor._simulate_interval(0, 0, 0, 0, 0, 0, 0, 0) == {"ok": True}
    assert sensor._calculate_interval_cost({}, 1, 2, "day") == {"cost": 1}
    assert sensor._calculate_fixed_mode_cost(0, 1, 2, 3, [], [], {}, []) == 2.0
    assert sensor._calculate_mode_baselines(1, 2, 0, [], [], {}, []) == {
        "home1": {"cost": 1}
    }
    assert sensor._calculate_do_nothing_cost(1, 2, 0, [], [], {}, []) == 3.0
    assert sensor._calculate_full_ups_cost(1, 2, 0, [], [], {}, []) == 4.0


def test_sensor_battery_state_proxies(monkeypatch):
    sensor = _setup_sensor(monkeypatch)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.data.battery_state.get_current_battery_capacity",
        lambda *_a, **_k: 5.0,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.data.battery_state.get_max_battery_capacity",
        lambda *_a, **_k: 10.0,
    )

    assert sensor._get_current_battery_capacity() == 5.0
    assert sensor._get_max_battery_capacity() == 10.0
