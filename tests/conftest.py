"""Pytest configuration for OIG Cloud tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest


class FakeState:
    def __init__(self, entity_id: str, state: str) -> None:
        self.entity_id = entity_id
        self.state = state
        self.last_changed = datetime.now(timezone.utc)
        self.last_updated = self.last_changed


class FakeStates:
    def __init__(self) -> None:
        self._states: Dict[str, FakeState] = {}

    def get(self, entity_id: str) -> Optional[FakeState]:
        return self._states.get(entity_id)

    def async_set(self, entity_id: str, state: str) -> None:
        self._states[entity_id] = FakeState(entity_id, state)

    def async_all(self, domain: str) -> list[FakeState]:
        prefix = f"{domain}."
        return [st for st in self._states.values() if st.entity_id.startswith(prefix)]


@pytest.fixture
def e2e_setup():
    """Minimal mock hass and entry for e2e tests."""
    entry = SimpleNamespace(
        entry_id="test_entry_123",
        options={"box_id": "123456"},
        data={},
        title="OIG Cloud 123456",
    )

    coordinator = SimpleNamespace()
    coordinator.config_entry = entry
    coordinator.data = {"123456": {"some": "data"}}

    hass = SimpleNamespace()
    hass.data = {
        "oig_cloud": {
            entry.entry_id: {
                "coordinator": coordinator,
            }
        },
        "core.uuid": "test-uuid",
    }
    hass.states = FakeStates()

    return hass, entry