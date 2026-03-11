from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.planning import (
    forecast_update as forecast_update_module,
)
from custom_components.oig_cloud.const import DOMAIN


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
        self._side_effects_enabled = True
        self._box_id = "123"
        self._config_entry = SimpleNamespace(options={}, entry_id="entry1")
        self._hass = SimpleNamespace(data={DOMAIN: {"entry1": {}}})
        self.hass = SimpleNamespace()
        self.coordinator = SimpleNamespace(battery_forecast_data=None)
        self._write_called = False
        self._precompute_called = False
        self._task_called = False

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
        return [
            {"time": "2025-01-01T11:45:00", "price": 2.0},
            {"time": "2025-01-01T12:00:00", "price": 1.0},
        ]

    async def _get_export_price_timeline(self):
        return [
            {"time": "2025-01-01T11:45:00", "price": 0.2},
            {"time": "2025-01-01T12:00:00", "price": 0.1},
        ]

    def _get_solar_forecast(self):
        return {}

    def _get_load_avg_sensors(self):
        return {}

    def _get_balancing_plan(self):
        return None

    def _get_target_battery_capacity(self):
        return 8.0

    def _get_current_battery_soc_percent(self):
        return 50.0

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
        self._task_called = True


@pytest.mark.asyncio
async def test_async_update_adaptive_profiles_and_filters(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)
    bucket_start = fixed_now.replace(minute=0, second=0, microsecond=0)

    sensor = DummySensor()

    class DummyBalancingManager:
        def get_active_plan(self):
            return None

    sensor._hass.data[DOMAIN]["entry1"]["balancing_manager"] = DummyBalancingManager()

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    class DummyAdaptiveHelper:
        def __init__(self, *_args, **_kwargs):
            self.boost_called = False

        async def get_adaptive_load_prediction(self):
            return {
                "today_profile": {
                    "start_hour": 0,
                    "hourly_consumption": [1.0],
                    "avg_kwh_h": 0.5,
                }
            }

        async def calculate_recent_consumption_ratio(self, _profiles):
            return 1.2

        def calculate_consumption_summary(self, _profiles):
            return {"ok": True}

        def apply_consumption_boost_to_forecast(self, *_args, **_kwargs):
            self.boost_called = True

    helper = DummyAdaptiveHelper()
    monkeypatch.setattr(
        forecast_update_module, "AdaptiveConsumptionHelper", lambda *_a, **_k: helper
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
        forecast_update_module.auto_switch_module,
        "update_auto_switch_schedule",
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
    assert sensor._write_called is True
    assert sensor._precompute_called is True
    assert sensor._task_called is True
    assert sensor._consumption_summary == {"ok": True}
    assert helper.boost_called is True


@pytest.mark.asyncio
async def test_async_update_skips_write_without_hass(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)
    sensor = DummySensor()
    sensor.hass = None

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
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

    await forecast_update_module.async_update(sensor)

    assert sensor._write_called is False
    assert sensor._precompute_called is False


@pytest.mark.asyncio
async def test_async_update_warns_on_empty_spot_prices(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor = DummySensor()
    sensor._data_hash = "hash"

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    async def _empty_prices():
        return []

    sensor._get_spot_price_timeline = _empty_prices
    sensor._get_export_price_timeline = _empty_prices

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
        modes = []
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
        lambda *_a, **_k: ([], {}, None),
    )
    monkeypatch.setattr(
        forecast_update_module,
        "build_planner_timeline",
        lambda *_a, **_k: [],
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

    assert sensor._data_hash == "hash"


@pytest.mark.asyncio
async def test_async_update_tomorrow_profile_and_padding(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor = DummySensor()

    spot_prices = [
        {"time": "2025-01-02T01:00:00", "price": 2.0},
        {"time": "2025-01-02T01:15:00", "price": 1.0},
    ]

    async def _spot_prices():
        return spot_prices

    async def _export_prices():
        return [{"time": "2025-01-02T01:00:00", "price": 0.2}]

    sensor._get_spot_price_timeline = _spot_prices
    sensor._get_export_price_timeline = _export_prices

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    class DummyAdaptiveHelper:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_adaptive_load_prediction(self):
            return {
                "today_profile": {
                    "start_hour": 0,
                    "hourly_consumption": [1.0],
                    "avg_kwh_h": 0.5,
                },
                "tomorrow_profile": {
                    "start_hour": 0,
                    "hourly_consumption": [1.0, 2.0],
                    "avg_kwh_h": 0.5,
                },
            }

        async def calculate_recent_consumption_ratio(self, _profiles):
            return None

        def calculate_consumption_summary(self, _profiles):
            return {}

        def apply_consumption_boost_to_forecast(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        forecast_update_module, "AdaptiveConsumptionHelper", DummyAdaptiveHelper
    )
    monkeypatch.setattr(
        forecast_update_module, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )

    class DummyResult:
        def __init__(self, modes):
            self.modes = modes
            self.decisions = []
            self.infeasible = False
            self.infeasible_reason = None

    class DummyStrategy:
        def __init__(self, *_args, **_kwargs):
            pass

        def optimize(self, *_args, **kwargs):
            return DummyResult([0] * len(kwargs["spot_prices"]))

    monkeypatch.setattr(forecast_update_module, "HybridStrategy", DummyStrategy)
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "build_plan_lock",
        lambda *_a, **_k: (None, None),
    )
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "apply_mode_guard",
        lambda *_a, **_k: ([0, 0], {}, None),
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


@pytest.mark.asyncio
async def test_async_update_load_forecast_exception_and_solar_error(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor = DummySensor()

    spot_prices = [{"time": "2025-01-01T12:15:00", "price": 2.0}]

    async def _spot_prices():
        return spot_prices

    async def _export_prices():
        return spot_prices

    sensor._get_spot_price_timeline = _spot_prices
    sensor._get_export_price_timeline = _export_prices

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    class DummyAdaptiveHelper:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_adaptive_load_prediction(self):
            return {"today_profile": {"start_hour": 0}}

        async def calculate_recent_consumption_ratio(self, _profiles):
            return None

        def calculate_consumption_summary(self, _profiles):
            return {}

        def apply_consumption_boost_to_forecast(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        forecast_update_module, "AdaptiveConsumptionHelper", DummyAdaptiveHelper
    )
    monkeypatch.setattr(
        forecast_update_module,
        "get_solar_for_timestamp",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("boom")),
    )

    class DummyResult:
        modes = [0]
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
        lambda *_a, **_k: ([0], {}, None),
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


@pytest.mark.asyncio
async def test_async_update_truncates_horizon(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor = DummySensor()

    base = datetime(2025, 1, 1, 12, 0, 0)
    spot_prices = [
        {
            "time": (base + timedelta(minutes=15 * i)).isoformat(),
            "price": 1.0,
        }
        for i in range(145)
    ]

    async def _spot_prices():
        return spot_prices

    async def _export_prices():
        return [{"time": spot_prices[0]["time"], "price": 0.1}]

    sensor._get_spot_price_timeline = _spot_prices
    sensor._get_export_price_timeline = _export_prices

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
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
    monkeypatch.setattr(
        forecast_update_module, "get_solar_for_timestamp", lambda *_a, **_k: 0.0
    )

    class DummyResult:
        def __init__(self, modes):
            self.modes = modes
            self.decisions = []
            self.infeasible = False
            self.infeasible_reason = None

    class DummyStrategy:
        def __init__(self, *_args, **_kwargs):
            pass

        def optimize(self, *_args, **kwargs):
            return DummyResult([0] * len(kwargs["spot_prices"]))

    monkeypatch.setattr(forecast_update_module, "HybridStrategy", DummyStrategy)
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "build_plan_lock",
        lambda *_a, **_k: (None, None),
    )
    monkeypatch.setattr(
        forecast_update_module.mode_guard_module,
        "apply_mode_guard",
        lambda *_a, **_k: ([0] * 144, {}, None),
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


@pytest.mark.asyncio
async def test_async_update_planner_failure(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    sensor = DummySensor()

    async def _spot_prices():
        return [{"time": "2025-01-01T12:15:00", "price": 1.0}]

    sensor._get_spot_price_timeline = _spot_prices
    sensor._get_export_price_timeline = _spot_prices

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
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

    class DummyStrategy:
        def __init__(self, *_args, **_kwargs):
            pass

        def optimize(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(forecast_update_module, "HybridStrategy", DummyStrategy)

    await forecast_update_module.async_update(sensor)

    assert sensor._mode_optimization_result is None


@pytest.mark.asyncio
async def test_async_update_outer_exception_and_finally_guard(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 12, 7, 0)

    class RaisingSensor(DummySensor):
        def __init__(self):
            super().__init__()
            self._raise_on_bucket = True

        def __setattr__(self, name, value):
            if name == "_last_forecast_bucket" and getattr(
                self, "_raise_on_bucket", False
            ):
                raise RuntimeError("nope")
            super().__setattr__(name, value)

    sensor = RaisingSensor()

    async def _spot_prices():
        raise RuntimeError("boom")

    sensor._get_spot_price_timeline = _spot_prices

    monkeypatch.setattr(
        "custom_components.oig_cloud.battery_forecast.planning.forecast_update.dt_util.now",
        lambda: fixed_now,
    )

    await forecast_update_module.async_update(sensor)

    assert sensor._forecast_in_progress is False
