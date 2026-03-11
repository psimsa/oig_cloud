from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        self._write_calls = 0

    def async_write(self):
        self._write_calls += 1


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


def test_get_entity_number_and_oig_number():
    sensor = _make_sensor()
    sensor.hass = DummyHass({"sensor.oig_123_batt_bat_c": DummyState("50")})

    assert sensor._get_entity_number("sensor.oig_123_batt_bat_c") == 50.0
    assert sensor._get_oig_number("batt_bat_c") == 50.0


def test_get_oig_last_updated():
    sensor = _make_sensor()
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    sensor.hass = DummyHass({"sensor.oig_123_batt_bat_c": DummyState("50", ts)})

    updated = sensor._get_oig_last_updated("batt_bat_c")
    assert updated is not None
    assert updated.tzinfo is not None


@pytest.mark.asyncio
async def test_energy_store_load_and_save(monkeypatch):
    monkeypatch.setattr(module, "Store", DummyStore)

    sensor = _make_sensor()
    dummy_store = DummyStore()
    dummy_store.loaded = {
        "energy": {"charge_today": 5.0},
        "last_save": "2025-01-01T00:00:00",
    }

    def _store_factory(*_args, **_kwargs):
        return dummy_store

    monkeypatch.setattr(module, "Store", _store_factory)
    module._energy_stores.clear()
    module._energy_data_cache.clear()
    module._energy_cache_loaded.clear()

    sensor.hass = DummyHass({})

    loaded = await sensor._load_energy_from_storage()
    assert loaded is True
    assert sensor._energy["charge_today"] == 5.0

    sensor._energy["charge_today"] = 7.0
    await sensor._save_energy_to_storage(force=True)
    assert dummy_store.saved is not None
    assert dummy_store.saved["energy"]["charge_today"] == 7.0


def test_format_time_variants():
    sensor = _make_sensor()

    assert sensor._format_time(0) == "N/A"
    assert sensor._format_time(0.5) == "30 minut"
    assert sensor._format_time(1.5) == "1 hodin 30 minut"
    assert sensor._format_time(25.0).startswith("1 den")


def test_check_for_real_data_changes():
    sensor = _make_sensor()
    sensor._initialize_monitored_sensors()

    assert sensor._check_for_real_data_changes({}) is False

    pv_data = {"actual": {"bat_p": 10, "bat_c": 0, "fv_p1": 0, "fv_p2": 0, "aco_p": 0, "aci_wr": 0, "aci_ws": 0, "aci_wt": 0}}
    assert sensor._check_for_real_data_changes(pv_data) is True
    assert sensor._check_for_real_data_changes(pv_data) is False

    pv_data["actual"]["bat_p"] = 11
    assert sensor._check_for_real_data_changes(pv_data) is True


def test_batt_power_charge_discharge():
    sensor = _make_sensor()
    assert sensor._get_batt_power_charge({"actual": {"bat_p": 5}}) == 5.0
    assert sensor._get_batt_power_charge({"actual": {"bat_p": -5}}) == 0.0
    assert sensor._get_batt_power_discharge({"actual": {"bat_p": -7}}) == 7.0
    assert sensor._get_batt_power_discharge({"actual": {"bat_p": 7}}) == 0.0


def test_extended_fve_current():
    sensor = _make_sensor()
    coordinator = SimpleNamespace(data={"extended_fve_power_1": 100, "extended_fve_voltage_1": 50})
    assert sensor._get_extended_fve_current_1(coordinator) == 2.0

    coordinator = SimpleNamespace(data={"extended_fve_power_2": 0, "extended_fve_voltage_2": 0})
    assert sensor._get_extended_fve_current_2(coordinator) == 0.0


def test_get_energy_value_from_cache():
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"
    sensor._box_id = "123"

    module._energy_data_cache["123"] = {"charge_today": 12.345}

    assert sensor._get_energy_value() == 12.345


def test_accumulate_energy_charging(monkeypatch):
    sensor = _make_sensor()
    sensor._sensor_type = "computed_batt_charge_energy_today"
    sensor._box_id = "123"

    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


    module._energy_last_update_cache.clear()
    module._energy_data_cache.clear()

    module._energy_last_update_cache["123"] = fixed_now - timedelta(hours=1)

    def _get_number(sensor_type):
        return {
            "batt_batt_comp_p": 1000,
            "actual_fv_p1": 500,
            "actual_fv_p2": 500,
        }.get(sensor_type)

    sensor._get_oig_number = _get_number

    class DummyHass:
        def async_create_task(self, coro):
            coro.close()
            return object()

    sensor.hass = DummyHass()

    value = sensor._accumulate_energy()

    assert value is not None
    assert sensor._energy["charge_today"] > 0


def test_state_totals_from_entities():
    sensor = _make_sensor()
    sensor._sensor_type = "ac_in_aci_wtotal"
    sensor.hass = DummyHass(
        {
            "sensor.oig_123_ac_in_aci_wr": DummyState("1.5"),
            "sensor.oig_123_ac_in_aci_ws": DummyState("2.5"),
            "sensor.oig_123_ac_in_aci_wt": DummyState("3.0"),
        }
    )
    assert sensor.state == 7.0

    sensor._sensor_type = "actual_fv_total"
    sensor.hass = DummyHass(
        {
            "sensor.oig_123_actual_fv_p1": DummyState("10"),
            "sensor.oig_123_actual_fv_p2": DummyState("5"),
        }
    )
    assert sensor.state == 15.0


def test_boiler_current_manual_and_auto_modes():
    sensor = _make_sensor()
    sensor._sensor_type = "boiler_current_w"
    sensor.hass = DummyHass(
        {
            "sensor.oig_123_actual_fv_p1": DummyState("1000"),
            "sensor.oig_123_actual_fv_p2": DummyState("1000"),
            "sensor.oig_123_actual_aco_p": DummyState("500"),
            "sensor.oig_123_actual_aci_wr": DummyState("0"),
            "sensor.oig_123_actual_aci_ws": DummyState("0"),
            "sensor.oig_123_actual_aci_wt": DummyState("0"),
            "sensor.oig_123_boiler_install_power": DummyState("1200"),
            "sensor.oig_123_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_123_boiler_manual_mode": DummyState("Zapnuto"),
        }
    )
    assert sensor.state == 1200.0

    sensor.hass = DummyHass(
        {
            "sensor.oig_123_actual_fv_p1": DummyState("1000"),
            "sensor.oig_123_actual_fv_p2": DummyState("0"),
            "sensor.oig_123_actual_aco_p": DummyState("100"),
            "sensor.oig_123_actual_aci_wr": DummyState("0"),
            "sensor.oig_123_actual_aci_ws": DummyState("0"),
            "sensor.oig_123_actual_aci_wt": DummyState("0"),
            "sensor.oig_123_boiler_install_power": DummyState("900"),
            "sensor.oig_123_batt_batt_comp_p": DummyState("500"),
            "sensor.oig_123_boiler_manual_mode": DummyState("off"),
        }
    )
    assert sensor.state == 0.0

    sensor.hass = DummyHass(
        {
            "sensor.oig_123_actual_fv_p1": DummyState("1500"),
            "sensor.oig_123_actual_fv_p2": DummyState("0"),
            "sensor.oig_123_actual_aco_p": DummyState("200"),
            "sensor.oig_123_actual_aci_wr": DummyState("100"),
            "sensor.oig_123_actual_aci_ws": DummyState("0"),
            "sensor.oig_123_actual_aci_wt": DummyState("0"),
            "sensor.oig_123_boiler_install_power": DummyState("1200"),
            "sensor.oig_123_batt_batt_comp_p": DummyState("-50"),
            "sensor.oig_123_boiler_manual_mode": DummyState("off"),
        }
    )
    assert sensor.state == 1200.0


@pytest.mark.asyncio
async def test_reset_daily_resets_periods(monkeypatch):
    sensor = _make_sensor()
    sensor._energy["charge_today"] = 10.0
    sensor._energy["charge_month"] = 20.0
    sensor._energy["charge_year"] = 30.0

    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    saved = {"count": 0}

    async def _save(force=False):
        saved["count"] += 1

    sensor._save_energy_to_storage = _save

    await sensor._reset_daily(fixed_now)

    assert sensor._energy["charge_today"] == 0.0
    assert sensor._energy["charge_month"] == 0.0
    assert sensor._energy["charge_year"] == 0.0
    assert saved["count"] == 1


@pytest.mark.asyncio
async def test_async_added_to_hass_restores_from_state(monkeypatch):
    sensor = _make_sensor()
    sensor.hass = DummyHass({})

    module._energy_data_cache.clear()
    module._energy_cache_loaded.clear()

    async def _load_storage():
        return False

    sensor._load_energy_from_storage = _load_storage
    sensor._save_energy_to_storage = AsyncMock()

    old_state = SimpleNamespace(
        state="12.5",
        attributes={
            "charge_today": 1.0,
            "charge_month": 2.0,
            "charge_year": 3.0,
        },
    )
    sensor.async_get_last_state = AsyncMock(return_value=old_state)
    sensor.async_write_ha_state = lambda: None

    monkeypatch.setattr(
        module, "async_track_time_change", lambda *_a, **_k: (lambda: None)
    )

    await sensor.async_added_to_hass()

    assert sensor._energy["charge_today"] == 1.0
    assert module._energy_cache_loaded.get(sensor._box_id) is True
