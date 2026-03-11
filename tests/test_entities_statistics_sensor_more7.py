from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import statistics_sensor as module


class DummyCoordinator:
    def __init__(self):
        self.data = {}
        self.config_entry = SimpleNamespace(options=SimpleNamespace(enable_statistics=True))


class DummyStore:
    def __init__(self, data=None):
        self._data = data
        self.saved = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self.saved = data


def _make_sensor(monkeypatch, sensor_type="battery_load_median", sensor_config=None):
    sensor_config = sensor_config or {
        "name_cs": "Stat",
        "unit": "W",
        "device_class": "madeup",
        "state_class": "otherbad",
    }
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensor_types.SENSOR_TYPES",
        {sensor_type: sensor_config},
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no box")),
    )
    coord = DummyCoordinator()
    sensor = module.OigCloudStatisticsSensor(coord, sensor_type, {"identifiers": set()})
    sensor.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))
    return sensor


@pytest.mark.asyncio
async def test_load_statistics_data_invalid_records(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    store = DummyStore(
        {
            "sampling_data": [["bad", 1.0]],
            "hourly_data": [{"foo": "bar"}],
            "current_hourly_value": 1.2,
            "last_source_value": 3.0,
            "last_hour_reset": "bad",
        }
    )
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    await sensor._load_statistics_data()
    assert sensor._current_hourly_value == 1.2


@pytest.mark.asyncio
async def test_save_statistics_data_filters_hourly(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    store = DummyStore()
    monkeypatch.setattr(module, "Store", lambda *_a, **_k: store)
    sensor._sampling_data = [(datetime.now(timezone.utc), 1.0)]
    sensor._hourly_data = [{"datetime": "bad", "value": "bad"}]
    await sensor._save_statistics_data()
    assert store.saved is not None


@pytest.mark.asyncio
async def test_cleanup_old_data_invalid_hourly(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    old = datetime.now() - timedelta(days=2)
    sensor._sampling_data = [(old, 1.0)]
    sensor._interval_data = {"2000-01-01": [1.0]}
    sensor._hourly_data = [{"datetime": "bad"}]
    await sensor._cleanup_old_data()


@pytest.mark.asyncio
async def test_daily_statistics_update_no_value(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        sensor_type="interval",
        sensor_config={"name_cs": "X", "time_range": (6, 8)},
    )
    sensor._interval_data = {}

    async def _calc():
        return None

    monkeypatch.setattr(sensor, "_calculate_interval_statistics_from_history", _calc)
    await sensor._daily_statistics_update(None)
    assert sensor._interval_data == {}


@pytest.mark.asyncio
async def test_calculate_interval_statistics_no_data(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        sensor_type="interval",
        sensor_config={"name_cs": "X", "time_range": (6, 8), "max_age_days": 1},
    )
    sensor.hass = SimpleNamespace(
        async_add_executor_job=lambda *_a, **_k: {"sensor.oig_unknown_actual_aco_p": []}
    )
    assert await sensor._calculate_interval_statistics_from_history() is None


def test_get_actual_load_value_invalid_float(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor.hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _eid: SimpleNamespace(state="bad")
        )
    )
    assert sensor._get_actual_load_value() is None


@pytest.mark.asyncio
async def test_calculate_hourly_energy_unknown_unit(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        sensor_type="hourly_energy",
        sensor_config={"name_cs": "X", "source_sensor": "src", "hourly_data_type": "power_integral"},
    )
    sensor._source_entity_id = "sensor.oig_unknown_src"
    sensor.hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _eid: SimpleNamespace(
                state="100", attributes={"unit_of_measurement": "invalid"}
            )
        )
    )
    assert await sensor._calculate_hourly_energy() == 0.1


def test_extra_state_attributes_hourly_invalid_record(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        sensor_type="hourly_energy",
        sensor_config={"name_cs": "X", "source_sensor": "src", "hourly_data_type": "energy_diff"},
    )
    sensor._hourly_data = [{"datetime": "bad"}]
    attrs = sensor.extra_state_attributes
    assert "hourly_data_points" in attrs


def test_create_hourly_attributes_error(monkeypatch):
    monkeypatch.setattr(module, "ensure_timezone_aware", lambda _dt: (_ for _ in ()).throw(RuntimeError("bad")))
    result = module.create_hourly_attributes("s", [], None)
    assert "error" in result


def test_statistics_processor_error(monkeypatch):
    processor = module.StatisticsProcessor(SimpleNamespace())

    def _boom(*_a, **_k):
        raise RuntimeError("bad")

    monkeypatch.setattr(module, "create_hourly_attributes", _boom)
    result = processor.process_hourly_data("s", [{"timestamp": "bad"}])
    assert "error" in result["attributes"]
