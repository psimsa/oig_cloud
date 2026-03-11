from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.shield import dispatch as module


class DummyHass:
    def __init__(self):
        self.states = SimpleNamespace(get=lambda _eid: None, async_entity_ids=lambda: [])
        self.services = SimpleNamespace(async_call=lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_safe_call_service_error(monkeypatch):
    shield = SimpleNamespace(
        hass=DummyHass(),
        _logger=SimpleNamespace(info=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
        _check_entity_state_change=lambda *_a, **_k: False,
    )

    async def _raise(*_a, **_k):
        raise RuntimeError("boom")

    shield.hass.services.async_call = _raise
    result = await module.safe_call_service(shield, "any", {"entity_id": "sensor.x"})
    assert result is False
