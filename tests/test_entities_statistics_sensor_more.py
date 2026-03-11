from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.statistics_sensor import (
    OigCloudStatisticsSensor,
    create_hourly_attributes,
    safe_datetime_compare,
)


class DummyCoordinator:
    def __init__(self):
        self.data = {"123": {}}

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyStates:
    def __init__(self, state_map):
        self._map = state_map

    def get(self, entity_id):
        return self._map.get(entity_id)


class DummyOptions(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(name)


def _make_sensor(sensor_type="battery_load_median", state_map=None, options=None):
    coordinator = DummyCoordinator()
    if options is None:
        options = DummyOptions()
    elif isinstance(options, dict):
        options = DummyOptions(options)
    coordinator.config_entry = SimpleNamespace(options=options)
    device_info = {"identifiers": {("oig_cloud", "123")}}
    sensor = OigCloudStatisticsSensor(coordinator, sensor_type, device_info)
    sensor.hass = SimpleNamespace(states=DummyStates(state_map or {}))
    sensor.async_write_ha_state = lambda: None
    return sensor


class DummyStore:
    data = None
    saved = None

    def __init__(self, *_args, **_kwargs):
        pass

    async def async_load(self):
        return DummyStore.data

    async def async_save(self, data):
        DummyStore.saved = data


@pytest.mark.asyncio
async def test_load_statistics_data_invalid_records(monkeypatch):
    sensor = _make_sensor()
    now = datetime.now()
    DummyStore.data = {
        "sampling_data": [["bad", 1.5]],
        "hourly_data": [{"datetime": "bad", "value": "nope"}],
        "last_hour_reset": "bad",
    }
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", DummyStore
    )

    await sensor._load_statistics_data()
    assert sensor._sampling_data == []
    assert sensor._hourly_data == []
    assert sensor._last_hour_reset is None


@pytest.mark.asyncio
async def test_save_statistics_data_store_failure(monkeypatch):
    sensor = _make_sensor()

    class BrokenStore(DummyStore):
        async def async_save(self, _data):
            raise RuntimeError("fail")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", BrokenStore
    )
    await sensor._save_statistics_data()


@pytest.mark.asyncio
async def test_update_sampling_data_no_value():
    sensor = _make_sensor()
    sensor._sensor_type = "battery_load_median"
    sensor._get_actual_load_value = lambda: None

    await sensor._update_sampling_data(datetime.now())
    assert sensor._sampling_data == []


@pytest.mark.asyncio
async def test_check_hourly_end_skips_outside_window():
    sensor = _make_sensor("hourly_test")
    sensor._sensor_type = "hourly_test"
    sensor._calculate_hourly_energy = lambda: 1.0
    sensor._save_statistics_data = lambda: None

    now = datetime.now().replace(minute=10, second=0, microsecond=0)
    await sensor._check_hourly_end(now)
    assert sensor._current_hourly_value is None


@pytest.mark.asyncio
async def test_check_hourly_end_skip_same_hour():
    sensor = _make_sensor("hourly_test")
    sensor._sensor_type = "hourly_test"

    async def _calc():
        return 2.0

    sensor._calculate_hourly_energy = _calc
    sensor._save_statistics_data = lambda: None
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    sensor._last_hour_reset = now

    await sensor._check_hourly_end(now)
    assert sensor._current_hourly_value is None


@pytest.mark.asyncio
async def test_calculate_hourly_energy_unknown_unit_energy_diff():
    source_state = SimpleNamespace(
        state="1500",
        attributes={"unit_of_measurement": "unknown"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "energy_diff"}
    sensor._source_entity_id = "sensor.oig_123_source"
    sensor._last_source_value = 500.0
    result = await sensor._calculate_hourly_energy()
    assert result == 1.0


@pytest.mark.asyncio
async def test_calculate_hourly_energy_power_integral_kw():
    source_state = SimpleNamespace(
        state="2.5",
        attributes={"unit_of_measurement": "kW"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "power_integral"}
    sensor._source_entity_id = "sensor.oig_123_source"
    result = await sensor._calculate_hourly_energy()
    assert result == 2.5


@pytest.mark.asyncio
async def test_calculate_hourly_energy_initial_none():
    source_state = SimpleNamespace(
        state="10",
        attributes={"unit_of_measurement": "kWh"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "energy_diff"}
    sensor._source_entity_id = "sensor.oig_123_source"
    sensor._last_source_value = None
    result = await sensor._calculate_hourly_energy()
    assert result is None
    assert sensor._last_source_value == 10.0


def test_calculate_statistics_value_interval_empty():
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._time_range = (6, 8)
    sensor._interval_data = {}
    assert sensor._calculate_statistics_value() is None


def test_extra_state_attributes_battery_load_median():
    sensor = _make_sensor()
    now = datetime.now()
    sensor._sampling_data = [(now - timedelta(minutes=1), 1.0)]
    attrs = sensor.extra_state_attributes
    assert attrs["sampling_points"] == 1
    assert "last_sample" in attrs


def test_extra_state_attributes_interval():
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._time_range = (6, 8)
    sensor._interval_data = {"2025-01-01": [1.0, 2.0]}
    attrs = sensor.extra_state_attributes
    assert attrs["total_days"] == 1
    assert attrs["total_values"] == 2


def test_available_hourly_unavailable_state():
    source_state = SimpleNamespace(state="unavailable", attributes={})
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._source_entity_id = "sensor.oig_123_source"
    assert sensor.available is False


def test_create_hourly_attributes_error():
    attrs = create_hourly_attributes("sensor", [], current_time="bad")
    assert attrs["data_points"] == 0
    assert "error" in attrs


def test_safe_datetime_compare_error():
    assert safe_datetime_compare("bad", datetime.now()) is False


@pytest.mark.asyncio
async def test_calculate_interval_statistics_from_history_no_data(monkeypatch):
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._time_range = (6, 8)
    sensor._max_age_days = 1

    def _history_period(_hass, _start, _end, entity_id):
        return {entity_id: []}

    async def _exec(func, *args):
        return func(*args)

    sensor.hass = SimpleNamespace(async_add_executor_job=_exec)
    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history_period,
    )

    value = await sensor._calculate_interval_statistics_from_history()
    assert value is None
