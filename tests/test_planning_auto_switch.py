from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.planning import auto_switch
from custom_components.oig_cloud.battery_forecast.planning import scenario_analysis
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_UPS,
)
from custom_components.oig_cloud.const import CONF_AUTO_MODE_SWITCH


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options
        self.data = options


class DummySensor:
    def __init__(self, options):
        self._config_entry = DummyConfigEntry(options)
        self._auto_switch_handles = []
        self._auto_switch_retry_unsub = None
        self._hass = object()
        self._box_id = "123"


class DummyStates:
    def __init__(self, state_map):
        self._state_map = state_map

    def get(self, entity_id):
        return self._state_map.get(entity_id)


class DummyServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data, blocking))


class DummyHass:
    def __init__(self, states=None, data=None):
        self.states = states or DummyStates({})
        self.services = DummyServices()
        self.data = data or {}


def test_auto_mode_switch_enabled():
    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    assert auto_switch.auto_mode_switch_enabled(sensor) is True

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: False})
    assert auto_switch.auto_mode_switch_enabled(sensor) is False


def test_normalize_service_mode():
    sensor = DummySensor({})
    assert auto_switch.normalize_service_mode(sensor, None) is None
    assert auto_switch.normalize_service_mode(sensor, 0) == "Home 1"
    assert auto_switch.normalize_service_mode(sensor, "HOME UPS") == "Home UPS"
    assert auto_switch.normalize_service_mode(sensor, "home ii") == "Home 2"
    assert auto_switch.normalize_service_mode(sensor, "Home 1") == "Home 1"
    assert auto_switch.normalize_service_mode(sensor, "unknown") is None
    assert auto_switch.normalize_service_mode(sensor, "  ") is None


def test_get_planned_mode_for_time():
    sensor = DummySensor({})
    base = dt_util.now().replace(minute=0, second=0, microsecond=0)
    timeline = [
        {"time": base.isoformat(), "mode": CBB_MODE_HOME_I, "mode_name": "Home 1"},
        {
            "time": (base + timedelta(minutes=15)).isoformat(),
            "mode": CBB_MODE_HOME_UPS,
            "mode_name": "Home UPS",
        },
    ]

    assert (
        auto_switch.get_planned_mode_for_time(sensor, base, timeline) == "Home 1"
    )
    assert (
        auto_switch.get_planned_mode_for_time(
            sensor, base + timedelta(minutes=16), timeline
        )
        == "Home UPS"
    )


def test_cancel_auto_switch_schedule_clears_handles():
    sensor = DummySensor({})
    called = {"count": 0}

    def _unsub():
        called["count"] += 1

    sensor._auto_switch_handles = [_unsub, _unsub]
    sensor._auto_switch_retry_unsub = _unsub

    auto_switch.cancel_auto_switch_schedule(sensor)

    assert called["count"] == 3
    assert sensor._auto_switch_handles == []
    assert sensor._auto_switch_retry_unsub is None


def test_schedule_auto_switch_retry_sets_unsub(monkeypatch):
    sensor = DummySensor({})
    called = {}

    def _fake_async_call_later(_hass, _delay, _cb):
        called["ok"] = True
        return lambda: None

    monkeypatch.setattr(auto_switch, "async_call_later", _fake_async_call_later)

    auto_switch.schedule_auto_switch_retry(sensor, 5.0)
    assert called["ok"] is True
    assert sensor._auto_switch_retry_unsub is not None


def test_get_current_box_mode():
    sensor = DummySensor({})
    sensor._hass = None
    assert auto_switch.get_current_box_mode(sensor) is None

    sensor._hass = DummyHass()
    assert auto_switch.get_current_box_mode(sensor) is None

    state = SimpleNamespace(state="HOME I")
    sensor._hass = DummyHass(
        states=DummyStates({"sensor.oig_123_box_prms_mode": state})
    )
    sensor._box_id = "123"
    assert auto_switch.get_current_box_mode(sensor) == "Home 1"


def test_cancel_auto_switch_schedule_handles_errors():
    sensor = DummySensor({})

    def _boom():
        raise RuntimeError("fail")

    sensor._auto_switch_handles = [_boom]
    sensor._auto_switch_retry_unsub = _boom
    auto_switch.cancel_auto_switch_schedule(sensor)
    assert sensor._auto_switch_handles == []
    assert sensor._auto_switch_retry_unsub is None


def test_clear_auto_switch_retry_handles_error():
    sensor = DummySensor({})

    def _boom():
        raise RuntimeError("fail")

    sensor._auto_switch_retry_unsub = _boom
    auto_switch.clear_auto_switch_retry(sensor)
    assert sensor._auto_switch_retry_unsub is None


def test_start_stop_watchdog(monkeypatch):
    sensor = DummySensor({})
    sensor._hass = None
    auto_switch.start_auto_switch_watchdog(sensor)

    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_unsub = lambda: None
    auto_switch.start_auto_switch_watchdog(sensor)

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_unsub = None
    sensor._auto_switch_watchdog_interval = timedelta(seconds=30)

    def _track(_hass, _cb, _interval):
        return lambda: None

    monkeypatch.setattr(auto_switch, "_async_track_time_interval", _track)
    auto_switch.start_auto_switch_watchdog(sensor)
    assert sensor._auto_switch_watchdog_unsub is not None

    auto_switch.stop_auto_switch_watchdog(sensor)
    assert sensor._auto_switch_watchdog_unsub is None

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_unsub = None
    monkeypatch.setattr(auto_switch, "_async_track_time_interval", None)
    auto_switch.start_auto_switch_watchdog(sensor)


@pytest.mark.asyncio
async def test_auto_switch_watchdog_tick(monkeypatch):
    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_unsub = lambda: None

    fixed_now = dt_util.now()
    monkeypatch.setattr(auto_switch, "get_mode_switch_timeline", lambda _s: ([], "none"))
    await auto_switch.auto_switch_watchdog_tick(sensor, fixed_now)

    monkeypatch.setattr(
        auto_switch,
        "get_mode_switch_timeline",
        lambda _s: ([{"time": fixed_now.isoformat(), "mode_name": "Home 1"}], "hybrid"),
    )
    monkeypatch.setattr(auto_switch, "get_current_box_mode", lambda _s: "Home 1")
    await auto_switch.auto_switch_watchdog_tick(sensor, fixed_now)

    called = {}

    async def _ensure(_sensor, _mode, _reason):
        called["ok"] = True

    monkeypatch.setattr(auto_switch, "ensure_current_mode", _ensure)
    monkeypatch.setattr(auto_switch, "get_current_box_mode", lambda _s: "Home UPS")
    await auto_switch.auto_switch_watchdog_tick(sensor, fixed_now)
    assert called["ok"] is True

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: False})
    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_unsub = lambda: None
    await auto_switch.auto_switch_watchdog_tick(sensor, fixed_now)

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    monkeypatch.setattr(
        auto_switch, "get_mode_switch_timeline", lambda _s: ([{"time": fixed_now.isoformat()}], "hybrid")
    )
    monkeypatch.setattr(auto_switch, "get_planned_mode_for_time", lambda *_a, **_k: None)
    await auto_switch.auto_switch_watchdog_tick(sensor, fixed_now)


def test_get_planned_mode_for_time_invalid():
    sensor = DummySensor({})
    base = dt_util.now()
    timeline = [{"time": "bad", "mode_name": "Home 1"}, {"mode_name": None}]
    assert auto_switch.get_planned_mode_for_time(sensor, base, timeline) is None


def test_schedule_auto_switch_retry_skip(monkeypatch):
    sensor = DummySensor({})
    sensor._hass = None
    auto_switch.schedule_auto_switch_retry(sensor, 5.0)

    sensor._hass = DummyHass()
    auto_switch.schedule_auto_switch_retry(sensor, 0.0)

    sensor._auto_switch_retry_unsub = lambda: None
    auto_switch.schedule_auto_switch_retry(sensor, 5.0)

    sensor._auto_switch_retry_unsub = None
    sensor._log_rate_limited = lambda *_a, **_k: None
    monkeypatch.setattr(auto_switch, "async_call_later", lambda *_a, **_k: (lambda: None))
    auto_switch.schedule_auto_switch_retry(sensor, 1.0)
    assert sensor._auto_switch_retry_unsub is not None

    called = {}

    def _fake_call_later(_hass, _delay, callback):
        callback(dt_util.now())
        called["done"] = True
        return lambda: None

    sensor._auto_switch_retry_unsub = None
    sensor._create_task_threadsafe = lambda *_a, **_k: called.setdefault("task", True)
    monkeypatch.setattr(auto_switch, "async_call_later", _fake_call_later)
    auto_switch.schedule_auto_switch_retry(sensor, 1.0)
    assert called.get("task") is True


def test_get_mode_switch_offset(monkeypatch):
    sensor = DummySensor({"auto_mode_switch_lead_seconds": 120})
    sensor._hass = DummyHass()
    sensor._config_entry.entry_id = "entry"
    assert auto_switch.get_mode_switch_offset(sensor, None, "Home 1") == 120.0

    class ModeTracker:
        def get_offset_for_scenario(self, *_a):
            return 30.0

    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": SimpleNamespace(mode_tracker=ModeTracker())}}}
    assert auto_switch.get_mode_switch_offset(sensor, "Home 1", "Home 2") == 30.0

    class BadTracker:
        def get_offset_for_scenario(self, *_a):
            return 0

    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": SimpleNamespace(mode_tracker=BadTracker())}}}
    assert auto_switch.get_mode_switch_offset(sensor, "Home 1", "Home 2") == 120.0

    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": None}}}
    assert auto_switch.get_mode_switch_offset(sensor, "Home 1", "Home 2") == 120.0


def test_get_service_shield():
    sensor = DummySensor({})
    sensor._hass = None
    assert auto_switch.get_service_shield(sensor) is None

    sensor._hass = DummyHass()
    sensor._config_entry.entry_id = "entry"
    assert auto_switch.get_service_shield(sensor) is None

    shield = object()
    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": shield}}}
    assert auto_switch.get_service_shield(sensor) is shield


@pytest.mark.asyncio
async def test_execute_mode_change_branches(monkeypatch):
    sensor = DummySensor({})
    sensor._side_effects_enabled = False
    await auto_switch.execute_mode_change(sensor, "Home 1", "reason")

    sensor._side_effects_enabled = True
    sensor._hass = DummyHass()

    class Shield:
        def has_pending_mode_change(self, _mode):
            return True

    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": Shield()}}}
    sensor._config_entry.entry_id = "entry"
    await auto_switch.execute_mode_change(sensor, "Home 1", "reason")

    sensor._hass.data = {"oig_cloud": {"entry": {"service_shield": None}}}
    now = dt_util.now()
    sensor._last_auto_switch_request = ("Home 1", now)
    monkeypatch.setattr(auto_switch.dt_util, "now", lambda: now + timedelta(seconds=10))
    await auto_switch.execute_mode_change(sensor, "Home 1", "reason")

    async def _ok(*_a, **_k):
        return None

    sensor._hass.services.async_call = _ok
    sensor._last_auto_switch_request = None
    await auto_switch.execute_mode_change(sensor, "Home 2", "reason")
    assert sensor._last_auto_switch_request[0] == "Home 2"

    async def _boom(*_a, **_k):
        raise RuntimeError("fail")

    sensor._hass.services.async_call = _boom
    sensor._last_auto_switch_request = None
    await auto_switch.execute_mode_change(sensor, "Home 3", "reason")


@pytest.mark.asyncio
async def test_ensure_current_mode(monkeypatch):
    sensor = DummySensor({})
    monkeypatch.setattr(auto_switch, "get_current_box_mode", lambda _s: "Home 1")
    await auto_switch.ensure_current_mode(sensor, "Home 1", "reason")

    called = {}

    async def _execute(_s, _mode, _reason):
        called["ok"] = True

    monkeypatch.setattr(auto_switch, "get_current_box_mode", lambda _s: "Home 2")
    monkeypatch.setattr(auto_switch, "execute_mode_change", _execute)
    await auto_switch.ensure_current_mode(sensor, "Home 1", "reason")
    assert called["ok"] is True


def test_get_mode_switch_timeline():
    sensor = DummySensor({})
    sensor._timeline_data = []
    assert auto_switch.get_mode_switch_timeline(sensor) == ([], "none")

    sensor._timeline_data = [{"time": dt_util.now().isoformat()}]
    timeline, source = auto_switch.get_mode_switch_timeline(sensor)
    assert timeline
    assert source == "hybrid"


@pytest.mark.asyncio
async def test_update_auto_switch_schedule(monkeypatch):
    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: False})
    sensor._hass = DummyHass()
    sensor._auto_switch_ready_at = None
    sensor._auto_switch_watchdog_unsub = lambda: None

    await auto_switch.update_auto_switch_schedule(sensor)

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_ready_at = dt_util.now() + timedelta(seconds=10)
    sensor._auto_switch_watchdog_interval = timedelta(seconds=30)
    called = {}

    monkeypatch.setattr(auto_switch, "schedule_auto_switch_retry", lambda *_a: called.setdefault("retry", 0))
    sensor._log_rate_limited = lambda *_a, **_k: called.setdefault("log", 0)
    await auto_switch.update_auto_switch_schedule(sensor)
    assert "retry" in called

    sensor._auto_switch_ready_at = dt_util.now() - timedelta(seconds=1)
    monkeypatch.setattr(auto_switch, "clear_auto_switch_retry", lambda *_a: called.setdefault("cleared", 0))
    monkeypatch.setattr(auto_switch, "get_mode_switch_timeline", lambda _s: ([], "none"))
    await auto_switch.update_auto_switch_schedule(sensor)
    assert "cleared" in called

    now = dt_util.now()
    timeline = [
        {"time": (now - timedelta(minutes=15)).isoformat(), "mode_name": "Home 1"},
        {"time": (now + timedelta(minutes=15)).isoformat(), "mode_name": "Home UPS"},
        {"time": (now + timedelta(minutes=30)).isoformat(), "mode_name": "Home UPS"},
        {"time": "bad", "mode_name": "Home 1"},
        {"time": (now + timedelta(minutes=45)).isoformat()},
    ]
    sensor._timeline_data = timeline
    sensor._auto_switch_handles = []
    sensor._auto_switch_ready_at = None

    async def _ensure(_s, _mode, _reason):
        called["ensure"] = True

    monkeypatch.setattr(auto_switch, "ensure_current_mode", _ensure)
    monkeypatch.setattr(
        auto_switch,
        "async_track_point_in_time",
        lambda *_a, **_k: (lambda: None),
    )
    monkeypatch.setattr(
        auto_switch,
        "get_mode_switch_timeline",
        lambda _s: (timeline, "hybrid"),
    )
    monkeypatch.setattr(
        auto_switch,
        "start_auto_switch_watchdog",
        lambda *_a: called.setdefault("watchdog", 0),
    )
    await auto_switch.update_auto_switch_schedule(sensor)
    assert sensor._auto_switch_handles
    assert "ensure" in called

    sensor._auto_switch_handles = []
    sensor._timeline_data = [
        {"time": (now - timedelta(minutes=15)).isoformat(), "mode_name": "Home 1"}
    ]
    monkeypatch.setattr(
        auto_switch,
        "get_mode_switch_timeline",
        lambda _s: (sensor._timeline_data, "hybrid"),
    )
    await auto_switch.update_auto_switch_schedule(sensor)
    assert sensor._auto_switch_handles == []


@pytest.mark.asyncio
async def test_start_watchdog_ticks(monkeypatch):
    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_watchdog_interval = timedelta(seconds=30)
    sensor._auto_switch_watchdog_unsub = None

    stored = {}

    def _track(_hass, cb, _interval):
        stored["cb"] = cb
        return lambda: None

    monkeypatch.setattr(auto_switch, "_async_track_time_interval", _track)

    async def _tick(_sensor, _now):
        stored["hit"] = True

    monkeypatch.setattr(auto_switch, "auto_switch_watchdog_tick", _tick)
    auto_switch.start_auto_switch_watchdog(sensor)
    await stored["cb"](dt_util.now())
    assert stored["hit"] is True


@pytest.mark.asyncio
async def test_update_auto_switch_schedule_adjusts_past(monkeypatch):
    class FakeTime:
        def __init__(self):
            self._calls = 0

        def __le__(self, _other):
            self._calls += 1
            return self._calls > 1

        def isoformat(self):
            return "2025-01-01T00:00:00"

    fake_time = FakeTime()

    sensor = DummySensor({CONF_AUTO_MODE_SWITCH: True})
    sensor._hass = DummyHass()
    sensor._auto_switch_ready_at = None
    sensor._auto_switch_handles = []
    sensor._auto_switch_watchdog_unsub = None
    sensor._auto_switch_watchdog_interval = timedelta(seconds=30)

    timeline = [{"time": "2025-01-01T00:00:00", "mode_name": "Home 1"}]

    monkeypatch.setattr(auto_switch, "get_mode_switch_timeline", lambda _s: (timeline, "hybrid"))
    monkeypatch.setattr(auto_switch, "parse_timeline_timestamp", lambda _t: fake_time)
    monkeypatch.setattr(auto_switch, "start_auto_switch_watchdog", lambda *_a, **_k: None)

    callbacks = {}

    def _track(_hass, cb, _when):
        callbacks["cb"] = cb
        return lambda: None

    monkeypatch.setattr(auto_switch, "async_track_point_in_time", _track)
    async def _execute(*_a, **_k):
        return None

    monkeypatch.setattr(auto_switch, "execute_mode_change", _execute)

    await auto_switch.update_auto_switch_schedule(sensor)
    await callbacks["cb"](dt_util.now())


def test_calculate_interval_cost_opportunity():
    result = scenario_analysis.calculate_interval_cost(
        {"net_cost": 2.0, "battery_discharge": 1.0},
        spot_price=3.0,
        export_price=1.0,
        time_of_day="night",
    )

    assert result["direct_cost"] == 2.0
    assert result["opportunity_cost"] > 0
    assert result["total_cost"] > result["direct_cost"]


def test_calculate_fixed_mode_cost_basic():
    class DummySensorForScenario:
        def _get_battery_efficiency(self):
            return 1.0

        def _log_rate_limited(self, *_args, **_kwargs):
            return None

    sensor = DummySensorForScenario()
    now = dt_util.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=15)).isoformat(), "price": 2.0},
        {"time": (now + timedelta(minutes=30)).isoformat(), "price": 3.0},
    ]
    export_prices = [
        {"time": (now + timedelta(minutes=15)).isoformat(), "price": 1.0},
        {"time": (now + timedelta(minutes=30)).isoformat(), "price": 1.0},
    ]

    result = scenario_analysis.calculate_fixed_mode_cost(
        sensor,
        fixed_mode=CBB_MODE_HOME_I,
        current_capacity=2.0,
        max_capacity=10.0,
        min_capacity=1.0,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast={},
        load_forecast=[0.5, 0.5],
        physical_min_capacity=0.5,
    )

    assert result["total_cost"] >= 0
    assert result["grid_import_kwh"] >= 0
    assert "penalty_cost" in result


def test_calculate_mode_baselines():
    class DummySensorForScenario:
        def _get_battery_efficiency(self):
            return 1.0

        def _log_rate_limited(self, *_args, **_kwargs):
            return None

    sensor = DummySensorForScenario()
    now = dt_util.now()
    spot_prices = [
        {"time": (now + timedelta(minutes=15)).isoformat(), "price": 2.0},
    ]
    export_prices = [
        {"time": (now + timedelta(minutes=15)).isoformat(), "price": 1.0},
    ]

    baselines = scenario_analysis.calculate_mode_baselines(
        sensor,
        current_capacity=2.0,
        max_capacity=10.0,
        physical_min_capacity=0.5,
        spot_prices=spot_prices,
        export_prices=export_prices,
        solar_forecast={},
        load_forecast=[0.5],
    )

    assert "HOME_I" in baselines
    assert baselines["HOME_I"]["total_cost"] >= 0
