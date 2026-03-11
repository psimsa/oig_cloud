from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.util import dt as dt_util

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SOURCE_CLOUD_ONLY = "cloud_only"
DATA_SOURCE_HYBRID = "hybrid"
DATA_SOURCE_LOCAL_ONLY = "local_only"

DEFAULT_DATA_SOURCE_MODE = DATA_SOURCE_CLOUD_ONLY
DEFAULT_PROXY_STALE_MINUTES = 10
DEFAULT_LOCAL_EVENT_DEBOUNCE_MS = 300

# Fired on hass.bus when effective data source changes for a config entry.
# Payload: {"entry_id": str, "configured_mode": str, "effective_mode": str, "local_available": bool, "reason": str}
EVENT_DATA_SOURCE_CHANGED = "oig_cloud_data_source_changed"

PROXY_LAST_DATA_ENTITY_ID = "sensor.oig_local_oig_proxy_proxy_status_last_data"
PROXY_BOX_ID_ENTITY_ID = "sensor.oig_local_oig_proxy_proxy_status_box_device_id"

try:
    from homeassistant.helpers.event import (
        async_track_state_change_event as _async_track_state_change_event,
    )  # type: ignore
except Exception:  # pragma: no cover
    _async_track_state_change_event = None

try:
    from homeassistant.helpers.event import (
        async_track_time_interval as _async_track_time_interval,
    )  # type: ignore
except Exception:  # pragma: no cover
    _async_track_time_interval = None


@dataclass(slots=True)
class DataSourceState:
    configured_mode: str
    effective_mode: str
    local_available: bool
    last_local_data: Optional[datetime]
    reason: str


def get_data_source_state(hass: HomeAssistant, entry_id: str) -> DataSourceState:
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    state = entry_data.get("data_source_state")
    if isinstance(state, DataSourceState):
        return state
    # Fallback for early startup
    return DataSourceState(
        configured_mode=DEFAULT_DATA_SOURCE_MODE,
        effective_mode=DEFAULT_DATA_SOURCE_MODE,
        local_available=False,
        last_local_data=None,
        reason="not_initialized",
    )


def get_effective_mode(hass: HomeAssistant, entry_id: str) -> str:
    return get_data_source_state(hass, entry_id).effective_mode


def get_configured_mode(entry: ConfigEntry) -> str:
    mode = entry.options.get("data_source_mode", DEFAULT_DATA_SOURCE_MODE)
    if mode == DATA_SOURCE_HYBRID:
        _LOGGER.debug(
            "Data source mode 'hybrid' mapped to 'local_only' for compatibility"
        )
        return DATA_SOURCE_LOCAL_ONLY
    return mode


def get_proxy_stale_minutes(entry: ConfigEntry) -> int:
    try:
        return int(
            entry.options.get("local_proxy_stale_minutes", DEFAULT_PROXY_STALE_MINUTES)
        )
    except Exception:
        return DEFAULT_PROXY_STALE_MINUTES


def get_local_event_debounce_ms(entry: ConfigEntry) -> int:
    try:
        return int(
            entry.options.get(
                "local_event_debounce_ms", DEFAULT_LOCAL_EVENT_DEBOUNCE_MS
            )
        )
    except Exception:
        return DEFAULT_LOCAL_EVENT_DEBOUNCE_MS


def _parse_dt(value: Any) -> Optional[dt_util.dt.datetime]:
    if value in (None, "", "unknown", "unavailable"):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:  # ms epoch
            ts = ts / 1000.0
        try:
            return dt_util.dt.datetime.fromtimestamp(ts, tz=dt_util.UTC)
        except Exception:
            return None
    if isinstance(value, dt_util.dt.datetime):
        return (
            dt_util.as_utc(value) if value.tzinfo else value.replace(tzinfo=dt_util.UTC)
        )
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            try:
                ts = float(value)
                if ts > 1_000_000_000_000:  # ms epoch
                    ts = ts / 1000.0
                return dt_util.dt.datetime.fromtimestamp(ts, tz=dt_util.UTC)
            except Exception as err:
                _LOGGER.debug("Failed to parse numeric timestamp '%s': %s", value, err)
        dt = dt_util.parse_datetime(value)
        if dt is None:
            try:
                dt = dt_util.dt.datetime.fromisoformat(value)
            except Exception:
                return None
        if dt.tzinfo is None:
            # Proxy často posílá lokální čas bez timezone → interpretuj jako lokální TZ HA, ne UTC.
            dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(dt)
    return None


def _coerce_box_id(value: Any) -> Optional[str]:
    if value in (None, "", "unknown", "unavailable"):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, float):
        try:
            as_int = int(value)
            return str(as_int) if as_int > 0 else None
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return s
        try:
            m = re.search(r"(\d{6,})", s)
            return m.group(1) if m else None
        except Exception:
            return None
    return None


def _get_latest_local_entity_update(
    hass: HomeAssistant, box_id: str
) -> Optional[dt_util.dt.datetime]:
    """Return the most recent update timestamp among local telemetry entities for a box."""
    if not (isinstance(box_id, str) and box_id.isdigit()):
        return None
    try:
        latest: Optional[dt_util.dt.datetime] = None
        for domain in ("sensor", "binary_sensor"):
            prefix = f"{domain}.oig_local_{box_id}_"
            for st in hass.states.async_all(domain):
                if not st.entity_id.startswith(prefix):
                    continue
                if st.state in (None, "", "unknown", "unavailable"):
                    continue
                dt = st.last_updated or st.last_changed
                if dt is None:
                    continue
                dt_utc = (
                    dt_util.as_utc(dt) if dt.tzinfo else dt.replace(tzinfo=dt_util.UTC)
                )
                latest = dt_utc if latest is None else max(latest, dt_utc)
        return latest
    except Exception:
        return None


def init_data_source_state(hass: HomeAssistant, entry: ConfigEntry) -> DataSourceState:
    """Initialize (or refresh) data source state early during setup.

    This allows coordinators to respect local/hybrid mode before the controller is started.
    """
    configured = get_configured_mode(entry)
    stale_minutes = get_proxy_stale_minutes(entry)

    expected_box_id: Optional[str] = None
    try:
        expected_box_id = _coerce_box_id(entry.options.get("box_id"))
    except Exception:
        expected_box_id = None

    proxy_state = hass.states.get(PROXY_LAST_DATA_ENTITY_ID)
    proxy_last_dt = _parse_dt(proxy_state.state if proxy_state else None)
    proxy_entity_dt: Optional[dt_util.dt.datetime] = None
    if proxy_state is not None:
        try:
            dt = proxy_state.last_updated or proxy_state.last_changed
            if dt is not None:
                proxy_entity_dt = (
                    dt_util.as_utc(dt) if dt.tzinfo else dt.replace(tzinfo=dt_util.UTC)
                )
        except Exception:
            proxy_entity_dt = None

    proxy_box_state = hass.states.get(PROXY_BOX_ID_ENTITY_ID)
    proxy_box_id = _coerce_box_id(proxy_box_state.state if proxy_box_state else None)

    box_id_for_scan = expected_box_id or proxy_box_id
    local_entities_dt = (
        _get_latest_local_entity_update(hass, box_id_for_scan)
        if box_id_for_scan
        else None
    )

    candidates: list[tuple[str, dt_util.dt.datetime]] = []
    if proxy_last_dt:
        candidates.append(("proxy_last_data", proxy_last_dt))
    if proxy_entity_dt:
        candidates.append(("proxy_entity_updated", proxy_entity_dt))
    if local_entities_dt:
        candidates.append(("local_entities", local_entities_dt))

    source = "none"
    last_dt: Optional[dt_util.dt.datetime] = None
    if candidates:
        source, last_dt = max(candidates, key=lambda item: item[1])
    now = dt_util.utcnow()

    local_available = False
    reason = "local_missing"
    if last_dt:
        age = (now - last_dt).total_seconds()
        if age <= stale_minutes * 60:
            local_available = True
            reason = f"local_ok_{source}"
        else:
            reason = f"local_stale_{int(age)}s_{source}"

    if local_available and expected_box_id:
        # Extra safety: if proxy reports a box_id, it must match the configured one.
        if proxy_box_id is None:
            # Proxy box id sensor missing/unparseable; allow only if we can confirm local entities
            # exist for the configured box id.
            if local_entities_dt is None:
                local_available = False
                reason = "proxy_box_id_missing"
        elif proxy_box_id != expected_box_id:
            local_available = False
            reason = "proxy_box_id_mismatch"

    if configured == DATA_SOURCE_CLOUD_ONLY:
        effective = DATA_SOURCE_CLOUD_ONLY
    else:
        effective = configured if local_available else DATA_SOURCE_CLOUD_ONLY

    state = DataSourceState(
        configured_mode=configured,
        effective_mode=effective,
        local_available=local_available,
        last_local_data=last_dt,
        reason=reason,
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
        "data_source_state"
    ] = state
    return state


class DataSourceController:
    """Controls effective data source mode based on local proxy health."""

    _LOCAL_ENTITY_RE = re.compile(r"^(?:sensor|binary_sensor)\.oig_local_(\d+)_")

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: Any,
        telemetry_store: Optional[Any] = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.telemetry_store = telemetry_store

        self._unsubs: list[callable] = []
        self._last_local_entity_update: Optional[dt_util.dt.datetime] = None
        self._pending_local_entities: set[str] = set()
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=get_local_event_debounce_ms(entry) / 1000,
            immediate=False,
            function=self._handle_local_event,
        )

    async def async_start(self) -> None:
        self._update_state(force=True)

        # Seed coordinator payload from existing local states (only in configured local/hybrid mode).
        try:
            if (
                get_configured_mode(self.entry) != DATA_SOURCE_CLOUD_ONLY
                and self.telemetry_store
            ):
                did_seed = self.telemetry_store.seed_from_existing_local_states()
                if did_seed and getattr(
                    self.coordinator, "async_set_updated_data", None
                ):
                    snap = self.telemetry_store.get_snapshot()
                    self.coordinator.async_set_updated_data(snap.payload)
        except Exception as err:
            _LOGGER.debug("Failed to seed local telemetry snapshot: %s", err)

        # Watch proxy last_data changes
        if _async_track_state_change_event is not None:
            self._unsubs.append(
                _async_track_state_change_event(
                    self.hass, [PROXY_LAST_DATA_ENTITY_ID], self._on_proxy_change
                )
            )
        else:
            # Compatibility for older/stubbed HA helpers used in unit tests.
            @callback
            def _on_state_changed(event: Any) -> None:
                if event.data.get("entity_id") == PROXY_LAST_DATA_ENTITY_ID:
                    self._on_proxy_change(event)

            self._unsubs.append(
                self.hass.bus.async_listen("state_changed", _on_state_changed)
            )

        # Periodic HC: detect stale even without state changes
        if _async_track_time_interval is not None:
            self._unsubs.append(
                _async_track_time_interval(
                    self.hass, self._on_periodic, timedelta(minutes=1)
                )
            )

        # Local telemetry events (5s updates) – just poke coordinator listeners
        self._unsubs.append(
            self.hass.bus.async_listen("state_changed", self._on_any_state_change)
        )

        _LOGGER.info(
            "DataSourceController started: mode=%s stale=%smin",
            get_configured_mode(self.entry),
            get_proxy_stale_minutes(self.entry),
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception as err:
                _LOGGER.debug("Failed to unsubscribe data source listener: %s", err)
        self._unsubs.clear()

    @callback
    def _on_proxy_change(self, _event: Any) -> None:
        _, mode_changed = self._update_state()
        if mode_changed:
            self._on_effective_mode_changed()

    @callback
    def _on_periodic(self, _now: Any) -> None:
        _, mode_changed = self._update_state()
        if mode_changed:
            self._on_effective_mode_changed()

    @callback
    def _on_any_state_change(self, event: Any) -> None:
        # Ignore local events unless user configured local/hybrid mode.
        if get_configured_mode(self.entry) == DATA_SOURCE_CLOUD_ONLY:
            return

        # Ignore local events while effective mode is cloud fallback (no mixing).
        try:
            state = get_data_source_state(self.hass, self.entry.entry_id)
            if state.effective_mode == DATA_SOURCE_CLOUD_ONLY:
                return
        except Exception as err:
            _LOGGER.debug("Failed to read data source state: %s", err)

        entity_id = event.data.get("entity_id")
        if not isinstance(entity_id, str):
            return
        if not (
            entity_id.startswith("sensor.oig_local_")
            or entity_id.startswith("binary_sensor.oig_local_")
        ):
            return

        # Ensure the local update belongs to this entry's box_id (prevents cross-device wiring).
        m = self._LOCAL_ENTITY_RE.match(entity_id)
        if not m:
            return
        event_box_id = m.group(1)

        expected_box_id: Optional[str] = None
        try:
            expected_box_id = _coerce_box_id(self.entry.options.get("box_id"))
        except Exception:
            expected_box_id = None

        if expected_box_id and event_box_id != expected_box_id:
            return

        # If box_id isn't configured yet, fall back to proxy-reported box_id (if available).
        if expected_box_id is None:
            proxy_box = self.hass.states.get(PROXY_BOX_ID_ENTITY_ID)
            proxy_box_id = _coerce_box_id(proxy_box.state if proxy_box else None)
            if proxy_box_id and event_box_id != proxy_box_id:
                return

        # Remember the latest local telemetry activity timestamp.
        try:
            self._last_local_entity_update = dt_util.as_utc(event.time_fired)
        except Exception:
            self._last_local_entity_update = dt_util.utcnow()

        # Track changed entities and apply mapping to coordinator payload (debounced).
        self._pending_local_entities.add(entity_id)
        self._schedule_debounced_poke()

    @callback
    def _schedule_debounced_poke(self) -> None:
        try:
            self.hass.async_create_task(self._debouncer.async_call())
        except Exception as err:
            _LOGGER.debug("Failed to schedule local telemetry debounce: %s", err)

    async def _handle_local_event(self) -> None:
        """Debounced handler for local telemetry changes.

        - Updates DataSourceState (may switch effective mode)
        - Applies local mapping into coordinator.data (cloud-shaped payload)
        """
        try:
            _, mode_changed = self._update_state()
            if mode_changed:
                self._on_effective_mode_changed()
            # Only apply local mapping when effective mode is local.
            state = get_data_source_state(self.hass, self.entry.entry_id)
            if state.effective_mode != DATA_SOURCE_CLOUD_ONLY and self.telemetry_store:
                pending = list(self._pending_local_entities)
                self._pending_local_entities.clear()
                if pending:
                    changed = self.telemetry_store.apply_local_events(pending)
                    if changed and getattr(
                        self.coordinator, "async_set_updated_data", None
                    ):
                        snap = self.telemetry_store.get_snapshot()
                        self.coordinator.async_set_updated_data(snap.payload)
        except Exception as err:
            _LOGGER.debug("Failed to handle local telemetry event: %s", err)

    @callback
    def _update_state(self, force: bool = False) -> tuple[bool, bool]:
        entry_id = self.entry.entry_id
        configured = get_configured_mode(self.entry)
        stale_minutes = get_proxy_stale_minutes(self.entry)

        proxy_state = self.hass.states.get(PROXY_LAST_DATA_ENTITY_ID)
        if proxy_state is None:
            _LOGGER.debug("Proxy health entity not found")
        proxy_last_dt = _parse_dt(proxy_state.state if proxy_state else None)
        if proxy_state and proxy_last_dt is None:
            _LOGGER.debug(
                "Proxy health parse failed for value=%s, attributes=%s",
                proxy_state.state,
                proxy_state.attributes,
            )
        proxy_entity_dt: Optional[dt_util.dt.datetime] = None
        if proxy_state is not None:
            try:
                dt = proxy_state.last_updated or proxy_state.last_changed
                if dt is not None:
                    proxy_entity_dt = (
                        dt_util.as_utc(dt)
                        if dt.tzinfo
                        else dt.replace(tzinfo=dt_util.UTC)
                    )
            except Exception:
                proxy_entity_dt = None
        now = dt_util.utcnow()

        expected_box_id: Optional[str] = None
        try:
            expected_box_id = _coerce_box_id(self.entry.options.get("box_id"))
        except Exception:
            expected_box_id = None

        proxy_box_state = self.hass.states.get(PROXY_BOX_ID_ENTITY_ID)
        proxy_box_id = _coerce_box_id(
            proxy_box_state.state if proxy_box_state else None
        )

        box_id_for_scan = expected_box_id or proxy_box_id
        local_entities_dt = self._last_local_entity_update
        if local_entities_dt is None and box_id_for_scan:
            # Startup fallback when we haven't seen any local state_changed yet.
            local_entities_dt = _get_latest_local_entity_update(
                self.hass, box_id_for_scan
            )

        candidates: list[tuple[str, dt_util.dt.datetime]] = []
        if proxy_last_dt:
            candidates.append(("proxy_last_data", proxy_last_dt))
        if proxy_entity_dt:
            candidates.append(("proxy_entity_updated", proxy_entity_dt))
        if local_entities_dt:
            candidates.append(("local_entities", local_entities_dt))

        source = "none"
        last_dt: Optional[dt_util.dt.datetime] = None
        if candidates:
            source, last_dt = max(candidates, key=lambda item: item[1])

        local_available = False
        reason = "local_missing"
        if last_dt:
            age = (now - last_dt).total_seconds()
            if age <= stale_minutes * 60:
                local_available = True
                reason = f"local_ok_{source}"
            else:
                reason = f"local_stale_{int(age)}s_{source}"

        # Require proxy box id to match configured box id (prevents cross-device wiring).
        if local_available and expected_box_id:
            # Extra safety: if proxy reports a box_id, it must match the configured one.
            if proxy_box_id is None:
                # Proxy box id sensor missing/unparseable; allow only if we can confirm local entities
                # exist for the configured box id.
                if local_entities_dt is None:
                    local_available = False
                    reason = "proxy_box_id_missing"
            elif proxy_box_id != expected_box_id:
                local_available = False
                reason = "proxy_box_id_mismatch"

        if configured == DATA_SOURCE_CLOUD_ONLY:
            effective = DATA_SOURCE_CLOUD_ONLY
        else:
            effective = configured if local_available else DATA_SOURCE_CLOUD_ONLY

        prev = get_data_source_state(self.hass, entry_id)
        changed = force or (
            prev.configured_mode != configured
            or prev.effective_mode != effective
            or prev.local_available != local_available
            or prev.last_local_data != last_dt
        )
        mode_changed = force or (
            prev.configured_mode != configured
            or prev.effective_mode != effective
            or prev.local_available != local_available
        )

        if changed:
            new_state = DataSourceState(
                configured_mode=configured,
                effective_mode=effective,
                local_available=local_available,
                last_local_data=last_dt,
                reason=reason,
            )
            self.hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {})[
                "data_source_state"
            ] = new_state
        return changed, mode_changed

    @callback
    def _on_effective_mode_changed(self) -> None:
        state = get_data_source_state(self.hass, self.entry.entry_id)
        _LOGGER.info(
            "Data source mode switch: configured=%s effective=%s local_ok=%s (%s)",
            state.configured_mode,
            state.effective_mode,
            state.local_available,
            state.reason,
        )

        # Notify entities so UI can re-render immediately (per-entity listeners).
        try:
            self.hass.bus.async_fire(
                EVENT_DATA_SOURCE_CHANGED,
                {
                    "entry_id": self.entry.entry_id,
                    "configured_mode": state.configured_mode,
                    "effective_mode": state.effective_mode,
                    "local_available": state.local_available,
                    "reason": state.reason,
                },
            )
        except Exception as err:
            _LOGGER.debug("Failed to fire data source change event: %s", err)

        if state.effective_mode == DATA_SOURCE_CLOUD_ONLY:
            # Ensure cloud data is fresh when falling back
            try:
                self.hass.async_create_task(self.coordinator.async_request_refresh())
            except Exception as err:
                _LOGGER.debug("Failed to schedule coordinator refresh: %s", err)

    async def _poke_coordinator(self) -> None:
        try:
            if self.coordinator and getattr(self.coordinator, "data", None) is not None:
                self.coordinator.async_set_updated_data(self.coordinator.data)
        except Exception as err:
            _LOGGER.debug("Failed to poke coordinator: %s", err)
