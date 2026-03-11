from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.entities.statistics_sensor import (
    OigCloudStatisticsSensor,
    StatisticsProcessor,
    create_hourly_attributes,
    ensure_timezone_aware,
    safe_datetime_compare,
)


def test_ensure_timezone_aware():
    naive = datetime(2025, 1, 1, 12, 0)
    aware = ensure_timezone_aware(naive)
    assert aware.tzinfo is not None


def test_safe_datetime_compare():
    dt1 = datetime(2025, 1, 1, 10, 0)
    dt2 = datetime(2025, 1, 1, 11, 0)
    assert safe_datetime_compare(dt1, dt2) is True


def test_create_hourly_attributes():
    now = dt_util.now()
    data_points = [
        {"timestamp": now - timedelta(hours=1), "value": 1.0},
        {"time": now, "value": 2.0},
    ]
    attrs = create_hourly_attributes("sensor", data_points, now)
    assert attrs["data_points"] == 2
    assert "last_updated" in attrs
    assert "latest_data_time" in attrs


def test_statistics_processor_process_hourly_data():
    processor = StatisticsProcessor(hass=None)
    raw_data = [
        {"timestamp": "2025-01-01T10:00:00", "value": 1.0},
        {"timestamp": "2025-01-01T11:00:00", "value": 2.5},
    ]
    result = processor.process_hourly_data("sensor", raw_data, value_key="value")
    assert result["value"] == 2.5
    assert result["attributes"]["data_points"] == 2


class DummyCoordinator:
    def __init__(self):
        self.data = {"123": {}}

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyStore:
    data = None
    saved = None

    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key

    async def async_load(self):
        return DummyStore.data

    async def async_save(self, data):
        DummyStore.saved = data


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
    elif not hasattr(options, "get"):
        options = DummyOptions(options.__dict__)
    coordinator.config_entry = SimpleNamespace(options=options)
    device_info = {"identifiers": {("oig_cloud", "123")}}
    sensor = OigCloudStatisticsSensor(coordinator, sensor_type, device_info)
    sensor.hass = SimpleNamespace(states=DummyStates(state_map or {}))
    sensor.async_write_ha_state = lambda: None
    return sensor


@pytest.mark.asyncio
async def test_load_statistics_data(monkeypatch):
    sensor = _make_sensor()
    sensor._sampling_data = []
    sensor._interval_data = {}
    sensor._hourly_data = []

    now = datetime.now()
    today_key = now.strftime("%Y-%m-%d")
    DummyStore.data = {
        "sampling_data": [[now.isoformat(), 1.5]],
        "interval_data": {today_key: [1.0, 2.0]},
        "hourly_data": [
            {"datetime": now.isoformat(), "value": 0.5},
            {"bad": "record"},
        ],
        "current_hourly_value": 0.7,
        "last_source_value": 1.1,
        "last_hour_reset": now.isoformat(),
    }

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", DummyStore
    )

    await sensor._load_statistics_data()

    assert sensor._sampling_data
    assert sensor._interval_data[today_key] == [1.0, 2.0]
    assert len(sensor._hourly_data) == 1
    assert sensor._current_hourly_value == 0.7


@pytest.mark.asyncio
async def test_save_statistics_data(monkeypatch):
    sensor = _make_sensor()
    sensor._sampling_data = [
        (datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc), 2.0)
    ]
    sensor._hourly_data = [
        {"datetime": datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc).isoformat(), "value": 1.2},
        {"datetime": "bad", "value": "bad"},
    ]
    sensor._interval_data = {"2025-01-01": [1.0]}
    sensor._current_hourly_value = 1.5
    sensor._last_source_value = 2.1
    sensor._last_hour_reset = datetime(2025, 1, 1, 11, 0)

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", DummyStore
    )

    await sensor._save_statistics_data()

    assert DummyStore.saved["sampling_data"][0][1] == 2.0
    assert DummyStore.saved["interval_data"]["2025-01-01"] == [1.0]
    assert DummyStore.saved["current_hourly_value"] == 1.5


@pytest.mark.asyncio
async def test_cleanup_old_data():
    sensor = _make_sensor()
    sensor._sampling_minutes = 1
    sensor._sampling_data = [
        (datetime.now() - timedelta(minutes=5), 1.0),
        (datetime.now(), 2.0),
    ]
    sensor._interval_data = {
        (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"): [1.0],
        datetime.now().strftime("%Y-%m-%d"): [2.0],
    }
    sensor._hourly_data = [
        {"datetime": (datetime.now() - timedelta(hours=60)).isoformat(), "value": 1.0},
        {"datetime": datetime.now().isoformat(), "value": 2.0},
    ]
    sensor._max_age_days = 30

    await sensor._cleanup_old_data()

    assert len(sensor._sampling_data) == 1
    assert len(sensor._interval_data) == 1
    assert len(sensor._hourly_data) == 1


@pytest.mark.asyncio
async def test_update_sampling_data_triggers_save(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "battery_load_median"
    sensor._max_sampling_size = 10
    sensor._sampling_data = [(datetime.now(), 1.0) for _ in range(9)]

    async def _save():
        sensor._saved = True

    sensor._saved = False
    sensor._get_actual_load_value = lambda: 5.0
    sensor._save_statistics_data = _save

    await sensor._update_sampling_data(datetime.now())

    assert sensor._saved is True
    assert sensor._sampling_data


@pytest.mark.asyncio
async def test_check_hourly_end_updates(monkeypatch):
    sensor = _make_sensor("hourly_test")
    sensor._sensor_type = "hourly_test"
    sensor._current_hourly_value = None
    sensor._last_hour_reset = None

    async def _calc():
        return 1.234

    async def _save():
        sensor._saved = True

    sensor._saved = False
    sensor._calculate_hourly_energy = _calc
    sensor._save_statistics_data = _save

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    await sensor._check_hourly_end(now)

    assert sensor._saved is True
    assert sensor._current_hourly_value == 1.234


def test_available_disabled_statistics():
    options = {"enable_statistics": False}
    sensor = _make_sensor(options=options)
    sensor._sampling_data = [(datetime.now(), 1.0)]
    assert sensor.available is False


def test_available_hourly_with_source_entity():
    source_state = SimpleNamespace(
        state="1.0",
        attributes={"unit_of_measurement": "kWh"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._source_entity_id = "sensor.oig_123_source"
    assert sensor.available is True


@pytest.mark.asyncio
async def test_calculate_hourly_energy_diff_kwh():
    source_state = SimpleNamespace(
        state="10.0",
        attributes={"unit_of_measurement": "kWh"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "energy_diff"}
    sensor._source_entity_id = "sensor.oig_123_source"
    sensor._last_source_value = 5.0
    result = await sensor._calculate_hourly_energy()
    assert result == 5.0


@pytest.mark.asyncio
async def test_calculate_hourly_energy_diff_wh():
    source_state = SimpleNamespace(
        state="2000",
        attributes={"unit_of_measurement": "Wh"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "energy_diff"}
    sensor._source_entity_id = "sensor.oig_123_source"
    sensor._last_source_value = 1000.0
    result = await sensor._calculate_hourly_energy()
    assert result == 1.0


@pytest.mark.asyncio
async def test_calculate_hourly_energy_power_integral_w():
    source_state = SimpleNamespace(
        state="1200",
        attributes={"unit_of_measurement": "W"},
        last_updated=datetime.now(),
        last_changed=datetime.now(),
    )
    sensor = _make_sensor(
        sensor_type="hourly_test", state_map={"sensor.oig_123_source": source_state}
    )
    sensor._sensor_config = {"hourly_data_type": "power_integral"}
    sensor._source_entity_id = "sensor.oig_123_source"
    result = await sensor._calculate_hourly_energy()
    assert result == 1.2


def test_calculate_statistics_value_interval_median():
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._interval_data = {"2025-01-01": [1.0, 2.0], "2025-01-02": [3.0]}
    sensor._time_range = (6, 8)
    assert sensor._calculate_statistics_value() == 2.0


def test_calculate_statistics_value_uses_all_samples_when_stale():
    sensor = _make_sensor(sensor_type="battery_load_median")
    sensor._sampling_minutes = 5
    sensor._sampling_data = [
        (datetime.now() - timedelta(minutes=30), 1.0),
        (datetime.now() - timedelta(minutes=20), 3.0),
    ]
    assert sensor._calculate_statistics_value() == 2.0


def test_extra_state_attributes_hourly_totals():
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    today = now.replace(hour=9, minute=0, second=0, microsecond=0)
    sensor = _make_sensor(sensor_type="hourly_test")
    sensor._hourly_data = [
        {"datetime": yesterday.isoformat(), "value": 1.5},
        {"datetime": today.isoformat(), "value": 2.0},
    ]
    attrs = sensor.extra_state_attributes
    assert attrs["today_total"] == 2.0
    assert attrs["yesterday_total"] == 1.5
    assert sensor._hourly_data


def test_get_actual_load_value():
    state = SimpleNamespace(state="123", attributes={})
    hass = SimpleNamespace(states=DummyStates({"sensor.oig_123_actual_aco_p": state}))
    sensor = _make_sensor()
    sensor.hass = hass

    assert sensor._get_actual_load_value() == 123.0


@pytest.mark.asyncio
async def test_daily_statistics_update_saves(monkeypatch):
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._time_range = (6, 8)
    sensor._interval_data = {}
    sensor._max_age_days = 3
    sensor.async_write_ha_state = lambda: None

    async def _calc():
        return 5.5

    async def _save():
        sensor._saved = True

    sensor._saved = False
    monkeypatch.setattr(sensor, "_calculate_interval_statistics_from_history", _calc)
    monkeypatch.setattr(sensor, "_save_statistics_data", _save)

    await sensor._daily_statistics_update(None)

    assert sensor._saved is True
    assert sensor._interval_data


@pytest.mark.asyncio
async def test_calculate_interval_statistics_from_history_cross_midnight(monkeypatch):
    sensor = _make_sensor(sensor_type="interval_test")
    sensor._time_range = (22, 6)
    sensor._day_type = "weekday"
    sensor._max_age_days = 2

    class DummyState:
        def __init__(self, state, last_updated):
            self.state = state
            self.last_updated = last_updated

    fixed_now = datetime(2025, 1, 3, 12, 0)

    class FixedDatetime(datetime):
        min = datetime.min

        @classmethod
        def now(cls):
            return fixed_now

        @classmethod
        def combine(cls, date, time_obj):
            return datetime.combine(date, time_obj)

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.datetime", FixedDatetime
    )

    def _history_period(_hass, _start, _end, entity_id):
        day1 = datetime(2025, 1, 2, 23, 0)
        day2 = datetime(2025, 1, 3, 1, 0)
        day2_late = datetime(2025, 1, 3, 23, 0)
        return {
            entity_id: [
                DummyState("10", day1),
                DummyState("20", day2),
                DummyState("30", day2_late),
            ]
        }

    async def _exec(func, *args):
        return func(*args)

    sensor.hass = SimpleNamespace(async_add_executor_job=_exec)
    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history_period,
    )

    value = await sensor._calculate_interval_statistics_from_history()
    assert value == 17.5


def test_state_hourly_without_coordinator_data():
    sensor = _make_sensor(sensor_type="hourly_test")
    sensor._sensor_type = "hourly_test"
    sensor._coordinator.data = None
    sensor._current_hourly_value = 1.5
    assert sensor.state == 1.5
