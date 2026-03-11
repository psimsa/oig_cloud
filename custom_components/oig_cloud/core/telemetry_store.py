from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .local_mapper import LocalUpdateApplier

_LOGGER = logging.getLogger(__name__)


def _utcnow() -> datetime:
    utcnow = getattr(dt_util, "utcnow", None)
    if callable(utcnow):
        return utcnow()
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class TelemetrySnapshot:
    """Cloud-shaped payload for coordinator.data."""

    payload: Dict[str, Any]
    updated_at: datetime


class TelemetryStore:
    """Maintain a normalized (cloud-shaped) telemetry payload.

    - In cloud mode: coordinator writes full payload from the cloud API.
    - In local mode: DataSourceController applies local entity updates into the same
      cloud-shaped structure so *all* entities (including computed) can stay transparent.
    """

    def __init__(self, hass: HomeAssistant, *, box_id: str) -> None:
        self.hass = hass
        self.box_id = box_id
        self._applier = LocalUpdateApplier(box_id)
        self._payload: Dict[str, Any] = {box_id: {}}
        self._updated_at: Optional[datetime] = None

    def set_cloud_payload(self, payload: Dict[str, Any]) -> None:
        """Replace store content with a cloud payload (already normalized)."""
        if not isinstance(payload, dict):
            return
        # Keep only dict payloads and ensure box_id key exists.
        if self.box_id not in payload:
            payload = {**payload, self.box_id: payload.get(self.box_id, {})}
        self._payload = payload
        self._updated_at = _utcnow()

    def apply_local_events(self, entity_ids: Iterable[str]) -> bool:
        """Apply current HA states for given local entity_ids into the normalized payload.

        Returns True if anything changed.
        """
        changed = False
        for entity_id in entity_ids:
            st = self.hass.states.get(entity_id)
            if st is None:
                continue
            try:
                did = self._applier.apply_state(
                    self._payload, entity_id, st.state, st.last_updated
                )
            except Exception as err:
                _LOGGER.debug("Local apply failed for %s: %s", entity_id, err)
                did = False
            changed = changed or did
        if changed:
            self._updated_at = _utcnow()
        return changed

    def seed_from_existing_local_states(self) -> bool:
        """Seed payload from all currently-known local entity states for this box."""
        entity_ids = []
        for domain in ("sensor", "binary_sensor"):
            prefix = f"{domain}.oig_local_{self.box_id}_"
            for st in self.hass.states.async_all(domain):
                if st.entity_id.startswith(prefix):
                    entity_ids.append(st.entity_id)
        return self.apply_local_events(entity_ids)

    def get_snapshot(self) -> TelemetrySnapshot:
        """Return a (mutable) snapshot suitable for coordinator.data."""
        if self._updated_at is None:
            self._updated_at = _utcnow()
        return TelemetrySnapshot(payload=self._payload, updated_at=self._updated_at)
