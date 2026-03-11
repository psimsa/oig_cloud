from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.adaptive_load_profiles_sensor import (
    _generate_profile_name,
    _get_season,
    OigCloudAdaptiveLoadProfilesSensor,
)


class DummyCoordinator:
    def __init__(self):
        self.hass = SimpleNamespace()

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(monkeypatch):
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda *_args, **_kwargs: "123",
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        {"adaptive_profiles": {"name_cs": "Profil"}},
    )
    coordinator = DummyCoordinator()
    config_entry = SimpleNamespace()
    device_info = {"identifiers": {("oig_cloud", "123")}}
    sensor = OigCloudAdaptiveLoadProfilesSensor(
        coordinator,
        "adaptive_profiles",
        config_entry,
        device_info,
        hass=coordinator.hass,
    )
    sensor.hass = coordinator.hass
    return sensor


def test_get_season():
    assert _get_season(datetime(2025, 1, 1)) == "winter"
    assert _get_season(datetime(2025, 4, 1)) == "spring"
    assert _get_season(datetime(2025, 7, 1)) == "summer"
    assert _get_season(datetime(2025, 10, 1)) == "autumn"


def test_generate_profile_name_variants():
    base = [0.2] * 24
    winter_evening = base[:18] + [2.0] * 6
    assert _generate_profile_name(winter_evening, "winter", False) == "Pracovní den s topením"

    summer_afternoon = base[:12] + [1.2] * 6 + base[18:]
    assert _generate_profile_name(summer_afternoon, "summer", False) == "Pracovní den s klimatizací"

    weekend_morning = [0.2] * 6 + [1.5] * 6 + [0.2] * 12
    assert _generate_profile_name(weekend_morning, "spring", True) == "Víkend s praním"

    home_office = [0.9] * 24
    assert _generate_profile_name(home_office, "autumn", False) == "Home office"

    night_heating = [0.6] * 6 + [0.1] * 18
    assert _generate_profile_name(night_heating, "autumn", False) == "Pracovní den s nočním ohřevem"

    evening_spike = [0.1] * 18 + [1.0] * 6
    assert _generate_profile_name(evening_spike, "spring", False) == "Pracovní den - večerní špička"


def test_fill_missing_values(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    values = [1.0, None, 3.0, None]
    filled, interpolated = sensor._fill_missing_values(
        values, hour_medians={3: 4.0}, day_avg=2.0, global_median=1.5
    )
    assert filled[1] == 2.0
    assert filled[3] == 4.0
    assert interpolated == 2


def test_build_daily_profiles_and_72h(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly = []
    for day in range(3):
        for hour in range(24):
            hourly.append((start + timedelta(days=day, hours=hour), float(hour)))
    daily, medians, interpolated = sensor._build_daily_profiles(hourly)
    assert len(daily) == 3
    profiles = sensor._build_72h_profiles(daily)
    assert len(profiles) == 1
    assert profiles[0]["total_consumption"] > 0
    assert interpolated
    assert medians


def test_build_current_match(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = datetime(2025, 1, 2, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )
    hourly = []
    yesterday = now - timedelta(days=1)
    for hour in range(24):
        hourly.append((yesterday.replace(hour=hour), 1.0))
    for hour in range(3):
        hourly.append((now.replace(hour=hour), 2.0))
    match = sensor._build_current_match(hourly, {hour: 1.0 for hour in range(24)})
    assert match is not None
    assert len(match) == 27


def test_apply_floor_to_prediction(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    predicted, applied = sensor._apply_floor_to_prediction(
        [0.0, 0.1, 0.2], 0, {0: 1.0, 1: 1.0, 2: 1.0}, [1.0] * 24
    )
    assert applied == 3
    assert all(val > 0 for val in predicted)


def test_calculate_profile_similarity(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    assert sensor._calculate_profile_similarity([1.0], [1.0, 2.0]) == 0.0
    score = sensor._calculate_profile_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert score > 0.9


def test_extra_state_attributes_prediction(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = datetime(2025, 1, 5, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )
    sensor._current_prediction = {
        "predicted_total_kwh": 1.5,
        "predicted_avg_kwh": 0.3,
        "predicted_consumption": [0.2, 0.2, 0.2, 0.2, 0.2],
        "predict_hours": 5,
        "similarity_score": 0.88,
        "sample_count": 2,
        "match_hours": 12,
        "data_source": "sensor.test",
        "floor_applied": 1,
        "interpolated_hours": 0,
        "matched_profile_full": [],
    }
    attrs = sensor.extra_state_attributes
    assert attrs["prediction_summary"]["predicted_total_kwh"] == 1.5
    assert len(attrs["tomorrow_profile"]["hourly_consumption"]) == 24
    assert "profile_name" in attrs


@pytest.mark.asyncio
async def test_async_added_and_removed_starts_task(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    created = {}

    class DummyTask:
        def done(self):
            return False

        def cancel(self):
            created["cancelled"] = True

    class DummyHass:
        def async_create_background_task(self, *_args, **_kwargs):
            coro = _args[0]
            coro.close()
            created["task"] = True
            return DummyTask()

    sensor.hass = DummyHass()
    await sensor.async_added_to_hass()
    assert created["task"] is True
    await sensor.async_will_remove_from_hass()
    assert created["cancelled"] is True


@pytest.mark.asyncio
async def test_profiling_loop_cancel(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def _noop():
        return None

    sensor._create_and_update_profile = _noop
    call = {"count": 0}

    async def _sleep(_seconds):
        call["count"] += 1
        if call["count"] > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.asyncio.sleep",
        _sleep,
    )
    with pytest.raises(asyncio.CancelledError):
        await sensor._profiling_loop()


@pytest.mark.asyncio
async def test_wait_for_next_profile_window(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )
    slept = {}

    async def _sleep(seconds):
        slept["seconds"] = seconds

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.asyncio.sleep",
        _sleep,
    )
    await sensor._wait_for_next_profile_window()
    assert slept["seconds"] > 0


@pytest.mark.asyncio
async def test_create_and_update_profile_success(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    async def _match(*_args, **_kwargs):
        return {"predicted_total_kwh": 1.0}

    sensor._find_best_matching_profile = _match
    sensor.async_write_ha_state = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_send",
        lambda *_args, **_kwargs: None,
    )
    await sensor._create_and_update_profile()
    assert sensor._profiling_status == "ok"


@pytest.mark.asyncio
async def test_create_and_update_profile_warming_up(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    async def _match(*_args, **_kwargs):
        sensor._last_profile_reason = "not_enough_data"
        return None

    sensor._find_best_matching_profile = _match
    sensor.async_write_ha_state = lambda *_args, **_kwargs: None
    await sensor._create_and_update_profile()
    assert sensor._profiling_status == "warming_up"


def test_get_energy_unit_factor(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    state = SimpleNamespace(attributes={"unit_of_measurement": "kWh"})
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: state))
    assert sensor._get_energy_unit_factor("sensor.test") == 1.0


@pytest.mark.asyncio
async def test_load_hourly_series_and_earliest_start(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def scalar(self):
            return self._rows

    class DummySession:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, *_args, **_kwargs):
            return DummyResult(self._rows)

    class DummyRecorder:
        def __init__(self, rows):
            self._rows = rows

        async def async_add_executor_job(self, func):
            return func()

        def get_session(self):
            return DummySession(self._rows)

    def _session_scope(*_args, **_kwargs):
        session = _kwargs.get("session")

        class _Ctx:
            def __enter__(self_inner):
                return session

            def __exit__(self_inner, *_exc):
                return False

        return _Ctx()

    rows = [(1000.0, 500.0, None, 1000.0)]
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda *_args, **_kwargs: DummyRecorder(rows),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.session_scope",
        _session_scope,
    )
    monkeypatch.setattr("sqlalchemy.text", lambda _q: _q)
    series = await sensor._load_hourly_series(
        "sensor.test",
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 2, tzinfo=timezone.utc),
        value_field="sum",
    )
    assert series

    min_ts = 1234.0
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda *_args, **_kwargs: DummyRecorder(min_ts),
    )
    earliest = await sensor._get_earliest_statistics_start("sensor.test")
    assert earliest is not None


@pytest.mark.asyncio
async def test_find_best_matching_profile_paths(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.np.corrcoef",
        lambda *_a, **_k: [[1.0, 1.0], [1.0, 1.0]],
    )
    now = datetime(2025, 1, 2, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )
    async def _earliest(*_args, **_kwargs):
        return now - timedelta(days=3)

    sensor._get_earliest_statistics_start = _earliest

    async def _load(*_args, **_kwargs):
        return [(now - timedelta(days=1), 1.0)] * 48

    sensor._load_hourly_series = _load

    def _build_daily(_series):
        day = (now - timedelta(days=2)).date()
        profile = [1.0] * 24
        return {day: profile, day + timedelta(days=1): profile, day + timedelta(days=2): profile}, {h: 1.0 for h in range(24)}, {}

    sensor._build_daily_profiles = _build_daily
    sensor._build_current_match = lambda *_args, **_kwargs: [1.0] * 30
    sensor._build_72h_profiles = lambda *_args, **_kwargs: [
        {"consumption_kwh": [1.0] * 72, "start_date": "2025-01-01"}
    ]
    prediction = await sensor._find_best_matching_profile_for_sensor(
        "sensor.test", value_field="sum"
    )
    assert prediction is not None


@pytest.mark.asyncio
async def test_find_best_matching_profile_fallback(monkeypatch):
    sensor = _make_sensor(monkeypatch)

    async def _first(*_args, **_kwargs):
        return None

    async def _second(*_args, **_kwargs):
        return {"predicted_total_kwh": 1.0}

    sensor._find_best_matching_profile_for_sensor = _first
    prediction = await sensor._find_best_matching_profile(
        "sensor.a", fallback_sensor=None
    )
    assert prediction is None

    calls = {"count": 0}

    async def _switch(*_args, **_kwargs):
        calls["count"] += 1
        return await _second() if calls["count"] > 1 else None

    sensor._find_best_matching_profile_for_sensor = _switch
    prediction = await sensor._find_best_matching_profile(
        "sensor.a", fallback_sensor="sensor.b"
    )
    assert prediction is not None
