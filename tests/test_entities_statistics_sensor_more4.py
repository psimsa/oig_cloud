from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.statistics_sensor import (
    OigCloudStatisticsSensor,
    StatisticsProcessor,
    create_hourly_attributes,
    ensure_timezone_aware,
)


class DummyCoordinator:
    def __init__(self, data=None, options=None):
        self.data = data
        if options is None:
            options = {}
        self.config_entry = SimpleNamespace(options=SimpleNamespace(**options))

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyStore:
    data = None
    saved = None

    def __init__(self, *_args, **_kwargs):
        pass

    async def async_load(self):
        return DummyStore.data

    async def async_save(self, data):
        DummyStore.saved = data


def _make_sensor(sensor_type="battery_load_median", data=None, options=None):
    coordinator = DummyCoordinator(data=data, options=options or {})
    device_info = {"identifiers": {("oig_cloud", "123")}}
    sensor = OigCloudStatisticsSensor(coordinator, sensor_type, device_info)
    sensor.hass = SimpleNamespace(states=DummyStates({}))
    sensor.async_write_ha_state = lambda: None
    return sensor


@pytest.mark.asyncio
async def test_load_statistics_data_success(monkeypatch):
    sensor = _make_sensor()
    now = datetime.now()
    DummyStore.data = {
        "sampling_data": [[now.isoformat(), 1.5]],
        "interval_data": {"2025-01-01": [2.0]},
        "hourly_data": [{"datetime": now.isoformat(), "value": 0.5}],
        "current_hourly_value": 3.0,
        "last_source_value": 2.0,
        "last_hour_reset": now.isoformat(),
    }
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", DummyStore
    )

    await sensor._load_statistics_data()
    assert len(sensor._sampling_data) == 1
    assert sensor._sampling_data[0][0].tzinfo is None
    assert sensor._hourly_data
    assert sensor._current_hourly_value == 3.0
    assert sensor._last_source_value == 2.0
    assert sensor._last_hour_reset is not None


@pytest.mark.asyncio
async def test_save_statistics_data_tzaware(monkeypatch):
    sensor = _make_sensor()
    now = datetime.now(timezone.utc)
    sensor._sampling_data = [(now, 1.0)]
    sensor._hourly_data = [{"datetime": now.isoformat(), "value": 2.0}]
    sensor._last_hour_reset = now
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.statistics_sensor.Store", DummyStore
    )

    await sensor._save_statistics_data()
    assert DummyStore.saved is not None
    assert "+00:00" not in DummyStore.saved["sampling_data"][0][0]
    assert "+00:00" not in DummyStore.saved["hourly_data"][0]["datetime"]


@pytest.mark.asyncio
async def test_cleanup_old_data(monkeypatch):
    sensor = _make_sensor()
    now = datetime.now()
    sensor._sampling_minutes = 1
    sensor._sampling_data = [(now - timedelta(minutes=10), 1.0), (now, 2.0)]
    sensor._interval_data = {"2020-01-01": [1.0], now.strftime("%Y-%m-%d"): [2.0]}
    sensor._max_age_days = 1
    sensor._hourly_data = [
        {"datetime": (now - timedelta(hours=100)).isoformat(), "value": 1.0},
        {"datetime": now.isoformat(), "value": 2.0},
    ]

    await sensor._cleanup_old_data()
    assert sensor._sampling_data == [(sensor._sampling_data[0][0], 2.0)]
    assert "2020-01-01" not in sensor._interval_data
    assert len(sensor._hourly_data) == 1


@pytest.mark.asyncio
async def test_update_sampling_data_triggers_save():
    sensor = _make_sensor()
    sensor._sensor_type = "battery_load_median"
    sensor._sampling_data = [(datetime.now(), 1.0)] * 9
    sensor._get_actual_load_value = lambda: 5.0

    saved = {"called": False}

    async def _save():
        saved["called"] = True

    sensor._save_statistics_data = _save
    await sensor._update_sampling_data(datetime.now())
    assert saved["called"] is True


@pytest.mark.asyncio
async def test_check_hourly_end_updates_hour(monkeypatch):
    sensor = _make_sensor("hourly_test")
    sensor._sensor_type = "hourly_test"

    async def _calc():
        return 1.25

    sensor._calculate_hourly_energy = _calc
    sensor._save_statistics_data = lambda: None
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    await sensor._check_hourly_end(now)
    assert sensor._current_hourly_value == 1.25
    assert sensor._hourly_data
    assert sensor._last_hour_reset is not None


@pytest.mark.asyncio
async def test_daily_statistics_update_success():
    sensor = _make_sensor("interval_test")
    sensor._time_range = (6, 8)
    sensor._interval_data = {"2025-01-01": [1.0]}

    async def _calc():
        return 5.5

    sensor._calculate_interval_statistics_from_history = _calc
    sensor._save_statistics_data = lambda: None
    await sensor._daily_statistics_update(datetime.now())
    assert list(sensor._interval_data.values())[-1] == [5.5]


@pytest.mark.asyncio
async def test_calculate_interval_statistics_overnight(monkeypatch):
    sensor = _make_sensor("interval_test")
    sensor._time_range = (22, 6)
    sensor._max_age_days = 1

    class DummyState:
        def __init__(self, state, last_updated):
            self.state = state
            self.last_updated = last_updated

    end_time = datetime.now()
    late = end_time.replace(hour=23, minute=0, second=0, microsecond=0)
    early = end_time.replace(hour=2, minute=0, second=0, microsecond=0)

    def _history(_hass, _start, _end, entity_id):
        return {entity_id: [DummyState("10", late), DummyState("20", early)]}

    async def _exec(func, *args):
        return func(*args)

    sensor.hass = SimpleNamespace(async_add_executor_job=_exec)
    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _history,
    )

    result = await sensor._calculate_interval_statistics_from_history()
    assert result == 15.0


def test_state_hourly_without_coordinator_data():
    sensor = _make_sensor("hourly_test", data=None)
    sensor._sensor_type = "hourly_test"
    sensor._current_hourly_value = 2.0
    assert sensor.state == 2.0


def test_available_statistics_disabled():
    sensor = _make_sensor(options={"enable_statistics": False})
    assert sensor.available is False


def test_extra_state_attributes_hourly_totals():
    sensor = _make_sensor("hourly_test")
    sensor._sensor_type = "hourly_test"
    now = datetime.now()
    sensor._hourly_data = [
        {"datetime": now.isoformat(), "value": 1.2},
        {"datetime": (now - timedelta(days=1)).isoformat(), "value": 0.8},
    ]
    attrs = sensor.extra_state_attributes
    assert attrs["today_total"] == 1.2
    assert attrs["yesterday_total"] == 0.8


def test_extra_state_attributes_interval_latest():
    sensor = _make_sensor("interval_test")
    sensor._time_range = (6, 8)
    sensor._interval_data = {"2024-12-01": [1.0], "2025-01-02": [2.0]}
    attrs = sensor.extra_state_attributes
    assert attrs["latest_data"] == "2025-01-02"


def test_ensure_timezone_aware_for_naive():
    dt = datetime.now().replace(tzinfo=None)
    assert ensure_timezone_aware(dt).tzinfo is not None


def test_create_hourly_attributes_with_timestamp():
    now = datetime.now()
    attrs = create_hourly_attributes(
        "sensor",
        [{"timestamp": now}],
        current_time=now,
    )
    assert attrs["data_points"] == 1
    assert "latest_data_time" in attrs


def test_statistics_processor_process_hourly_data():
    processor = StatisticsProcessor(SimpleNamespace())
    now = datetime.now().isoformat()
    result = processor.process_hourly_data(
        "sensor",
        [{"timestamp": now, "value": 5.0}],
    )
    assert result["value"] == 5.0
    assert "last_updated" in result["attributes"]
