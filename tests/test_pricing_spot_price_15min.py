from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.pricing import spot_price_15min as price15_module


class DummyOteApi:
    def __init__(self, cache_path=None):
        self.cache_path = cache_path

    @staticmethod
    def get_current_15min_interval(_now):
        return 0

    @staticmethod
    def get_15min_price_for_interval(_idx, data, _date):
        return data.get("prices15m_czk_kwh", {}).get("2025-01-01T12:00:00")

    async def async_load_cached_spot_prices(self):
        return None

    async def get_spot_prices(self):
        return {}


class DummyConfig:
    def path(self, *parts):
        return "/" + "/".join(parts)


class DummyHass:
    def __init__(self):
        self.config = DummyConfig()

    def async_create_task(self, coro):
        coro.close()
        return object()


class DummyCoordinator:
    def __init__(self):
        self.hass = DummyHass()
        self.data = {}
        self.forced_box_id = "123"
        self.refresh_called = False

    async def async_request_refresh(self):
        self.refresh_called = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(monkeypatch, options=None):
    options = options or {}
    entry = SimpleNamespace(options=options, data={})
    coordinator = DummyCoordinator()
    device_info = {"identifiers": {("oig_cloud", "123")}}

    monkeypatch.setattr(price15_module, "OteApi", DummyOteApi)
    monkeypatch.setattr(
        price15_module,
        "SENSOR_TYPES_SPOT",
        {"spot_price_current_15m": {"name": "Spot 15m"}},
    )

    sensor = price15_module.SpotPrice15MinSensor(
        coordinator,
        entry,
        "spot_price_current_15m",
        device_info,
    )
    sensor.hass = coordinator.hass
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    return sensor


def test_tariff_parsing_and_calculation_percentage(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        {
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 10.0,
            "spot_negative_fee_percent": 5.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "vat_rate": 0.0,
            "dual_tariff_enabled": False,
        },
    )

    assert sensor._parse_tariff_times("22,2") == [22, 2]
    assert sensor._parse_tariff_times("") == []

    dt = datetime(2025, 1, 1, 12, 0, 0)
    price = sensor._calculate_final_price_15min(2.0, dt)
    assert price == 3.2

    negative_price = sensor._calculate_final_price_15min(-1.0, dt)
    assert negative_price == 0.05


def test_tariff_fixed_prices_and_fee(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        {
            "spot_pricing_model": "fixed_prices",
            "fixed_commercial_price_vt": 4.0,
            "fixed_commercial_price_nt": 3.0,
            "distribution_fee_vt_kwh": 1.0,
            "distribution_fee_nt_kwh": 0.5,
            "vat_rate": 0.0,
            "dual_tariff_enabled": True,
            "tariff_nt_start_weekday": "0",
            "tariff_vt_start_weekday": "6",
        },
    )

    dt = datetime(2025, 1, 1, 7, 0, 0)
    price = sensor._calculate_final_price_15min(2.0, dt)
    assert price == 5.0

    sensor._entry.options["spot_pricing_model"] = "fixed_fee"
    sensor._entry.options["spot_fixed_fee_mwh"] = 100.0
    fee_price = sensor._calculate_final_price_15min(2.0, dt)
    assert fee_price == 3.1


def test_calculate_attributes_and_state(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        {
            "dual_tariff_enabled": False,
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 0.0,
            "spot_negative_fee_percent": 0.0,
            "distribution_fee_vt_kwh": 0.0,
            "distribution_fee_nt_kwh": 0.0,
            "vat_rate": 0.0,
        },
    )

    fixed_now = datetime(2025, 1, 1, 12, 7, 0)
    monkeypatch.setattr(price15_module, "dt_now", lambda: fixed_now)

    sensor._spot_data_15min = {
        "prices15m_czk_kwh": {
            "2025-01-01T11:45:00": 2.0,
            "2025-01-01T12:00:00": 2.5,
            "2025-01-01T12:15:00": 3.0,
        }
    }

    state = sensor._calculate_current_state()
    assert state == 2.5

    attrs = sensor._calculate_attributes()
    assert attrs["current_interval"] == 0
    assert attrs["price_min"] == 2.5
    assert attrs["price_max"] == 3.0
    assert attrs["price_avg"] == 2.75


def test_handle_coordinator_update(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor.coordinator.data = {
        "spot_prices": {"prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}}
    }
    sensor._handle_coordinator_update()
    assert sensor._spot_data_15min


def test_handle_coordinator_update_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor.coordinator.data = {
        "spot_prices": {"prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}}
    }
    monkeypatch.setattr(
        sensor, "_refresh_cached_state_and_attributes", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    sensor._handle_coordinator_update()


@pytest.mark.asyncio
async def test_async_added_to_hass_initial_fetch(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"fetch": 0}

    async def fake_fetch():
        called["fetch"] += 1

    async def fake_restore():
        return None

    monkeypatch.setattr(sensor, "_fetch_spot_data_with_retry", fake_fetch)
    monkeypatch.setattr(sensor, "_restore_data", fake_restore)
    monkeypatch.setattr(sensor, "_setup_daily_tracking", lambda: None)
    monkeypatch.setattr(sensor, "_setup_15min_tracking", lambda: None)
    monkeypatch.setattr(price15_module, "dt_now", lambda: datetime(2025, 1, 1, 10, 0, 0))

    await sensor.async_added_to_hass()
    assert called["fetch"] == 1


@pytest.mark.asyncio
async def test_async_added_to_hass_initial_fetch_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def fake_fetch():
        raise RuntimeError("boom")

    async def fake_restore():
        return None

    monkeypatch.setattr(sensor, "_fetch_spot_data_with_retry", fake_fetch)
    monkeypatch.setattr(sensor, "_restore_data", fake_restore)
    monkeypatch.setattr(sensor, "_setup_daily_tracking", lambda: None)
    monkeypatch.setattr(sensor, "_setup_15min_tracking", lambda: None)
    monkeypatch.setattr(price15_module, "dt_now", lambda: datetime(2025, 1, 1, 10, 0, 0))

    await sensor.async_added_to_hass()


@pytest.mark.asyncio
async def test_restore_data_valid(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    class DummyState:
        attributes = {"last_update": "2025-01-01T10:00:00"}

    async def fake_last_state():
        return DummyState()

    monkeypatch.setattr(sensor, "async_get_last_state", fake_last_state)
    await sensor._restore_data()
    assert sensor._last_update is not None


@pytest.mark.asyncio
async def test_restore_data_invalid(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    class DummyState:
        attributes = {"last_update": "bad"}

    async def fake_last_state():
        return DummyState()

    monkeypatch.setattr(sensor, "async_get_last_state", fake_last_state)
    await sensor._restore_data()


def test_setup_daily_tracking(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    monkeypatch.setattr(price15_module, "dt_now", lambda: datetime(2025, 1, 1, 14, 0, 0))
    monkeypatch.setattr(price15_module, "async_track_time_change", lambda *_a, **_k: lambda: None)
    called = {"task": 0}

    def fake_task(coro):
        called["task"] += 1
        coro.close()
        return object()

    sensor.hass.async_create_task = fake_task
    sensor._setup_daily_tracking()
    assert called["task"] == 1


def test_setup_15min_tracking(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    monkeypatch.setattr(price15_module, "async_track_time_change", lambda *_a, **_k: lambda: None)
    sensor._setup_15min_tracking()
    assert sensor._track_15min_remove is not None


@pytest.mark.asyncio
async def test_async_will_remove_cleans_tracking(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"daily": 0, "interval": 0}

    def daily_remove():
        called["daily"] += 1

    def interval_remove():
        called["interval"] += 1

    sensor._track_time_interval_remove = daily_remove
    sensor._track_15min_remove = interval_remove

    await sensor.async_will_remove_from_hass()
    assert called["daily"] == 1
    assert called["interval"] == 1


@pytest.mark.asyncio
async def test_update_current_interval_triggers_refresh(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = {
        "prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}
    }
    sensor.hass.async_create_task = lambda coro: asyncio.create_task(coro)
    await sensor._update_current_interval()
    await asyncio.sleep(0)
    assert sensor.coordinator.refresh_called is True


@pytest.mark.asyncio
async def test_do_fetch_15min_spot_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def fake_get():
        return {"prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}}

    async def fake_get_empty():
        return {}

    sensor._ote_api._is_cache_valid = lambda: True
    monkeypatch.setattr(sensor._ote_api, "get_spot_prices", fake_get)
    result = await sensor._do_fetch_15min_spot_data()
    assert result is True

    sensor._ote_api._is_cache_valid = lambda: False
    result = await sensor._do_fetch_15min_spot_data()
    assert result is False

    monkeypatch.setattr(sensor._ote_api, "get_spot_prices", fake_get_empty)
    result = await sensor._do_fetch_15min_spot_data()
    assert result is False


@pytest.mark.asyncio
async def test_do_fetch_15min_spot_data_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(sensor._ote_api, "get_spot_prices", boom)
    result = await sensor._do_fetch_15min_spot_data()
    assert result is False


def test_calculate_current_state_no_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = {}
    assert sensor._calculate_current_state() is None


def test_calculate_current_state_no_price(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = {"prices15m_czk_kwh": {"2025-01-01T10:00:00": 2.0}}
    assert sensor._calculate_current_state() is None


def test_calculate_current_state_exception(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = {
        "prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}
    }
    monkeypatch.setattr(
        sensor,
        "_calculate_final_price_15min",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert sensor._calculate_current_state() is None


def test_calculate_attributes_no_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = None
    assert sensor._calculate_attributes() == {}


def test_calculate_attributes_invalid_interval(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 12, 0, 0)
    monkeypatch.setattr(price15_module, "dt_now", lambda: fixed_now)
    sensor._spot_data_15min = {
        "prices15m_czk_kwh": {
            "bad": 2.0,
            "2025-01-01T12:00:00": 2.5,
        }
    }
    attrs = sensor._calculate_attributes()
    assert attrs["intervals_count"] >= 1


def test_calculate_attributes_rollover(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    fixed_now = datetime(2025, 1, 1, 23, 59, 0)
    monkeypatch.setattr(price15_module, "dt_now", lambda: fixed_now)
    monkeypatch.setattr(sensor, "_get_current_interval_index", lambda _now: 95)
    sensor._spot_data_15min = {
        "prices15m_czk_kwh": {
            "2025-01-01T23:45:00": 2.0,
        }
    }
    attrs = sensor._calculate_attributes()
    assert "next_update" in attrs


def test_calculate_attributes_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._spot_data_15min = {"prices15m_czk_kwh": {"2025-01-01T12:00:00": 2.0}}
    monkeypatch.setattr(
        sensor, "_get_current_interval_index", lambda _now: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert sensor._calculate_attributes() == {}


def test_get_tariff_for_datetime_weekend(monkeypatch):
    sensor = _make_sensor(
        monkeypatch,
        {
            "dual_tariff_enabled": True,
            "tariff_nt_start_weekend": "1",
            "tariff_vt_start_weekend": "5",
        },
    )
    dt = datetime(2025, 1, 4, 6, 0, 0)
    assert sensor._get_tariff_for_datetime(dt) == "VT"


def test_parse_tariff_times_invalid(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    assert sensor._parse_tariff_times("bad,2x") == []


@pytest.mark.asyncio
async def test_fetch_with_retry_schedules(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def fake_do():
        return False

    called = {"scheduled": False}

    def fake_schedule(_coro):
        called["scheduled"] = True

    monkeypatch.setattr(sensor, "_do_fetch_15min_spot_data", fake_do)
    monkeypatch.setattr(sensor, "_schedule_retry", fake_schedule)

    await sensor._fetch_spot_data_with_retry()
    assert called["scheduled"] is True


@pytest.mark.asyncio
async def test_fetch_with_retry_success(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._retry_attempt = 2
    called = {"cancel": 0}

    async def fake_do():
        return True

    def fake_cancel():
        called["cancel"] += 1

    monkeypatch.setattr(sensor, "_do_fetch_15min_spot_data", fake_do)
    monkeypatch.setattr(sensor, "_cancel_retry_timer", fake_cancel)

    await sensor._fetch_spot_data_with_retry()
    assert sensor._retry_attempt == 0
    assert called["cancel"] == 1


def test_cancel_retry_timer(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    class DummyTask:
        def __init__(self, done=False):
            self._done = done
            self.cancelled = False

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True

    sensor._retry_remove = DummyTask()
    sensor._cancel_retry_timer()
    assert sensor._retry_remove is None


@pytest.mark.asyncio
async def test_schedule_retry_executes(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    called = {"fetch": 0}

    async def fake_fetch():
        called["fetch"] += 1

    async def fake_sleep(_delay):
        return None

    sensor.hass.async_create_task = lambda coro: asyncio.create_task(coro)
    monkeypatch.setattr(price15_module.asyncio, "sleep", fake_sleep)
    sensor._schedule_retry(fake_fetch)
    await sensor._retry_remove
    assert called["fetch"] == 1


def test_properties(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._cached_state = 1.23
    sensor._cached_attributes = {"foo": "bar"}
    assert sensor.state == 1.23
    assert sensor.extra_state_attributes["foo"] == "bar"
    assert sensor.unique_id == "oig_cloud_123_spot_price_current_15m"
    assert sensor.device_info == {"identifiers": {("oig_cloud", "123")}}
    assert sensor.should_poll is False


def test_properties_compute_without_cache(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    monkeypatch.setattr(sensor, "_calculate_current_state", lambda: 4.56)
    monkeypatch.setattr(sensor, "_calculate_attributes", lambda: {"baz": "qux"})
    assert sensor.state == 4.56
    assert sensor.extra_state_attributes["baz"] == "qux"
