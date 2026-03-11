"""Auto-switch helpers extracted from legacy battery forecast."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from homeassistant.helpers.event import async_call_later, async_track_point_in_time
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.event import (
        async_track_time_interval as _async_track_time_interval,
    )  # type: ignore
except Exception:  # pragma: no cover
    _async_track_time_interval = None

from ...const import CONF_AUTO_MODE_SWITCH, DOMAIN
from ..types import (
    CBB_MODE_SERVICE_MAP,
    SERVICE_MODE_HOME_1,
    SERVICE_MODE_HOME_2,
    SERVICE_MODE_HOME_3,
    SERVICE_MODE_HOME_UPS,
)
from ..utils_common import parse_timeline_timestamp

_LOGGER = logging.getLogger(__name__)


def auto_mode_switch_enabled(sensor: Any) -> bool:
    options = (
        (sensor._config_entry.options or {}) if sensor._config_entry else {}
    )  # pylint: disable=protected-access
    return bool(options.get(CONF_AUTO_MODE_SWITCH, False))


def normalize_service_mode(
    sensor: Any, mode_value: Optional[Union[str, int]]
) -> Optional[str]:
    _ = sensor
    if mode_value is None:
        return None
    if isinstance(mode_value, int):
        return CBB_MODE_SERVICE_MAP.get(mode_value)

    mode_str = str(mode_value).strip()
    if not mode_str:
        return None
    upper = mode_str.upper()
    legacy_map = {
        "HOME I": SERVICE_MODE_HOME_1,
        "HOME 1": SERVICE_MODE_HOME_1,
        "HOME II": SERVICE_MODE_HOME_2,
        "HOME 2": SERVICE_MODE_HOME_2,
        "HOME III": SERVICE_MODE_HOME_3,
        "HOME 3": SERVICE_MODE_HOME_3,
        "HOME UPS": SERVICE_MODE_HOME_UPS,
    }
    if upper in legacy_map:
        return legacy_map[upper]

    title = mode_str.title()
    if title in legacy_map.values():  # pragma: no cover - unreachable with current map
        return title

    return None


def get_current_box_mode(sensor: Any) -> Optional[str]:
    if not sensor._hass:  # pylint: disable=protected-access
        return None
    entity_id = (
        f"sensor.oig_{sensor._box_id}_box_prms_mode"  # pylint: disable=protected-access
    )
    state = sensor._hass.states.get(entity_id)  # pylint: disable=protected-access
    if not state or not state.state:
        return None
    return normalize_service_mode(sensor, state.state)


def cancel_auto_switch_schedule(sensor: Any) -> None:
    if sensor._auto_switch_handles:  # pylint: disable=protected-access
        for unsub in sensor._auto_switch_handles:  # pylint: disable=protected-access
            try:
                unsub()
            except Exception as err:
                _LOGGER.debug("Failed to cancel scheduled auto switch: %s", err)
    sensor._auto_switch_handles = []  # pylint: disable=protected-access
    clear_auto_switch_retry(sensor)


def clear_auto_switch_retry(sensor: Any) -> None:
    if not sensor._auto_switch_retry_unsub:  # pylint: disable=protected-access
        return
    try:
        sensor._auto_switch_retry_unsub()  # pylint: disable=protected-access
    except Exception as err:
        _LOGGER.debug("Failed to cancel delayed auto switch sync: %s", err)
    finally:
        sensor._auto_switch_retry_unsub = None  # pylint: disable=protected-access


def start_auto_switch_watchdog(sensor: Any) -> None:
    """Ensure periodic enforcement of planned modes is running."""
    if (
        not sensor._hass  # pylint: disable=protected-access
        or sensor._auto_switch_watchdog_unsub  # pylint: disable=protected-access
        or not auto_mode_switch_enabled(sensor)
    ):
        return

    if _async_track_time_interval is None:
        _LOGGER.debug(
            "[AutoModeSwitch] async_track_time_interval unavailable; watchdog disabled"
        )
        return

    async def _tick(now: datetime) -> None:
        await auto_switch_watchdog_tick(sensor, now)

    sensor._auto_switch_watchdog_unsub = (
        _async_track_time_interval(  # pylint: disable=protected-access
            sensor._hass,  # pylint: disable=protected-access
            _tick,
            sensor._auto_switch_watchdog_interval,  # pylint: disable=protected-access
        )
    )
    _LOGGER.debug(
        "[AutoModeSwitch] Watchdog started (interval=%ss)",
        int(
            sensor._auto_switch_watchdog_interval.total_seconds()
        ),  # pylint: disable=protected-access
    )


def stop_auto_switch_watchdog(sensor: Any) -> None:
    """Stop watchdog if running."""
    if sensor._auto_switch_watchdog_unsub:  # pylint: disable=protected-access
        sensor._auto_switch_watchdog_unsub()  # pylint: disable=protected-access
        sensor._auto_switch_watchdog_unsub = None  # pylint: disable=protected-access
        _LOGGER.debug("[AutoModeSwitch] Watchdog stopped")


async def auto_switch_watchdog_tick(sensor: Any, now: datetime) -> None:
    """Periodic check that correct mode is applied."""
    if not auto_mode_switch_enabled(sensor):
        stop_auto_switch_watchdog(sensor)
        return

    timeline, _ = get_mode_switch_timeline(sensor)
    if not timeline:
        return

    desired_mode = get_planned_mode_for_time(sensor, now, timeline)
    if not desired_mode:
        return

    current_mode = get_current_box_mode(sensor)
    if current_mode == desired_mode:
        return

    _LOGGER.warning(
        "[AutoModeSwitch] Watchdog correcting mode from %s -> %s",
        current_mode or "unknown",
        desired_mode,
    )
    await ensure_current_mode(sensor, desired_mode, "watchdog enforcement")


def get_planned_mode_for_time(
    sensor: Any, reference_time: datetime, timeline: List[Dict[str, Any]]
) -> Optional[str]:
    """Return planned mode for the interval covering reference_time."""
    planned_mode: Optional[str] = None

    for interval in timeline:
        timestamp = interval.get("time") or interval.get("timestamp")
        mode_label = normalize_service_mode(
            sensor, interval.get("mode_name")
        ) or normalize_service_mode(sensor, interval.get("mode"))
        if not timestamp or not mode_label:
            continue

        start_dt = parse_timeline_timestamp(timestamp)
        if not start_dt:
            continue

        if start_dt <= reference_time:
            planned_mode = mode_label
            continue

        break

    return planned_mode


def schedule_auto_switch_retry(sensor: Any, delay_seconds: float) -> None:
    if not sensor._hass or delay_seconds <= 0:  # pylint: disable=protected-access
        return
    if sensor._auto_switch_retry_unsub:  # pylint: disable=protected-access
        return

    def _retry(now: datetime) -> None:
        sensor._auto_switch_retry_unsub = None  # pylint: disable=protected-access
        sensor._create_task_threadsafe(
            update_auto_switch_schedule, sensor
        )  # pylint: disable=protected-access

    sensor._auto_switch_retry_unsub = (
        async_call_later(  # pylint: disable=protected-access
            sensor._hass, delay_seconds, _retry  # pylint: disable=protected-access
        )
    )
    log_rl = getattr(sensor, "_log_rate_limited", None)
    if log_rl:
        log_rl(
            "auto_mode_switch_delay_sync",
            "debug",
            "[AutoModeSwitch] Delaying auto-switch sync by %.0f seconds",
            delay_seconds,
            cooldown_s=60.0,
        )


def get_mode_switch_offset(
    sensor: Any, from_mode: Optional[str], to_mode: str
) -> float:
    """Return reaction-time offset based on shield tracker statistics."""
    fallback = 180.0
    if (
        sensor._config_entry and sensor._config_entry.options
    ):  # pylint: disable=protected-access
        fallback = float(
            sensor._config_entry.options.get(  # pylint: disable=protected-access
                "auto_mode_switch_lead_seconds",
                sensor._config_entry.options.get(  # pylint: disable=protected-access
                    "autonomy_switch_lead_seconds", 180.0
                ),
            )
        )
    if (
        not from_mode or not sensor._hass or not sensor._config_entry
    ):  # pylint: disable=protected-access
        return fallback

    try:
        entry = sensor._hass.data.get(DOMAIN, {}).get(
            sensor._config_entry.entry_id, {}
        )  # pylint: disable=protected-access
        service_shield = entry.get("service_shield")
        mode_tracker = getattr(service_shield, "mode_tracker", None)
        if not mode_tracker:
            return fallback

        offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)
        if offset_seconds is None or offset_seconds <= 0:
            return fallback

        return float(offset_seconds)
    except Exception as err:  # pragma: no cover - defensive
        _LOGGER.warning(
            "[AutoModeSwitch] Failed to read mode switch offset %s→%s: %s",
            from_mode,
            to_mode,
            err,
        )
        return fallback


def get_service_shield(sensor: Any) -> Optional[Any]:
    """Safe helper to get ServiceShield instance."""
    if not sensor._hass or not sensor._config_entry:  # pylint: disable=protected-access
        return None

    entry = sensor._hass.data.get(DOMAIN, {}).get(
        sensor._config_entry.entry_id, {}
    )  # pylint: disable=protected-access
    return entry.get("service_shield")


async def execute_mode_change(sensor: Any, target_mode: str, reason: str) -> None:
    if (
        not sensor._hass or not sensor._side_effects_enabled
    ):  # pylint: disable=protected-access
        return

    now = dt_util.now()
    service_shield = get_service_shield(sensor)
    if service_shield and hasattr(service_shield, "has_pending_mode_change"):
        if service_shield.has_pending_mode_change(target_mode):
            _LOGGER.debug(
                "[AutoModeSwitch] Skipping %s (%s) - shield already processing mode change",
                target_mode,
                reason,
            )
            return

    if (
        sensor._last_auto_switch_request  # pylint: disable=protected-access
        and sensor._last_auto_switch_request[0]
        == target_mode  # pylint: disable=protected-access
        and (now - sensor._last_auto_switch_request[1]).total_seconds()
        < 90  # pylint: disable=protected-access
    ):
        _LOGGER.debug(
            "[AutoModeSwitch] Skipping duplicate request for %s (%s)",
            target_mode,
            reason,
        )
        return

    try:
        await sensor._hass.services.async_call(  # pylint: disable=protected-access
            DOMAIN,
            "set_box_mode",
            {
                "mode": target_mode,
                "acknowledgement": True,
            },
            blocking=False,
        )
        sensor._last_auto_switch_request = (
            target_mode,
            now,
        )  # pylint: disable=protected-access
        _LOGGER.info("[AutoModeSwitch] Requested mode '%s' (%s)", target_mode, reason)
    except Exception as err:
        _LOGGER.error(
            "[AutoModeSwitch] Failed to switch to %s: %s",
            target_mode,
            err,
            exc_info=True,
        )


async def ensure_current_mode(sensor: Any, desired_mode: str, reason: str) -> None:
    current_mode = get_current_box_mode(sensor)
    if current_mode == desired_mode:
        _LOGGER.debug(
            "[AutoModeSwitch] Mode already %s (%s), no action", desired_mode, reason
        )
        return
    await execute_mode_change(sensor, desired_mode, reason)


def get_mode_switch_timeline(sensor: Any) -> Tuple[List[Dict[str, Any]], str]:
    """Return the best available timeline for automatic mode switching."""
    timeline = getattr(sensor, "_timeline_data", None) or []
    if timeline:
        return timeline, "hybrid"
    return [], "none"


async def update_auto_switch_schedule(sensor: Any) -> None:
    """Sync scheduled set_box_mode calls with planned timeline."""
    cancel_auto_switch_schedule(sensor)

    if not sensor._hass or not auto_mode_switch_enabled(
        sensor
    ):  # pylint: disable=protected-access
        _LOGGER.debug("[AutoModeSwitch] Auto mode switching disabled")
        stop_auto_switch_watchdog(sensor)
        return

    now = dt_util.now()
    if sensor._auto_switch_ready_at:  # pylint: disable=protected-access
        if now < sensor._auto_switch_ready_at:  # pylint: disable=protected-access
            wait_seconds = (
                sensor._auto_switch_ready_at - now  # pylint: disable=protected-access
            ).total_seconds()
            log_rl = getattr(sensor, "_log_rate_limited", None)
            if log_rl:
                log_rl(
                    "auto_mode_switch_startup_delay",
                    "debug",
                    "[AutoModeSwitch] Startup delay active (%.0fs remaining)",
                    wait_seconds,
                    cooldown_s=60.0,
                )
            schedule_auto_switch_retry(sensor, wait_seconds)
            return
        sensor._auto_switch_ready_at = None  # pylint: disable=protected-access
        clear_auto_switch_retry(sensor)

    timeline, timeline_source = get_mode_switch_timeline(sensor)
    if not timeline:
        _LOGGER.debug(
            "[AutoModeSwitch] No timeline available for auto switching (source=%s)",
            timeline_source,
        )
        return

    current_mode: Optional[str] = None
    last_mode: Optional[str] = None
    scheduled_events: List[Tuple[datetime, str, Optional[str]]] = []

    for interval in timeline:
        timestamp = interval.get("time") or interval.get("timestamp")
        mode_label = normalize_service_mode(
            sensor, interval.get("mode_name")
        ) or normalize_service_mode(sensor, interval.get("mode"))
        if not timestamp or not mode_label:
            continue

        start_dt = parse_timeline_timestamp(timestamp)
        if not start_dt:
            continue

        if start_dt <= now:
            current_mode = mode_label
            last_mode = mode_label
            continue

        if mode_label == last_mode:
            continue

        previous_mode = last_mode
        last_mode = mode_label
        scheduled_events.append((start_dt, mode_label, previous_mode))

    if current_mode:
        await ensure_current_mode(sensor, current_mode, "current planned block")

    if not scheduled_events:
        _LOGGER.debug("[AutoModeSwitch] No upcoming mode changes to schedule")
        start_auto_switch_watchdog(sensor)
        return

    for when, mode, prev_mode in scheduled_events:
        _ = prev_mode
        adjusted_when = when
        if adjusted_when <= now:
            adjusted_when = now + timedelta(seconds=1)

        async def _callback(event_time: datetime, desired_mode: str = mode) -> None:
            await execute_mode_change(
                sensor, desired_mode, f"scheduled {event_time.isoformat()}"
            )

        unsub = async_track_point_in_time(
            sensor._hass, _callback, adjusted_when
        )  # pylint: disable=protected-access
        sensor._auto_switch_handles.append(unsub)  # pylint: disable=protected-access
        _LOGGER.info(
            "[AutoModeSwitch] Scheduled switch to %s at %s",
            mode,
            adjusted_when.isoformat(),
        )

    start_auto_switch_watchdog(sensor)
