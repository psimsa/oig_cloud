from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.oig_cloud.battery_forecast.data import history as history_module
from custom_components.oig_cloud.battery_forecast.types import (
    CBBMode,
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    get_mode_name,
    get_service_name,
    is_charging_mode,
    mode_from_name,
    safe_nested_get,
)


class TestCBBTypes:
    def test_mode_values(self):
        assert CBBMode.HOME_I == 0
        assert CBBMode.HOME_II == 1
        assert CBBMode.HOME_III == 2
        assert CBBMode.HOME_UPS == 3

    def test_legacy_constants(self):
        assert CBB_MODE_HOME_I == 0
        assert CBB_MODE_HOME_II == 1
        assert CBB_MODE_HOME_III == 2
        assert CBB_MODE_HOME_UPS == 3

    def test_mode_names(self):
        assert CBB_MODE_NAMES[CBB_MODE_HOME_I] == "HOME I"
        assert CBB_MODE_NAMES[CBB_MODE_HOME_II] == "HOME II"
        assert CBB_MODE_NAMES[CBB_MODE_HOME_III] == "HOME III"
        assert CBB_MODE_NAMES[CBB_MODE_HOME_UPS] == "HOME UPS"

    def test_get_mode_name_known(self):
        assert get_mode_name(CBB_MODE_HOME_I) == "HOME I"
        assert get_mode_name(CBB_MODE_HOME_II) == "HOME II"
        assert get_mode_name(CBB_MODE_HOME_III) == "HOME III"
        assert get_mode_name(CBB_MODE_HOME_UPS) == "HOME UPS"

    def test_get_mode_name_unknown(self):
        assert get_mode_name(99) == "UNKNOWN (99)"

    def test_get_service_name_known(self):
        assert get_service_name(CBB_MODE_HOME_I) == "Home 1"
        assert get_service_name(CBB_MODE_HOME_II) == "Home 2"
        assert get_service_name(CBB_MODE_HOME_III) == "Home 3"
        assert get_service_name(CBB_MODE_HOME_UPS) == "Home UPS"

    def test_get_service_name_unknown(self):
        assert get_service_name(99) == "Home 1"

    def test_is_charging_mode(self):
        assert is_charging_mode(CBB_MODE_HOME_UPS) is True
        assert is_charging_mode(CBB_MODE_HOME_I) is False
        assert is_charging_mode(CBB_MODE_HOME_II) is False
        assert is_charging_mode(CBB_MODE_HOME_III) is False

    def test_mode_from_name_exact(self):
        assert mode_from_name("HOME I") == CBB_MODE_HOME_I
        assert mode_from_name("HOME II") == CBB_MODE_HOME_II
        assert mode_from_name("HOME III") == CBB_MODE_HOME_III
        assert mode_from_name("HOME UPS") == CBB_MODE_HOME_UPS

    def test_mode_from_name_variations(self):
        assert mode_from_name("Home I") == CBB_MODE_HOME_I
        assert mode_from_name("Home 1") == CBB_MODE_HOME_I
        assert mode_from_name("Home II") == CBB_MODE_HOME_II
        assert mode_from_name("Home 2") == CBB_MODE_HOME_II
        assert mode_from_name("Home III") == CBB_MODE_HOME_III
        assert mode_from_name("Home 3") == CBB_MODE_HOME_III
        assert mode_from_name("Home UPS") == CBB_MODE_HOME_UPS

    def test_mode_from_name_unknown(self):
        assert mode_from_name("Unknown Mode") == CBB_MODE_HOME_I

    def test_mode_from_name_empty(self):
        assert mode_from_name("") == CBB_MODE_HOME_I

    def test_mode_from_name_none(self):
        with pytest.raises(AttributeError):
            getattr(history_module, "mode_from_name")(None)


class TestSafeNestedGet:
    def test_safe_nested_get_basic(self):
        data = {"a": {"b": {"c": 42}}}
        assert safe_nested_get(data, "a", "b", "c") == 42

    def test_safe_nested_get_missing_key(self):
        data = {"a": {"b": {}}}
        assert safe_nested_get(data, "a", "b", "c") == 0

    def test_safe_nested_get_none_middle(self):
        data = {"a": None}
        assert safe_nested_get(data, "a", "b") == 0

    def test_safe_nested_get_none_value(self):
        data = {"a": {"b": None}}
        assert safe_nested_get(data, "a", "b") == 0

    def test_safe_nested_get_custom_default(self):
        data = {"a": {}}
        assert safe_nested_get(data, "a", "b", default="fallback") == "fallback"

    def test_safe_nested_get_non_dict(self):
        data = {"a": "string"}
        assert safe_nested_get(data, "a", "b") == 0

    def test_safe_nested_get_empty_keys(self):
        data = {"a": 1}
        assert safe_nested_get(data) == {"a": 1}

    def test_safe_nested_get_none_obj(self):
        assert safe_nested_get(None, "a") == 0


class TestHistoryHelpers:
    def test_safe_float_valid(self):
        assert history_module._safe_float("3.14") == 3.14
        assert history_module._safe_float(42) == 42.0

    def test_safe_float_invalid(self):
        assert history_module._safe_float("not_a_number") is None
        assert history_module._safe_float(None) is None

    def test_build_history_entity_ids(self):
        ids = history_module._build_history_entity_ids("12345")
        assert f"sensor.oig_12345_ac_out_en_day" in ids
        assert f"sensor.oig_12345_batt_bat_c" in ids
        assert len(ids) == 8

    def test_as_utc_with_tz(self):
        dt_local = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert history_module._as_utc(dt_local) == dt_local

    def test_as_utc_without_tz(self):
        dt_naive = datetime(2024, 1, 1, 12, 0)
        result = history_module._as_utc(dt_naive)
        assert result == dt_naive

    def test_state_last_updated_utc(self):
        state = SimpleNamespace(last_updated=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc))
        assert history_module._state_last_updated_utc(state) == state.last_updated

    def test_get_last_value_empty(self):
        assert history_module._get_last_value([]) is None

    def test_get_last_value(self):
        states = [SimpleNamespace(state="10"), SimpleNamespace(state="20")]
        assert history_module._get_last_value(states) == "20"

    def test_get_value_at_end_empty(self):
        assert history_module._get_value_at_end([], datetime.now()) is None

    def test_get_value_at_end_closest(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="10", last_updated=t1), SimpleNamespace(state="20", last_updated=t2)]
        result = history_module._get_value_at_end(states, t2)
        assert result == "20"

    def test_select_interval_states_empty(self):
        assert history_module._select_interval_states([], datetime.now(), datetime.now()) == []

    def test_select_interval_states_within_range(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="10", last_updated=t1), SimpleNamespace(state="20", last_updated=t2)]
        result = history_module._select_interval_states(states, t1, t2)
        assert len(result) == 2

    def test_select_interval_states_fallback_before_after(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        t3 = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="10", last_updated=t1), SimpleNamespace(state="30", last_updated=t3)]
        result = history_module._select_interval_states(states, t2, t2)
        assert len(result) == 2
        assert result[0].state == "10"
        assert result[1].state == "30"

    def test_select_interval_states_no_match(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="10", last_updated=t1)]
        result = history_module._select_interval_states(states, t1 + timedelta(hours=1), t1 + timedelta(hours=2))
        assert result == []

    def test_calc_delta_kwh_normal(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="1000", last_updated=t1), SimpleNamespace(state="2000", last_updated=t2)]
        result = history_module._calc_delta_kwh(states, t1, t2)
        assert result == 1.0

    def test_calc_delta_kwh_negative_wrap(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="2000", last_updated=t1), SimpleNamespace(state="500", last_updated=t2)]
        result = history_module._calc_delta_kwh(states, t1, t2)
        assert result == 0.5

    def test_calc_delta_kwh_insufficient_states(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="1000", last_updated=t1)]
        result = history_module._calc_delta_kwh(states, t1, t1 + timedelta(minutes=15))
        assert result == 0.0

    def test_calc_delta_kwh_invalid_state(self):
        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 1, 12, 15, tzinfo=timezone.utc)
        states = [SimpleNamespace(state="abc", last_updated=t1), SimpleNamespace(state="1000", last_updated=t2)]
        result = history_module._calc_delta_kwh(states, t1, t2)
        assert result == 0.0

    def test_parse_interval_start_none(self):
        assert history_module._parse_interval_start(None) is None
        assert history_module._parse_interval_start("") is None

    def test_parse_interval_start_iso(self):
        dt = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        result = history_module._parse_interval_start(dt.isoformat())
        assert result is not None

    def test_parse_interval_start_invalid(self):
        assert history_module._parse_interval_start("not-a-date") is None

    def test_build_actual_interval_entry(self):
        data = {
            "solar_kwh": 1.23456,
            "consumption_kwh": 2.34567,
            "battery_soc": 55.555,
            "battery_capacity_kwh": 10.12345,
            "grid_import": 0.5,
            "grid_export": 0.3,
            "net_cost": 12.345,
            "spot_price": 5.5,
            "export_price": 2.2,
            "mode": 1,
            "mode_name": "HOME II",
        }
        interval_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        result = history_module._build_actual_interval_entry(interval_time, data)
        assert result["time"] == interval_time.isoformat()
        assert result["solar_kwh"] == 1.2346
        assert result["consumption_kwh"] == 2.3457
        assert result["battery_soc"] == 55.55
        assert result["mode"] == 1
        assert result["mode_name"] == "HOME II"

    def test_build_actual_interval_entry_defaults(self):
        data = {}
        interval_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        result = history_module._build_actual_interval_entry(interval_time, data)
        assert result["solar_kwh"] == 0
        assert result["mode_name"] == "N/A"

    def test_normalize_mode_history(self):
        history = [
            {"time": "2024-01-01T12:00:00+00:00", "mode": 0, "mode_name": "HOME I"},
            {"time": "2024-01-01T13:00:00+00:00", "mode": 1, "mode_name": "HOME II"},
        ]
        result = history_module._normalize_mode_history(history)
        assert len(result) == 2
        assert result[0]["mode"] == 0
        assert result[1]["mode"] == 1

    def test_normalize_mode_history_no_time(self):
        history = [{"mode": 0, "mode_name": "HOME I"}]
        result = history_module._normalize_mode_history(history)
        assert result == []

    def test_normalize_mode_history_invalid_time(self):
        history = [{"time": "invalid", "mode": 0, "mode_name": "HOME I"}]
        result = history_module._normalize_mode_history(history)
        assert result == []

    def test_normalize_mode_history_naive_time(self):
        history = [{"time": "2024-01-01T12:00:00", "mode": 0, "mode_name": "HOME I"}]
        result = history_module._normalize_mode_history(history)
        assert len(result) == 1
        assert result[0]["time"].tzinfo is not None

    def test_expand_modes_to_intervals(self):
        day_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        fetch_end = day_start + timedelta(minutes=15)
        mode_changes = [
            {"time": day_start, "mode": 0, "mode_name": "HOME I"},
        ]
        result = history_module._expand_modes_to_intervals(mode_changes, day_start, fetch_end)
        assert len(result) == 2
        assert list(result.values())[0]["mode"] == 0

    def test_expand_modes_to_intervals_no_changes(self):
        day_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        fetch_end = day_start + timedelta(minutes=15)
        result = history_module._expand_modes_to_intervals([], day_start, fetch_end)
        assert len(result) == 0

    def test_expand_modes_to_intervals_multiple_intervals(self):
        day_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        fetch_end = day_start + timedelta(minutes=30)
        mode_changes = [
            {"time": day_start, "mode": 0, "mode_name": "HOME I"},
        ]
        result = history_module._expand_modes_to_intervals(mode_changes, day_start, fetch_end)
        assert len(result) == 3


class TestMapModeNameToId:
    def test_known_modes(self):
        assert history_module.map_mode_name_to_id("Home 1") == CBB_MODE_HOME_I
        assert history_module.map_mode_name_to_id("Home 2") == CBB_MODE_HOME_II
        assert history_module.map_mode_name_to_id("Home 3") == CBB_MODE_HOME_III
        assert history_module.map_mode_name_to_id("Home UPS") == CBB_MODE_HOME_UPS

    def test_unknown_mode_fallback(self):
        assert history_module.map_mode_name_to_id("Mystery Mode") == CBB_MODE_HOME_I

    def test_empty_mode(self):
        assert history_module.map_mode_name_to_id("") == CBB_MODE_HOME_I
        assert getattr(history_module, "map_mode_name_to_id")(None) == CBB_MODE_HOME_I

    def test_unavailable_modes(self):
        assert history_module.map_mode_name_to_id("unknown") == CBB_MODE_HOME_I
        assert history_module.map_mode_name_to_id("unavailable") == CBB_MODE_HOME_I
        assert history_module.map_mode_name_to_id("neznámý") == CBB_MODE_HOME_I
        assert history_module.map_mode_name_to_id("neznamy") == CBB_MODE_HOME_I


class TestAsyncHistoryFunctions:
    async def test_patch_existing_actual_with_net_cost(self):
        existing = [{"time": "2024-01-01T12:00:00+00:00", "net_cost": 5.0}]
        sensor = MagicMock()
        result = await history_module._patch_existing_actual(sensor, existing)
        assert len(result) == 1
        assert result[0]["net_cost"] == 5.0

    async def test_patch_existing_actual_invalid_time(self):
        existing = [{"time": "invalid", "net_cost": None}]
        sensor = MagicMock()
        result = await history_module._patch_existing_actual(sensor, existing)
        assert len(result) == 1

    async def test_build_new_actual_intervals_skips_existing(self):
        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = start
        existing_times = {start.isoformat()}
        sensor = MagicMock()

        with patch.object(history_module, "fetch_interval_from_history", new_callable=AsyncMock) as mock_fetch:
            result = await history_module._build_new_actual_intervals(sensor, start, now, existing_times)
            assert result == []
            mock_fetch.assert_not_awaited()

    async def test_build_new_actual_intervals_fetch_new(self):
        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = start
        existing_times = set()
        sensor = MagicMock()

        with patch.object(history_module, "fetch_interval_from_history", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {"solar_kwh": 1.0}
            result = await history_module._build_new_actual_intervals(sensor, start, now, existing_times)
            assert len(result) == 1
            mock_fetch.assert_awaited_once()

    async def test_build_new_actual_intervals_no_data(self):
        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = start
        existing_times = set()
        sensor = MagicMock()

        with patch.object(history_module, "fetch_interval_from_history", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            result = await history_module._build_new_actual_intervals(sensor, start, now, existing_times)
            assert result == []

    async def test_fetch_mode_history_no_hass(self):
        sensor = MagicMock()
        sensor._hass = None
        result = await history_module.fetch_mode_history_from_recorder(sensor, datetime.now(), datetime.now())
        assert result == []

    async def test_fetch_mode_history_empty_states(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                return {}

        with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
            result = await history_module.fetch_mode_history_from_recorder(sensor, datetime.now(), datetime.now())
            assert result == []

    async def test_fetch_mode_history_with_states(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()

        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        state = SimpleNamespace(state="Home 1", last_changed=t1)

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                return {f"sensor.oig_12345_box_prms_mode": [state]}

        with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
            result = await history_module.fetch_mode_history_from_recorder(sensor, t1, t1 + timedelta(hours=1))
            assert len(result) == 1
            assert result[0]["mode"] == CBB_MODE_HOME_I

    async def test_fetch_mode_history_unknown_state(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()

        t1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        state = SimpleNamespace(state="unavailable", last_changed=t1)

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                return {f"sensor.oig_12345_box_prms_mode": [state]}

        with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
            result = await history_module.fetch_mode_history_from_recorder(sensor, t1, t1 + timedelta(hours=1))
            assert result == []

    async def test_fetch_mode_history_import_error(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()

        with patch("homeassistant.helpers.recorder.get_instance", side_effect=ImportError("no recorder")):
            result = await history_module.fetch_mode_history_from_recorder(sensor, datetime.now(), datetime.now())
            assert result == []

    async def test_fetch_mode_history_exception(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()

        with patch("homeassistant.helpers.recorder.get_instance", side_effect=RuntimeError("boom")):
            result = await history_module.fetch_mode_history_from_recorder(sensor, datetime.now(), datetime.now())
            assert result == []

    async def test_build_historical_modes_lookup_no_hass(self):
        sensor = MagicMock()
        sensor._hass = None
        result = await history_module.build_historical_modes_lookup(
            sensor, day_start=datetime.now(), fetch_end=datetime.now(), date_str="2024-01-01", source="test"
        )
        assert result == {}

    async def test_update_actual_from_history_no_plan(self):
        sensor = MagicMock()
        sensor._hass = MagicMock()
        sensor._box_id = "12345"
        sensor._load_plan_from_storage = AsyncMock(return_value=None)

        with patch.object(history_module, "dt_util"):
            result = await history_module.update_actual_from_history(sensor)
            assert result is None

    async def test_fetch_interval_from_history_no_hass(self):
        sensor = MagicMock()
        sensor._hass = None
        result = await history_module.fetch_interval_from_history(sensor, datetime.now(), datetime.now())
        assert result is None

    async def test_fetch_interval_from_history_with_data(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()
        sensor._get_total_battery_capacity = MagicMock(return_value=10.0)
        sensor._log_rate_limited = None

        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)

        def _state(value, ts):
            return SimpleNamespace(state=str(value), last_updated=ts)

        states = {
            f"sensor.oig_12345_ac_out_en_day": [_state(1000, start), _state(1500, end)],
            f"sensor.oig_12345_ac_in_ac_ad": [_state(200, start), _state(400, end)],
            f"sensor.oig_12345_ac_in_ac_pd": [_state(50, start), _state(150, end)],
            f"sensor.oig_12345_dc_in_fv_ad": [_state(300, start), _state(900, end)],
            f"sensor.oig_12345_batt_bat_c": [_state(60, end)],
            f"sensor.oig_12345_box_prms_mode": [_state("Home 2", end)],
            f"sensor.oig_12345_spot_price_current_15min": [_state(5.0, end)],
            f"sensor.oig_12345_export_price_current_15min": [_state(2.0, end)],
        }

        def fake_get_significant_states(_hass, _start, _end, entity_ids, *_args, **_kwargs):
            return {eid: states.get(eid, []) for eid in entity_ids}

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        with patch("homeassistant.components.recorder.history.get_significant_states", fake_get_significant_states):
            with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
                result = await history_module.fetch_interval_from_history(sensor, start, end)
                assert result is not None
                assert result["consumption_kwh"] == 0.5
                assert result["grid_import"] == 0.2
                assert result["grid_export"] == 0.1
                assert result["solar_kwh"] == 0.6
                assert result["battery_kwh"] == 6.0
                assert result["mode"] == CBB_MODE_HOME_II

    async def test_fetch_interval_from_history_no_states(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()
        sensor._get_total_battery_capacity = MagicMock(return_value=10.0)
        sensor._log_rate_limited = None

        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)

        def fake_get_significant_states(_hass, _start, _end, entity_ids, *_args, **_kwargs):
            return {}

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        with patch("homeassistant.components.recorder.history.get_significant_states", fake_get_significant_states):
            with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
                result = await history_module.fetch_interval_from_history(sensor, start, end)
                assert result is None

    async def test_fetch_interval_from_history_exception(self):
        sensor = MagicMock()
        sensor._box_id = "12345"
        sensor._hass = MagicMock()
        sensor._log_rate_limited = None

        start = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)

        class MockRecorder:
            async def async_add_executor_job(self, func, *args):
                raise RuntimeError("recorder error")

        with patch("homeassistant.helpers.recorder.get_instance", return_value=MockRecorder()):
            result = await history_module.fetch_interval_from_history(sensor, start, end)
            assert result is None
