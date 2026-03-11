from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.chmu_sensor import OigCloudChmuSensor


class DummyCoordinator:
    def __init__(self, warning_data=None):
        self.forced_box_id = "123"
        self.chmu_warning_data = warning_data
        self.chmu_api = None
        self.last_update_success = True
        self.data = {"123": {}}

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyConfigEntry:
    def __init__(self, options):
        self.options = options


class DummyHass:
    def __init__(self, lat=None, lon=None):
        self.config = SimpleNamespace(latitude=lat, longitude=lon)
        self.tasks = []

    def async_create_task(self, coro):
        coro.close()
        self.tasks.append(coro)
        return coro


def test_get_gps_coordinates_priority():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry(
        {
            "enable_solar_forecast": True,
            "solar_forecast_latitude": 50.1,
            "solar_forecast_longitude": 14.2,
        }
    )
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass(lat=49.0, lon=13.0)

    lat, lon = sensor._get_gps_coordinates()
    assert lat == 50.1
    assert lon == 14.2


def test_get_gps_coordinates_fallback_to_ha():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({"enable_solar_forecast": False})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass(lat=49.0, lon=13.0)

    lat, lon = sensor._get_gps_coordinates()
    assert lat == 49.0
    assert lon == 13.0


def test_compute_severity_global_and_local():
    warning_data = {
        "highest_severity_cz": 3,
        "severity_level": 2,
        "top_local_warning": {"event": "\u017d\u00e1dn\u00e1", "severity": 0},
    }

    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})

    global_sensor = OigCloudChmuSensor(
        coordinator, "chmu_warning_level_global", entry, {}
    )
    global_sensor.hass = DummyHass()
    assert global_sensor._compute_severity() == 3

    local_sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    local_sensor.hass = DummyHass()
    assert local_sensor._compute_severity() == 0


def test_extra_state_attributes_global_truncates_description():
    long_desc = "x" * 200
    warning_data = {
        "all_warnings_count": 2,
        "all_warnings": [
            {"event": "Test", "severity": 2, "description": long_desc}
        ],
        "last_update": "2025-01-01T00:00:00",
        "highest_severity_cz": 2,
    }

    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level_global", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    assert attrs["warnings_count"] == 2
    assert len(attrs["all_warnings"]) == 1
    assert attrs["all_warnings"][0]["description"].endswith("...")


def test_extra_state_attributes_global_short_description():
    warning_data = {
        "all_warnings_count": 1,
        "all_warnings": [{"event": "Test", "severity": 1, "description": "short"}],
        "last_update": "2025-01-01T00:00:00",
        "highest_severity_cz": 1,
    }
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level_global", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    assert attrs["all_warnings"][0]["description"] == "short"


def test_available_fallback_to_super():
    coordinator = DummyCoordinator()
    coordinator.last_update_success = False
    coordinator.data = {}
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    assert sensor.available is False


def test_compute_severity_no_data():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    assert sensor.native_value == 0


def test_get_gps_coordinates_default():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass(lat=None, lon=None)

    lat, lon = sensor._get_gps_coordinates()
    assert (lat, lon) == (50.0875, 14.4213)


def test_get_warning_data_from_coordinator():
    warning_data = {"severity_level": 1}
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    assert sensor._get_warning_data() == warning_data


@pytest.mark.asyncio
async def test_async_added_to_hass_sets_attribute_when_missing(monkeypatch):
    coordinator = SimpleNamespace(forced_box_id="123")
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = {"severity_level": 1}
    sensor._last_api_call = 100.0

    async def fake_super(_self):
        return None

    async def fake_load(_self):
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.OigCloudSensor.async_added_to_hass",
        fake_super,
    )
    monkeypatch.setattr(OigCloudChmuSensor, "_load_persistent_data", fake_load)
    monkeypatch.setattr(OigCloudChmuSensor, "_should_fetch_data", lambda *_a: False)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )

    await sensor.async_added_to_hass()
    assert hasattr(coordinator, "chmu_warning_data")


def test_available_with_cached_data():
    warning_data = {"severity_level": 1}
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    assert sensor.available is True


def test_extra_state_attributes_no_data():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    attrs = sensor.extra_state_attributes
    assert attrs["warnings_count"] == 0
    assert attrs["source"] == "ČHMÚ CAP Feed"


def test_extra_state_attributes_local_no_top_warning():
    warning_data = {"local_warnings": [], "last_update": "2025-01-01T00:00:00"}
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    assert attrs["event_type"] == "Žádné"
    assert attrs["warnings_count"] == 0


def test_extra_state_attributes_local_with_details():
    warning_data = {
        "top_local_warning": {
            "event": "Silný vítr",
            "severity": "Severe",
            "onset": "2025-01-01T00:00:00",
            "expires": "2025-01-01T12:00:00",
            "eta_hours": 2,
            "description": "x" * 310,
            "instruction": "y" * 310,
            "areas": [{"description": "Praha"}, {"description": "Praha"}],
        },
        "local_warnings": [
            {"event": "Žádná výstraha"},
            {"event": "Silný vítr", "severity": "Severe", "areas": []},
        ],
        "last_update": "2025-01-01T00:00:00",
        "source": "test",
    }
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    assert attrs["warnings_count"] == 1
    assert len(attrs["all_warnings_details"]) == 1
    assert attrs["description"].endswith("...")
    assert attrs["instruction"].endswith("...")


def test_extra_state_attributes_local_regions_limit():
    warning_data = {
        "top_local_warning": {"event": "X", "severity": "Severe", "areas": []},
        "local_warnings": [
            {
                "event": "X",
                "severity": "Severe",
                "areas": [{"description": f"R{i}"} for i in range(10)],
            }
        ],
    }
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    regions = attrs["all_warnings_details"][0]["regions"]
    assert len(regions) == 8


def test_extra_state_attributes_local_regions_exception():
    class BadArea:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    warning_data = {
        "top_local_warning": {"event": "X", "severity": "Severe", "areas": []},
        "local_warnings": [
            {
                "event": "X",
                "severity": "Severe",
                "areas": [BadArea()],
                "description": "d" * 300,
                "instruction": "i" * 300,
            },
        ],
    }
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    attrs = sensor.extra_state_attributes
    assert attrs["all_warnings_details"][0]["regions"] == []


def test_get_severity_distribution():
    warning_data = {
        "all_warnings": [
            {"severity": "Minor"},
            {"severity": "Minor"},
            {"severity": "Severe"},
        ]
    }
    coordinator = DummyCoordinator(warning_data)
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level_global", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data

    dist = sensor._get_severity_distribution()
    assert dist["Minor"] == 2
    assert dist["Severe"] == 1


def test_get_severity_distribution_no_data():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level_global", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = None
    dist = sensor._get_severity_distribution()
    assert dist["Minor"] == 0


def test_icon_thresholds():
    coordinator = DummyCoordinator({"severity_level": 4, "top_local_warning": {"event": "X"}})
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = coordinator.chmu_warning_data
    assert sensor.icon == "mdi:alert-octagon"

    sensor._last_warning_data["severity_level"] = 3
    assert sensor.icon == "mdi:alert"

    sensor._last_warning_data["severity_level"] = 2
    assert sensor.icon == "mdi:alert-circle"

    sensor._last_warning_data["severity_level"] = 1
    assert sensor.icon == "mdi:alert-circle-outline"

    sensor._last_warning_data["severity_level"] = 0
    assert sensor.icon == "mdi:check-circle-outline"


def test_device_info_passthrough():
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    info = {"identifiers": {("oig_cloud", "123")}}
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, info)
    sensor.hass = DummyHass()
    assert sensor.device_info == info


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
async def test_load_and_save_persistent_data(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    DummyStore.data = {
        "last_api_call": 123.0,
        "warning_data": {"severity_level": 1},
    }
    monkeypatch.setattr("custom_components.oig_cloud.entities.chmu_sensor.Store", DummyStore)

    await sensor._load_persistent_data()
    assert sensor._last_api_call == 123.0
    assert sensor._last_warning_data == {"severity_level": 1}

    sensor._last_api_call = 456.0
    sensor._last_warning_data = {"severity_level": 2}
    await sensor._save_persistent_data()
    assert DummyStore.saved["last_api_call"] == 456.0


@pytest.mark.asyncio
async def test_load_persistent_data_no_warning(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    DummyStore.data = {"last_api_call": 123, "warning_data": "bad"}
    monkeypatch.setattr("custom_components.oig_cloud.entities.chmu_sensor.Store", DummyStore)

    await sensor._load_persistent_data()
    assert sensor._last_api_call == 123.0


@pytest.mark.asyncio
async def test_load_persistent_data_none(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    DummyStore.data = None
    monkeypatch.setattr("custom_components.oig_cloud.entities.chmu_sensor.Store", DummyStore)

    await sensor._load_persistent_data()


@pytest.mark.asyncio
async def test_load_persistent_data_error(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    class BoomStore:
        def __init__(self, hass, version, key):
            pass

        async def async_load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("custom_components.oig_cloud.entities.chmu_sensor.Store", BoomStore)
    await sensor._load_persistent_data()
    assert sensor._last_api_call == 0


@pytest.mark.asyncio
async def test_save_persistent_data_error(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    class BoomStore:
        def __init__(self, hass, version, key):
            pass

        async def async_save(self, _data):
            raise RuntimeError("boom")

    monkeypatch.setattr("custom_components.oig_cloud.entities.chmu_sensor.Store", BoomStore)
    await sensor._save_persistent_data()


@pytest.mark.asyncio
async def test_async_added_to_hass_fetches_immediately(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    async def fake_super(_self):
        return None

    async def fake_load(_self):
        return None

    async def fake_delayed(_self):
        return None

    monkeypatch.setattr(OigCloudChmuSensor, "_load_persistent_data", fake_load)
    monkeypatch.setattr(OigCloudChmuSensor, "_delayed_initial_fetch", fake_delayed)
    monkeypatch.setattr(OigCloudChmuSensor, "_should_fetch_data", lambda *_a: True)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.OigCloudSensor.async_added_to_hass",
        fake_super,
    )

    await sensor.async_added_to_hass()


@pytest.mark.asyncio
async def test_async_added_to_hass_loads_cached(monkeypatch):
    warning_data = {"severity_level": 1}
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = warning_data
    sensor._last_api_call = 100.0

    async def fake_super(_self):
        return None

    async def fake_load(_self):
        return None

    monkeypatch.setattr(OigCloudChmuSensor, "_load_persistent_data", fake_load)
    monkeypatch.setattr(OigCloudChmuSensor, "_should_fetch_data", lambda *_a: False)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.async_track_time_interval",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.OigCloudSensor.async_added_to_hass",
        fake_super,
    )

    await sensor.async_added_to_hass()
    assert coordinator.chmu_warning_data == warning_data


def test_should_fetch_data(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    sensor._last_api_call = 0
    assert sensor._should_fetch_data() is True

    monkeypatch.setattr("time.time", lambda: 1000.0)
    sensor._last_api_call = 900.0
    assert sensor._should_fetch_data() is False

    sensor._last_api_call = 0.0
    assert sensor._should_fetch_data() is True


@pytest.mark.asyncio
async def test_delayed_initial_fetch(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    called = {"done": False}

    async def fake_sleep(_delay):
        return None

    async def fake_fetch():
        called["done"] = True

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sensor, "_fetch_warning_data", fake_fetch)

    await sensor._delayed_initial_fetch()
    assert called["done"] is True


@pytest.mark.asyncio
async def test_periodic_update_triggers_fetch(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    called = {"done": False}

    async def fake_fetch():
        called["done"] = True

    monkeypatch.setattr(sensor, "_fetch_warning_data", fake_fetch)
    await sensor._periodic_update(datetime.now())
    assert called["done"] is True


@pytest.mark.asyncio
async def test_fetch_warning_data_no_gps(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    monkeypatch.setattr(sensor, "_get_gps_coordinates", lambda: (None, None))
    await sensor._fetch_warning_data()
    assert sensor._attr_available is False


@pytest.mark.asyncio
async def test_fetch_warning_data_no_api(monkeypatch):
    coordinator = DummyCoordinator()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    monkeypatch.setattr(sensor, "_get_gps_coordinates", lambda: (50.0, 14.0))
    await sensor._fetch_warning_data()
    assert sensor._attr_available is False


@pytest.mark.asyncio
async def test_fetch_warning_data_success(monkeypatch):
    coordinator = DummyCoordinator()

    class DummyApi:
        async def get_warnings(self, *_args, **_kwargs):
            return {
                "all_warnings_count": 1,
                "local_warnings_count": 1,
                "severity_level": 1,
                "last_update": "2025-01-01T00:00:00",
            }

    coordinator.chmu_api = DummyApi()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    monkeypatch.setattr(sensor, "_get_gps_coordinates", lambda: (50.0, 14.0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.aiohttp_client.async_get_clientsession",
        lambda *_args, **_kwargs: object(),
    )

    called = {"saved": False}

    async def fake_save():
        called["saved"] = True

    monkeypatch.setattr(sensor, "_save_persistent_data", fake_save)
    await sensor._fetch_warning_data()
    assert sensor.available is True
    assert called["saved"] is True


@pytest.mark.asyncio
async def test_fetch_warning_data_api_error_cached(monkeypatch):
    from custom_components.oig_cloud.api.api_chmu import ChmuApiError

    coordinator = DummyCoordinator()

    class DummyApi:
        async def get_warnings(self, *_args, **_kwargs):
            raise ChmuApiError("boom")

    coordinator.chmu_api = DummyApi()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()
    sensor._last_warning_data = {"last_update": "2025-01-01T00:00:00"}

    monkeypatch.setattr(sensor, "_get_gps_coordinates", lambda: (50.0, 14.0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.aiohttp_client.async_get_clientsession",
        lambda *_args, **_kwargs: object(),
    )

    await sensor._fetch_warning_data()
    assert sensor.available is True


@pytest.mark.asyncio
async def test_fetch_warning_data_api_error_no_cache(monkeypatch):
    coordinator = DummyCoordinator()

    class DummyApi:
        async def get_warnings(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    coordinator.chmu_api = DummyApi()
    entry = DummyConfigEntry({})
    sensor = OigCloudChmuSensor(coordinator, "chmu_warning_level", entry, {})
    sensor.hass = DummyHass()

    monkeypatch.setattr(sensor, "_get_gps_coordinates", lambda: (50.0, 14.0))
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.chmu_sensor.aiohttp_client.async_get_clientsession",
        lambda *_args, **_kwargs: object(),
    )

    await sensor._fetch_warning_data()
    assert sensor._attr_available is False
