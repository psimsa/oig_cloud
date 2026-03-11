from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.planning import (
    forecast_update as forecast_update_module,
)


class DummySensor:
    def __init__(self):
        self._forecast_in_progress = False
        self._last_forecast_bucket = None
        self._current_capacity = 5.0
        self._max_capacity = 10.0
        self._min_capacity = 2.0
        self._retry_delay = None
        self._log_entries = []
        self._plan_lock_until = None
        self._plan_lock_modes = None
        self._timeline_data = []
        self._hybrid_timeline = []
        self._mode_optimization_result = None
        self._mode_recommendations = []
        self._data_hash = None
        self._last_update = None
        self._consumption_summary = None
        self._first_update = True
        self._profiles_dirty = True
        self._last_precompute_hash = None
        self._last_precompute_at = None
        self._side_effects_enabled = False
        self._box_id = "123"
        self._config_entry = SimpleNamespace(options={})
        self._hass = SimpleNamespace(data={})
        self.hass = SimpleNamespace()
        self.coordinator = SimpleNamespace(battery_forecast_data=None)
        self._write_called = False
        self._precompute_called = False

    def _log_rate_limited(self, key, level, message, *args, **kwargs):
        self._log_entries.append((key, level, message))

    def _get_current_battery_capacity(self):
        return self._current_capacity

    def _get_max_battery_capacity(self):
        return self._max_capacity

    def _get_min_battery_capacity(self):
        return self._min_capacity

    def _schedule_forecast_retry(self, delay_s):
        self._retry_delay = delay_s

    async def _get_spot_price_timeline(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        return [{"time": now.isoformat(), "price": 1.0}]

    async def _get_export_price_timeline(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        return [{"time": now.isoformat(), "price": 0.5}]

    def _get_solar_forecast(self):
        return {}

    def _get_load_avg_sensors(self):
        return {}

    def _get_balancing_plan(self):
        return None

    def _get_target_battery_capacity(self):
        return None

    def _get_current_battery_soc_percent(self):
        return None

    def _get_battery_efficiency(self):
        return 0.9

    def _build_strategy_balancing_plan(self, *_args, **_kwargs):
        return None

    def _create_mode_recommendations(self, *_args, **_kwargs):
        return [{"mode": "Home 1"}]

    async def _maybe_fix_daily_plan(self):
        return None

    def _calculate_data_hash(self, _data):
        return "hash"

    def async_write_ha_state(self):
        self._write_called = True

    def _schedule_precompute(self, force=False):
        self._precompute_called = force

    def _create_task_threadsafe(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_async_update_skips_when_in_progress(monkeypatch):
    sensor = DummySensor()
    sensor._forecast_in_progress = True

    await forecast_update_module.async_update(sensor)

    assert sensor._forecast_in_progress is False
    assert sensor._last_forecast_bucket is None


@pytest.mark.asyncio
async def test_async_update_skips_same_bucket(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)
    bucket_start = fixed_now.replace(minute=0, second=0, microsecond=0)

    sensor = DummySensor()
    sensor._last_forecast_bucket = bucket_start

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    await forecast_update_module.async_update(sensor)

    assert sensor._forecast_in_progress is False
    assert sensor._last_forecast_bucket == bucket_start


@pytest.mark.asyncio
async def test_async_update_missing_capacity_schedules_retry(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)

    sensor = DummySensor()
    sensor._current_capacity = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    await forecast_update_module.async_update(sensor)

    assert sensor._retry_delay == 10.0
    assert sensor._last_forecast_bucket is None
    assert sensor._forecast_in_progress is False


@pytest.mark.asyncio
async def test_async_update_happy_path(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)
    bucket_start = fixed_now.replace(minute=0, second=0, microsecond=0)

    sensor = DummySensor()
    sensor.hass = SimpleNamespace()

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.get_load_avg_for_timestamp",
        lambda *_a, **_k: 0.25,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.get_solar_for_timestamp",
        lambda *_a, **_k: 0.1,
    )

    class DummyAdaptiveHelper:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_adaptive_load_prediction(self):
            return None

        async def calculate_recent_consumption_ratio(self, _profiles):
            return None

        def calculate_consumption_summary(self, _profiles):
            return {}

        def apply_consumption_boost_to_forecast(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        forecast_update_module, "AdaptiveConsumptionHelper", DummyAdaptiveHelper
    )

    class DummyResult:
        modes = ["HOME1"]
        decisions = []
        infeasible = False
        infeasible_reason = None

    class DummyStrategy:
        def __init__(self, *_args, **_kwargs):
            pass

        def optimize(self, *_args, **_kwargs):
            return DummyResult()

    monkeypatch.setattr(forecast_update_module, "HybridStrategy", DummyStrategy)
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "build_plan_lock",
        lambda *_a, **_k: (None, None),
    )
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "apply_mode_guard",
        lambda *_a, **_k: (["HOME1"], {}, None),
    )
    monkeypatch.setattr(
        forecast_update_module,
        "build_planner_timeline",
        lambda *_a, **_k: [{"battery_capacity_kwh": 4.0}],
    )
    monkeypatch.setattr(
        forecast_update_module, "attach_planner_reasons", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        forecast_update_module, "add_decision_reasons_to_timeline", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "apply_guard_reasons_to_timeline",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_send",
        lambda *_a, **_k: None,
    )

    await forecast_update_module.async_update(sensor)

    assert sensor._timeline_data
    assert sensor._data_hash == "hash"
    assert sensor._last_forecast_bucket == bucket_start
    assert sensor._forecast_in_progress is False
    assert sensor._write_called is True
    assert sensor._precompute_called is True
