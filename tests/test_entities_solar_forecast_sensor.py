from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import solar_forecast_sensor as sensor_module

from custom_components.oig_cloud.entities.solar_forecast_sensor import (
    OigCloudSolarForecastSensor,
    _parse_forecast_hour,
)


class DummyCoordinator:
    def __init__(self):
        self.forced_box_id = "123"

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options


def _make_sensor(options):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry(options)
    return OigCloudSolarForecastSensor(coordinator, "solar_forecast", entry, {})


def _make_sensor_type(options, sensor_type):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry(options)
    return OigCloudSolarForecastSensor(coordinator, sensor_type, entry, {})


def test_parse_forecast_hour():
    assert _parse_forecast_hour("2025-01-01T12:00:00") is not None
    assert _parse_forecast_hour("bad") is None


def test_should_fetch_data_daily_optimized(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily_optimized"})
    sensor._last_api_call = 1000.0

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 15000.0,
    )

    assert sensor._should_fetch_data() is True


def test_should_fetch_data_manual(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "manual"})
    sensor._last_api_call = 1000.0

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 99999.0,
    )

    assert sensor._should_fetch_data() is False


def test_get_update_interval():
    sensor = _make_sensor({})
    assert sensor._get_update_interval("hourly") is not None
    assert sensor._get_update_interval("manual") is None


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


@pytest.mark.asyncio
async def test_load_persistent_data(monkeypatch):
    sensor = _make_sensor({})
    sensor.hass = SimpleNamespace()
    DummyStore.data = {"last_api_call": 1234, "forecast_data": {"a": 1}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.Store", DummyStore
    )

    await sensor._load_persistent_data()

    assert sensor._last_api_call == 1234.0
    assert sensor._last_forecast_data == {"a": 1}


@pytest.mark.asyncio
async def test_save_persistent_data(monkeypatch):
    sensor = _make_sensor({})
    sensor.hass = SimpleNamespace()
    sensor._last_api_call = 4321.0
    sensor._last_forecast_data = {"b": 2}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.Store", DummyStore
    )

    await sensor._save_persistent_data()

    assert DummyStore.saved["last_api_call"] == 4321.0
    assert DummyStore.saved["forecast_data"] == {"b": 2}


def test_should_fetch_data_modes(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily"})
    sensor._last_api_call = 1000.0
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 80000.0,
    )
    assert sensor._should_fetch_data() is True

    sensor._config_entry.options["solar_forecast_mode"] = "every_4h"
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 100.0,
    )
    assert sensor._should_fetch_data() is False


def test_convert_to_hourly_keeps_max():
    sensor = _make_sensor({})
    watts_data = {
        "2025-01-01T10:15:00+00:00": 100.0,
        "2025-01-01T10:45:00+00:00": 150.0,
        "2025-01-01T11:00:00+00:00": 90.0,
    }
    hourly = sensor._convert_to_hourly(watts_data)
    key_10 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc).isoformat()
    key_11 = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc).isoformat()

    assert hourly[key_10] == 150.0
    assert hourly[key_11] == 90.0


def test_process_forecast_data_combines_strings():
    sensor = _make_sensor({})
    data_string1 = {
        "result": {
            "watts": {
                "2025-01-01T10:00:00+00:00": 100.0,
            },
            "watt_hours_day": {"2025-01-01": 1000.0},
        }
    }
    data_string2 = {
        "result": {
            "watts": {
                "2025-01-01T10:30:00+00:00": 200.0,
            },
            "watt_hours_day": {"2025-01-01": 500.0},
        }
    }
    result = sensor._process_forecast_data(data_string1, data_string2)

    assert result["string1_today_kwh"] == 1.0
    assert result["string2_today_kwh"] == 0.5
    assert result["total_today_kwh"] == 1.5
    assert result["total_hourly"]


@pytest.mark.asyncio
async def test_periodic_update_daily_optimized_triggers(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily_optimized"})
    sensor._last_api_call = 0
    sensor._min_api_interval = 0

    async_fetch = pytest.raises  # placeholder

    async def _fetch():
        sensor._called = True

    sensor._called = False
    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _fetch)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 20000.0,
    )

    now = datetime(2025, 1, 1, 6, 0)
    await sensor._periodic_update(now)

    assert sensor._called is True


@pytest.mark.asyncio
async def test_periodic_update_daily_optimized_skips_recent(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily_optimized"})
    sensor._last_api_call = 1000.0
    sensor._min_api_interval = 0
    sensor._called = False

    async def _fetch():
        sensor._called = True

    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _fetch)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 3600.0,
    )

    now = datetime(2025, 1, 1, 6, 0)
    await sensor._periodic_update(now)

    assert sensor._called is False


@pytest.mark.asyncio
async def test_periodic_update_daily_calls(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily"})
    sensor._min_api_interval = 0
    sensor._called = False

    async def _fetch():
        sensor._called = True

    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _fetch)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 20000.0,
    )

    now = datetime(2025, 1, 1, 6, 0)
    await sensor._periodic_update(now)

    assert sensor._called is True


@pytest.mark.asyncio
async def test_async_fetch_forecast_data_rate_limit(monkeypatch):
    sensor = _make_sensor({})
    sensor._min_api_interval = 300
    sensor._last_api_call = 1000.0
    sensor._processed = False

    async def _save():
        sensor._saved = True

    monkeypatch.setattr(sensor, "_save_persistent_data", _save)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1005.0,
    )

    await sensor.async_fetch_forecast_data()

    assert sensor._last_api_call == 1000.0


@pytest.mark.asyncio
async def test_async_fetch_forecast_data_string1_only(monkeypatch):
    sensor = _make_sensor(
        {
            "solar_forecast_string1_enabled": True,
            "solar_forecast_string2_enabled": False,
            "solar_forecast_latitude": 50.0,
            "solar_forecast_longitude": 14.0,
        }
    )
    sensor._min_api_interval = 0

    class DummyResponse:
        def __init__(self, status, payload):
            self.status = status
            self._payload = payload

        async def json(self):
            return self._payload

        async def text(self):
            return "ok"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummySession:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, *_args, **_kwargs):
            return self._response

    dummy_payload = {"result": {"watts": {}, "watt_hours_day": {}}}
    monkeypatch.setattr(
        sensor_module.aiohttp,
        "ClientSession",
        lambda: DummySession(DummyResponse(200, dummy_payload)),
    )

    async def _save():
        sensor._saved = True

    async def _broadcast():
        sensor._broadcasted = True

    monkeypatch.setattr(sensor, "_save_persistent_data", _save)
    monkeypatch.setattr(sensor, "_broadcast_forecast_data", _broadcast)
    monkeypatch.setattr(sensor, "_process_forecast_data", lambda *_a: {"ok": True})
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 20000.0,
    )
    sensor.async_write_ha_state = lambda: None

    await sensor.async_fetch_forecast_data()

    assert sensor._last_forecast_data == {"ok": True}
    assert sensor.coordinator.solar_forecast_data == {"ok": True}


@pytest.mark.asyncio
async def test_broadcast_forecast_data_triggers_updates(monkeypatch):
    sensor = _make_sensor({})
    sensor.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda _eid: True),
        services=SimpleNamespace(async_call=lambda *_a, **_k: None),
        async_create_task=lambda coro: coro,
    )

    class DummyEntityEntry:
        def __init__(self, entity_id, device_id):
            self.entity_id = entity_id
            self.device_id = device_id

    entity_entries = [
        DummyEntityEntry("sensor.x_solar_forecast_string1", "dev1"),
        DummyEntityEntry("sensor.x_solar_forecast_string2", "dev1"),
    ]

    class DummyEntityRegistry:
        def async_get(self, _entity_id):
            return DummyEntityEntry("sensor.x_solar_forecast", "dev1")

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_get",
        lambda _hass: DummyEntityRegistry(),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_device",
        lambda _reg, _device_id: entity_entries,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.device_registry.async_get",
        lambda _hass: SimpleNamespace(),
    )

    await sensor._broadcast_forecast_data()


@pytest.mark.asyncio
async def test_async_added_to_hass_schedules_fetch(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "daily"})

    class DummyHass:
        def __init__(self):
            self.created = []

        def async_create_task(self, coro):
            self.created.append(coro)
            coro.close()

    sensor.hass = DummyHass()

    async def _load():
        sensor._last_forecast_data = None
        sensor._last_api_call = 0

    async def _delayed():
        return None

    monkeypatch.setattr(sensor, "_load_persistent_data", _load)
    monkeypatch.setattr(sensor, "_should_fetch_data", lambda: True)
    monkeypatch.setattr(sensor, "_delayed_initial_fetch", _delayed)
    monkeypatch.setattr(
        sensor_module,
        "async_track_time_interval",
        lambda *_args, **_kwargs: "remover",
    )

    await sensor.async_added_to_hass()

    assert sensor._update_interval_remover == "remover"
    assert sensor.hass.created


@pytest.mark.asyncio
async def test_async_added_to_hass_uses_cached_data(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "manual"})
    coordinator = sensor.coordinator

    class DummyHass:
        def __init__(self):
            self.created = []

        def async_create_task(self, coro):
            self.created.append(coro)
            coro.close()

    sensor.hass = DummyHass()

    async def _load():
        sensor._last_forecast_data = {"k": 1}
        sensor._last_api_call = 1234.0

    monkeypatch.setattr(sensor, "_load_persistent_data", _load)
    monkeypatch.setattr(sensor, "_should_fetch_data", lambda: False)

    await sensor.async_added_to_hass()

    assert coordinator.solar_forecast_data == {"k": 1}
    assert not sensor.hass.created


def test_state_uses_coordinator_and_availability(monkeypatch):
    sensor = _make_sensor_type({"enable_solar_forecast": False}, "solar_forecast")
    sensor.coordinator.solar_forecast_data = {"total_today_kwh": 4.2}
    assert sensor.state is None

    sensor = _make_sensor_type({"enable_solar_forecast": True}, "solar_forecast")
    sensor.coordinator.solar_forecast_data = {"total_today_kwh": 4.2}
    assert sensor.state == 4.2


def test_state_and_attributes_all_sensors(monkeypatch):
    fixed_now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    today_key = fixed_now.isoformat()
    tomorrow_key = (fixed_now + timedelta(days=1)).isoformat()

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz:
                return fixed_now.astimezone(tz)
            return fixed_now

        @classmethod
        def fromtimestamp(cls, ts, tz=None):
            return datetime.fromtimestamp(ts, tz)

        @classmethod
        def fromisoformat(cls, date_string):
            return datetime.fromisoformat(date_string)

    monkeypatch.setattr(sensor_module, "datetime", FixedDatetime)

    data = {
        "response_time": "2025-01-01T09:00:00",
        "total_today_kwh": 5.5,
        "string1_today_kwh": 3.0,
        "string2_today_kwh": 2.5,
        "total_hourly": {today_key: 1000, tomorrow_key: 2000},
        "string1_hourly": {today_key: 600, tomorrow_key: 900},
        "string2_hourly": {today_key: 400, tomorrow_key: 1100},
    }

    sensor = _make_sensor_type({"enable_solar_forecast": True}, "solar_forecast")
    sensor._last_forecast_data = data
    assert sensor.state == 5.5
    attrs = sensor.extra_state_attributes
    assert attrs["today_total_kwh"] == 5.5
    assert attrs["current_hour_kw"] == 1.0
    assert attrs["today_total_sum_kw"] == 1.0
    assert attrs["tomorrow_total_sum_kw"] == 2.0

    sensor = _make_sensor_type({"enable_solar_forecast": True}, "solar_forecast_string1")
    sensor._last_forecast_data = data
    assert sensor.state == 3.0
    attrs = sensor.extra_state_attributes
    assert attrs["today_kwh"] == 3.0
    assert attrs["today_sum_kw"] == 0.6

    sensor = _make_sensor_type({"enable_solar_forecast": True}, "solar_forecast_string2")
    sensor._last_forecast_data = data
    assert sensor.state == 2.5
    attrs = sensor.extra_state_attributes
    assert attrs["today_kwh"] == 2.5
    assert attrs["today_sum_kw"] == 0.4


@pytest.mark.asyncio
async def test_periodic_update_every_4h_and_hourly(monkeypatch):
    sensor = _make_sensor({"solar_forecast_mode": "every_4h"})
    sensor._min_api_interval = 0
    sensor._last_api_call = 1000.0
    sensor._called = False

    async def _fetch():
        sensor._called = True

    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _fetch)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 15000.0,
    )

    await sensor._periodic_update(datetime(2025, 1, 1, 8, 0))
    assert sensor._called is True

    sensor = _make_sensor({"solar_forecast_mode": "hourly"})
    sensor._min_api_interval = 0
    sensor._last_api_call = 1000.0
    sensor._called = False

    async def _fetch_hourly():
        sensor._called = True

    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _fetch_hourly)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.solar_forecast_sensor.time.time",
        lambda: 1000.0 + 4000.0,
    )

    await sensor._periodic_update(datetime(2025, 1, 1, 8, 0))
    assert sensor._called is True


@pytest.mark.asyncio
async def test_manual_update_handles_failure(monkeypatch):
    sensor = _make_sensor({})

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "async_fetch_forecast_data", _raise)

    assert await sensor.async_manual_update() is False
