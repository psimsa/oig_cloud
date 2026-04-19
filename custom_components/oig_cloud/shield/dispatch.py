"""Service shield dispatch helpers."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.core import Context
from homeassistant.util.dt import now as dt_now

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_BOX_MODE = "oig_cloud.set_box_mode"


def _split_grid_delivery_params(params: Dict[str, Any]) -> Optional[list[Dict[str, Any]]]:
    """Split mode+limit into ordered steps: mode=limited first, then numeric limit.

    The box can only process one value change at a time, so grid delivery must
    stay split. Order is critical: mode must be set to 'limited' BEFORE the
    numeric limit is applied.
    """
    if "mode" in params and "limit" in params:
        # Step 1: Mode must be 'limited' for the limit to take effect
        mode_params = {
            k: v for k, v in params.items() if k != "limit"
        }
        mode_params["_grid_delivery_step"] = "mode"

        # Step 2: Numeric limit (only meaningful after mode=limited)
        limit_params = {
            k: v for k, v in params.items() if k != "mode"
        }
        limit_params["_grid_delivery_step"] = "limit"

        return [mode_params, limit_params]
    return None


_TOGGLE_KEYS = ("home_grid_v", "home_grid_vi")


def _split_box_mode_params(params: Dict[str, Any]) -> Optional[list[Dict[str, Any]]]:
    """Split mode+toggles into ordered steps: mode first, then app toggles.

    The box can only process one value change at a time, so composite box mode
    calls must stay split. Order is critical: main mode must be set BEFORE
    supplementary app bits are applied.
    """
    has_mode = "mode" in params
    has_toggles = any(k in params for k in _TOGGLE_KEYS)
    if has_mode and has_toggles:
        mode_params = {k: v for k, v in params.items() if k not in _TOGGLE_KEYS}
        mode_params["_box_mode_step"] = "mode"

        app_params = {k: v for k, v in params.items() if k != "mode"}
        app_params["_box_mode_step"] = "app"

        return [mode_params, app_params]
    return None


def _is_duplicate(
    shield: Any,
    service_name: str,
    params: Dict[str, Any],
    expected_entities: Dict[str, str],
) -> Optional[str]:
    new_expected_set = frozenset(expected_entities.items())
    new_params_set = frozenset(params.items()) if params else frozenset()

    for q in shield.queue:
        queue_service = q[0]
        queue_params = q[1]
        queue_expected = q[2]

        queue_params_set = (
            frozenset(queue_params.items()) if queue_params else frozenset()
        )
        queue_expected_set = frozenset(queue_expected.items())

        if (
            queue_service == service_name
            and queue_params_set == new_params_set
            and queue_expected_set == new_expected_set
        ):
            return "queue"

    for pending_service_key, pending_info in shield.pending.items():
        pending_entities = pending_info.get("entities", {})
        pending_expected_set = frozenset(pending_entities.items())

        if (
            pending_service_key == service_name
            and pending_expected_set == new_expected_set
        ):
            return "pending"

    return None


def _entities_already_match(
    shield: Any, expected_entities: Dict[str, str], params: Optional[Dict[str, Any]] = None
) -> bool:
    """Check if entities already match expected values.

    For grid delivery limit step (step 2 of split flow), we must NOT skip
    even if the mode is already 'limited' - the limit value itself needs
    to be applied. The step metadata in params helps identify this case.
    """
    # For grid delivery limit step, always proceed (don't skip early)
    if params and params.get("_grid_delivery_step") == "limit":
        _LOGGER.debug(
            "Intercept: grid delivery limit step detected - proceeding regardless of current state"
        )
        return False

    for entity_id, expected_value in expected_entities.items():
        state = shield.hass.states.get(entity_id)
        current = shield._normalize_value(state.state if state else None)
        expected = shield._normalize_value(expected_value)
        _LOGGER.debug(
            "Intercept: entity=%s current=%r expected=%r",
            entity_id,
            current,
            expected,
        )
        if current != expected:
            return False
    return True


async def _handle_split_grid_delivery(
    shield: Any,
    domain: str,
    service: str,
    params: Dict[str, Any],
    original_call: Any,
    blocking: bool,
    context: Optional[Context],
) -> bool:
    """Handle split grid delivery: mode=limited first, then numeric limit."""
    split_params = _split_grid_delivery_params(params)
    if not split_params:
        return False

    mode_step = split_params[0]
    limit_step = split_params[1]

    _LOGGER.info(
        "[Grid Delivery] Splitting mode+limit into ordered steps: "
        "mode='%s' (step 1) → limit='%s' (step 2)",
        mode_step.get("mode"),
        limit_step.get("limit"),
    )

    # Step 1: Set mode to 'limited' first
    _LOGGER.info("[Grid Delivery] Step 1/2: Setting mode to 'limited'")
    await intercept_service_call(
        shield,
        domain,
        service,
        {"params": mode_step},
        original_call,
        blocking,
        context,
    )

    # Step 2: Set numeric limit after mode=limited is confirmed
    _LOGGER.info("[Grid Delivery] Step 2/2: Setting numeric limit")
    await intercept_service_call(
        shield,
        domain,
        service,
        {"params": limit_step},
        original_call,
        blocking,
        context,
    )

    _LOGGER.info("[Grid Delivery] Both ordered steps queued successfully")
    return True


async def _handle_split_box_mode(
    shield: Any,
    domain: str,
    service: str,
    params: Dict[str, Any],
    original_call: Any,
    blocking: bool,
    context: Optional[Context],
) -> bool:
    """Handle split box mode: main mode first, then app toggles."""
    split_params = _split_box_mode_params(params)
    if not split_params:
        return False

    mode_step = split_params[0]
    app_step = split_params[1]

    _LOGGER.info(
        "[Box Mode] Splitting mode+toggles into ordered steps: "
        "mode='%s' (step 1) → app='%s' (step 2)",
        mode_step.get("mode"),
        {k: v for k, v in app_step.items() if not k.startswith("_")},
    )

    _LOGGER.info("[Box Mode] Step 1/2: Setting main mode")
    await intercept_service_call(
        shield,
        domain,
        service,
        {"params": mode_step},
        original_call,
        blocking,
        context,
    )

    _LOGGER.info("[Box Mode] Step 2/2: Setting app toggles")
    await intercept_service_call(
        shield,
        domain,
        service,
        {"params": app_step},
        original_call,
        blocking,
        context,
    )

    _LOGGER.info("[Box Mode] Both ordered steps queued successfully")
    return True


async def _handle_duplicate(
    shield: Any,
    duplicate_location: str,
    service_name: str,
    params: Dict[str, Any],
    expected_entities: Dict[str, str],
    context: Optional[Context],
) -> None:
    _LOGGER.debug(
        "Intercept: service already in %s; returning early", duplicate_location
    )
    await shield._log_event(
        "ignored",
        service_name,
        {"params": params, "entities": expected_entities},
        reason=(
            "Ignorováno – služba se stejným efektem je již "
            f"{'ve frontě' if duplicate_location == 'queue' else 'spuštěna'}"
        ),
        context=context,
    )
    await shield._log_telemetry(
        "ignored",
        service_name,
        {
            "params": params,
            "entities": expected_entities,
            "reason": f"duplicate_in_{duplicate_location}",
        },
    )


def _log_dedup_state(shield: Any, service_name: str, params: Dict[str, Any], expected: Dict[str, str]) -> None:
    _LOGGER.debug("Dedup: checking for duplicates")
    _LOGGER.debug("Dedup: new service=%s", service_name)
    _LOGGER.debug("Dedup: new params=%s", params)
    _LOGGER.debug("Dedup: new expected=%s", expected)
    _LOGGER.debug("Dedup: queue length=%s", len(shield.queue))
    _LOGGER.debug("Dedup: pending length=%s", len(shield.pending))
    for i, q in enumerate(shield.queue):
        _LOGGER.debug(
            "Dedup: queue[%s] service=%s params=%s expected=%s", i, q[0], q[1], q[2]
        )
    for service_key, pending_info in shield.pending.items():
        _LOGGER.debug(
            "Dedup: pending service=%s entities=%s",
            service_key,
            pending_info.get("entities", {}),
        )


async def _enqueue_or_run(
    shield: Any,
    service_name: str,
    params: Dict[str, Any],
    expected_entities: Dict[str, str],
    original_call: Any,
    domain: str,
    service: str,
    blocking: bool,
    context: Optional[Context],
    trace_id: str,
) -> None:
    if shield.running is not None:
        _LOGGER.info(
            "[OIG Shield] Služba %s přidána do fronty (běží: %s)",
            service_name,
            shield.running,
        )
        shield.queue.append(
            (
                service_name,
                params,
                expected_entities,
                original_call,
                domain,
                service,
                blocking,
                context,
            )
        )
        shield.queue_metadata[(service_name, str(params))] = {
            "trace_id": trace_id,
            "queued_at": datetime.now(),
        }

        if service_name == SERVICE_SET_BOX_MODE and shield.mode_tracker:
            from_mode = params.get("current_value")
            to_mode = params.get("value")
            if from_mode and to_mode:
                shield.mode_tracker.track_request(trace_id, from_mode, to_mode)

        shield._notify_state_change()

        await shield._log_event(
            "queued",
            service_name,
            {"params": params, "entities": expected_entities},
            reason=f"Přidáno do fronty (běží: {shield.running})",
            context=context,
        )
        return

    _LOGGER.info("[OIG Shield] Spouštím službu %s (fronta prázdná)", service_name)

    if service_name == SERVICE_SET_BOX_MODE and shield.mode_tracker:
        from_mode = params.get("current_value")
        to_mode = params.get("value")
        if from_mode and to_mode:
            shield.mode_tracker.track_request(trace_id, from_mode, to_mode)

    await start_call(
        shield,
        service_name,
        params,
        expected_entities,
        original_call,
        domain,
        service,
        blocking,
        context,
    )


async def intercept_service_call(
    shield: Any,
    domain: str,
    service: str,
    data: Dict[str, Any],
    original_call: Any,
    blocking: bool,
    context: Optional[Context],
) -> None:
    """Intercept service calls and queue/execute in shield."""
    service_name = f"{domain}.{service}"
    params = data["params"]
    trace_id = str(uuid.uuid4())[:8]

    if service_name == "oig_cloud.set_grid_delivery" and await _handle_split_grid_delivery(
        shield, domain, service, params, original_call, blocking, context
    ):
        return

    if service_name == SERVICE_SET_BOX_MODE and await _handle_split_box_mode(
        shield, domain, service, params, original_call, blocking, context
    ):
        return

    expected_entities = shield.extract_expected_entities(service_name, params)
    api_info = shield._extract_api_info(service_name, params)

    _LOGGER.debug("Intercept service: %s", service_name)
    _LOGGER.debug("Intercept expected entities: %s", expected_entities)
    _LOGGER.debug("Intercept queue length: %s", len(shield.queue))
    _LOGGER.debug("Intercept running: %s", shield.running)

    shield._log_security_event(
        "SERVICE_INTERCEPTED",
        {
            "task_id": trace_id,
            "service": service_name,
            "params": str(params),
            "expected_entities": str(expected_entities),
        },
    )

    if not expected_entities and getattr(shield, "_expected_entity_missing", False):
        _LOGGER.debug(
            "Intercept: expected entities missing; calling original service without state verification"
        )
        await original_call(
            domain, service, service_data=params, blocking=blocking, context=context
        )
        await shield._log_event(
            "change_requested",
            service_name,
            {"params": params, "entities": {}},
            reason="Entita nenalezena – volám službu bez state validace",
            context=context,
        )
        return

    _log_dedup_state(shield, service_name, params, expected_entities)

    duplicate_location = _is_duplicate(
        shield, service_name, params, expected_entities
    )

    if duplicate_location:
        await _handle_duplicate(
            shield, duplicate_location, service_name, params, expected_entities, context
        )
        return

    if _entities_already_match(shield, expected_entities, params):
        _LOGGER.debug("Intercept: all entities already match; returning early")
        await shield._log_telemetry(
            "skipped",
            service_name,
            {
                "trace_id": trace_id,
                "params": params,
                "entities": expected_entities,
                "reason": "already_completed",
                **api_info,
            },
        )
        await shield._log_event(
            "skipped",
            service_name,
            {"params": params, "entities": expected_entities},
            reason="Změna již provedena – není co volat",
            context=context,
        )
        return

    _LOGGER.debug("Intercept: will execute service; logging telemetry")
    await shield._log_telemetry(
        "change_requested",
        service_name,
        {
            "trace_id": trace_id,
            "params": params,
            "entities": expected_entities,
            **api_info,
        },
    )

    await _enqueue_or_run(
        shield,
        service_name,
        params,
        expected_entities,
        original_call,
        domain,
        service,
        blocking,
        context,
        trace_id,
    )


async def start_call(
    shield: Any,
    service_name: str,
    data: Dict[str, Any],
    expected_entities: Dict[str, str],
    original_call: Any,
    domain: str,
    service: str,
    blocking: bool,
    context: Optional[Context],
) -> None:
    """Start a call and register pending state."""
    original_states = _capture_original_states(shield, expected_entities)
    power_monitor = _init_power_monitor(shield, service_name, data)

    shield.pending[service_name] = {
        "entities": expected_entities,
        "original_states": original_states,
        "params": data,
        "called_at": datetime.now(),
        "power_monitor": power_monitor,
    }

    shield.running = service_name
    shield.queue_metadata.pop((service_name, str(data)), None)

    _fire_queue_info_event(shield)

    shield._notify_state_change()

    await _log_start_events(
        shield,
        service_name,
        data=data,
        expected_entities=expected_entities,
        original_states=original_states,
        context=context,
    )

    actual_params = data.get("params", data)
    try:
        await original_call(
            domain, service, service_data=actual_params, blocking=blocking, context=context
        )
    except Exception as err:
        _LOGGER.error("[OIG Shield] Service call %s failed: %s", service_name, err)
        shield.pending.pop(service_name, None)
        shield.running = None
        await shield._log_event(
            "error",
            service_name,
            {"params": data, "entities": expected_entities, "error": str(err)},
            reason=f"Služba selhala: {err}",
            context=context,
        )
        shield._notify_state_change()
        if shield.queue:
            shield.hass.async_create_task(shield._check_loop(datetime.now()))
        return

    await _refresh_coordinator_after_call(shield, service_name)

    shield._setup_state_listener()


async def safe_call_service(
    shield: Any, service_name: str, service_data: Dict[str, Any]
) -> bool:
    """Safely call service with state verification."""
    try:
        await shield.hass.services.async_call("oig_cloud", service_name, service_data)

        await asyncio.sleep(2)

        entity_id = service_data.get("entity_id")
        if not entity_id:
            return True

        if service_name == "set_boiler_mode":
            mode_value = service_data.get("mode", "CBB")
            expected_value = 1 if mode_value == "Manual" else 0

            boiler_entities = [
                entity_id
                for entity_id in shield.hass.states.async_entity_ids()
                if "boiler_manual_mode" in entity_id
            ]

            for boiler_entity in boiler_entities:
                if shield._check_entity_state_change(boiler_entity, expected_value):
                    shield._logger.info("✅ Boiler mode změněn na %s", mode_value)
                    return True
            return False  # pragma: no cover

        if "mode" in service_data:
            expected_value = service_data["mode"]
            if shield._check_entity_state_change(entity_id, expected_value):
                shield._logger.info(
                    "✅ Entita %s změněna na %s", entity_id, expected_value
                )
                return True
            return False  # pragma: no cover

        return True  # pragma: no cover

    except Exception as err:
        shield._logger.error("❌ Chyba při volání služby %s: %s", service_name, err)
        return False


async def log_event(
    shield: Any,
    event_type: str,
    service: str,
    data: Dict[str, Any],
    reason: Optional[str] = None,
    context: Optional[Context] = None,
) -> None:
    """Log an event to logbook + fire event."""
    await asyncio.sleep(0)
    params = data.get("params", {}) if data else {}
    entities = data.get("entities", {}) if data else {}

    entity_id = list(entities.keys())[0] if entities else None
    expected_value = list(entities.values())[0] if entities else None

    display_entity_id = (
        shield.last_checked_entity_id if shield.last_checked_entity_id else entity_id
    )

    from_value = None
    if entity_id:
        state = shield.hass.states.get(entity_id)
        from_value = state.state if state else None

    friendly_name = entity_id
    if entity_id:
        state = shield.hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            friendly_name = state.attributes.get("friendly_name")

    is_limit_change = bool(
        entity_id and entity_id.endswith("_invertor_prm1_p_max_feed_grid")
    )
    message = _build_log_message(
        event_type,
        service,
        friendly_name,
        expected_value,
        from_value,
        is_limit_change,
    )

    shield.hass.bus.async_fire(
        "logbook_entry",
        {
            "name": "OIG Shield",
            "message": message,
            "domain": "oig_cloud",
            "entity_id": display_entity_id,
            "when": dt_now(),
            "source": "OIG Cloud Shield",
            "source_type": "system",
        },
        context=context,
    )

    shield.hass.bus.async_fire(
        "oig_cloud_service_shield_event",
        {
            "event_type": event_type,
            "service": service,
            "entity_id": entity_id,
            "from": from_value,
            "to": expected_value,
            "friendly_name": friendly_name,
            "reason": reason,
            "params": params,
        },
        context=context,
    )


def _capture_original_states(
    shield: Any, expected_entities: Dict[str, str]
) -> Dict[str, Optional[str]]:
    original_states: Dict[str, Optional[str]] = {}
    for entity_id in expected_entities.keys():
        state = shield.hass.states.get(entity_id)
        original_states[entity_id] = state.state if state else None
    return original_states


def _init_power_monitor(
    shield: Any, service_name: str, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    if service_name != SERVICE_SET_BOX_MODE:
        return None
    box_id = _resolve_box_id_for_power_monitor(shield)
    if not box_id:
        _LOGGER.warning("[OIG Shield] Power monitor: box_id nenalezen!")
        return None

    power_entity = _build_power_entity(box_id)
    current_power = _read_power_state(shield, power_entity)
    if current_power is None:
        return None

    target_mode = _normalize_target_mode(data)
    if target_mode is None:
        return None  # pragma: no cover

    power_monitor = _build_power_monitor(power_entity, current_power, target_mode)
    _LOGGER.info(
        "[OIG Shield] Power monitor aktivní pro %s: baseline=%sW, target=%s, going_to_ups=%s",
        service_name,
        current_power,
        target_mode,
        power_monitor["is_going_to_home_ups"],
    )
    return power_monitor


def _build_power_entity(box_id: str) -> str:
    return f"sensor.oig_{box_id}_actual_aci_wtotal"


def _read_power_state(shield: Any, power_entity: str) -> Optional[float]:
    power_state = shield.hass.states.get(power_entity)
    if not power_state:
        _LOGGER.warning(
            "[OIG Shield] Power monitor: entita %s neexistuje!",
            power_entity,
        )
        return None
    if power_state.state in ["unknown", "unavailable"]:
        _LOGGER.warning(
            "[OIG Shield] Power monitor: entita %s je %s",
            power_entity,
            power_state.state,
        )
        return None
    try:
        return float(power_state.state)
    except (ValueError, TypeError) as err:
        _LOGGER.warning("[OIG Shield] Nelze inicializovat power monitor: %s", err)
        return None


def _normalize_target_mode(data: Dict[str, Any]) -> Optional[str]:
    target_mode = data.get("value", "")
    if not isinstance(target_mode, str):
        return None  # pragma: no cover
    return target_mode.upper()


def _build_power_monitor(
    power_entity: str, current_power: float, target_mode: str
) -> Dict[str, Any]:
    return {
        "entity_id": power_entity,
        "baseline_power": current_power,
        "last_power": current_power,
        "target_mode": target_mode,
        "is_going_to_home_ups": "HOME UPS" in target_mode,
        "threshold_kw": 2.5,
        "started_at": datetime.now(),
    }


def _resolve_box_id_for_power_monitor(shield: Any) -> Optional[str]:
    if not shield.hass.data.get("oig_cloud"):
        return None  # pragma: no cover
    for _entry_id, entry_data in shield.hass.data["oig_cloud"].items():
        if entry_data.get("service_shield") != shield:
            continue  # pragma: no cover
        coordinator = entry_data.get("coordinator")
        if coordinator:
            try:
                from ..entities.base_sensor import resolve_box_id

                return resolve_box_id(coordinator)
            except Exception:
                return None
    return None


def _fire_queue_info_event(shield: Any) -> None:
    shield.hass.bus.async_fire(
        "oig_cloud_shield_queue_info",
        {
            "running": shield.running,
            "queue_length": len(shield.queue),
            "pending_count": len(shield.pending),
            "queue_services": [item[0] for item in shield.queue],
            "timestamp": dt_now().isoformat(),
        },
    )


async def _log_start_events(
    shield: Any,
    service_name: str,
    *,
    data: Dict[str, Any],
    expected_entities: Dict[str, str],
    original_states: Dict[str, Optional[str]],
    context: Optional[Context],
) -> None:
    await shield._log_event(
        "change_requested",
        service_name,
        {
            "params": data,
            "entities": expected_entities,
            "original_states": original_states,
        },
        reason="Požadavek odeslán do API",
        context=context,
    )

    await shield._log_event(
        "started",
        service_name,
        {
            "params": data,
            "entities": expected_entities,
            "original_states": original_states,
        },
        context=context,
    )


async def _refresh_coordinator_after_call(shield: Any, service_name: str) -> None:
    try:
        from ..const import DOMAIN

        coordinator = (
            shield.hass.data.get(DOMAIN, {})
            .get(shield.entry.entry_id, {})
            .get("coordinator")
        )
        if coordinator:
            _LOGGER.debug(
                "[OIG Shield] Vynucuji okamžitou aktualizaci coordinatoru po API volání pro %s",
                service_name,
            )
            await coordinator.async_request_refresh()
            _LOGGER.debug(
                "[OIG Shield] Coordinator refreshnut - entity by měly být aktuální"
            )
        else:
            _LOGGER.warning(
                "[OIG Shield] Coordinator nenalezen - entity se aktualizují až při příštím scheduled update!"
            )
    except Exception as err:
        _LOGGER.error(
            "[OIG Shield] Chyba při refreshu coordinatoru: %s",
            err,
            exc_info=True,
        )


def _build_log_message(
    event_type: str,
    service: str,
    friendly_name: Optional[str],
    expected_value: Optional[str],
    from_value: Optional[str],
    is_limit_change: bool,
) -> str:
    if event_type == "queued":
        return f"Zařazeno do fronty – {friendly_name}: čeká na změnu"
    if event_type == "started":
        return f"Spuštěno – {friendly_name}: zahajuji změnu"
    if event_type == "completed":
        if is_limit_change:
            return (
                f"Dokončeno – {friendly_name}: limit nastaven na {expected_value}W"
            )
        return f"Dokončeno – {friendly_name}: změna na '{expected_value}'"
    if event_type == "timeout":
        if is_limit_change:
            return (
                f"Časový limit vypršel – {friendly_name}: limit stále není {expected_value}W"
            )
        return (
            f"Časový limit vypršel – {friendly_name} stále není '{expected_value}' "
            f"(aktuální: '{from_value}')"
        )
    if event_type == "released":
        return f"Semafor uvolněn – služba {service} dokončena"
    if event_type == "cancelled":
        return (
            f"Zrušeno uživatelem – {friendly_name}: očekávaná změna na '{expected_value}' nebyla provedena"
        )
    return f"{event_type} – {service}"
