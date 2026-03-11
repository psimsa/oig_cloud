import builtins
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.data import history as history_module
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    SERVICE_MODE_HOME_UPS,
)


class DummyState:
    def __init__(self, state, last_updated):
        self.state = state
        self.last_updated = last_updated
        self.last_changed = last_updated


class DummySensor:
    def __init__(self, hass):
        self._hass = hass
        self._box_id = "123"

    def _get_total_battery_capacity(self):
        return 10.0

    def _log_rate_limited(self, *args, **kwargs):
        return None


class DummyHass:
    def __init__(self):
        self.data = {}

    async def async_add_executor_job(self, func, *args, **kwargs):
        return func(*args, **kwargs)


def test_safe_float_and_build_ids():
    assert history_module._safe_float("3.14") == 3.14
    assert history_module._safe_float("bad") is None
    assert history_module._safe_float(None) is None

    ids = history_module._build_history_entity_ids("123")
    assert "sensor.oig_123_ac_out_en_day" in ids


def test_select_interval_states_in_range_and_neighbors():
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    before = DummyState("1", start - timedelta(minutes=15))
    inside = DummyState("2", start + timedelta(minutes=5))
    after = DummyState("3", end + timedelta(minutes=5))

    states = [before, inside, after]
    assert history_module._select_interval_states(states, start, end) == [inside]

    states = [before, after]
    assert history_module._select_interval_states(states, start, end) == [before, after]

    assert history_module._select_interval_states([before], start, end) == []


def test_calc_delta_kwh_handles_edge_cases():
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)

    assert history_module._calc_delta_kwh([], start, end) == 0.0

    states = [DummyState("bad", start), DummyState("10", end)]
    assert history_module._calc_delta_kwh(states, start, end) == 0.0

    states = [DummyState("10", start), DummyState("8", end)]
    assert history_module._calc_delta_kwh(states, start, end) == 0.008


def test_get_values_and_parse_start():
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    states = [
        DummyState("1", start),
        DummyState("2", end + timedelta(minutes=1)),
    ]
    assert history_module._get_value_at_end(states, end) == "2"
    assert history_module._get_last_value(states) == "2"
    assert history_module._get_last_value([]) is None
    assert history_module._get_value_at_end([], end) is None

    parsed = history_module._parse_interval_start("2025-01-01T00:00:00")
    assert parsed is not None
    assert history_module._parse_interval_start("bad") is None
    assert history_module._parse_interval_start(None) is None


def test_build_actual_interval_entry_rounding():
    entry = history_module._build_actual_interval_entry(
        datetime(2025, 1, 1, 0, 0),
        {
            "solar_kwh": 0.12345,
            "consumption_kwh": 0.6789,
            "battery_soc": 55.55,
            "battery_capacity_kwh": 4.444,
            "grid_import": 0.3333,
            "grid_export": 0.2222,
            "net_cost": 1.239,
            "spot_price": 5.129,
            "export_price": 2.555,
            "mode": 1,
            "mode_name": "HOME",
        },
    )
    assert entry["solar_kwh"] == 0.1235
    assert entry["battery_soc"] == 55.55


@pytest.mark.asyncio
async def test_fetch_interval_from_history_basic(hass, monkeypatch):
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)

    def _states(start_val, end_val):
        return [DummyState(start_val, start), DummyState(end_val, end)]

    states = {
        "sensor.oig_123_ac_out_en_day": _states("1000", "1500"),
        "sensor.oig_123_ac_in_ac_ad": _states("2000", "2300"),
        "sensor.oig_123_ac_in_ac_pd": _states("0", "100"),
        "sensor.oig_123_dc_in_fv_ad": _states("0", "200"),
        "sensor.oig_123_batt_bat_c": [DummyState("50", end)],
        "sensor.oig_123_box_prms_mode": [DummyState(SERVICE_MODE_HOME_UPS, end)],
        "sensor.oig_123_spot_price_current_15min": [DummyState("5", end)],
        "sensor.oig_123_export_price_current_15min": [DummyState("2", end)],
    }

    def fake_get_significant_states(*_args, **_kwargs):
        return states

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )

    sensor = DummySensor(hass)
    result = await history_module.fetch_interval_from_history(sensor, start, end)

    assert result is not None
    assert result["consumption_kwh"] == 0.5
    assert result["grid_import"] == 0.3
    assert result["grid_export"] == 0.1
    assert result["solar_kwh"] == 0.2
    assert result["battery_soc"] == 50.0
    assert result["battery_kwh"] == 5.0
    assert result["spot_price"] == 5.0
    assert result["export_price"] == 2.0
    assert result["net_cost"] == 1.3
    assert result["mode"] == CBB_MODE_HOME_UPS
    assert result["mode_name"] == CBB_MODE_NAMES[CBB_MODE_HOME_UPS]


@pytest.mark.asyncio
async def test_fetch_interval_from_history_no_hass():
    sensor = DummySensor(None)
    assert (
        await history_module.fetch_interval_from_history(
            sensor,
            datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc),
        )
        is None
    )


@pytest.mark.asyncio
async def test_fetch_interval_from_history_no_states(hass, monkeypatch):
    def fake_get_significant_states(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_interval_from_history(
        sensor,
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc),
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_interval_from_history_exception(hass, monkeypatch):
    def fake_get_significant_states(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_interval_from_history(
        sensor,
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc),
    )
    assert result is None


@pytest.mark.asyncio
async def test_patch_existing_actual(monkeypatch):
    sensor = DummySensor(DummyHass())

    async def fake_fetch(*_args, **_kwargs):
        return {"net_cost": 1.2, "spot_price": 4.5, "export_price": 2.2}

    monkeypatch.setattr(history_module, "fetch_interval_from_history", fake_fetch)
    existing = [
        {"time": "2025-01-01T00:00:00", "net_cost": None},
        {"time": "bad", "net_cost": None},
        {"time": "2025-01-01T00:15:00", "net_cost": 1.0},
    ]
    patched = await history_module._patch_existing_actual(sensor, existing)
    assert patched[0]["net_cost"] == 1.2
    assert patched[1]["time"] == "bad"
    assert patched[2]["net_cost"] == 1.0


@pytest.mark.asyncio
async def test_build_new_actual_intervals(monkeypatch):
    sensor = DummySensor(DummyHass())
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    now = start + timedelta(minutes=30)
    existing_times = {start.isoformat()}

    async def fake_fetch(*_args, **_kwargs):
        return {
            "solar_kwh": 0.1,
            "consumption_kwh": 0.2,
            "battery_soc": 50,
            "battery_capacity_kwh": 5,
            "grid_import": 0.1,
            "grid_export": 0.0,
            "net_cost": 1.0,
            "spot_price": 2.0,
            "export_price": 1.0,
            "mode": 0,
            "mode_name": "HOME I",
        }

    monkeypatch.setattr(history_module, "fetch_interval_from_history", fake_fetch)
    intervals = await history_module._build_new_actual_intervals(
        sensor, start, now, existing_times
    )
    assert len(intervals) == 2


def test_normalize_mode_history():
    history = [
        {"time": "bad", "mode": 1, "mode_name": "Home 1"},
        {"time": "", "mode": 1, "mode_name": "Home 1"},
        {"time": "2025-01-01T00:00:00", "mode": 2, "mode_name": "Home 2"},
    ]
    normalized = history_module._normalize_mode_history(history)
    assert len(normalized) == 1
    assert normalized[0]["mode"] == 2


def test_expand_modes_to_intervals():
    day_start = datetime(2025, 1, 1, 0, 0)
    end = day_start + timedelta(minutes=30)
    changes = [
        {"time": day_start, "mode": 1, "mode_name": "Home 1"},
        {"time": end + timedelta(minutes=15), "mode": 2, "mode_name": "Home 2"},
    ]
    lookup = history_module._expand_modes_to_intervals(changes, day_start, end)
    assert len(lookup) == 3


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_no_hass():
    sensor = DummySensor(None)
    assert (
        await history_module.fetch_mode_history_from_recorder(
            sensor,
            datetime(2025, 1, 1, 0, 0),
            datetime(2025, 1, 1, 1, 0),
        )
        == []
    )


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_empty(hass, monkeypatch):
    def fake_state_changes(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        fake_state_changes,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_mode_history_from_recorder(
        sensor,
        datetime(2025, 1, 1, 0, 0),
        datetime(2025, 1, 1, 1, 0),
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_import_error(monkeypatch):
    sensor = DummySensor(DummyHass())

    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "homeassistant.components.recorder":
            raise ImportError("boom")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = await history_module.fetch_mode_history_from_recorder(
        sensor,
        datetime(2025, 1, 1, 0, 0),
        datetime(2025, 1, 1, 1, 0),
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_empty_states(hass, monkeypatch):
    sensor_id = "sensor.oig_123_box_prms_mode"

    def fake_state_changes(*_args, **_kwargs):
        return {sensor_id: []}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        fake_state_changes,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_mode_history_from_recorder(
        sensor,
        datetime(2025, 1, 1, 0, 0),
        datetime(2025, 1, 1, 1, 0),
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_exception(hass, monkeypatch):
    def fake_state_changes(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        fake_state_changes,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_mode_history_from_recorder(
        sensor,
        datetime(2025, 1, 1, 0, 0),
        datetime(2025, 1, 1, 1, 0),
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_mode_history_from_recorder_filters_states(hass, monkeypatch):
    sensor_id = "sensor.oig_123_box_prms_mode"
    states = [
        SimpleNamespace(state="unavailable", last_changed=datetime(2025, 1, 1, 0, 0)),
        SimpleNamespace(state="Home 1", last_changed=datetime(2025, 1, 1, 0, 15)),
    ]

    def fake_state_changes(*_args, **_kwargs):
        return {sensor_id: states}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.state_changes_during_period",
        fake_state_changes,
    )
    sensor = DummySensor(hass)
    result = await history_module.fetch_mode_history_from_recorder(
        sensor,
        datetime(2025, 1, 1, 0, 0),
        datetime(2025, 1, 1, 1, 0),
    )
    assert len(result) == 1


def test_map_mode_name_to_id_unknown() -> None:
    assert history_module.map_mode_name_to_id("unknown") == CBB_MODE_HOME_I


def test_map_mode_name_to_id_fallbacks():
    assert history_module.map_mode_name_to_id("") == CBB_MODE_HOME_I
    assert history_module.map_mode_name_to_id("Home 6") == CBB_MODE_HOME_I
    assert history_module.map_mode_name_to_id("Home UPS") == CBB_MODE_HOME_UPS
    assert history_module.map_mode_name_to_id("Home X") == CBB_MODE_HOME_I


@pytest.mark.asyncio
async def test_build_historical_modes_lookup(monkeypatch):
    sensor = DummySensor(DummyHass())

    async def fake_fetch(*_args, **_kwargs):
        return [
            {"time": "2025-01-01T00:00:00", "mode": 1, "mode_name": "Home 1"}
        ]

    monkeypatch.setattr(history_module, "fetch_mode_history_from_recorder", fake_fetch)
    lookup = await history_module.build_historical_modes_lookup(
        sensor,
        day_start=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        fetch_end=datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
        date_str="2025-01-01",
        source="test",
    )
    assert lookup


@pytest.mark.asyncio
async def test_build_historical_modes_lookup_no_hass():
    sensor = DummySensor(None)
    lookup = await history_module.build_historical_modes_lookup(
        sensor,
        day_start=datetime(2025, 1, 1, 0, 0),
        fetch_end=datetime(2025, 1, 1, 0, 30),
        date_str="2025-01-01",
        source="test",
    )
    assert lookup == {}


@pytest.mark.asyncio
async def test_update_actual_from_history_no_plan(monkeypatch):
    sensor = DummySensor(DummyHass())
    async def fake_load(*_args, **_kwargs):
        return None

    sensor._load_plan_from_storage = fake_load
    sensor._daily_plan_state = None

    await history_module.update_actual_from_history(sensor)


@pytest.mark.asyncio
async def test_update_actual_from_history_updates(monkeypatch):
    sensor = DummySensor(DummyHass())
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    async def fake_load(*_args, **_kwargs):
        return {"intervals": []}

    async def fake_patch(*_args, **_kwargs):
        return []

    async def fake_build(*_args, **_kwargs):
        return [{"time": now.isoformat()}]

    monkeypatch.setattr(history_module.dt_util, "now", lambda: now)
    monkeypatch.setattr(history_module, "_patch_existing_actual", fake_patch)
    monkeypatch.setattr(history_module, "_build_new_actual_intervals", fake_build)
    sensor._load_plan_from_storage = fake_load
    sensor._daily_plan_state = None

    await history_module.update_actual_from_history(sensor)
    assert sensor._daily_plan_state is not None


@pytest.mark.asyncio
async def test_update_actual_from_history_existing_state(monkeypatch):
    sensor = DummySensor(DummyHass())
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    async def fake_load(*_args, **_kwargs):
        return {"intervals": []}

    async def fake_patch(*_args, **_kwargs):
        return []

    async def fake_build(*_args, **_kwargs):
        return []

    monkeypatch.setattr(history_module.dt_util, "now", lambda: now)
    monkeypatch.setattr(history_module, "_patch_existing_actual", fake_patch)
    monkeypatch.setattr(history_module, "_build_new_actual_intervals", fake_build)
    sensor._load_plan_from_storage = fake_load
    sensor._daily_plan_state = {"date": now.strftime("%Y-%m-%d"), "actual": [{"time": "t"}]}

    await history_module.update_actual_from_history(sensor)
