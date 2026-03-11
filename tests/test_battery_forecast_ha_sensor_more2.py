from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_build_strategy_balancing_plan_skips_invalid_intervals(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    spot_prices = [
        {"time": "2025-01-01T00:00:00"},
        {"time": "2025-01-01T00:15:00"},
    ]
    plan = {
        "active": True,
        "intervals": [
            SimpleNamespace(ts="2025-01-01T00:00:00", mode=CBB_MODE_HOME_UPS),
            {"ts": "bad", "mode": CBB_MODE_HOME_UPS},
            {"ts": "2025-01-01T00:15:00", "mode": None},
        ],
        "holding_start": "bad",
        "holding_end": "2025-01-01T00:30:00",
    }
    result = sensor._build_strategy_balancing_plan(spot_prices, plan)
    assert result is not None
    assert result.charging_intervals == {0}
    assert result.holding_intervals == set()


def test_handle_coordinator_update_and_device_info(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"update": False}

    def _handle(_sensor):
        called["update"] = True

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.sensor_runtime_module.handle_coordinator_update",
        _handle,
    )
    sensor._handle_coordinator_update()
    assert called["update"] is True
    assert sensor.device_info == {}


def test_proxy_methods_sync(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.battery_state_module.get_battery_efficiency",
        lambda *_a, **_k: 0.9,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.battery_state_module.get_ac_charging_limit_kwh_15min",
        lambda *_a, **_k: 0.7,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.battery_state_module.get_current_mode",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.battery_state_module.get_boiler_available_capacity",
        lambda *_a, **_k: 2.5,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.pricing_module.calculate_final_spot_price",
        lambda *_a, **_k: 3.5,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.pricing_module.get_spot_data_from_price_sensor",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.solar_forecast_module.get_solar_forecast",
        lambda *_a, **_k: {"solar": True},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.solar_forecast_module.get_solar_forecast_strings",
        lambda *_a, **_k: {"solar": "ok"},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.balancing_helpers_module.get_balancing_plan",
        lambda *_a, **_k: {"plan": True},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.charging_helpers_module.economic_charging_plan",
        lambda *_a, **_k: [{"grid_charge_kwh": 1.0}],
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.charging_helpers_module.smart_charging_plan",
        lambda *_a, **_k: [{"grid_charge_kwh": 2.0}],
    )

    assert sensor._get_battery_efficiency() == 0.9
    assert sensor._get_ac_charging_limit_kwh_15min() == 0.7
    assert sensor._get_current_mode() == 1
    assert sensor._get_boiler_available_capacity() == 2.5
    assert sensor._calculate_final_spot_price(1.0, None) == 3.5
    assert sensor._get_spot_data_from_price_sensor(price_type="spot") == {"ok": True}
    assert sensor._get_solar_forecast() == {"solar": True}
    assert sensor._get_solar_forecast_strings() == {"solar": "ok"}
    assert sensor._get_balancing_plan() == {"plan": True}
    assert sensor._economic_charging_plan([], 1.0, 1.0, 1.0, 1.0, 0.1, 1.0, 1.0, False, 1, 1.0, False, "low", 1.0) == [
        {"grid_charge_kwh": 1.0}
    ]
    assert sensor._smart_charging_plan([], 1.0, 1.0, 1.0, 0.1, 1.0, 1.0) == [
        {"grid_charge_kwh": 2.0}
    ]


@pytest.mark.asyncio
async def test_proxy_methods_async(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def _backfill(*_a, **_k):
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.plan_storage_module.backfill_daily_archive_from_storage",
        _backfill,
    )

    async def _spot_timeline(*_a, **_k):
        return [{"time": "t"}]

    async def _export_timeline(*_a, **_k):
        return [{"time": "t"}]

    async def _ote_cache(*_a, **_k):
        return {"ote": True}

    async def _plan_balancing(*_a, **_k):
        return {"ok": True}

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.pricing_module.get_spot_price_timeline",
        _spot_timeline,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.pricing_module.get_export_price_timeline",
        _export_timeline,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.pricing_module.get_spot_data_from_ote_cache",
        _ote_cache,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.balancing_helpers_module.plan_balancing",
        _plan_balancing,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.sensors.ha_sensor.load_profiles_module.get_load_avg_sensors",
        lambda *_a, **_k: {"load": True},
    )

    await sensor._backfill_daily_archive_from_storage()
    assert await sensor._get_spot_price_timeline() == [{"time": "t"}]
    assert await sensor._get_export_price_timeline() == [{"time": "t"}]
    assert await sensor._get_spot_data_from_ote_cache() == {"ote": True}
    assert await sensor.plan_balancing(None, None, 0.0, "mode") == {"ok": True}
    assert sensor._get_load_avg_sensors() == {"load": True}


def test_build_strategy_balancing_plan_attr_plan_and_missing_index(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    spot_prices = [
        {"time": "2025-01-01T00:00:00"},
    ]

    plan = SimpleNamespace(
        active=True,
        intervals=[SimpleNamespace(ts="2025-01-02T00:00:00", mode=CBB_MODE_HOME_UPS)],
        holding_start=None,
        holding_end=None,
    )
    result = sensor._build_strategy_balancing_plan(spot_prices, plan)
    assert result is not None
    assert result.charging_intervals == set()


def test_build_strategy_balancing_plan_exception(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    spot_prices = [{"time": "2025-01-01T00:00:00"}]

    class BadInt:
        def __int__(self):
            raise ValueError("boom")

    plan = {
        "active": True,
        "intervals": [{"ts": "2025-01-01T00:00:00", "mode": BadInt()}],
    }

    assert sensor._build_strategy_balancing_plan(spot_prices, plan) is None
