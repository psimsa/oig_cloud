from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield.core import ModeTransitionTracker


class DummyHass:
    def __init__(self):
        self.jobs = []

    async def async_add_executor_job(self, func, *args):
        self.jobs.append((func, args))
        return func(*args)


@pytest.mark.asyncio
async def test_async_setup_tracks_listener(monkeypatch):
    hass = DummyHass()
    tracker = ModeTransitionTracker(hass, "123")

    called = {}

    def _track_state_change(_hass, entity_id, callback):
        called["entity_id"] = entity_id
        called["callback"] = callback
        return lambda: None

    async def _load_history(_sensor_id):
        called["loaded"] = True

    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.async_track_state_change_event",
        _track_state_change,
    )
    monkeypatch.setattr(tracker, "_async_load_historical_data", _load_history)

    await tracker.async_setup()

    assert called["entity_id"] == "sensor.oig_123_box_prms_mode"
    assert called["loaded"] is True


def test_track_request_skips_same_mode():
    tracker = ModeTransitionTracker(SimpleNamespace(), "123")
    tracker.track_request("t1", "Home 1", "Home 1")
    assert tracker._active_transitions == {}


def test_async_mode_changed_updates_history(monkeypatch):
    hass = DummyHass()
    tracker = ModeTransitionTracker(hass, "123")

    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.oig_cloud.shield.core.dt_now", lambda: fixed_now
    )

    tracker.track_request("t1", "Home 1", "Home UPS")

    event = SimpleNamespace(
        data={
            "old_state": SimpleNamespace(state="Home 1", last_changed=fixed_now),
            "new_state": SimpleNamespace(
                state="Home UPS", last_changed=fixed_now + timedelta(seconds=5)
            ),
        }
    )

    tracker._async_mode_changed(event)

    stats = tracker.get_statistics()
    assert "Home 1→Home UPS" in stats
    assert stats["Home 1→Home UPS"]["samples"] == 1


def test_get_offset_for_scenario_uses_p95(monkeypatch):
    tracker = ModeTransitionTracker(SimpleNamespace(), "123")
    tracker._transition_history["Home 1→Home UPS"] = [2.0, 4.0, 6.0]

    offset = tracker.get_offset_for_scenario("Home 1", "Home UPS")

    assert offset >= 4.0


@pytest.mark.asyncio
async def test_async_load_historical_data_handles_missing(monkeypatch):
    hass = DummyHass()
    tracker = ModeTransitionTracker(hass, "123")

    import homeassistant.components.recorder as recorder

    def _state_changes(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(recorder.history, "state_changes_during_period", _state_changes)

    await tracker._async_load_historical_data("sensor.oig_123_box_prms_mode")

    assert tracker._transition_history == {}


@pytest.mark.asyncio
async def test_async_load_historical_data_parses_transitions(monkeypatch):
    hass = DummyHass()
    tracker = ModeTransitionTracker(hass, "123")

    import homeassistant.components.recorder as recorder

    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    states = [
        SimpleNamespace(
            state="Home 1",
            last_changed=start,
            attributes={},
        ),
        SimpleNamespace(
            state="Home UPS",
            last_changed=start + timedelta(seconds=10),
            attributes={},
        ),
    ]

    def _state_changes(*_args, **_kwargs):
        return {"sensor.oig_123_box_prms_mode": states}

    monkeypatch.setattr(recorder.history, "state_changes_during_period", _state_changes)

    await tracker._async_load_historical_data("sensor.oig_123_box_prms_mode")

    assert "Home 1→Home UPS" in tracker._transition_history
    assert tracker._transition_history["Home 1→Home UPS"]


@pytest.mark.asyncio
async def test_async_cleanup_unsubscribes():
    hass = DummyHass()
    tracker = ModeTransitionTracker(hass, "123")

    called = {"count": 0}

    def _unsub():
        called["count"] += 1

    tracker._state_listener_unsub = _unsub

    await tracker.async_cleanup()

    assert called["count"] == 1
    assert tracker._state_listener_unsub is None
