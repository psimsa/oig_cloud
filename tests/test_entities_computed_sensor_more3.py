from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import computed_sensor as module
from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


class DummyStore:
    def __init__(self, payload=None):
        self._payload = payload
        self.saved = None

    async def async_load(self):
        return self._payload

    async def async_save(self, data):
        self.saved = data


class DummyHass:
    def __init__(self):
        self.states = {}
        self._tasks = []

    def async_create_task(self, coro):
        self._tasks.append(coro)


def _make_sensor(sensor_type="computed_batt_charge_energy_today"):
    coordinator = SimpleNamespace(async_add_listener=lambda *_a, **_k: lambda: None)
    sensor = OigCloudComputedSensor(coordinator, sensor_type)
    sensor._box_id = "test"
    sensor.hass = DummyHass()
    return sensor


def test_get_entity_number_variants():
    sensor = _make_sensor()
    sensor.hass.states["sensor.oig_123_x"] = SimpleNamespace(state="1.5")
    assert sensor._get_entity_number("sensor.oig_123_x") == 1.5

    sensor.hass.states["sensor.oig_123_y"] = SimpleNamespace(state="bad")
    assert sensor._get_entity_number("sensor.oig_123_y") is None


def test_get_oig_number_invalid_box():
    sensor = _make_sensor()
    sensor._box_id = "bad"
    assert sensor._get_oig_number("any") is None


def test_get_oig_last_updated_missing_hass():
    sensor = _make_sensor()
    sensor.hass = None
    assert sensor._get_oig_last_updated("test") is None


def test_get_oig_last_updated_invalid_box():
    sensor = _make_sensor()
    sensor._box_id = "bad"
    assert sensor._get_oig_last_updated("test") is None


def test_get_oig_last_updated_handles_timezone():
    sensor = _make_sensor()
    sensor._box_id = "123"
    now = datetime.now(timezone.utc)
    sensor.hass.states["sensor.oig_123_test"] = SimpleNamespace(
        state="1", last_updated=now, last_changed=now
    )
    assert sensor._get_oig_last_updated("test") == now


def test_get_oig_last_updated_missing_dt():
    sensor = _make_sensor()
    sensor._box_id = "123"
    sensor.hass.states["sensor.oig_123_test"] = SimpleNamespace(
        state="1", last_updated=None, last_changed=None
    )
    assert sensor._get_oig_last_updated("test") is None


def test_get_oig_last_updated_invalid_dt():
    sensor = _make_sensor()
    sensor._box_id = "123"
    sensor.hass.states["sensor.oig_123_test"] = SimpleNamespace(
        state="1", last_updated="bad", last_changed=None
    )
    assert sensor._get_oig_last_updated("test") is None


@pytest.mark.asyncio
async def test_load_energy_from_storage_populates_defaults(monkeypatch):
    sensor = _make_sensor()
    module._energy_data_cache.pop(sensor._box_id, None)
    module._energy_cache_loaded.pop(sensor._box_id, None)
    store = DummyStore(payload={"energy": {"charge_today": "2"}})
    monkeypatch.setattr(sensor, "_get_energy_store", lambda: store)

    loaded = await sensor._load_energy_from_storage()
    assert loaded is True
    assert sensor._energy["charge_today"] == 2.0
    assert sensor._energy["charge_month"] == 0.0


@pytest.mark.asyncio
async def test_load_energy_from_storage_cache(monkeypatch):
    sensor = _make_sensor()
    module._energy_data_cache[sensor._box_id] = {"charge_today": 1.0}
    module._energy_cache_loaded[sensor._box_id] = True

    loaded = await sensor._load_energy_from_storage()
    assert loaded is True
    assert sensor._energy["charge_today"] == 1.0


@pytest.mark.asyncio
async def test_load_energy_from_storage_error(monkeypatch):
    sensor = _make_sensor()
    module._energy_data_cache.pop(sensor._box_id, None)
    module._energy_cache_loaded.pop(sensor._box_id, None)

    class FailingStore(DummyStore):
        async def async_load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "_get_energy_store", lambda: FailingStore())
    loaded = await sensor._load_energy_from_storage()
    assert loaded is False


@pytest.mark.asyncio
async def test_save_energy_to_storage_forced(monkeypatch):
    sensor = _make_sensor()
    store = DummyStore()
    monkeypatch.setattr(sensor, "_get_energy_store", lambda: store)
    sensor._energy["charge_today"] = 5.0

    await sensor._save_energy_to_storage(force=True)
    assert store.saved is not None
    assert store.saved["energy"]["charge_today"] == 5.0


@pytest.mark.asyncio
async def test_save_energy_to_storage_error(monkeypatch):
    sensor = _make_sensor()

    class FailingStore(DummyStore):
        async def async_save(self, data):
            raise RuntimeError("boom")

    monkeypatch.setattr(sensor, "_get_energy_store", lambda: FailingStore())
    await sensor._save_energy_to_storage(force=True)


@pytest.mark.asyncio
async def test_save_energy_to_storage_no_store(monkeypatch):
    sensor = _make_sensor()
    monkeypatch.setattr(sensor, "_get_energy_store", lambda: None)
    await sensor._save_energy_to_storage(force=True)


@pytest.mark.asyncio
async def test_async_added_to_hass_restore_from_state(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"
    sensor._box_id = "123"
    sensor.hass = SimpleNamespace()
    sensor.async_write_ha_state = lambda: None

    async def _no_storage():
        return False

    async def _get_last_state():
        return SimpleNamespace(
            state="5",
            attributes={
                "charge_today": "bad",
                "charge_month": "10",
            },
        )

    monkeypatch.setattr(sensor, "_load_energy_from_storage", _no_storage)
    monkeypatch.setattr(sensor, "async_get_last_state", _get_last_state)
    monkeypatch.setattr(module, "async_track_time_change", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(sensor, "_get_energy_store", lambda: DummyStore())
    module._energy_data_cache.pop(sensor._box_id, None)
    module._energy_cache_loaded.pop(sensor._box_id, None)

    await sensor.async_added_to_hass()
    assert sensor._energy["charge_month"] == 10.0


@pytest.mark.asyncio
async def test_async_added_to_hass_restore_from_entity_state(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"
    sensor._box_id = "123"
    sensor.hass = SimpleNamespace()
    sensor.async_write_ha_state = lambda: None

    async def _no_storage():
        return False

    async def _get_last_state():
        return SimpleNamespace(state="8", attributes={"dummy": 0})

    monkeypatch.setattr(sensor, "_load_energy_from_storage", _no_storage)
    monkeypatch.setattr(sensor, "async_get_last_state", _get_last_state)
    monkeypatch.setattr(module, "async_track_time_change", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(sensor, "_get_energy_store", lambda: DummyStore())
    module._energy_data_cache.pop(sensor._box_id, None)
    module._energy_cache_loaded.pop(sensor._box_id, None)

    await sensor.async_added_to_hass()
    assert sensor._energy["charge_today"] == 8.0


def test_state_invalid_box_returns_none():
    sensor = _make_sensor()
    sensor._sensor_type = "ac_in_aci_wtotal"
    sensor._box_id = "bad"
    assert sensor.state is None


def test_state_ac_in_total_missing_component():
    sensor = _make_sensor()
    sensor._sensor_type = "ac_in_aci_wtotal"
    sensor._get_oig_number = lambda _name: None
    assert sensor.state is None


def test_state_actual_aci_total_missing_component():
    sensor = _make_sensor()
    sensor._sensor_type = "actual_aci_wtotal"
    sensor._get_oig_number = lambda _name: None
    assert sensor.state is None


def test_state_dc_in_total_missing_component():
    sensor = _make_sensor()
    sensor._sensor_type = "dc_in_fv_total"
    sensor._get_oig_number = lambda _name: None
    assert sensor.state is None


def test_state_actual_fv_total_missing_component():
    sensor = _make_sensor()
    sensor._sensor_type = "actual_fv_total"
    sensor._get_oig_number = lambda _name: None
    assert sensor.state is None


def test_state_time_to_full_charged():
    sensor = _make_sensor()
    sensor._sensor_type = "time_to_full"
    sensor._box_id = "123"

    def _get_number(name):
        mapping = {
            "installed_battery_capacity_kwh": 10.0,
            "batt_bat_min": 20.0,
            "batt_bat_c": 100.0,
            "batt_batt_comp_p": 0.0,
        }
        return mapping.get(name, 0.0)

    sensor._get_oig_number = _get_number
    assert sensor.state == "Nabito"


def test_state_time_to_empty_discharge(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "time_to_empty"
    sensor._box_id = "123"

    def _get_number(name):
        mapping = {
            "installed_battery_capacity_kwh": 10.0,
            "batt_bat_min": 20.0,
            "batt_bat_c": 50.0,
            "batt_batt_comp_p": -200.0,
        }
        return mapping.get(name, 0.0)

    sensor._get_oig_number = _get_number
    monkeypatch.setattr(sensor, "_format_time", lambda _h: "1h")
    assert sensor.state == "1h"


def test_state_battery_calculation_exception():
    sensor = _make_sensor()
    sensor._sensor_type = "time_to_full"

    def _raise(_name):
        raise ValueError("boom")

    sensor._get_oig_number = _raise
    assert sensor.state is None


def test_accumulate_energy_fv_low_updates_grid():
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"
    sensor._box_id = "123"
    sensor._energy = {k: 0.0 for k in sensor._energy}
    module._energy_last_update_cache.pop(sensor._box_id, None)
    module._energy_data_cache.pop(sensor._box_id, None)
    now = datetime.now(timezone.utc)
    sensor._last_update = now - timedelta(hours=1)
    module._energy_last_update_cache[sensor._box_id] = sensor._last_update

    def _get_number(name):
        mapping = {
            "batt_batt_comp_p": 100.0,
            "actual_fv_p1": 0.0,
            "actual_fv_p2": 0.0,
        }
        return mapping.get(name)

    sensor._get_oig_number = _get_number
    result = sensor._accumulate_energy()
    assert result is not None
    assert sensor._energy["charge_grid_today"] > 0
    assert sensor._energy["charge_fve_today"] == 0.0


def test_accumulate_energy_exception():
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"

    def _raise(_name):
        raise RuntimeError("boom")

    sensor._get_oig_number = _raise
    assert sensor._accumulate_energy() is None


def test_get_boiler_consumption_wrong_type():
    sensor = _make_sensor()
    sensor._sensor_type = "other"
    assert sensor._get_boiler_consumption_from_entities() is None


def test_get_boiler_consumption_error():
    sensor = _make_sensor()
    sensor._sensor_type = "boiler_current_w"

    def _raise(_name):
        raise RuntimeError("boom")

    sensor._get_oig_number = _raise
    assert sensor._get_boiler_consumption_from_entities() is None


def test_get_batt_power_charge_no_actual():
    sensor = _make_sensor()
    assert sensor._get_batt_power_charge({}) == 0.0


def test_get_batt_power_discharge_no_actual():
    sensor = _make_sensor()
    assert sensor._get_batt_power_discharge({}) == 0.0


def test_extended_fve_current_voltage_zero():
    sensor = _make_sensor()
    coordinator = SimpleNamespace(
        data={"extended_fve_power_1": 100.0, "extended_fve_voltage_1": 0.0}
    )
    assert sensor._get_extended_fve_current_1(coordinator) == 0.0


def test_extended_fve_current_missing_data():
    sensor = _make_sensor()
    coordinator = SimpleNamespace(data={})
    assert sensor._get_extended_fve_current_1(coordinator) is None


def test_extra_state_attributes_default():
    sensor = _make_sensor()
    assert sensor.extra_state_attributes == {}


def test_real_data_changes_exception():
    sensor = _make_sensor()
    sensor._initialize_monitored_sensors()
    sensor._monitored_sensors = {"bat_p": 0}
    pv_data = {"actual": {"bat_p": object()}}
    assert sensor._check_for_real_data_changes(pv_data) is False
