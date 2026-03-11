from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import statistics_sensor as module
from custom_components.oig_cloud.entities.statistics_sensor import (
    OigCloudStatisticsSensor,
    StatisticsProcessor,
    create_hourly_attributes,
)


class DummyCoordinator:
    def __init__(self, data=None, options=None):
        self.data = data if data is not None else {"123": {}}
        self.config_entry = SimpleNamespace(
            options=options or SimpleNamespace(enable_statistics=True)
        )

    def async_add_listener(self, *_a, **_k):
        return lambda: None


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyState:
    def __init__(self, state, attributes=None, last_updated=None):
        self.state = state
        self.attributes = attributes or {}
        self.last_updated = last_updated or datetime.now()


def _install_sensor_types(monkeypatch):
    module_types = types.ModuleType("custom_components.oig_cloud.sensor_types")
    module_types.SENSOR_TYPES = {
        "battery_load_median": {"name": "Median", "unit": "W"},
        "hourly_energy": {
            "name": "Hourly",
            "unit": "kWh",
            "source_sensor": "energy_total",
            "hourly_data_type": "energy_diff",
        },
        "interval_stat": {
            "name": "Interval",
            "unit": "W",
            "time_range": (22, 6),
            "day_type": "weekday",
            "statistic": "median",
            "max_age_days": 2,
        },
    }
    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.sensor_types", module_types)


@pytest.mark.asyncio
async def test_init_resolve_box_id_fallback(monkeypatch):
    _install_sensor_types(monkeypatch)

    def _boom(_coord):
        raise RuntimeError("bad resolve")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        _boom,
    )
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "battery_load_median", {})
    assert sensor._data_key == "unknown"


@pytest.mark.asyncio
async def test_async_added_to_hass_hourly_setup(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "hourly_energy", {})
    sensor.hass = SimpleNamespace(async_create_task=lambda coro: coro)

    called = {"interval": 0}

    def _track_interval(_hass, _cb, _delta):
        called["interval"] += 1
        return None

    monkeypatch.setattr(module, "async_track_time_interval", _track_interval)
    async def _load():
        return None

    monkeypatch.setattr(sensor, "_load_statistics_data", _load)
    await sensor.async_added_to_hass()
    assert called["interval"] == 1


@pytest.mark.asyncio
async def test_load_statistics_data_invalid_records(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "battery_load_median", {})
    sensor.hass = SimpleNamespace(loop_thread_id=0)
    sensor._hass = sensor.hass
    monkeypatch.setattr(
        "homeassistant.helpers.entity.Entity.async_write_ha_state",
        lambda *_a, **_k: None,
    )

    class DummyStore:
        def __init__(self, *_a, **_k):
            pass

        async def async_load(self):
            return {
                "sampling_data": [
                    ("bad", 1.0),
                    (datetime.now().isoformat(), 2.0),
                ],
                "hourly_data": [{"datetime": "bad", "value": 1.0}, {"x": 1}],
                "current_hourly_value": 1.0,
                "last_source_value": 2.0,
                "last_hour_reset": "bad",
            }

    monkeypatch.setattr(module, "Store", DummyStore)
    await sensor._load_statistics_data()
    assert len(sensor._sampling_data) == 1


@pytest.mark.asyncio
async def test_save_statistics_data_and_cleanup(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "battery_load_median", {})
    sensor.hass = SimpleNamespace(loop_thread_id=0)
    monkeypatch.setattr(
        OigCloudStatisticsSensor, "async_write_ha_state", lambda *_a, **_k: None
    )

    saved = {}

    class DummyStore:
        def __init__(self, *_a, **_k):
            pass

        async def async_save(self, data):
            saved.update(data)

    sensor._sampling_data = [(datetime.now(timezone.utc), 1.0)]
    sensor._hourly_data = [{"datetime": "2025-01-01T00:00:00+00:00", "value": "1"}]
    monkeypatch.setattr(module, "Store", DummyStore)
    await sensor._save_statistics_data()
    assert saved["sampling_data"]

    sensor._interval_data = {
        "2020-01-01": [1.0],
        datetime.now().strftime("%Y-%m-%d"): [2.0],
    }
    sensor._hourly_data.append({"datetime": "bad", "value": 1})
    await sensor._cleanup_old_data()
    assert "2020-01-01" not in sensor._interval_data


@pytest.mark.asyncio
async def test_update_sampling_data_and_check_hourly(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "battery_load_median", {})
    sensor.hass = SimpleNamespace()

    monkeypatch.setattr(sensor, "_get_actual_load_value", lambda: None)
    await sensor._update_sampling_data(datetime.now())
    assert sensor._sampling_data == []

    monkeypatch.setattr(sensor, "_get_actual_load_value", lambda: 5.0)
    sensor._sampling_data = [(datetime.now(), 1.0)] * 9
    called = {"save": 0}

    async def _save():
        called["save"] += 1

    monkeypatch.setattr(sensor, "_save_statistics_data", _save)
    await sensor._update_sampling_data(datetime.now())

    hourly = OigCloudStatisticsSensor(DummyCoordinator(), "hourly_energy", {})
    hourly.hass = SimpleNamespace(loop_thread_id=0)
    hourly._hass = hourly.hass
    async def _calc_hour():
        return 1.2

    monkeypatch.setattr(hourly, "_calculate_hourly_energy", _calc_hour)
    monkeypatch.setattr(hourly, "_save_statistics_data", _save)
    hourly.async_write_ha_state = lambda: None
    await hourly._check_hourly_end(datetime(2025, 1, 1, 10, 2, 0))
    assert hourly._current_hourly_value == 1.2


@pytest.mark.asyncio
async def test_daily_statistics_update_and_interval_history(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "interval_stat", {})
    async def _add_executor_job(func, *args):
        return func(*args)
    sensor.hass = SimpleNamespace(async_add_executor_job=_add_executor_job)
    sensor._time_range = (22, 6)

    async def _calc():
        return None

    monkeypatch.setattr(sensor, "_calculate_interval_statistics_from_history", _calc)
    await sensor._daily_statistics_update(None)

    # History with no data
    history_mod = types.ModuleType("homeassistant.components.recorder.history")
    history_mod.state_changes_during_period = lambda *_a, **_k: {}
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder.history", history_mod)
    assert await sensor._calculate_interval_statistics_from_history() is None


@pytest.mark.asyncio
async def test_interval_history_with_values(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "interval_stat", {})
    async def _add_executor_job(func, *args):
        return func(*args)
    sensor.hass = SimpleNamespace(async_add_executor_job=_add_executor_job)
    sensor._time_range = (0, 24)
    sensor._day_type = None
    sensor._max_age_days = 1

    history_mod = types.ModuleType("homeassistant.components.recorder.history")
    def _changes(_hass, _start, _end, entity_id):
        return {
            entity_id: [
                DummyState("10", last_updated=datetime.now()),
                DummyState("-1", last_updated=datetime.now()),
                DummyState("bad", last_updated=datetime.now()),
            ]
        }
    history_mod.state_changes_during_period = _changes
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder.history", history_mod)
    import homeassistant.components.recorder as recorder
    monkeypatch.setattr(recorder, "history", history_mod)
    result = await sensor._calculate_interval_statistics_from_history()
    assert result == 10.0


def test_hourly_energy_and_availability(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "hourly_energy", {})
    sensor.hass = SimpleNamespace(states=DummyStates({}))
    assert sensor.available is False

    sensor._sensor_config["hourly_data_type"] = "energy_diff"
    sensor._source_entity_id = "sensor.oig_123_energy_total"
    sensor.hass = SimpleNamespace(
        states=DummyStates(
            {
                "sensor.oig_123_energy_total": DummyState(
                    "1000", {"unit_of_measurement": "Wh"}
                )
            }
        )
    )
    assert sensor.available is True


@pytest.mark.asyncio
async def test_calculate_hourly_energy_branches(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "hourly_energy", {})
    sensor._source_entity_id = "sensor.oig_123_energy_total"
    sensor.hass = SimpleNamespace(
        states=DummyStates(
            {
                "sensor.oig_123_energy_total": DummyState(
                    "1000", {"unit_of_measurement": "Wh"}
                )
            }
        )
    )
    assert await sensor._calculate_hourly_energy() is None
    sensor._last_source_value = 1500
    assert await sensor._calculate_hourly_energy() == 1.0

    sensor._sensor_config["hourly_data_type"] = "power_integral"
    sensor.hass = SimpleNamespace(
        states=DummyStates(
            {
                "sensor.oig_123_energy_total": DummyState(
                    "2", {"unit_of_measurement": "kW"}
                )
            }
        )
    )
    assert await sensor._calculate_hourly_energy() == 2.0


def test_extra_state_attributes_and_processor(monkeypatch):
    _install_sensor_types(monkeypatch)
    sensor = OigCloudStatisticsSensor(DummyCoordinator(), "battery_load_median", {})
    sensor._sampling_data = [(datetime.now(), 1.0)]
    attrs = sensor.extra_state_attributes
    assert attrs["sampling_points"] == 1

    # Error path when config is missing
    hourly = OigCloudStatisticsSensor(DummyCoordinator(), "hourly_energy", {})
    hourly._sensor_config = None
    assert "error" in hourly.extra_state_attributes

    # create_hourly_attributes default current_time
    attrs = create_hourly_attributes("sensor", [], current_time=None)
    assert "last_updated" in attrs

    processor = StatisticsProcessor(SimpleNamespace())
    result = processor.process_hourly_data(
        "sensor",
        [{"timestamp": "bad"}, {"time": datetime.now(), "value": 2}],
        value_key="value",
    )
    assert result["value"] == 2.0
