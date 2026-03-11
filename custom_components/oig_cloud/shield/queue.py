"""Service shield queue helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.core import callback
from homeassistant.util.dt import now as dt_now

TIMEOUT_MINUTES = 15
SERVICE_SET_BOX_MODE = "oig_cloud.set_box_mode"

_LOGGER = logging.getLogger(__name__)


async def handle_shield_status(shield: Any, call: Any) -> None:
    """Handle shield status service call."""
    status = get_shield_status(shield)
    _LOGGER.info("[OIG Shield] Current status: %s", status)

    shield.hass.bus.async_fire(
        "oig_cloud_shield_status",
        {"status": status, "timestamp": dt_now().isoformat()},
    )


async def handle_queue_info(shield: Any, call: Any) -> None:
    """Handle queue info service call."""
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

    def _matches_target(entities: Dict[str, str]) -> bool:
        if not entities:
            return False
        if not target_mode:
            return True

        normalized_target = shield._normalize_value(target_mode)
        for value in entities.values():
            if shield._normalize_value(value) == normalized_target:
                return True
        return False

    for service_name, info in shield.pending.items():
        if service_name == SERVICE_SET_BOX_MODE and _matches_target(
            info.get("entities", {})
        ):
            return True

    for service_name, _params, expected_entities, *_ in shield.queue:
        if service_name == SERVICE_SET_BOX_MODE and _matches_target(expected_entities):
            return True

    if shield.running == SERVICE_SET_BOX_MODE:
        return True

    return False


@callback
async def check_loop(shield: Any, _now: datetime) -> None:  # noqa: C901
    """Check pending operations and advance queue."""
    if shield._is_checking:
        _LOGGER.debug("[OIG Shield] Check loop již běží, přeskakuji")
        return

    shield._is_checking = True
    try:
        _LOGGER.debug(
            "[OIG Shield] Check loop tick - pending: %s, queue: %s, running: %s",
            len(shield.pending),
            len(shield.queue),
            shield.running,
        )

        if not shield.pending and not shield.queue and not shield.running:
            _LOGGER.debug("[OIG Shield] Check loop - vše prázdné, žádná akce")
            if shield._state_listener_unsub:
                shield._state_listener_unsub()
                shield._state_listener_unsub = None
            return

        finished = []

        for service_name, info in shield.pending.items():
            _LOGGER.debug("[OIG Shield] Kontroluji pending službu: %s", service_name)

            timeout_minutes = (
                2 if service_name == "oig_cloud.set_formating_mode" else TIMEOUT_MINUTES
            )

            if datetime.now() - info["called_at"] > timedelta(minutes=timeout_minutes):
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
                else:
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
                finished.append(service_name)
                continue

            power_completed = False
            power_monitor = info.get("power_monitor")
            if power_monitor:
                power_entity = power_monitor["entity_id"]
                power_state = shield.hass.states.get(power_entity)

                if not power_state:
                    _LOGGER.warning(
                        "[OIG Shield] Power monitor: entita %s neexistuje",
                        power_entity,
                    )
                elif power_state.state in ["unknown", "unavailable"]:
                    _LOGGER.debug(
                        "[OIG Shield] Power monitor: entita %s je %s",
                        power_entity,
                        power_state.state,
                    )
                else:
                    try:
                        current_power = float(power_state.state)
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
                            power_completed = True
                        elif not is_going_to_home_ups and power_delta <= -threshold_w:
                            _LOGGER.info(
                                "[OIG Shield] ✅ POWER DROP DETECTED! Pokles %sW (<= -%sW) → HOME UPS vypnutý",
                                power_delta,
                                threshold_w,
                            )
                            power_completed = True
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning(
                            "[OIG Shield] Chyba při parsování power hodnoty: %s", err
                        )

            if power_completed:
                _LOGGER.info(
                    "[SHIELD CHECK] ✅✅✅ Služba %s dokončena pomocí POWER MONITOR!",
                    service_name,
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
                finished.append(service_name)
                continue

            all_ok = True
            _LOGGER.info(
                "[SHIELD CHECK] Služba: %s, entities: %s",
                service_name,
                info["entities"],
            )
            for entity_id, expected_value in info["entities"].items():
                if entity_id.startswith("fake_formating_mode_"):
                    all_ok = False
                    _LOGGER.debug(
                        "[OIG Shield] Formating mode - čekám na timeout (zbývá %.1f min)",
                        timeout_minutes
                        - (datetime.now() - info["called_at"]).total_seconds() / 60,
                    )
                    break

                state = shield.hass.states.get(entity_id)
                current_value = state.state if state else None

                if entity_id and entity_id.endswith("_invertor_prm1_p_max_feed_grid"):
                    try:
                        norm_expected = str(round(float(expected_value)))
                        norm_current = str(round(float(current_value)))
                    except (ValueError, TypeError):
                        norm_expected = str(expected_value)
                        norm_current = str(current_value or "")
                elif entity_id and entity_id.endswith("_invertor_prms_to_grid"):
                    norm_expected = shield._normalize_value(expected_value)
                    norm_current = shield._normalize_value(current_value)
                    if (
                        entity_id.startswith("binary_sensor.")
                        and norm_expected == "omezeno"
                    ):
                        norm_expected = "zapnuto"
                else:
                    norm_expected = shield._normalize_value(expected_value)
                    norm_current = shield._normalize_value(current_value)

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
                    all_ok = False
                    _LOGGER.debug(
                        "[SHIELD CHECK] ❌ Entity %s NENÍ v požadovaném stavu! Očekáváno '%s', je '%s'",
                        entity_id,
                        norm_expected,
                        norm_current,
                    )
                    break

            if all_ok:
                _LOGGER.info(
                    "[SHIELD CHECK] ✅ Service %s completed - all entities match",
                    service_name,
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
                finished.append(service_name)

        for service_name in finished:
            shield.pending.pop(service_name, None)
            if shield.running == service_name:
                shield.running = None

        if not shield.running and shield.queue:
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

        if finished:
            shield._notify_state_change()

    finally:
        shield._is_checking = False


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
