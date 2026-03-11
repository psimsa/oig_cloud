from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import computed_sensor as module
from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


class DummyCoordinator:
    def __init__(self):
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyState:
    def __init__(self, state, last_updated=None, last_changed=None):
        self.state = state
        self.last_updated = last_updated
        self.last_changed = last_changed or last_updated


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


class DummyHass:
    def __init__(self, mapping):
        self.states = DummyStates(mapping)
        self.data = {}

    def async_create_task(self, coro):
        coro.close()
        return object()


class DummyStore:
    def __init__(self, *_args, **_kwargs):
        self.saved = None
        self.loaded = None

    async def async_load(self):
        return self.loaded

    async def async_save(self, data):
        self.saved = data


def _make_sensor():
    coordinator = DummyCoordinator()
    return OigCloudComputedSensor(coordinator, "batt_bat_c")


def test_get_entity_number_invalid_inputs():
    sensor = _make_sensor()
    assert sensor._get_entity_number("sensor.oig_123_batt_bat_c") is None

    sensor.hass = DummyHass({"sensor.oig_123_batt_bat_c": DummyState("unknown")})
    assert sensor._get_entity_number("sensor.oig_123_batt_bat_c") is None

    sensor.hass = DummyHass({"sensor.oig_123_batt_bat_c": DummyState("bad")})
    assert sensor._get_entity_number("sensor.oig_123_batt_bat_c") is None


def test_get_oig_number_invalid_box():
    sensor = _make_sensor()
    sensor._box_id = "unknown"
    sensor.hass = DummyHass({})
    assert sensor._get_oig_number("batt_bat_c") is None


def test_get_oig_last_updated_naive_time():
    sensor = _make_sensor()
    naive = datetime(2025, 1, 1, 10, 0, 0)
    sensor.hass = DummyHass({"sensor.oig_123_batt_bat_c": DummyState("50", naive)})
    updated = sensor._get_oig_last_updated("batt_bat_c")
    assert updated is not None
    assert updated.tzinfo is not None


@pytest.mark.asyncio
async def test_load_energy_from_storage_non_numeric(monkeypatch):
    dummy_store = DummyStore()
    dummy_store.loaded = {
        "energy": {"charge_today": "bad", "charge_month": "2"},
        "last_save": "2025-01-01T00:00:00",
    }

    def _store_factory(*_args, **_kwargs):
        return dummy_store

    monkeypatch.setattr(module, "Store", _store_factory)
    module._energy_stores.clear()
    module._energy_data_cache.clear()
    module._energy_cache_loaded.clear()

    sensor = _make_sensor()
    sensor.hass = DummyHass({})

    loaded = await sensor._load_energy_from_storage()
    assert loaded is True
    assert sensor._energy["charge_today"] == 0.0
    assert sensor._energy["charge_month"] == 2.0


@pytest.mark.asyncio
async def test_save_energy_to_storage_throttled(monkeypatch):
    sensor = _make_sensor()
    sensor.hass = DummyHass({})
    module._energy_stores.clear()

    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    sensor._last_storage_save = fixed_now - timedelta(minutes=1)

    await sensor._save_energy_to_storage()
    assert module._energy_stores == {}


def test_state_real_data_update():
    sensor = _make_sensor()
    sensor._sensor_type = "real_data_update"
    ts = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    sensor.hass = DummyHass(
        {
            "sensor.oig_123_batt_batt_comp_p": DummyState("1", ts),
        }
    )
    assert sensor.state is not None


def test_state_various_aggregations():
    sensor = _make_sensor()
    sensor.hass = DummyHass(
        {
            "sensor.oig_123_actual_aci_wr": DummyState("1"),
            "sensor.oig_123_actual_aci_ws": DummyState("2"),
            "sensor.oig_123_actual_aci_wt": DummyState("3"),
            "sensor.oig_123_dc_in_fv_p1": DummyState("4"),
            "sensor.oig_123_dc_in_fv_p2": DummyState("6"),
        }
    )
    sensor._sensor_type = "actual_aci_wtotal"
    assert sensor.state == 6.0
    sensor._sensor_type = "dc_in_fv_total"
    assert sensor.state == 10.0


def test_state_batt_comp_charge_discharge():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_123_batt_batt_comp_p": DummyState("-5")})
    sensor._sensor_type = "batt_batt_comp_p_discharge"
    assert sensor.state == 5.0
    sensor._sensor_type = "batt_batt_comp_p_charge"
    assert sensor.state == 0.0


def test_state_capacity_variants_and_time():
    sensor = _make_sensor()

    def _get_number(sensor_type):
        return {
            "installed_battery_capacity_kwh": 10000,
            "batt_bat_min": 20,
            "batt_bat_c": 50,
            "batt_batt_comp_p": 2000,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number

    sensor._sensor_type = "usable_battery_capacity"
    assert sensor.state == 8.0

    sensor._sensor_type = "missing_battery_kwh"
    assert sensor.state == 5.0

    sensor._sensor_type = "remaining_usable_capacity"
    assert sensor.state == 3.0

    sensor._sensor_type = "time_to_full"
    assert "hodin" in sensor.state

    sensor._sensor_type = "time_to_empty"
    assert sensor.state == "Nabíjí se"


def test_state_time_edge_strings():
    sensor = _make_sensor()

    def _get_number(sensor_type):
        return {
            "installed_battery_capacity_kwh": 10000,
            "batt_bat_min": 20,
            "batt_bat_c": 100,
            "batt_batt_comp_p": -1000,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number

    sensor._sensor_type = "time_to_empty"
    assert sensor.state == "Nabito"

    def _get_number_full(sensor_type):
        return {
            "installed_battery_capacity_kwh": 10000,
            "batt_bat_min": 20,
            "batt_bat_c": 50,
            "batt_batt_comp_p": 0,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number_full
    sensor._sensor_type = "time_to_full"
    assert sensor.state == "Vybíjí se"

    def _get_number_empty(sensor_type):
        return {
            "installed_battery_capacity_kwh": 10000,
            "batt_bat_min": 20,
            "batt_bat_c": 20,
            "batt_batt_comp_p": 0,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number_empty
    sensor._sensor_type = "time_to_empty"
    assert sensor.state == "Vybito"

    sensor._get_oig_number = _get_number_full
    sensor._sensor_type = "time_to_empty"
    assert sensor.state == "Nabíjí se"


def test_format_time_plural_variants():
    sensor = _make_sensor()
    assert sensor._format_time(24) == "1 den 0 hodin 0 minut"
    assert sensor._format_time(48).startswith("2 dny")
    assert sensor._format_time(72).startswith("3 dny")
    assert sensor._format_time(96).startswith("4 dny")
    assert sensor._format_time(120).startswith("5 dnů")


def test_get_energy_value_missing_key():
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_unknown"
    assert sensor._get_energy_value() is None


def test_accumulate_energy_discharge(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_discharge_energy_today"
    sensor._box_id = "123"
    sensor.hass = DummyHass({})

    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(module, "datetime", FixedDatetime)

    module._energy_last_update_cache.clear()
    module._energy_data_cache.clear()
    module._energy_last_update_cache["123"] = fixed_now - timedelta(hours=1)

    def _get_number(sensor_type):
        return {
            "batt_batt_comp_p": -500,
            "actual_fv_p1": 0,
            "actual_fv_p2": 0,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number

    value = sensor._accumulate_energy()
    assert value is not None
    assert sensor._energy["discharge_today"] > 0


def test_boiler_consumption_error():
    sensor = _make_sensor()
    sensor._sensor_type = "boiler_current_w"
    sensor.hass = DummyHass({"sensor.oig_123_actual_fv_p1": DummyState("bad")})
    assert sensor.state == 0.0


@pytest.mark.asyncio
async def test_cancel_reset_unsub_error():
    sensor = _make_sensor()

    def _boom():
        raise RuntimeError("fail")

    sensor._daily_reset_unsub = _boom
    await sensor.async_will_remove_from_hass()
    assert sensor._daily_reset_unsub is None
