"""Service shield queue helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from homeassistant.core import callback
from homeassistant.util.dt import now as dt_now

TIMEOUT_MINUTES = 15
SERVICE_SET_BOX_MODE = "oig_cloud.set_box_mode"

_LOGGER = logging.getLogger(__name__)


async def handle_shield_status(shield: Any, call: Any) -> None:
    """Handle shield status service call."""
    await asyncio.sleep(0)
    _ = call
    status = get_shield_status(shield)
    _LOGGER.info("[OIG Shield] Current status: %s", status)

    shield.hass.bus.async_fire(
        "oig_cloud_shield_status",
        {"status": status, "timestamp": dt_now().isoformat()},
    )


async def handle_queue_info(shield: Any, call: Any) -> None:
    """Handle queue info service call."""
    await asyncio.sleep(0)
    _ = call
    queue_info = get_queue_info(shield)
    _LOGGER.info("[OIG Shield] Queue info: %s", queue_info)

    shield.hass.bus.async_fire(
        "oig_cloud_shield_queue_info",
        {**queue_info, "timestamp": dt_now().isoformat()},
    )


async def handle_remove_from_queue(shield: Any, call: Any) -> None:
    """Handle remove from queue service call."""
    position = call.data.get("position")
    total_items = len(shield.pending) + len(shield.queue)

    if position < 1 or position > total_items:
        _LOGGER.error(
            "[OIG Shield] Neplatná pozice: %s (pending: %s, queue: %s)",
            position,
            len(shield.pending),
            len(shield.queue),
        )
        return

    if position == 1 and len(shield.pending) > 0:
        _LOGGER.warning(
            "[OIG Shield] Nelze smazat běžící službu na pozici 1 (running: %s)",
            shield.running,
        )
        return

    queue_index = position - 1 - len(shield.pending)

    if queue_index < 0 or queue_index >= len(shield.queue):
        _LOGGER.error(
            "[OIG Shield] Chyba výpočtu indexu: position=%s, queue_index=%s, queue_len=%s",
            position,
            queue_index,
            len(shield.queue),
        )
        return

    removed_item = shield.queue[queue_index]
    service_name = removed_item[0]
    params = removed_item[1]
    expected_entities = removed_item[2]

    del shield.queue[queue_index]
    shield.queue_metadata.pop((service_name, str(params)), None)

    _LOGGER.info(
        "[OIG Shield] Odstraněna položka z fronty na pozici %s: %s",
        position,
        service_name,
    )

    await shield._log_event(
        "cancelled",
        service_name,
        {
            "params": params,
            "entities": expected_entities,
        },
        reason=f"Uživatel zrušil požadavek z fronty (pozice {position})",
        context=call.context,
    )

    shield._notify_state_change()

    shield.hass.bus.async_fire(
        "oig_cloud_shield_queue_removed",
        {
            "position": position,
            "service": service_name,
            "remaining": len(shield.queue),
            "timestamp": dt_now().isoformat(),
        },
    )


def _clear_state_listener(shield: Any) -> None:
    if shield._state_listener_unsub:
        shield._state_listener_unsub()
        shield._state_listener_unsub = None


def _get_timeout_minutes(service_name: str) -> int:
    return 2 if service_name == "oig_cloud.set_formating_mode" else TIMEOUT_MINUTES


async def _handle_timeout(shield: Any, service_name: str, info: Dict[str, Any]) -> None:
    if service_name == "oig_cloud.set_formating_mode":
        _LOGGER.info(
            "[OIG Shield] Formating mode dokončeno po 2 minutách (automaticky)"
        )
        await shield._log_event(
            "completed",
            service_name,
            {
                "params": info["params"],
                "entities": info["entities"],
                "original_states": info.get("original_states", {}),
            },
            reason="Formátování dokončeno (automaticky po 2 min)",
        )
        await shield._log_telemetry(
            "completed",
            service_name,
            {
                "params": info["params"],
                "entities": info["entities"],
                "reason": "auto_timeout",
            },
        )
        return

    _LOGGER.warning("[OIG Shield] Timeout pro službu %s", service_name)
    await shield._log_event(
        "timeout",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "original_states": info.get("original_states", {}),
        },
    )
    await shield._log_telemetry(
        "timeout",
        service_name,
        {"params": info["params"], "entities": info["entities"]},
    )


def _get_power_monitor_state(
    shield: Any, power_monitor: Dict[str, Any]
) -> Optional[float]:
    power_entity = power_monitor["entity_id"]
    power_state = shield.hass.states.get(power_entity)

    if not power_state:
        _LOGGER.warning(
            "[OIG Shield] Power monitor: entita %s neexistuje",
            power_entity,
        )
        return None
    if power_state.state in ["unknown", "unavailable"]:
        _LOGGER.debug(
            "[OIG Shield] Power monitor: entita %s je %s",
            power_entity,
            power_state.state,
        )
        return None
    try:
        return float(power_state.state)
    except (ValueError, TypeError):
        return None


def get_shield_status(shield: Any) -> str:
    """Return shield status."""
    if shield.running:
        return f"Běží: {shield.running}"
    if shield.queue:
        return f"Ve frontě: {len(shield.queue)} služeb"
    return "Neaktivní"


def get_queue_info(shield: Any) -> Dict[str, Any]:
    """Return queue info."""
    return {
        "running": shield.running,
        "queue_length": len(shield.queue),
        "pending_count": len(shield.pending),
        "queue_services": [item[0] for item in shield.queue],
    }


def has_pending_mode_change(shield: Any, target_mode: Optional[str] = None) -> bool:
    """Return True if pending/queued mode change already exists."""
    if _pending_has_box_mode(shield, target_mode):
        return True
    if _queue_has_box_mode(shield, target_mode):
        return True
    return shield.running == SERVICE_SET_BOX_MODE


def _matches_target_mode(
    shield: Any, entities: Dict[str, str], target_mode: Optional[str]
) -> bool:
    if not entities:
        return False
    if not target_mode:
        return True

    normalized_target = shield._normalize_value(target_mode)
    return any(
        shield._normalize_value(value) == normalized_target for value in entities.values()
    )


def _pending_has_box_mode(shield: Any, target_mode: Optional[str]) -> bool:
    return any(
        _matches_target_mode(shield, info.get("entities", {}), target_mode)
        for service_name, info in shield.pending.items()
        if service_name == SERVICE_SET_BOX_MODE
    )


def _queue_has_box_mode(shield: Any, target_mode: Optional[str]) -> bool:
    return any(
        _matches_target_mode(shield, expected_entities, target_mode)
        for service_name, _params, expected_entities, *_ in shield.queue
        if service_name == SERVICE_SET_BOX_MODE
    )


@callback
async def check_loop(shield: Any, _now: datetime) -> None:  # noqa: C901
    """Check pending operations and advance queue."""
    if shield._is_checking:
        _LOGGER.debug("[OIG Shield] Check loop již běží, přeskakuji")
        return

    shield._is_checking = True
    try:
        _log_check_loop_state(shield)
        if _is_queue_idle(shield):
            _LOGGER.debug("[OIG Shield] Check loop - vše prázdné, žádná akce")
            _clear_state_listener(shield)
            return

        finished = await _collect_finished_pending(shield)
        _clear_finished_pending(shield, finished)
        await _maybe_start_next_call(shield)

        if finished:
            shield._notify_state_change()

    finally:
        shield._is_checking = False


def _log_check_loop_state(shield: Any) -> None:
    _LOGGER.debug(
        "[OIG Shield] Check loop tick - pending: %s, queue: %s, running: %s",
        len(shield.pending),
        len(shield.queue),
        shield.running,
    )


def _is_queue_idle(shield: Any) -> bool:
    return not shield.pending and not shield.queue and not shield.running


async def _collect_finished_pending(shield: Any) -> list[str]:
    finished = []
    for service_name, info in shield.pending.items():
        _LOGGER.debug("[OIG Shield] Kontroluji pending službu: %s", service_name)
        if await _process_pending_service(shield, service_name, info):
            finished.append(service_name)
    return finished


def _clear_finished_pending(shield: Any, finished: list[str]) -> None:
    for service_name in finished:
        shield.pending.pop(service_name, None)
        if shield.running == service_name:
            shield.running = None


async def _maybe_start_next_call(shield: Any) -> None:
    if shield.running or not shield.queue:
        return
    (
        service_name,
        params,
        expected_entities,
        original_call,
        domain,
        service,
        blocking,
        context,
    ) = shield.queue.pop(0)
    await shield._start_call(
        service_name,
        params,
        expected_entities,
        original_call,
        domain,
        service,
        blocking,
        context,
    )


async def _process_pending_service(
    shield: Any, service_name: str, info: Dict[str, Any]
) -> bool:
    timeout_minutes = _get_timeout_minutes(service_name)

    if datetime.now() - info["called_at"] > timedelta(minutes=timeout_minutes):
        await _handle_timeout(shield, service_name, info)
        return True

    if _check_power_monitor(shield, info):
        await _handle_power_monitor_completion(shield, service_name, info)
        return True

    if _entities_match(shield, service_name, info, timeout_minutes):
        await _handle_entity_completion(shield, service_name, info)
        return True

    return False


def _check_power_monitor(shield: Any, info: Dict[str, Any]) -> bool:
    power_monitor = info.get("power_monitor")
    if not power_monitor:
        return False

    current_power = _get_power_monitor_state(shield, power_monitor)
    if current_power is None:
        return False

    try:
        last_power = power_monitor["last_power"]
        is_going_to_home_ups = power_monitor["is_going_to_home_ups"]
        threshold_w = power_monitor["threshold_kw"] * 1000
        power_delta = current_power - last_power

        _LOGGER.info(
            "[OIG Shield] Power monitor check: current=%sW, last=%sW, delta=%sW, threshold=±%sW, going_to_ups=%s",
            current_power,
            last_power,
            power_delta,
            threshold_w,
            is_going_to_home_ups,
        )

        power_monitor["last_power"] = current_power

        if is_going_to_home_ups and power_delta >= threshold_w:
            _LOGGER.info(
                "[OIG Shield] ✅ POWER JUMP DETECTED! Nárůst %sW (>= %sW) → HOME UPS aktivní",
                power_delta,
                threshold_w,
            )
            return True

        if not is_going_to_home_ups and power_delta <= -threshold_w:
            _LOGGER.info(
                "[OIG Shield] ✅ POWER DROP DETECTED! Pokles %sW (<= -%sW) → HOME UPS vypnutý",
                power_delta,
                threshold_w,
            )
            return True

    except (ValueError, TypeError) as err:
        _LOGGER.warning("[OIG Shield] Chyba při parsování power hodnoty: %s", err)

    return False


async def _handle_power_monitor_completion(
    shield: Any, service_name: str, info: Dict[str, Any]
) -> None:
    _LOGGER.info(
        "[SHIELD CHECK] ✅✅✅ Služba %s dokončena pomocí POWER MONITOR!", service_name
    )
    await shield._log_event(
        "completed",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "original_states": info.get("original_states", {}),
        },
        reason="Detekován skok výkonu (power monitor)",
    )
    await shield._log_telemetry(
        "completed",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "completion_method": "power_monitor",
        },
    )
    await shield._log_event(
        "released",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "original_states": info.get("original_states", {}),
        },
        reason="Semafor uvolněn – služba dokončena (power monitor)",
    )


def _entities_match(
    shield: Any, service_name: str, info: Dict[str, Any], timeout_minutes: int
) -> bool:
    _LOGGER.info(
        "[SHIELD CHECK] Služba: %s, entities: %s",
        service_name,
        info["entities"],
    )

    # Log grid delivery step info for debugging split flow
    params = info.get("params", {})
    grid_step = params.get("_grid_delivery_step")
    if grid_step:
        _LOGGER.info(
            "[SHIELD CHECK] Grid delivery split step detected: %s", grid_step
        )

    # Log box mode step info for debugging composite split flow
    box_mode_step = params.get("_box_mode_step")
    if box_mode_step:
        _LOGGER.info(
            "[SHIELD CHECK] Box mode split step detected: %s", box_mode_step
        )

    all_expected = info["entities"]
    for entity_id, expected_value in all_expected.items():
        if entity_id.startswith("fake_formating_mode_"):
            _LOGGER.debug(
                "[OIG Shield] Formating mode - čekám na timeout (zbývá %.1f min)",
                timeout_minutes
                - (datetime.now() - info["called_at"]).total_seconds() / 60,
            )
            return False

        state = shield.hass.states.get(entity_id)
        current_value = state.state if state else None

        # Reject completion on malformed/unavailable values
        if _is_unavailable_value(current_value):
            _LOGGER.debug(
                "[SHIELD CHECK] ❌ Entity %s je nedostupná (hodnota: '%s'), čekám na platná data",
                entity_id,
                current_value,
            )
            return False

        # Check for telemetry lag in grid delivery flow
        if _should_reject_completion_due_to_telemetry_lag(
            shield, entity_id, expected_value, current_value, all_expected
        ):
            _LOGGER.debug(
                "[SHIELD CHECK] ❌ Entity %s - potenciální telemetry lag, čekám na stabilní stav",
                entity_id,
            )
            return False

        norm_expected, norm_current = _normalize_entity_values(
            shield, entity_id, expected_value, current_value
        )

        _LOGGER.info(
            "[SHIELD CHECK] Kontrola %s: aktuální='%s', očekávaná='%s' (normalizace: '%s' vs '%s') → MATCH: %s",
            entity_id,
            current_value,
            expected_value,
            norm_current,
            norm_expected,
            norm_current == norm_expected,
        )

        if norm_current != norm_expected:
            _LOGGER.debug(
                "[SHIELD CHECK] ❌ Entity %s NENÍ v požadovaném stavu! Očekáváno '%s', je '%s'",
                entity_id,
                norm_expected,
                norm_current,
            )
            return False

    return True


def _is_unavailable_value(value: Any) -> bool:
    """Check if a value represents unavailable/unknown state.

    Returns True for None, empty string, 'unknown', 'unavailable', or any
    value that indicates the entity is not providing valid data.
    """
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in ("", "unknown", "unavailable", "none")
    return False


def _is_numeric_value(value: Any) -> bool:
    """Check if value can be converted to a valid numeric value."""
    if _is_unavailable_value(value):
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _get_grid_delivery_related_entity(entity_id: str) -> Optional[str]:
    """Get the related grid delivery entity for cross-validation.

    For limit entity, returns the mode entity and vice versa.
    Derives the related entity by suffix substitution on the entity_id.
    """
    if entity_id.endswith("_invertor_prm1_p_max_feed_grid"):
        return entity_id[: -len("_invertor_prm1_p_max_feed_grid")] + "_invertor_prms_to_grid"
    elif entity_id.endswith("_invertor_prms_to_grid"):
        return entity_id[: -len("_invertor_prms_to_grid")] + "_invertor_prm1_p_max_feed_grid"
    return None


def _should_reject_completion_due_to_telemetry_lag(
    shield: Any,
    entity_id: str,
    expected_value: Any,
    current_value: Any,
    all_expected: Dict[str, str],
) -> bool:
    """Check if completion should be rejected due to telemetry lag/mismatch.

    During grid delivery transitions, mode and limit may temporarily disagree
    due to telemetry lag. This prevents false completion when:
    1. Limit step completes but mode hasn't updated to 'limited' yet
    2. Mode shows 'limited' but limit value is still stale

    Returns True if completion should be rejected, False otherwise.
    """
    # Only apply to grid delivery entities
    if not entity_id or not (
        entity_id.endswith("_invertor_prm1_p_max_feed_grid")
        or entity_id.endswith("_invertor_prms_to_grid")
    ):
        return False

    # Check for unavailable/malformed values - always reject
    if _is_unavailable_value(current_value):
        return True

    # For limit entity, check if the related mode entity shows "limited"
    if entity_id.endswith("_invertor_prm1_p_max_feed_grid"):
        related_mode_entity = _get_grid_delivery_related_entity(entity_id)
        if related_mode_entity and related_mode_entity not in all_expected:
            mode_state = shield.hass.states.get(related_mode_entity)
            if mode_state is not None:
                mode_current = mode_state.state if mode_state else None
                mode_normalized = shield._normalize_value(mode_current)
                if mode_normalized != "omezeno":
                    _LOGGER.debug(
                        "[SHIELD CHECK] Rejecting limit completion: mode is '%s' (expected 'omezeno'), "
                        "possible telemetry lag",
                        mode_current,
                    )
                    return True

    return False


def _normalize_entity_values(
    shield: Any,
    entity_id: str,
    expected_value: Any,
    current_value: Any,
) -> Tuple[str, str]:
    """Normalize entity values for comparison.

    For grid delivery limit entity, performs numeric comparison.
    For other entities, uses string normalization.

    Returns normalized (expected, current) tuple.
    """
    if entity_id and entity_id.endswith("_invertor_prm1_p_max_feed_grid"):
        # For limit entity, prefer numeric comparison
        expected_is_numeric = _is_numeric_value(expected_value)
        current_is_numeric = _is_numeric_value(current_value)

        if expected_is_numeric and current_is_numeric:
            try:
                return (
                    str(round(float(expected_value))),
                    str(round(float(current_value))),
                )
            except (ValueError, TypeError):
                pass
        # Fall through to string comparison if numeric fails
        # Use empty string for unavailable current values
        safe_current = "" if _is_unavailable_value(current_value) else str(current_value or "")
        return (str(expected_value), safe_current)

    norm_expected = shield._normalize_value(expected_value)
    norm_current = shield._normalize_value(current_value)

    if entity_id and entity_id.endswith("_invertor_prms_to_grid"):
        if entity_id.startswith("binary_sensor.") and norm_expected == "omezeno":
            norm_expected = "zapnuto"

    return norm_expected, norm_current


async def _handle_entity_completion(
    shield: Any, service_name: str, info: Dict[str, Any]
) -> None:
    _LOGGER.info(
        "[SHIELD CHECK] ✅ Service %s completed - all entities match", service_name
    )
    await shield._log_event(
        "completed",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "original_states": info.get("original_states", {}),
        },
        reason="Všechny entity mají očekávané hodnoty",
    )
    await shield._log_telemetry(
        "completed",
        service_name,
        {"params": info["params"], "entities": info["entities"]},
    )
    await shield._log_event(
        "released",
        service_name,
        {
            "params": info["params"],
            "entities": info["entities"],
            "original_states": info.get("original_states", {}),
        },
        reason="Semafor uvolněn – služba dokončena",
    )


def start_monitoring_task(
    shield: Any, task_id: str, expected_entities: Dict[str, str], timeout: int
) -> None:
    """Start monitoring task."""
    shield._active_tasks[task_id] = {
        "expected_entities": expected_entities,
        "timeout": timeout,
        "start_time": time.time(),
        "status": "monitoring",
    }

    shield._log_security_event(
        "MONITORING_STARTED",
        {
            "task_id": task_id,
            "expected_entities": str(expected_entities),
            "timeout": timeout,
            "status": "started",
        },
    )


async def check_entities_periodically(shield: Any, task_id: str) -> None:
    """Periodically check entities for a task."""
    await asyncio.sleep(0)
    while task_id in shield._active_tasks:
        task_info = shield._active_tasks[task_id]
        expected_entities = task_info["expected_entities"]

        all_conditions_met = True
        for entity_id, expected_value in expected_entities.items():
            current_value = shield._get_entity_state(entity_id)
            if not shield._values_match(current_value, expected_value):
                all_conditions_met = False
                shield._log_security_event(
                    "VERIFICATION_FAILED",
                    {
                        "task_id": task_id,
                        "entity": entity_id,
                        "expected_value": expected_value,
                        "actual_value": current_value,
                        "status": "mismatch",
                    },
                )

        if all_conditions_met:
            shield._log_security_event(
                "MONITORING_SUCCESS",
                {
                    "task_id": task_id,
                    "status": "completed",
                    "duration": time.time() - task_info["start_time"],
                },
            )
            shield._log_security_event(
                "MONITORING_SUCCESS",
                {
                    "task_id": task_id,
                    "status": "completed",
                    "duration": time.time() - task_info["start_time"],
                },
            )
            break

        if time.time() - task_info["start_time"] > task_info["timeout"]:
            shield._log_security_event(
                "MONITORING_TIMEOUT",
                {
                    "task_id": task_id,
                    "status": "timeout",
                    "duration": task_info["timeout"],
                },
            )
            shield._log_security_event(
                "MONITORING_TIMEOUT",
                {
                    "task_id": task_id,
                    "status": "timeout",
                    "duration": task_info["timeout"],
                },
            )
            break


def start_monitoring(shield: Any) -> None:
    """Start monitoring task."""
    if shield.check_task is None or shield.check_task.done():
        _LOGGER.info("[OIG Shield] Spouštím monitoring task")

        if shield.check_task and shield.check_task.done():
            _LOGGER.warning(
                "[OIG Shield] Předchozí task byl dokončen: %s", shield.check_task
            )

        shield.check_task = asyncio.create_task(async_check_loop(shield))

        _LOGGER.info("[OIG Shield] Task vytvořen: %s", shield.check_task)
        _LOGGER.info("[OIG Shield] Task done: %s", shield.check_task.done())
        _LOGGER.info("[OIG Shield] Task cancelled: %s", shield.check_task.cancelled())
    else:
        _LOGGER.debug("[OIG Shield] Monitoring task již běží")


async def async_check_loop(shield: Any) -> None:
    """Async loop for processing services."""
    _LOGGER.debug("[OIG Shield] Monitoring loop spuštěn")

    while True:
        try:
            await check_loop(shield, datetime.now())
            await asyncio.sleep(1)
        except Exception as err:
            _LOGGER.error(
                "[OIG Shield] Chyba v monitoring smyčce: %s", err, exc_info=True
            )
            await asyncio.sleep(5)
