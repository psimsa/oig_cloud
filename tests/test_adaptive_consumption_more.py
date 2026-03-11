from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.battery_forecast.data import adaptive_consumption as module


class DummyState:
    def __init__(self, attributes):
        self.attributes = attributes


class DummyStates:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class DummyHass:
    def __init__(self, states):
        self.states = DummyStates(states)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def test_normalize_profile_name_empty():
    assert module.AdaptiveConsumptionHelper._normalize_profile_name("") == ""


def test_normalize_profile_name_fallback():
    assert module.AdaptiveConsumptionHelper._normalize_profile_name(None) == "None"


def test_build_profile_suffix_invalid_values():
    profile = {"characteristics": {"season": "winter"}, "sample_count": "bad"}
    ui = {"sample_count": "bad", "similarity_score": "oops"}
    suffix = module.AdaptiveConsumptionHelper._build_profile_suffix(profile, ui)
    assert "zimní" in suffix


def test_build_dashboard_profile_details_no_score():
    details = module.AdaptiveConsumptionHelper._build_dashboard_profile_details(
        {"season": "winter", "day_count": 0}, 0
    )
    assert details == "zimní"


def test_calculate_charging_cost_today_invalid_rows():
    now = datetime.now()
    timeline = [
        {"timestamp": None},
        {"timestamp": "bad"},
        {
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "charging_kwh": 2.0,
            "spot_price_czk_per_kwh": 5.0,
        },
        {
            "timestamp": now.isoformat(),
            "charging_kwh": 0,
            "spot_price_czk_per_kwh": 5.0,
        },
    ]
    total = module.AdaptiveConsumptionHelper._calculate_charging_cost_today(
        timeline, now.date(), "+00:00"
    )
    assert total == 0.0


def test_season_and_transition_helpers():
    assert module.AdaptiveConsumptionHelper._season_for_month(3) == "spring"
    assert module.AdaptiveConsumptionHelper._season_for_month(10) == "autumn"
    assert (
        module.AdaptiveConsumptionHelper._transition_type(6, 0)
        == "sunday_to_monday"
    )


def test_select_profile_by_prefix():
    profiles = {
        "weekday_winter_typical": {"id": "typ"},
        "weekday_winter_alt": {"id": "alt"},
    }
    selected = module.AdaptiveConsumptionHelper._select_profile_by_prefix(
        profiles, "weekday_winter", prefer_typical=True
    )
    assert selected["id"] == "typ"


def test_process_adaptive_consumption_invalid_profiles():
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert helper.process_adaptive_consumption_for_dashboard(None, []) == {}


def test_calculate_consumption_summary_invalid_type():
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert helper.calculate_consumption_summary("bad") == {}


@pytest.mark.asyncio
async def test_get_adaptive_load_prediction_variants():
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert await helper.get_adaptive_load_prediction() is None

    state = DummyState({"today_profile": {"total_kwh": 1}, "tomorrow_profile": {}})
    hass = DummyHass({"sensor.oig_123_adaptive_load_profiles": state})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    result = await helper.get_adaptive_load_prediction()
    assert result["match_score"] == 0.0

    state = DummyState({})
    hass = DummyHass({"sensor.oig_123_adaptive_load_profiles": state})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert await helper.get_adaptive_load_prediction() is None

    hass = DummyHass({})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert await helper.get_adaptive_load_prediction() is None

    class BadStates(DummyStates):
        def get(self, _entity_id):
            raise RuntimeError("boom")

    bad_hass = DummyHass({})
    bad_hass.states = BadStates({})
    helper = module.AdaptiveConsumptionHelper(bad_hass, "123")
    assert await helper.get_adaptive_load_prediction() is None


def test_get_profiles_from_sensor_variants():
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert helper.get_profiles_from_sensor() == {}

    state = DummyState({"profiles": [{"profile_id": "a"}, {"profile_id": "b"}]})
    helper = module.AdaptiveConsumptionHelper(
        DummyHass({"sensor.oig_123_adaptive_load_profiles": state}), "123"
    )
    profiles = helper.get_profiles_from_sensor()
    assert profiles["a"]["profile_id"] == "a"

    state = DummyState({"profiles": {"x": {"id": 1}}})
    helper = module.AdaptiveConsumptionHelper(
        DummyHass({"sensor.oig_123_adaptive_load_profiles": state}), "123"
    )
    assert helper.get_profiles_from_sensor()["x"]["id"] == 1

    state = DummyState({"profiles": "bad"})
    helper = module.AdaptiveConsumptionHelper(
        DummyHass({"sensor.oig_123_adaptive_load_profiles": state}), "123"
    )
    assert helper.get_profiles_from_sensor() == {}

    helper = module.AdaptiveConsumptionHelper(DummyHass({}), "123")
    assert helper.get_profiles_from_sensor() == {}

    class BadStates(DummyStates):
        def get(self, _entity_id):
            raise RuntimeError("boom")

    bad_hass = DummyHass({})
    bad_hass.states = BadStates({})
    helper = module.AdaptiveConsumptionHelper(bad_hass, "123")
    assert helper.get_profiles_from_sensor() == {}


@pytest.mark.asyncio
async def test_get_today_hourly_consumption_variants(monkeypatch):
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert await helper.get_today_hourly_consumption() == []

    from homeassistant.components.recorder import statistics as rec_stats

    def _stats(_hass, *_a, **_k):
        return {"sensor.oig_123_actual_aco_p": [{"mean": 2000}, {"mean": None}]}

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)

    helper = module.AdaptiveConsumptionHelper(DummyHass({}), "123")
    result = await helper.get_today_hourly_consumption()
    assert result == [2.0]

    def _stats_empty(_hass, *_a, **_k):
        return {}

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats_empty)
    result = await helper.get_today_hourly_consumption()
    assert result == []

    def _stats_error(_hass, *_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats_error)
    result = await helper.get_today_hourly_consumption()
    assert result == []


@pytest.mark.asyncio
async def test_calculate_recent_consumption_ratio_variants(monkeypatch):
    helper = module.AdaptiveConsumptionHelper(DummyHass({}), "123")
    assert await helper.calculate_recent_consumption_ratio(None) is None

    async def _empty():
        return []

    helper.get_today_hourly_consumption = _empty
    assert (
        await helper.calculate_recent_consumption_ratio(
            {"today_profile": {"hourly_consumption": [1]}}
        )
        is None
    )

    async def _hourly():
        return [1.0, 2.0, 3.0]

    helper.get_today_hourly_consumption = _hourly
    assert (
        await helper.calculate_recent_consumption_ratio(
            {"today_profile": {"hourly_consumption": "bad"}}
        )
        is None
    )

    ratio = await helper.calculate_recent_consumption_ratio(
        {"today_profile": {"hourly_consumption": [1, 1, 1], "start_hour": 0}}
    )
    assert ratio is not None

    ratio = await helper.calculate_recent_consumption_ratio(
        {"today_profile": {"hourly_consumption": [0, 0, 0], "start_hour": 0}}
    )
    assert ratio is None

    ratio = await helper.calculate_recent_consumption_ratio(
        {"today_profile": {"hourly_consumption": [1], "start_hour": 10}}
    )
    assert ratio is not None

    class ZeroLenTruthy(list):
        def __len__(self):
            return 0

        def __bool__(self):
            return True

    async def _zero_len():
        return ZeroLenTruthy()

    helper.get_today_hourly_consumption = _zero_len
    assert (
        await helper.calculate_recent_consumption_ratio(
            {"today_profile": {"hourly_consumption": [1]}}
        )
        is None
    )


def test_apply_consumption_boost_and_similarity():
    forecast = [1.0, 1.0, 1.0, 1.0]
    module.AdaptiveConsumptionHelper.apply_consumption_boost_to_forecast(
        forecast, 0.5, hours=1
    )
    assert forecast[0] == 0.5

    empty = []
    module.AdaptiveConsumptionHelper.apply_consumption_boost_to_forecast(
        empty, 2.0, hours=1
    )
    assert empty == []

    assert module.AdaptiveConsumptionHelper.calculate_profile_similarity([], []) == 0
    assert (
        module.AdaptiveConsumptionHelper.calculate_profile_similarity([0, 0], [1, 1])
        == 0
    )
    assert (
        module.AdaptiveConsumptionHelper.calculate_profile_similarity([1, 2], [1, 2])
        == 100.0
    )


def test_select_tomorrow_profile_error():
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert helper.select_tomorrow_profile(None, datetime.now()) is None


@pytest.mark.asyncio
async def test_get_consumption_today_variants(monkeypatch):
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert await helper.get_consumption_today() is None

    from homeassistant.components.recorder import history

    def _states_none(*_a, **_k):
        return {}

    hass = DummyHass({})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    monkeypatch.setattr(history, "get_significant_states", _states_none)
    assert await helper.get_consumption_today() is None

    def _states_bad(*_a, **_k):
        return {"sensor.oig_123_actual_aco_p": []}

    monkeypatch.setattr(history, "get_significant_states", _states_bad)
    assert await helper.get_consumption_today() is None

    class DummyStateValue:
        def __init__(self, state):
            self.state = state

    def _states_values(*_a, **_k):
        return {
            "sensor.oig_123_actual_aco_p": [
                DummyStateValue("1000"),
                DummyStateValue("bad"),
            ]
        }

    monkeypatch.setattr(history, "get_significant_states", _states_values)
    value = await helper.get_consumption_today()
    assert value is not None

    def _states_invalid(*_a, **_k):
        return {
            "sensor.oig_123_actual_aco_p": [
                DummyStateValue("-1"),
                DummyStateValue("999999"),
            ]
        }

    monkeypatch.setattr(history, "get_significant_states", _states_invalid)
    assert await helper.get_consumption_today() is None

    def _states_error(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(history, "get_significant_states", _states_error)
    assert await helper.get_consumption_today() is None


def test_get_load_avg_fallback_variants(monkeypatch):
    helper = module.AdaptiveConsumptionHelper(None, "123")
    assert helper.get_load_avg_fallback() == 0.48

    class DummyStateValue:
        def __init__(self, state):
            self.state = state

    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 23, 0))
    hass = DummyHass({"sensor.oig_123_load_avg_22_6_weekday": DummyStateValue("1000")})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    value = helper.get_load_avg_fallback()
    assert value > 0

    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 7, 0))
    hass = DummyHass({"sensor.oig_123_load_avg_6_8_weekday": DummyStateValue("bad")})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert helper.get_load_avg_fallback() == 0.48

    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 13, 0))
    hass = DummyHass({"sensor.oig_123_load_avg_12_16_weekday": DummyStateValue("1000")})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert helper.get_load_avg_fallback() > 0

    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 9, 0))
    hass = DummyHass({"sensor.oig_123_load_avg_8_12_weekday": DummyStateValue("1000")})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert helper.get_load_avg_fallback() > 0

    monkeypatch.setattr(module.dt_util, "now", lambda: datetime(2025, 1, 1, 18, 0))
    hass = DummyHass({"sensor.oig_123_load_avg_16_22_weekday": DummyStateValue("1000")})
    helper = module.AdaptiveConsumptionHelper(hass, "123")
    assert helper.get_load_avg_fallback() > 0
