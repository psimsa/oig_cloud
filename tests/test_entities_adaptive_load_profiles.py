from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.adaptive_load_profiles_sensor import (
    OigCloudAdaptiveLoadProfilesSensor,
    _generate_profile_name,
    _get_season,
)


class DummyCoordinator:
    def __init__(self):
        self.data = {}
        self.forced_box_id = "123"
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyStates:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, entity_id):
        return self._mapping.get(entity_id)


def _make_sensor():
    coordinator = DummyCoordinator()
    entry = SimpleNamespace()
    device_info = {"identifiers": {("oig_cloud", "123")}}
    return OigCloudAdaptiveLoadProfilesSensor(
        coordinator,
        "adaptive_load_profiles",
        entry,
        device_info,
    )


def test_get_season():
    assert _get_season(datetime(2025, 1, 1)) == "winter"
    assert _get_season(datetime(2025, 4, 1)) == "spring"
    assert _get_season(datetime(2025, 7, 1)) == "summer"
    assert _get_season(datetime(2025, 10, 1)) == "autumn"


def test_generate_profile_name_winter_heating():
    hourly = [0.6] * 18 + [1.6] * 6
    name = _generate_profile_name(hourly, "winter", False)
    assert name == "Pracovn\u00ed den s topen\u00edm"


def test_generate_profile_name_weekend_morning_spike():
    hourly = [0.4] * 6 + [1.2] * 6 + [0.4] * 12
    name = _generate_profile_name(hourly, "spring", True)
    assert name == "V\u00edkend s pran\u00edm"


def test_generate_profile_name_invalid_length():
    assert _generate_profile_name([1.0], "summer", False) == "Nezn\u00e1m\u00fd profil"


def test_fill_missing_values_linear():
    sensor = _make_sensor()
    filled, interpolated = sensor._fill_missing_values(
        [1.0, None, 3.0],
        hour_medians={1: 2.0},
        day_avg=2.0,
        global_median=2.0,
    )
    assert filled == [1.0, 2.0, 3.0]
    assert interpolated == 1


def test_build_daily_profiles_interpolates():
    sensor = _make_sensor()
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    hourly_series = []

    for hour in range(24):
        if hour not in (5, 6):
            hourly_series.append((day1.replace(hour=hour), 1.0))
    for hour in range(24):
        hourly_series.append((day2.replace(hour=hour), 2.0))

    profiles, medians, interpolated = sensor._build_daily_profiles(hourly_series)

    assert len(profiles) == 2
    assert medians[5] == 2.0
    assert interpolated[day1.date()] == 2
    assert profiles[day1.date()][5] == 1.0


def test_build_72h_profiles():
    sensor = _make_sensor()
    base = datetime(2025, 1, 1).date()
    daily_profiles = {
        base: [1.0] * 24,
        base + timedelta(days=1): [2.0] * 24,
        base + timedelta(days=2): [3.0] * 24,
    }
    profiles = sensor._build_72h_profiles(daily_profiles)

    assert len(profiles) == 1
    assert profiles[0]["total_consumption"] == 144.0
    assert len(profiles[0]["consumption_kwh"]) == 72


def test_build_current_match(monkeypatch):
    sensor = _make_sensor()
    fixed_now = datetime(2025, 1, 2, 5, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: fixed_now,
    )

    hourly_series = [
        (datetime(2025, 1, 1, hour), 1.0) for hour in range(24)
    ] + [(datetime(2025, 1, 2, hour), 2.0) for hour in range(5)]
    hour_medians = {hour: 1.0 for hour in range(24)}

    match = sensor._build_current_match(hourly_series, hour_medians)

    assert match is not None
    assert len(match) == 29
    assert match[0] == 1.0
    assert match[-1] == 2.0


def test_apply_floor_to_prediction():
    sensor = _make_sensor()
    predicted = [0.1, 0.2]
    adjusted, applied = sensor._apply_floor_to_prediction(
        predicted,
        start_hour=0,
        hour_medians={0: 1.0, 1: 1.0},
        recent_match=[1.0] * 24,
    )

    assert applied == 2
    assert adjusted[0] >= 0.35
    assert adjusted[1] >= 0.35


def test_calculate_profile_similarity():
    sensor = _make_sensor()
    score = sensor._calculate_profile_similarity([1.0, 2.0], [1.0, 2.0])
    assert score > 0.99

    mismatch = sensor._calculate_profile_similarity([1.0], [1.0, 2.0])
    assert mismatch == 0.0


def test_extra_state_attributes_with_prediction(monkeypatch):
    sensor = _make_sensor()
    fixed_now = datetime(2025, 1, 2, 20, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: fixed_now,
    )

    sensor._profiling_status = "ok"
    sensor._profiling_error = None
    sensor._last_profile_reason = "matched"
    sensor._last_profile_created = fixed_now - timedelta(hours=1)

    predicted = [0.5] * 10
    sensor._current_prediction = {
        "similarity_score": 0.82,
        "predicted_consumption": predicted,
        "predicted_total_kwh": sum(predicted),
        "predicted_avg_kwh": 0.5,
        "sample_count": 3,
        "match_hours": 6,
        "predict_hours": len(predicted),
        "matched_profile_full": [0.2] * 72,
        "data_source": "sensor.oig_123_ac_out_en_day",
        "floor_applied": 2,
        "interpolated_hours": 1,
    }

    attrs = sensor.extra_state_attributes

    assert attrs["profiling_status"] == "ok"
    assert "today_profile" in attrs
    assert "tomorrow_profile" in attrs
    assert attrs["today_profile"]["start_hour"] == 20
    assert len(attrs["today_profile"]["hourly_consumption"]) == 4
    assert len(attrs["tomorrow_profile"]["hourly_consumption"]) == 24


def test_fill_missing_values_hour_median_fallback():
    sensor = _make_sensor()
    filled, interpolated = sensor._fill_missing_values(
        [None, None],
        hour_medians={0: 1.0, 1: 2.0},
        day_avg=1.5,
        global_median=1.0,
    )
    assert filled == [1.0, 2.0]
    assert interpolated == 2


def test_fill_missing_values_global_fallback():
    sensor = _make_sensor()
    filled, interpolated = sensor._fill_missing_values(
        [None],
        hour_medians={},
        day_avg=None,
        global_median=0.7,
    )
    assert filled == [0.7]
    assert interpolated == 1


def test_build_daily_profiles_skips_missing_days():
    sensor = _make_sensor()
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    hourly_series = []

    # Day1 has too many missing hours (only 10 values)
    for hour in range(10):
        hourly_series.append((day1.replace(hour=hour), 1.0))
    # Day2 complete
    for hour in range(24):
        hourly_series.append((day2.replace(hour=hour), 2.0))

    profiles, _medians, _interpolated = sensor._build_daily_profiles(hourly_series)
    assert list(profiles.keys()) == [day2.date()]


@pytest.mark.asyncio
async def test_find_best_matching_profile_no_hourly_data(monkeypatch):
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace()

    async def _empty_series(*_a, **_k):
        return []

    monkeypatch.setattr(sensor, "_load_hourly_series", _empty_series)

    result = await sensor._find_best_matching_profile_for_sensor(
        "sensor.oig_123_ac_out_en_day", value_field="sum", days_back=3
    )
    assert result is None
    assert sensor._last_profile_reason == "no_hourly_stats"


@pytest.mark.asyncio
async def test_find_best_matching_profile_not_enough_days(monkeypatch):
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace()

    async def _series(*_a, **_k):
        base = datetime(2025, 1, 1)
        return [
            (base.replace(hour=hour), 1.0) for hour in range(24)
        ] + [
            (base.replace(day=2, hour=hour), 2.0) for hour in range(24)
        ]

    monkeypatch.setattr(sensor, "_load_hourly_series", _series)

    result = await sensor._find_best_matching_profile_for_sensor(
        "sensor.oig_123_ac_out_en_day", value_field="sum", days_back=3
    )
    assert result is None
    assert sensor._last_profile_reason.startswith("not_enough_daily_profiles_")


@pytest.mark.asyncio
async def test_find_best_matching_profile_success(monkeypatch):
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace()
    fixed_now = datetime(2025, 1, 4, 5, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: fixed_now,
    )

    async def _series(*_a, **_k):
        base = datetime(2025, 1, 1)
        series = []
        for day in range(4):
            for hour in range(24):
                series.append(
                    (base + timedelta(days=day, hours=hour), 1.0 + day + (hour % 3) * 0.1)
                )
        return series

    monkeypatch.setattr(sensor, "_load_hourly_series", _series)

    result = await sensor._find_best_matching_profile_for_sensor(
        "sensor.oig_123_ac_out_en_day", value_field="sum", days_back=5
    )
    assert result is not None
    assert result["predicted_total_kwh"] > 0


def test_native_value_no_data_and_with_prediction():
    sensor = _make_sensor()
    assert sensor.native_value == "no_data"

    sensor._current_prediction = {"predicted_total_kwh": 12.34}
    assert sensor.native_value == "12.3 kWh"


def test_get_energy_unit_factor():
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace(
        states=DummyStates(
            {
                "sensor.oig_123_ac_out_en_day": SimpleNamespace(
                    attributes={"unit_of_measurement": "kWh"}
                )
            }
        )
    )
    assert sensor._get_energy_unit_factor("sensor.oig_123_ac_out_en_day") == 1.0

    sensor._hass = SimpleNamespace(states=DummyStates({}))
    assert sensor._get_energy_unit_factor("sensor.oig_123_ac_out_en_day") == 0.001


@pytest.mark.asyncio
async def test_create_and_update_profile_warming_up(monkeypatch):
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace()
    sensor.async_write_ha_state = lambda: None

    async def _no_profile(*_a, **_k):
        sensor._last_profile_reason = "no_hourly_stats"
        return None

    monkeypatch.setattr(sensor, "_find_best_matching_profile", _no_profile)

    await sensor._create_and_update_profile()

    assert sensor._profiling_status == "warming_up"
    assert sensor._profiling_error == "no_hourly_stats"


@pytest.mark.asyncio
async def test_create_and_update_profile_sends_signal(monkeypatch):
    sensor = _make_sensor()
    sensor._hass = SimpleNamespace()
    sensor.async_write_ha_state = lambda: None

    prediction = {"predicted_total_kwh": 5.0}

    async def _profile(*_a, **_k):
        return prediction

    sent = {"signal": None}

    def _send(_hass, signal):
        sent["signal"] = signal

    monkeypatch.setattr(sensor, "_find_best_matching_profile", _profile)
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_send", _send
    )

    await sensor._create_and_update_profile()

    assert sensor._profiling_status == "ok"
    assert sensor._current_prediction == prediction
    assert sent["signal"] == "oig_cloud_123_profiles_updated"


@pytest.mark.asyncio
async def test_wait_for_next_profile_window(monkeypatch):
    sensor = _make_sensor()
    fixed_now = datetime(2025, 1, 2, 0, 0, 0)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: fixed_now,
    )
    waited = {"seconds": 0}

    async def _sleep(seconds):
        waited["seconds"] = seconds

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.asyncio.sleep",
        _sleep,
    )

    await sensor._wait_for_next_profile_window()

    assert waited["seconds"] == 1800.0
