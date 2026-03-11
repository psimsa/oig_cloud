from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.sensors import (
    efficiency_sensor as eff_module,
)
from custom_components.oig_cloud.sensors import SENSOR_TYPES_STATISTICS as stats_module


class DummyState:
    def __init__(self, state):
        self.state = str(state)
        self.attributes = {}
        self.last_updated = datetime.now(timezone.utc)


class DummyStates:
    def __init__(self):
        self._states = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_set(self, entity_id, state):
        self._states[entity_id] = DummyState(state)

    def async_all(self, domain):
        prefix = f"{domain}."
        return [st for eid, st in self._states.items() if eid.startswith(prefix)]


class DummyHass:
    def __init__(self):
        self.states = DummyStates()
        self.created = []
        self.data = {}
        self.config = SimpleNamespace(config_dir="/tmp")

    def async_create_task(self, coro):
        coro.close()
        self.created.append(True)
        return object()

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class DummyCoordinator:
    def __init__(self, hass):
        self.hass = hass
        self.config_entry = SimpleNamespace(entry_id="entry")
        self.last_update_success = True

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(monkeypatch, hass):
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
    )
    monkeypatch.setitem(
        stats_module.SENSOR_TYPES_STATISTICS,
        "battery_efficiency",
        {"name": "Battery Efficiency"},
    )
    coordinator = DummyCoordinator(hass)
    device_info = {"identifiers": {("oig_cloud", "123")}}
    entry = SimpleNamespace(entry_id="entry")
    sensor = eff_module.OigCloudBatteryEfficiencySensor(
        coordinator,
        "battery_efficiency",
        entry,
        device_info,
        hass,
    )
    sensor.hass = hass
    sensor.async_write_ha_state = lambda *args, **kwargs: None
    return sensor


class DummyHistoryState:
    def __init__(self, state):
        self.state = state


@pytest.mark.asyncio
async def test_daily_update_computes_partial_efficiency(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    hass.states.async_set("sensor.oig_123_computed_batt_charge_energy_month", 10000)
    hass.states.async_set(
        "sensor.oig_123_computed_batt_discharge_energy_month", 8000
    )
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 4.0)

    sensor._battery_kwh_month_start = 5.0

    await sensor._daily_update()

    assert sensor._current_month_partial["charge"] == 10.0
    assert sensor._current_month_partial["discharge"] == 8.0
    assert sensor._current_month_partial["efficiency"] == 90.0
    assert sensor._attr_native_value == 90.0


@pytest.mark.asyncio
async def test_monthly_calculation_sets_last_month(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    sensor._current_month_partial = {
        "charge": 10.0,
        "discharge": 8.0,
        "battery_start": 5.0,
        "battery_end": 4.0,
    }
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 6.0)

    await sensor._monthly_calculation(datetime(2025, 2, 1, 0, 10, tzinfo=timezone.utc))

    assert sensor._efficiency_last_month == 90.0
    assert sensor._battery_kwh_month_start == 6.0
    assert sensor._current_month_partial == {}


@pytest.mark.asyncio
async def test_daily_update_without_month_start(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._battery_kwh_month_start = None
    sensor._efficiency_last_month = 88.0

    await sensor._daily_update()

    assert sensor._attr_native_value == 88.0


@pytest.mark.asyncio
async def test_monthly_calculation_insufficient_data(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._current_month_partial = {
        "charge": 1.0,
        "discharge": 1.0,
        "battery_start": 5.0,
        "battery_end": 4.0,
    }
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 6.0)

    await sensor._monthly_calculation(datetime(2025, 2, 1, 0, 10, tzinfo=timezone.utc))
    assert sensor._efficiency_last_month is None


@pytest.mark.asyncio
async def test_monthly_calculation_invalid_effective(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._current_month_partial = {
        "charge": 10.0,
        "discharge": 1.0,
        "battery_start": 5.0,
        "battery_end": 20.0,
    }
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 6.0)

    await sensor._monthly_calculation(datetime(2025, 2, 1, 0, 10, tzinfo=timezone.utc))
    assert sensor._efficiency_last_month is None


@pytest.mark.asyncio
async def test_monthly_calculation_invalid_effective_discharge(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._current_month_partial = {
        "charge": 10.0,
        "discharge": 5.0,
        "battery_start": 5.0,
        "battery_end": 25.0,
    }
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 6.0)

    await sensor._monthly_calculation(datetime(2025, 2, 1, 0, 10, tzinfo=timezone.utc))
    assert sensor._efficiency_last_month is None


def test_update_extra_state_attributes_triggers_history(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._battery_kwh_month_start = 5.0
    sensor._current_month_partial = {
        "charge": 10.0,
        "discharge": 9.0,
        "effective_discharge": 9.0,
    }
    sensor._efficiency_last_month = 90.0
    sensor._last_month_data = {}
    sensor._loading_history = False

    sensor._update_extra_state_attributes()
    assert hass.created
    assert sensor._attr_extra_state_attributes["losses_last_month_pct"] == 10.0


def test_get_sensor_handles_missing(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._hass = None
    assert sensor._get_sensor("missing") is None

    sensor._hass = hass
    assert sensor._get_sensor("missing") is None


def test_init_resolve_box_id_error(monkeypatch):
    hass = DummyHass()

    def boom(_coord):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        boom,
    )
    monkeypatch.setitem(
        stats_module.SENSOR_TYPES_STATISTICS,
        "battery_efficiency",
        {"name": "Battery Efficiency"},
    )
    coordinator = DummyCoordinator(hass)
    device_info = {"identifiers": {("oig_cloud", "123")}}
    entry = SimpleNamespace(entry_id="entry")
    sensor = eff_module.OigCloudBatteryEfficiencySensor(
        coordinator,
        "battery_efficiency",
        entry,
        device_info,
        hass,
    )
    assert sensor._box_id == "unknown"


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_import_error(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    import builtins

    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "homeassistant.components.recorder.history":
            raise ImportError("boom")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    await sensor._try_load_last_month_from_history()


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_success(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    def fake_get_significant_states(_hass, start, end, entity_ids):
        if len(entity_ids) == 3:
            return {
                entity_ids[0]: [{"state": "1000"}],
                entity_ids[1]: [{"state": "2000"}],
                entity_ids[2]: [{"state": "5"}],
            }
        return {entity_ids[0]: [{"state": "4"}]}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )
    sensor.async_write_ha_state = lambda *args, **kwargs: None

    await sensor._try_load_last_month_from_history()
    assert sensor._last_month_data.get("charge_kwh") == 1.0


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_invalid_data(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 5, 10, 12, 0, 0, tzinfo=tz)

    def fake_get_significant_states(_hass, _start, _end, entity_ids):
        if len(entity_ids) == 3:
            return {
                entity_ids[0]: [DummyHistoryState("1000"), DummyHistoryState("bad")],
                entity_ids[1]: [DummyHistoryState("2000"), DummyHistoryState("bad")],
                entity_ids[2]: [DummyHistoryState("50"), DummyHistoryState("bad")],
            }
        return {entity_ids[0]: [DummyHistoryState("bad"), DummyHistoryState("30")]}

    monkeypatch.setattr(eff_module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )

    await sensor._try_load_last_month_from_history()
    assert sensor._efficiency_last_month is None


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_bad_values(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    def fake_get_significant_states(_hass, _start, _end, entity_ids):
        if len(entity_ids) == 3:
            return {
                entity_ids[0]: [{"state": "bad"}, {"state": "1000"}],
                entity_ids[1]: [{"state": "bad"}, {"state": "2000"}],
                entity_ids[2]: [{"state": "bad"}, {"state": "50"}],
            }
        return {entity_ids[0]: [{"state": "bad"}, {"state": "30"}]}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )

    await sensor._try_load_last_month_from_history()
    assert sensor._efficiency_last_month is None


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_error(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(hass, "async_add_executor_job", boom)
    await sensor._try_load_last_month_from_history()


@pytest.mark.asyncio
async def test_async_added_to_hass_restores_state(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    class DummyState:
        state = "88.5"
        attributes = {
            "_battery_kwh_month_start": 3.5,
            "_current_month_partial": {"charge": 1.0},
            "_last_month_data": {"charge_kwh": 4.0},
        }

    async def fake_last_state():
        return DummyState()

    monkeypatch.setattr(sensor, "async_get_last_state", fake_last_state)
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_utc_time_change",
        lambda *_a, **_k: lambda: None,
    )
    await sensor.async_added_to_hass()

    assert sensor._efficiency_last_month == 88.5
    assert sensor._battery_kwh_month_start == 3.5


@pytest.mark.asyncio
async def test_async_added_to_hass_invalid_state(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    class DummyState:
        state = "bad"
        attributes = {}

    async def fake_last_state():
        return DummyState()

    monkeypatch.setattr(sensor, "async_get_last_state", fake_last_state)
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_utc_time_change",
        lambda *_a, **_k: lambda: None,
    )
    await sensor.async_added_to_hass()
    assert sensor._efficiency_last_month is None


@pytest.mark.asyncio
async def test_async_added_to_hass_initializes_mid_month(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 10, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(eff_module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_utc_time_change",
        lambda *_a, **_k: lambda: None,
    )
    await sensor.async_added_to_hass()
    assert sensor._battery_kwh_month_start is not None


def test_update_extra_state_attributes_without_efficiency(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._battery_kwh_month_start = 5.0
    sensor._current_month_partial = {}
    sensor._efficiency_last_month = None
    sensor._last_month_data = {}
    sensor._loading_history = True

    sensor._update_extra_state_attributes()
    assert sensor._attr_extra_state_attributes["losses_last_month_pct"] is None


@pytest.mark.asyncio
async def test_async_added_to_hass_no_last_state_beginning_month(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    async def fake_last_state():
        return None

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", 5.0)
    monkeypatch.setattr(sensor, "async_get_last_state", fake_last_state)
    monkeypatch.setattr(eff_module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        "homeassistant.helpers.event.async_track_utc_time_change",
        lambda *_a, **_k: lambda: None,
    )
    await sensor.async_added_to_hass()
    assert sensor._battery_kwh_month_start == 5.0


@pytest.mark.asyncio
async def test_async_will_remove_from_hass(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    await sensor.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_monthly_calculation_wrong_day(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    sensor._efficiency_last_month = 50.0
    await sensor._monthly_calculation(datetime(2025, 2, 2, 0, 10, tzinfo=timezone.utc))
    assert sensor._efficiency_last_month == 50.0


def test_get_sensor_invalid_state(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)
    hass.states.async_set("sensor.oig_123_remaining_usable_capacity", "bad")
    assert sensor._get_sensor("remaining_usable_capacity") is None


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_no_history(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    def fake_get_significant_states(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )
    await sensor._try_load_last_month_from_history()


@pytest.mark.asyncio
async def test_try_load_last_month_from_history_incomplete(monkeypatch):
    hass = DummyHass()
    sensor = _make_sensor(monkeypatch, hass)

    def fake_get_significant_states(_hass, _start, _end, entity_ids):
        return {entity_ids[0]: [{"state": "unknown"}]}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )
    await sensor._try_load_last_month_from_history()
