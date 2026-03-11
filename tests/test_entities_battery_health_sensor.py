from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import battery_health_sensor as module
from custom_components.oig_cloud.entities.battery_health_sensor import CapacityMeasurement


class DummyState:
    def __init__(self, state, last_changed):
        self.state = state
        self.last_changed = last_changed


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, states):
        self.states = states
        self.config = SimpleNamespace(config_dir="/tmp")
        self.created = []

    def async_create_task(self, coro):
        coro.close()
        self.created.append(True)
        return object()


class DummyStore:
    def __init__(self, *_args, **_kwargs):
        self.saved = None
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.saved = data


class BoomStore:
    async def async_load(self):
        raise RuntimeError("boom")

    async def async_save(self, _data):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_find_monotonic_charging_intervals(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)

    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    states = [
        DummyState("10", t0),
        DummyState("20", t0 + timedelta(hours=1)),
        DummyState("70", t0 + timedelta(hours=2)),
        DummyState("60", t0 + timedelta(hours=3)),
    ]

    intervals = tracker._find_monotonic_charging_intervals(states)
    assert len(intervals) == 1
    start_time, end_time, start_soc, end_soc = intervals[0]
    assert start_soc == 10.0
    assert end_soc == 70.0
    assert end_time == t0 + timedelta(hours=2)


@pytest.mark.asyncio
async def test_calculate_capacity(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)

    efficiency_state = DummyState("90", t0)
    hass = DummyHass(
        DummyStates({"sensor.oig_123_battery_efficiency": efficiency_state})
    )

    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=15.3)

    charge_states = [
        DummyState("1000", t0),
        DummyState("8000", t1),
    ]

    measurement = tracker._calculate_capacity(
        t0,
        t1,
        start_soc=10.0,
        end_soc=60.0,
        charge_states=charge_states,
    )

    assert measurement is not None
    assert measurement.delta_soc == 50.0
    assert measurement.capacity_kwh > 0
    assert 70.0 <= measurement.soh_percent <= 100.0


def test_get_value_at_time_invalid_state(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123")

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    states = [DummyState("bad", t0)]
    assert tracker._get_value_at_time(states, t0) is None


def test_current_soh_and_capacity(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123")

    base = CapacityMeasurement(
        timestamp="2025-01-01T00:00:00+00:00",
        start_soc=0.0,
        end_soc=50.0,
        delta_soc=50.0,
        charge_energy_wh=5000.0,
        capacity_kwh=10.0,
        soh_percent=90.0,
        duration_hours=1.0,
    )
    tracker._measurements = [base, replace(base, soh_percent=80.0, capacity_kwh=9.0)]

    assert tracker.get_current_soh() == 85.0
    assert tracker.get_current_capacity() == 9.5


@pytest.mark.asyncio
async def test_storage_load_and_save(monkeypatch):
    store = DummyStore()
    store.data = {
        "measurements": [
            {
                "timestamp": "2025-01-01T00:00:00+00:00",
                "start_soc": 0.0,
                "end_soc": 50.0,
                "delta_soc": 50.0,
                "charge_energy_wh": 5000.0,
                "capacity_kwh": 10.0,
                "soh_percent": 90.0,
                "duration_hours": 1.0,
            }
        ],
        "last_analysis": "2025-01-01T00:00:00+00:00",
    }
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)

    await tracker.async_load_from_storage()
    assert tracker._measurements
    await tracker.async_save_to_storage()
    assert store.saved["measurements"]


@pytest.mark.asyncio
async def test_storage_load_and_save_errors(monkeypatch):
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: BoomStore())
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)

    await tracker.async_load_from_storage()
    await tracker.async_save_to_storage()


@pytest.mark.asyncio
async def test_analyze_last_10_days_no_history(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)

    class DummyInstance:
        async def async_add_executor_job(self, _func, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "homeassistant.components.recorder.get_instance", lambda *_a, **_k: DummyInstance()
    )
    result = await tracker.analyze_last_10_days()
    assert result == []


@pytest.mark.asyncio
async def test_analyze_last_10_days_missing_sensors(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)

    class DummyInstance:
        async def async_add_executor_job(self, _func, *_args, **_kwargs):
            return {"sensor.oig_123_batt_bat_c": []}

    monkeypatch.setattr(
        "homeassistant.components.recorder.get_instance", lambda *_a, **_k: DummyInstance()
    )
    result = await tracker.analyze_last_10_days()
    assert result == []


@pytest.mark.asyncio
async def test_analyze_last_10_days_happy_path(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    hass = DummyHass(
        DummyStates({"sensor.oig_123_battery_efficiency": DummyState("90", t0)})
    )
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=15.3)

    soc_states = [
        DummyState("10", t0),
        DummyState("70", t0 + timedelta(hours=1)),
        DummyState("60", t0 + timedelta(hours=2)),
    ]
    charge_states = [
        DummyState("1000", t0),
        DummyState("8000", t0 + timedelta(hours=1)),
    ]

    class DummyInstance:
        async def async_add_executor_job(self, _func, *_args, **_kwargs):
            return {
                "sensor.oig_123_batt_bat_c": soc_states,
                "sensor.oig_123_computed_batt_charge_energy_month": charge_states,
            }

    monkeypatch.setattr(
        "homeassistant.components.recorder.get_instance", lambda *_a, **_k: DummyInstance()
    )
    result = await tracker.analyze_last_10_days()

    assert result
    assert tracker._last_analysis is not None


def test_find_monotonic_intervals_ignores_unknown(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123")

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    states = [
        DummyState("unknown", t0),
        DummyState("10", t0 + timedelta(hours=1)),
        DummyState("bad", t0 + timedelta(hours=2)),
        DummyState("70", t0 + timedelta(hours=3)),
    ]
    intervals = tracker._find_monotonic_charging_intervals(states)
    assert intervals


def test_calculate_capacity_rejects_invalid(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    charge_states = [DummyState("1000", t0), DummyState("500", t1)]
    assert tracker._calculate_capacity(t0, t1, 0, 60, charge_states) is None

    charge_states = [DummyState("1000", t0), DummyState("1500", t1)]
    assert tracker._calculate_capacity(t0, t1, 0, 60, charge_states) is None


def test_calculate_capacity_missing_charge_values(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=10.0)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    assert tracker._calculate_capacity(t0, t1, 0, 60, []) is None


def test_calculate_capacity_efficiency_invalid(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)
    hass = DummyHass(
        DummyStates({"sensor.oig_123_battery_efficiency": DummyState("bad", t0)})
    )
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=12.0)

    charge_states = [DummyState("0", t0), DummyState("6000", t1)]
    measurement = tracker._calculate_capacity(t0, t1, 0, 60, charge_states)
    assert measurement is not None


def test_calculate_capacity_soh_limits(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=1.0)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    charge_states = [DummyState("0", t0), DummyState("200000", t1)]
    assert tracker._calculate_capacity(t0, t1, 0, 60, charge_states) is None


def test_calculate_capacity_soh_too_low(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123", nominal_capacity_kwh=50.0)
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=1)

    charge_states = [DummyState("0", t0), DummyState("10000", t1)]
    assert tracker._calculate_capacity(t0, t1, 0, 60, charge_states) is None


def test_get_value_at_time_empty(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123")
    assert tracker._get_value_at_time([], datetime.now(timezone.utc)) is None


def test_current_soh_and_capacity_empty(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    tracker = module.BatteryHealthTracker(hass, "123")
    assert tracker.get_current_soh() is None
    assert tracker.get_current_capacity() is None


@pytest.mark.asyncio
async def test_battery_health_sensor_lifecycle(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)

    hass = DummyHass(DummyStates({}))
    coordinator = SimpleNamespace(
        hass=hass, last_update_success=True, async_add_listener=lambda *_a, **_k: lambda: None
    )
    sensor = module.BatteryHealthSensor(
        coordinator, "battery_health", SimpleNamespace(), {}, hass
    )
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    sensor.hass = hass

    monkeypatch.setattr(
        module, "async_track_time_change", lambda *_a, **_k: lambda: None
    )

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    await sensor.async_added_to_hass()
    await sensor._daily_analysis(datetime.now(timezone.utc))

    assert sensor.device_info == {}
    assert sensor.extra_state_attributes["nominal_capacity_kwh"] == 15.3


def test_battery_health_sensor_resolve_box_id_error(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)

    def boom(_coord):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        boom,
    )
    hass = DummyHass(DummyStates({}))
    coordinator = SimpleNamespace(
        hass=hass, last_update_success=True, async_add_listener=lambda *_a, **_k: lambda: None
    )
    sensor = module.BatteryHealthSensor(
        coordinator, "battery_health", SimpleNamespace(), {}, hass
    )
    assert sensor._box_id == "unknown"


@pytest.mark.asyncio
async def test_battery_health_sensor_remove_and_initial_analysis(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    coordinator = SimpleNamespace(
        hass=hass, last_update_success=True, async_add_listener=lambda *_a, **_k: lambda: None
    )
    sensor = module.BatteryHealthSensor(
        coordinator, "battery_health", SimpleNamespace(), {}, hass
    )
    sensor.hass = hass
    called = {"sleep": 0, "analyze": 0, "daily": 0}

    async def fake_sleep(_delay):
        called["sleep"] += 1

    async def fake_analyze():
        called["analyze"] += 1

    sensor._tracker = SimpleNamespace(analyze_last_10_days=fake_analyze)
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    sensor._daily_unsub = lambda: called.__setitem__("daily", called["daily"] + 1)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    await sensor._initial_analysis()
    await sensor.async_will_remove_from_hass()

    assert called["sleep"] == 1
    assert called["analyze"] == 1
    assert called["daily"] == 1


def test_battery_health_sensor_native_value_and_attrs(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)
    hass = DummyHass(DummyStates({}))
    coordinator = SimpleNamespace(
        hass=hass, last_update_success=True, async_add_listener=lambda *_a, **_k: lambda: None
    )
    sensor = module.BatteryHealthSensor(
        coordinator, "battery_health", SimpleNamespace(), {}, hass
    )

    assert sensor.native_value is None
    assert sensor.extra_state_attributes["nominal_capacity_kwh"] == 15.3

    tracker = SimpleNamespace(
        _measurements=[
            CapacityMeasurement(
                timestamp="2025-01-01T00:00:00+00:00",
                start_soc=0.0,
                end_soc=50.0,
                delta_soc=50.0,
                charge_energy_wh=5000.0,
                capacity_kwh=10.0,
                soh_percent=88.8,
                duration_hours=1.0,
            )
        ],
        _last_analysis=datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc),
        get_current_soh=lambda: 88.84,
        get_current_capacity=lambda: 10.25,
    )
    sensor._tracker = tracker

    assert sensor.native_value == 88.8
    attrs = sensor.extra_state_attributes
    assert attrs["measurement_count"] == 1
    assert attrs["current_capacity_kwh"] == 10.25
