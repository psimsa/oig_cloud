from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyHass:
    def __init__(self):
        self.data = {"oig_cloud": {}}
        self.states = SimpleNamespace(get=lambda _eid: None)
        self.bus = SimpleNamespace(async_fire=lambda *_a, **_k: None)

    class Services:
        async def async_call(self, *_a, **_k):
            return None

    @property
    def services(self):
        return self.Services()


class DummyShield:
    def __init__(self):
        self.hass = DummyHass()
        self.pending = {}
        self.queue = []
        self.queue_metadata = {}
        self.running = None
        self.entry = SimpleNamespace(entry_id="entry1")
        self._setup_state_listener = lambda: None

    async def _log_event(self, *_a, **_k):
        return None

    def _notify_state_change(self):
        return None


@pytest.mark.asyncio
async def test_start_call_power_monitor(monkeypatch):
    shield = DummyShield()
    async def _refresh():
        return None

    coordinator = SimpleNamespace(async_request_refresh=_refresh)
    shield.hass.data["oig_cloud"][shield.entry.entry_id] = {
        "coordinator": coordinator,
        "service_shield": shield,
    }
    shield.hass.states = SimpleNamespace(get=lambda _eid: SimpleNamespace(state="100"))

    async def _original_call(*_a, **_k):
        return None

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _c: "123",
    )

    await module.start_call(
        shield,
        module.SERVICE_SET_BOX_MODE,
        {"value": "HOME UPS"},
        {"sensor.oig_123_box_prms_mode": "HOME UPS"},
        _original_call,
        "oig_cloud",
        "set_box_mode",
        False,
        None,
    )

    assert shield.pending[module.SERVICE_SET_BOX_MODE]["power_monitor"] is not None


@pytest.mark.asyncio
async def test_safe_call_service_boiler_mode(monkeypatch):
    shield = SimpleNamespace(
        hass=DummyHass(),
        _logger=SimpleNamespace(info=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
        _check_entity_state_change=lambda *_a, **_k: True,
    )
    shield.hass.states = SimpleNamespace(
        async_entity_ids=lambda: ["sensor.boiler_manual_mode"],
        get=lambda _eid: SimpleNamespace(state="0"),
    )

    result = await module.safe_call_service(
        shield, "set_boiler_mode", {"entity_id": "sensor.x", "mode": "Manual"}
    )
    assert result is True
