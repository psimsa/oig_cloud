from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.sensors.ha_sensor import (
    OigCloudBatteryForecastSensor,
)
from custom_components.oig_cloud.battery_forecast.sensors import ha_sensor as ha_sensor_module


class DummyCoordinator:
    def __init__(self) -> None:
        self.refresh_called = False

    async def async_request_refresh(self) -> None:
        self.refresh_called = True


class DummyHass:
    def __init__(self) -> None:
        self.data = {}

    def async_create_task(self, coro):
        coro.close()
        return object()


def _make_sensor(monkeypatch):
    coordinator = DummyCoordinator()
    config_entry = SimpleNamespace(options={}, entry_id="entry")
    device_info = {"identifiers": {("oig_cloud", "123")}}
    hass = DummyHass()

    def _fake_initialize(
        self,
        _coordinator,
        _sensor_type,
        _config_entry,
        _device_info,
        _hass,
        **_kwargs,
    ):
        self._config_entry = _config_entry
        self._device_info = _device_info
        self._hass = _hass
        self.hass = _hass
        self._box_id = "123"

    monkeypatch.setattr(
        ha_sensor_module.sensor_setup_module,
        "initialize_sensor",
        _fake_initialize,
    )

    sensor = OigCloudBatteryForecastSensor(
        coordinator,
        "battery_forecast",
        config_entry,
        device_info,
        hass,
    )
    return sensor, coordinator


def test_state_and_availability_proxies(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.sensor_runtime_module,
        "get_state",
        lambda _sensor: 1.23,
    )
    monkeypatch.setattr(
        ha_sensor_module.sensor_runtime_module,
        "is_available",
        lambda _sensor: True,
    )
    monkeypatch.setattr(
        ha_sensor_module.sensor_runtime_module,
        "get_config",
        lambda _sensor: {"ok": True},
    )

    assert sensor.state == 1.23
    assert sensor.available is True
    assert sensor._get_config() == {"ok": True}


def test_extra_state_attributes_proxy(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.state_attributes_module,
        "build_extra_state_attributes",
        lambda _sensor, debug_expose_baseline_timeline=False: {"attr": 1},
    )

    assert sensor.extra_state_attributes == {"attr": 1}


def test_calculate_data_hash_proxy(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.state_attributes_module,
        "calculate_data_hash",
        lambda _timeline: "hash",
    )

    assert sensor._calculate_data_hash([]) == "hash"


@pytest.mark.asyncio
async def test_async_update_calls_forecast(monkeypatch):
    sensor, coordinator = _make_sensor(monkeypatch)
    called = {"forecast": False}

    async def _fake_forecast(_sensor):
        called["forecast"] = True

    monkeypatch.setattr(
        ha_sensor_module.forecast_update_module, "async_update", _fake_forecast
    )

    await sensor.async_update()

    assert called["forecast"] is True
    assert coordinator.refresh_called is True


@pytest.mark.asyncio
async def test_build_detail_tabs_passes_mode_names(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    async def _fake_detail_tabs(_sensor, tab=None, plan="hybrid", mode_names=None):
        return {"mode_names": mode_names, "plan": plan, "tab": tab}

    monkeypatch.setattr(
        ha_sensor_module.detail_tabs_module,
        "build_detail_tabs",
        _fake_detail_tabs,
    )

    result = await sensor.build_detail_tabs(tab="today", plan="active")
    assert result["mode_names"] == ha_sensor_module.CBB_MODE_NAMES
    assert result["plan"] == "active"


@pytest.mark.asyncio
async def test_build_timeline_extended(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    async def _fake_timeline(_sensor, mode_names=None):
        return {"mode_names": mode_names}

    monkeypatch.setattr(
        ha_sensor_module.timeline_extended_module,
        "build_timeline_extended",
        _fake_timeline,
    )

    result = await sensor.build_timeline_extended()
    assert result["mode_names"] == ha_sensor_module.CBB_MODE_NAMES


def test_schedule_precompute_proxy(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)
    called = {"force": None}

    def _fake_schedule(_sensor, force=False):
        called["force"] = force

    monkeypatch.setattr(
        ha_sensor_module.precompute_module,
        "schedule_precompute",
        _fake_schedule,
    )

    sensor._schedule_precompute(force=True)
    assert called["force"] is True


def test_simulate_interval_proxy(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "simulate_interval",
        lambda **_kwargs: {"ok": True},
    )

    result = sensor._simulate_interval(
        mode=0,
        solar_kwh=0.0,
        load_kwh=0.0,
        battery_soc_kwh=1.0,
        capacity_kwh=10.0,
        hw_min_capacity_kwh=2.0,
        spot_price_czk=3.0,
        export_price_czk=1.0,
    )
    assert result == {"ok": True}


def test_scenario_analysis_proxies(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "calculate_fixed_mode_cost",
        lambda *_args, **_kwargs: 1.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "calculate_mode_baselines",
        lambda *_args, **_kwargs: {"home1": {}},
    )
    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "calculate_do_nothing_cost",
        lambda *_args, **_kwargs: 2.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "calculate_full_ups_cost",
        lambda *_args, **_kwargs: 3.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.scenario_analysis_module,
        "generate_alternatives",
        lambda *_args, **_kwargs: {"alt": {"cost": 4.0}},
    )

    assert (
        sensor._calculate_fixed_mode_cost(
            fixed_mode=0,
            current_capacity=1.0,
            max_capacity=2.0,
            min_capacity=0.5,
            spot_prices=[],
            export_prices=[],
            solar_forecast={},
            load_forecast=[],
        )
        == 1.0
    )
    assert (
        sensor._calculate_mode_baselines(
            current_capacity=1.0,
            max_capacity=2.0,
            physical_min_capacity=0.5,
            spot_prices=[],
            export_prices=[],
            solar_forecast={},
            load_forecast=[],
        )
        == {"home1": {}}
    )
    assert (
        sensor._calculate_do_nothing_cost(
            current_capacity=1.0,
            max_capacity=2.0,
            min_capacity=0.5,
            spot_prices=[],
            export_prices=[],
            solar_forecast={},
            load_forecast=[],
        )
        == 2.0
    )
    assert (
        sensor._calculate_full_ups_cost(
            current_capacity=1.0,
            max_capacity=2.0,
            min_capacity=0.5,
            spot_prices=[],
            export_prices=[],
            solar_forecast={},
            load_forecast=[],
        )
        == 3.0
    )
    assert (
        sensor._generate_alternatives(
            spot_prices=[],
            solar_forecast={},
            load_forecast=[],
            optimal_cost_48h=1.0,
            current_capacity=1.0,
            max_capacity=2.0,
            efficiency=0.9,
        )
        == {"alt": {"cost": 4.0}}
    )


@pytest.mark.asyncio
async def test_storage_and_task_proxies(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    async def _maybe_fix(_sensor):
        return True

    async def _save_plan(_sensor, date_str, intervals, metadata=None):
        return True

    async def _load_plan(_sensor, date_str):
        return {"date": date_str}

    async def _exists(_sensor, date_str):
        return True

    async def _aggregate_daily(_sensor, date_str):
        return True

    async def _aggregate_weekly(_sensor, week_str, start_date, end_date):
        return True

    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "maybe_fix_daily_plan",
        _maybe_fix,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "save_plan_to_storage",
        _save_plan,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "load_plan_from_storage",
        _load_plan,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "plan_exists_in_storage",
        _exists,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "aggregate_daily",
        _aggregate_daily,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "aggregate_weekly",
        _aggregate_weekly,
    )

    assert await sensor._maybe_fix_daily_plan() is None
    assert await sensor._save_plan_to_storage("2025-01-01", []) is True
    assert await sensor._load_plan_from_storage("2025-01-01") == {"date": "2025-01-01"}
    assert await sensor._plan_exists_in_storage("2025-01-01") is True
    assert await sensor._aggregate_daily("2025-01-01") is True
    assert await sensor._aggregate_weekly("2025-W01", "2025-01-01", "2025-01-07") is True

    called = {}

    def _schedule_retry(_sensor, delay_seconds):
        called["retry"] = delay_seconds

    def _create_task(_sensor, coro_func, *args):
        called["task"] = (coro_func, args)

    monkeypatch.setattr(
        ha_sensor_module.task_utils_module,
        "schedule_forecast_retry",
        _schedule_retry,
    )
    monkeypatch.setattr(
        ha_sensor_module.task_utils_module,
        "create_task_threadsafe",
        _create_task,
    )

    sensor._schedule_forecast_retry(5.0)
    sensor._create_task_threadsafe(lambda _sensor: None, sensor)

    assert called["retry"] == 5.0
    assert called["task"][0]


@pytest.mark.asyncio
async def test_precompute_and_cost_tile_proxy(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)
    called = {"precompute": False}

    async def _precompute(_sensor):
        called["precompute"] = True

    async def _uct(_sensor, **_kwargs):
        return {"today": {"plan_total_cost": 1.0}}

    monkeypatch.setattr(
        ha_sensor_module.precompute_module,
        "precompute_ui_data",
        _precompute,
    )
    monkeypatch.setattr(
        ha_sensor_module.unified_cost_tile_module,
        "build_unified_cost_tile",
        _uct,
    )

    await sensor._precompute_ui_data()
    result = await sensor.build_unified_cost_tile()

    assert called["precompute"] is True
    assert result["today"]["plan_total_cost"] == 1.0


@pytest.mark.asyncio
async def test_additional_proxy_helpers(monkeypatch):
    sensor, _coordinator = _make_sensor(monkeypatch)

    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_total_battery_capacity",
        lambda _sensor: 10.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_current_battery_soc_percent",
        lambda _sensor: 55.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_current_battery_capacity",
        lambda _sensor: 5.5,
    )
    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_max_battery_capacity",
        lambda _sensor: 12.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_min_battery_capacity",
        lambda _sensor: 2.0,
    )
    monkeypatch.setattr(
        ha_sensor_module.battery_state_module,
        "get_target_battery_capacity",
        lambda _sensor: 9.0,
    )

    assert sensor._get_total_battery_capacity() == 10.0
    assert sensor._get_current_battery_soc_percent() == 55.0
    assert sensor._get_current_battery_capacity() == 5.5
    assert sensor._get_max_battery_capacity() == 12.0
    assert sensor._get_min_battery_capacity() == 2.0
    assert sensor._get_target_battery_capacity() == 9.0

    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "is_baseline_plan_invalid",
        lambda _plan: True,
    )
    async def _create_baseline(_sensor, date_str):
        return True

    async def _ensure_plan(_sensor, date_str):
        return True

    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "create_baseline_plan",
        _create_baseline,
    )
    monkeypatch.setattr(
        ha_sensor_module.plan_storage_module,
        "ensure_plan_exists",
        _ensure_plan,
    )
    assert sensor._is_baseline_plan_invalid({}) is True
    assert await sensor._create_baseline_plan("2025-01-01") is True
    assert await sensor.ensure_plan_exists("2025-01-01") is True

    monkeypatch.setattr(
        ha_sensor_module.plan_tabs_module,
        "decorate_plan_tabs",
        lambda *_args, **_kwargs: {"ok": True},
    )
    result = sensor._decorate_plan_tabs({}, {}, "primary", "secondary")
    assert result == {"ok": True}

    async def _build_day(_sensor, day, storage_plans, mode_names=None):
        return {"day": str(day), "mode_names": mode_names}

    monkeypatch.setattr(
        ha_sensor_module.timeline_extended_module,
        "build_day_timeline",
        _build_day,
    )

    day_result = await sensor._build_day_timeline(day=date(2025, 1, 1), storage_plans={})
    assert day_result["mode_names"] == ha_sensor_module.CBB_MODE_NAMES
