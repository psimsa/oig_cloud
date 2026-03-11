from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities import adaptive_load_profiles_sensor as module


class DummyCoordinator:
    def __init__(self):
        self.hass = SimpleNamespace()

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_sensor(monkeypatch, box_id="123"):
    if box_id is not None:
        monkeypatch.setattr(
            "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
            lambda *_args, **_kwargs: box_id,
        )
    else:
        monkeypatch.setattr(
            "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no box")),
        )
    monkeypatch.setattr(
        "custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS.SENSOR_TYPES_STATISTICS",
        {"adaptive_profiles": {"name_cs": "Profil"}},
    )
    coordinator = DummyCoordinator()
    config_entry = SimpleNamespace()
    device_info = {"identifiers": {("oig_cloud", "123")}}
    sensor = module.OigCloudAdaptiveLoadProfilesSensor(
        coordinator,
        "adaptive_profiles",
        config_entry,
        device_info,
        hass=coordinator.hass,
    )
    sensor.hass = coordinator.hass
    return sensor


def test_init_fallback_box_id(monkeypatch):
    sensor = _make_sensor(monkeypatch, box_id=None)
    assert sensor._box_id == "unknown"


@pytest.mark.asyncio
async def test_profiling_loop_error_branch(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    def _create_task(*args, **_kwargs):
        coro = args[0] if args else None
        if coro is not None:
            coro.close()
        return None

    sensor.hass = SimpleNamespace(async_create_task=_create_task)

    async def _noop():
        return None

    sensor._create_and_update_profile = _noop
    calls = {"count": 0}

    async def _sleep(seconds):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("boom")
        if calls["count"] == 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.asyncio.sleep",
        _sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await sensor._profiling_loop()
    assert sensor._profiling_status == "error"


@pytest.mark.asyncio
async def test_create_and_update_profile_error(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    async def _match(*_args, **_kwargs):
        sensor._last_profile_reason = "unexpected"
        return None

    sensor._find_best_matching_profile = _match
    sensor.async_write_ha_state = lambda *_args, **_kwargs: None
    await sensor._create_and_update_profile()
    assert sensor._profiling_status == "error"
    assert sensor._profiling_error == "Failed to create profile"


def test_get_energy_unit_factor_no_hass(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = None
    assert sensor._get_energy_unit_factor("sensor.test") == 0.001


@pytest.mark.asyncio
async def test_load_hourly_series_no_recorder(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance", lambda *_a, **_k: None
    )
    series = await sensor._load_hourly_series(
        "sensor.test",
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 2, tzinfo=timezone.utc),
        value_field="sum",
    )
    assert series == []


@pytest.mark.asyncio
async def test_load_hourly_series_invalid_rows(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    class DummyResult:
        def fetchall(self):
            return [(None, None, None, "bad")]

    class DummySession:
        def execute(self, *_args, **_kwargs):
            return DummyResult()

    class DummyRecorder:
        async def async_add_executor_job(self, func):
            return func()

        def get_session(self):
            return DummySession()

    def _session_scope(*_args, **_kwargs):
        session = _kwargs.get("session")

        class _Ctx:
            def __enter__(self_inner):
                return session

            def __exit__(self_inner, *_exc):
                return False

        return _Ctx()

    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda *_a, **_k: DummyRecorder(),
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
        value_field="mean",
    )
    assert series == []


@pytest.mark.asyncio
async def test_get_earliest_statistics_start_no_recorder(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance", lambda *_a, **_k: None
    )
    assert await sensor._get_earliest_statistics_start("sensor.test") is None


def test_build_daily_profiles_missing_too_many(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hourly = [(start, 1.0)]
    daily, medians, interpolated = sensor._build_daily_profiles(hourly)
    assert daily == {}
    assert interpolated == {}


def test_build_current_match_missing_days(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    now = datetime(2025, 1, 2, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )
    hourly = [(now, 1.0)]
    assert sensor._build_current_match(hourly, {}) is None


def test_apply_floor_to_prediction_empty(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    predicted, applied = sensor._apply_floor_to_prediction([], 0, {}, [])
    assert predicted == []
    assert applied == 0


def test_calculate_profile_similarity_total_profile_zero(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    monkeypatch.setattr(module.np, "corrcoef", lambda *_a, **_k: [[1.0, 1.0], [1.0, 1.0]])
    score = sensor._calculate_profile_similarity([1.0, 1.0], [0.0, 0.0])
    assert score >= 0.0


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_no_hass(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = None
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_no_data(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()

    async def _load(*_a, **_k):
        return []

    sensor._load_hourly_series = _load
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )
    assert sensor._last_profile_reason == "no_hourly_stats"


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_not_enough_days(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    now = datetime(2025, 1, 2, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )

    async def _load(*_a, **_k):
        return [(now - timedelta(days=1), 1.0)] * 48

    sensor._load_hourly_series = _load
    sensor._build_daily_profiles = lambda *_a, **_k: ({now.date(): [1.0]}, {}, {})
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )
    assert sensor._last_profile_reason.startswith("not_enough_daily_profiles")


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_not_enough_current(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    now = datetime(2025, 1, 2, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )

    async def _load(*_a, **_k):
        return [(now - timedelta(days=1), 1.0)] * 72

    day = (now - timedelta(days=2)).date()
    sensor._load_hourly_series = _load
    sensor._build_daily_profiles = lambda *_a, **_k: (
        {day: [1.0] * 24, day + timedelta(days=1): [1.0] * 24, day + timedelta(days=2): [1.0] * 24},
        {h: 1.0 for h in range(24)},
        {},
    )
    sensor._build_current_match = lambda *_a, **_k: [1.0]
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )
    assert sensor._last_profile_reason.startswith("not_enough_current_data")


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_no_profiles(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    now = datetime(2025, 1, 2, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )

    async def _load(*_a, **_k):
        return [(now - timedelta(days=1), 1.0)] * 72

    day = (now - timedelta(days=2)).date()
    sensor._load_hourly_series = _load
    sensor._build_daily_profiles = lambda *_a, **_k: (
        {day: [1.0] * 24, day + timedelta(days=1): [1.0] * 24, day + timedelta(days=2): [1.0] * 24},
        {h: 1.0 for h in range(24)},
        {},
    )
    sensor._build_current_match = lambda *_a, **_k: [1.0] * 30
    sensor._build_72h_profiles = lambda *_a, **_k: []
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )
    assert sensor._last_profile_reason == "no_historical_profiles"


@pytest.mark.asyncio
async def test_find_best_matching_profile_for_sensor_no_scored(monkeypatch):
    sensor = _make_sensor(monkeypatch)
    sensor._hass = SimpleNamespace()
    now = datetime(2025, 1, 2, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.adaptive_load_profiles_sensor.dt_util.now",
        lambda: now,
    )

    async def _load(*_a, **_k):
        return [(now - timedelta(days=1), 1.0)] * 72

    day = (now - timedelta(days=2)).date()
    sensor._load_hourly_series = _load
    sensor._build_daily_profiles = lambda *_a, **_k: (
        {day: [1.0] * 24, day + timedelta(days=1): [1.0] * 24, day + timedelta(days=2): [1.0] * 24},
        {h: 1.0 for h in range(24)},
        {},
    )
    sensor._build_current_match = lambda *_a, **_k: [1.0] * 30
    sensor._build_72h_profiles = lambda *_a, **_k: [
        {"consumption_kwh": [1.0] * 10, "start_date": "2025-01-01"}
    ]
    assert (
        await sensor._find_best_matching_profile_for_sensor(
            "sensor.test", value_field="sum"
        )
        is None
    )
    assert sensor._last_profile_reason == "no_matching_profiles"
