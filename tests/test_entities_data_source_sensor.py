from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.entities.data_source_sensor import (
    OigCloudDataSourceSensor,
)
from custom_components.oig_cloud.core.data_source import DATA_SOURCE_HYBRID, DATA_SOURCE_LOCAL_ONLY


class DummyCoordinator:
    def __init__(self, box_id="123"):
        self.forced_box_id = box_id


class DummyHass:
    def __init__(self):
        self.states = SimpleNamespace(get=lambda _eid: None)


def _make_entry(entry_id="entry1"):
    return SimpleNamespace(entry_id=entry_id)


def test_state_local_vs_cloud(monkeypatch):
    hass = DummyHass()
    coordinator = DummyCoordinator()
    entry = _make_entry()

    def _state_local(*_a, **_k):
        return SimpleNamespace(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_HYBRID,
            local_available=True,
            last_local_data=None,
            reason="ok",
        )

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_source_sensor.get_data_source_state",
        _state_local,
    )

    sensor = OigCloudDataSourceSensor(hass, coordinator, entry)
    assert sensor.state == "local"

    def _state_cloud(*_a, **_k):
        return SimpleNamespace(
            configured_mode=DATA_SOURCE_LOCAL_ONLY,
            effective_mode=DATA_SOURCE_LOCAL_ONLY,
            local_available=False,
            last_local_data=None,
            reason="missing",
        )

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_source_sensor.get_data_source_state",
        _state_cloud,
    )

    assert sensor.state == "cloud"


def test_extra_state_attributes(monkeypatch):
    hass = DummyHass()
    coordinator = DummyCoordinator()
    entry = _make_entry()
    last_dt = datetime(2025, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_source_sensor.get_data_source_state",
        lambda *_a, **_k: SimpleNamespace(
            configured_mode="cloud_only",
            effective_mode="cloud_only",
            local_available=False,
            last_local_data=last_dt,
            reason="test",
        ),
    )

    sensor = OigCloudDataSourceSensor(hass, coordinator, entry)
    attrs = sensor.extra_state_attributes

    assert attrs["configured_mode"] == "cloud_only"
    assert attrs["effective_mode"] == "cloud_only"
    assert attrs["local_available"] is False
    assert attrs["last_local_data"] == last_dt.isoformat()


@pytest.mark.asyncio
async def test_async_added_and_removed(monkeypatch):
    hass = DummyHass()
    coordinator = DummyCoordinator()
    entry = _make_entry()
    sensor = OigCloudDataSourceSensor(hass, coordinator, entry)

    calls = {"unsubs": 0}

    def _track_state(_hass, _entity_id, _cb):
        return lambda: calls.__setitem__("unsubs", calls["unsubs"] + 1)

    def _track_time(_hass, _cb, _interval):
        return lambda: calls.__setitem__("unsubs", calls["unsubs"] + 1)

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_source_sensor.async_track_state_change_event",
        _track_state,
    )
    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.data_source_sensor.async_track_time_interval",
        _track_time,
    )

    await sensor.async_added_to_hass()
    assert len(sensor._unsubs) == 2

    await sensor.async_will_remove_from_hass()
    assert calls["unsubs"] == 2
    assert sensor._unsubs == []
