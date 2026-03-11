from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.sensors import recommended_sensor


class DummyCoordinator:
    def __init__(self):
        self.hass = None
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options
        self.data = options
        self.entry_id = "entry-id"


class DummyStore:
    def __init__(self, data):
        self._data = data

    async def async_load(self):
        return self._data


class BoomStore:
    async def async_load(self):
        raise RuntimeError("boom")


def test_compute_state_and_attrs_with_detail_tabs(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {"planner_recommended_mode": {"name": "Recommended", "icon": "mdi:robot"}},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )

    coordinator = DummyCoordinator()
    config_entry = DummyConfigEntry({"auto_mode_switch_lead_seconds": 180.0})

    sensor = recommended_sensor.OigCloudPlannerRecommendedModeSensor(
        coordinator,
        "planner_recommended_mode",
        config_entry,
        device_info={},
        hass=None,
    )

    now = dt_util.now()
    current_start = now.replace(
        minute=(now.minute // 15) * 15, second=0, microsecond=0
    )
    next_start = current_start + timedelta(minutes=15)

    intervals = [
        {
            "time": current_start.strftime("%H:%M"),
            "planned": {"mode": 0, "mode_name": "HOME 1"},
        },
        {
            "time": next_start.strftime("%H:%M"),
            "planned": {"mode": 3, "mode_name": "HOME UPS"},
        },
    ]

    sensor._precomputed_payload = {
        "timeline_data": [],
        "calculation_time": now.isoformat(),
        "detail_tabs": {
            "today": {
                "date": current_start.date().isoformat(),
                "intervals": intervals,
            }
        },
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["next_mode"] == "Home UPS"

    effective_from = dt_util.parse_datetime(attrs["recommended_effective_from"])
    next_change = dt_util.parse_datetime(attrs["next_mode_change_at"])
    assert (next_change - effective_from).total_seconds() == 180.0


def test_init_with_entity_category_and_resolve_error(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {"planner_recommended_mode": {"name": "Recommended", "entity_category": "diagnostic"}},
    )

    def boom(_coord):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        boom,
    )
    sensor = recommended_sensor.OigCloudPlannerRecommendedModeSensor(
        DummyCoordinator(),
        "planner_recommended_mode",
        DummyConfigEntry({}),
        device_info={},
        hass=None,
    )
    assert sensor._box_id == "unknown"


def _make_sensor(monkeypatch, hass=None, options=None):
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {"planner_recommended_mode": {"name": "Recommended", "icon": "mdi:robot"}},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )
    coordinator = DummyCoordinator()
    coordinator.hass = hass
    config_entry = DummyConfigEntry(options or {})
    sensor = recommended_sensor.OigCloudPlannerRecommendedModeSensor(
        coordinator,
        "planner_recommended_mode",
        config_entry,
        device_info={},
        hass=hass,
    )
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    return sensor


def test_normalize_mode_label(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    assert sensor._normalize_mode_label("HOME UPS", None) == "Home UPS"
    assert sensor._normalize_mode_label("Home 1", None) == "Home 1"
    assert sensor._normalize_mode_label("HOME I", None) == "Home 1"
    assert sensor._normalize_mode_label("HOME II", None) == "Home 2"
    assert sensor._normalize_mode_label("HOME III", None) == "Home 3"
    assert sensor._normalize_mode_label("HOME 2", None) == "Home 2"
    assert sensor._normalize_mode_label("Home 3", None) == "Home 3"
    assert sensor._normalize_mode_label(None, 0) == "Home 1"
    assert sensor._normalize_mode_label(None, 2) == "Home 3"
    assert sensor._normalize_mode_label(None, 3) == "Home UPS"
    assert sensor._normalize_mode_label("custom", None) is None


def test_parse_local_start_none(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    assert sensor._parse_local_start(None) is None


def test_parse_interval_time(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    date_hint = "2025-01-01"
    dt_val = sensor._parse_interval_time("12:15", date_hint)
    assert dt_val is not None
    assert sensor._parse_interval_time("bad", date_hint) is None
    assert sensor._parse_interval_time(None, date_hint) is None


def test_get_auto_switch_lead_seconds(monkeypatch):
    hass = SimpleNamespace(data={}, config=SimpleNamespace(config_dir=str(Path.cwd())))
    sensor = _make_sensor(
        monkeypatch,
        hass=hass,
        options={"auto_mode_switch_lead_seconds": 90.0},
    )
    assert sensor._get_auto_switch_lead_seconds("Home 1", "Home 2") == 90.0

    hass.data["oig_cloud"] = {
        "entry-id": {
            "service_shield": SimpleNamespace(
                mode_tracker=SimpleNamespace(get_offset_for_scenario=lambda *_a: 120.0)
            )
        }
    }
    assert sensor._get_auto_switch_lead_seconds("Home 1", "Home 2") == 120.0

    hass.data["oig_cloud"]["entry-id"]["service_shield"] = SimpleNamespace(mode_tracker=SimpleNamespace(get_offset_for_scenario=lambda *_a: None))
    assert sensor._get_auto_switch_lead_seconds("Home 1", "Home 2") == 90.0


def test_get_auto_switch_lead_seconds_exception(monkeypatch):
    hass = SimpleNamespace(data={}, config=SimpleNamespace(config_dir=str(Path.cwd())))
    sensor = _make_sensor(
        monkeypatch,
        hass=hass,
        options={"auto_mode_switch_lead_seconds": 45.0},
    )
    hass.data["oig_cloud"] = {
        "entry-id": {
            "service_shield": SimpleNamespace(
                mode_tracker=SimpleNamespace(
                    get_offset_for_scenario=lambda *_a: (_ for _ in ()).throw(RuntimeError("boom"))
                )
            )
        }
    }
    assert sensor._get_auto_switch_lead_seconds("Home 1", "Home 2") == 45.0


def test_compute_state_and_attrs_no_payload(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    value, attrs, _sig = sensor._compute_state_and_attrs()
    assert value is None
    assert attrs["points_count"] == 0


def test_compute_state_and_attrs_timeline_only(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = dt_util.now()
    timeline = [
        {"time": (now - timedelta(minutes=15)).isoformat(), "mode": 0},
        {"time": now.isoformat(), "mode": 1},
        {"time": (now + timedelta(minutes=15)).isoformat(), "mode": 3},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
        "calculation_time": now.isoformat(),
    }
    value, attrs, _sig = sensor._compute_state_and_attrs()
    assert value in {"Home 2", "Home UPS", "Home 1"}
    assert attrs["next_mode_change_at"]


def test_compute_state_and_attrs_detail_tabs_timeline_current(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 5, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    detail_intervals = [
        {"time": "09:00", "planned": {"mode": None}},
    ]
    timeline = [
        {"time": "2025-01-01T10:00:00+00:00", "mode": 0},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
        "detail_tabs": {"today": {"date": "2025-01-01", "intervals": detail_intervals}},
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["recommended_interval_start"] is not None


def test_compute_state_and_attrs_detail_tabs_skips_and_breaks(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    intervals = [
        {"time": None, "planned": {"mode": 0, "mode_name": "HOME 1"}},
        {"time": "09:30", "planned": {"mode": None}},
        {"time": "09:00", "planned": {"mode": 0, "mode_name": "HOME 1"}},
        {"time": "10:15", "planned": {"mode": 1, "mode_name": "HOME 2"}},
    ]
    sensor._precomputed_payload = {
        "timeline_data": [],
        "detail_tabs": {"today": {"date": "2025-01-01", "intervals": intervals}},
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["recommended_interval_start"] is not None


def test_compute_state_and_attrs_detail_tabs_fallback_to_timeline(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 5, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    detail_intervals = [
        {"time": "09:00", "planned": {"mode": None}},
        {"time": "09:15", "planned": {}},
    ]
    timeline = [
        {"time": None, "mode": 0},
        {"time": "2025-01-01T09:45:00+00:00", "mode": 1},
        {"time": "2025-01-01T10:30:00+00:00", "mode": 3},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
        "detail_tabs": {"today": {"date": "2025-01-01", "intervals": detail_intervals}},
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value in {"Home 1", "Home 2", "Home UPS"}
    assert attrs["points_count"] == 2


def test_compute_state_and_attrs_timeline_skips_invalid(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    timeline = [
        {"time": None, "mode": 0},
        {"time": "2025-01-01T09:30:00+00:00", "mode": 0},
        {"time": "2025-01-01T10:30:00+00:00", "mode": 1},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["recommended_interval_start"] is not None


def test_compute_state_and_attrs_next_mode_invalid_time(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    intervals = [
        {"time": "10:00", "planned": {"mode": 0, "mode_name": "HOME 1"}},
        {"time": None, "planned": {"mode": 1, "mode_name": "HOME 2"}},
    ]
    sensor._precomputed_payload = {
        "timeline_data": [],
        "detail_tabs": {"today": {"date": "2025-01-01", "intervals": intervals}},
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["next_mode_change_at"] is None


def test_compute_state_and_attrs_next_mode_invalid_time_timeline(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    timeline = [
        {"time": "2025-01-01T10:00:00+00:00", "mode": 0},
        {"time": None, "mode": 1},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["next_mode_change_at"] is None


def test_compute_state_and_attrs_lead_seconds_zero(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(recommended_sensor.dt_util, "now", lambda: fixed_now)
    monkeypatch.setattr(sensor, "_get_auto_switch_lead_seconds", lambda *_a: 0.0)
    timeline = [
        {"time": "2025-01-01T09:45:00+00:00", "mode": 0},
        {"time": "2025-01-01T10:15:00+00:00", "mode": 1},
    ]
    sensor._precomputed_payload = {
        "timeline_data": timeline,
    }

    value, attrs, _sig = sensor._compute_state_and_attrs()

    assert value == "Home 1"
    assert attrs["recommended_effective_from"] is None


def test_get_forecast_payload_from_coordinator(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor.coordinator.battery_forecast_data = {"timeline_data": [{"time": dt_util.now().isoformat(), "mode": 0}]}
    payload = sensor._get_forecast_payload()
    assert payload is not None


@pytest.mark.asyncio
async def test_async_refresh_precomputed_payload(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._precomputed_store = DummyStore({"timeline": []})
    await sensor._async_refresh_precomputed_payload()
    assert sensor._precomputed_payload is None

    sensor._precomputed_store = DummyStore(
        {
            "timeline": [{"time": datetime.now().isoformat(), "mode": 0}],
            "last_update": "now",
            "detail_tabs": {},
        }
    )
    await sensor._async_refresh_precomputed_payload()
    assert sensor._precomputed_payload["timeline_data"]

    sensor._precomputed_store = DummyStore("bad")
    await sensor._async_refresh_precomputed_payload()
    assert sensor._precomputed_payload["timeline_data"]

    sensor._precomputed_store = BoomStore()
    await sensor._async_refresh_precomputed_payload()


@pytest.mark.asyncio
async def test_async_recompute_sets_state(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = dt_util.now()
    sensor._precomputed_payload = {
        "timeline_data": [{"time": now.isoformat(), "mode": 0}],
        "calculation_time": now.isoformat(),
    }
    await sensor._async_recompute()
    assert sensor.native_value == "Home 1"


@pytest.mark.asyncio
async def test_async_recompute_writes_state(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass=hass)
    sensor.async_write_ha_state = lambda *args, **kwargs: hass.created.append("write")
    now = dt_util.now()
    sensor._precomputed_payload = {
        "timeline_data": [{"time": now.isoformat(), "mode": 0}],
        "calculation_time": now.isoformat(),
    }
    await sensor._async_recompute()
    assert "write" in hass.created


@pytest.mark.asyncio
async def test_async_recompute_no_change(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._precomputed_payload = {
        "timeline_data": [{"time": dt_util.now().isoformat(), "mode": 0}],
    }
    value, attrs, sig = sensor._compute_state_and_attrs()
    sensor._last_signature = sig
    sensor._attr_native_value = value
    sensor._attr_extra_state_attributes = attrs

    await sensor._async_recompute()

    assert sensor._last_signature == sig


@pytest.mark.asyncio
async def test_async_recompute_handles_exception(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "_async_refresh_precomputed_payload", boom)
    await sensor._async_recompute()


def test_available_and_extra_attrs(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._attr_extra_state_attributes = {"points_count": 0}
    assert sensor.available is False
    sensor._attr_extra_state_attributes = {"points_count": 1, "foo": "bar"}
    assert sensor.available is True
    assert sensor.extra_state_attributes["foo"] == "bar"


class DummyHass:
    def __init__(self):
        self.data = {}
        self.config = SimpleNamespace(config_dir=str(Path.cwd()))
        self.created = []

    def async_create_task(self, coro):
        task = SimpleNamespace(coro=coro)
        self.created.append(task)
        coro.close()
        return task


class DummyStoreInit:
    def __init__(self, _hass, version, key):
        self.version = version
        self.key = key


@pytest.mark.asyncio
async def test_async_added_to_hass_setup_and_recompute(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass=hass)
    sensor._precomputed_store = None
    called = {"recompute": 0}

    async def fake_recompute():
        called["recompute"] += 1

    monkeypatch.setattr(recommended_sensor, "Store", DummyStoreInit)
    monkeypatch.setattr(sensor, "_async_recompute", fake_recompute)
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *_a, **_k: (lambda: None),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change",
        lambda *_a, **_k: (lambda: None),
    )

    await sensor.async_added_to_hass()

    assert sensor._precomputed_store is not None
    assert called["recompute"] == 1
    assert len(sensor._unsubs) == 5


@pytest.mark.asyncio
async def test_async_added_to_hass_triggers_callbacks(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass=hass)
    sensor._precomputed_store = DummyStore({"timeline": []})
    created = {"tasks": 0}
    dispatch_cb = {"cb": None}
    tick_cb = {"cb": None}

    async def fake_recompute():
        return None

    def fake_create_task(coro):
        created["tasks"] += 1
        coro.close()
        return object()

    def fake_dispatcher(_hass, _signal, cb):
        dispatch_cb["cb"] = cb
        return lambda: None

    def fake_track(_hass, cb, **_kw):
        tick_cb["cb"] = cb
        return lambda: None

    hass.async_create_task = fake_create_task
    monkeypatch.setattr(sensor, "_async_recompute", fake_recompute)
    monkeypatch.setattr(recommended_sensor, "Store", DummyStore)
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        fake_dispatcher,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change",
        fake_track,
    )

    await sensor.async_added_to_hass()
    await dispatch_cb["cb"]()
    await tick_cb["cb"](dt_util.now())

    assert created["tasks"] >= 2


@pytest.mark.asyncio
async def test_async_added_to_hass_handles_errors(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass=hass)

    async def fake_recompute():
        return None

    monkeypatch.setattr(recommended_sensor, "Store", DummyStoreInit)
    monkeypatch.setattr(sensor, "_async_recompute", fake_recompute)
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_time_change",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    await sensor.async_added_to_hass()

    assert sensor._unsubs == []


@pytest.mark.asyncio
async def test_async_will_remove_from_hass(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"ok": 0}

    def ok_unsub():
        called["ok"] += 1

    def boom_unsub():
        raise RuntimeError("boom")

    sensor._unsubs = [ok_unsub, boom_unsub]

    await sensor.async_will_remove_from_hass()

    assert called["ok"] == 1
    assert sensor._unsubs == []


def test_handle_coordinator_update(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    assert sensor._handle_coordinator_update() is None
