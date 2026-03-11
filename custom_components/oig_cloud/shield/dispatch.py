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

    if (
        service_name == "oig_cloud.set_grid_delivery"
        and "mode" in params
        and "limit" in params
    ):
        _LOGGER.info(
            "[Grid Delivery] Detected mode + limit together, splitting into 2 calls"
        )

        mode_params = {k: v for k, v in params.items() if k != "limit"}
        limit_params = {k: v for k, v in params.items() if k != "mode"}

        _LOGGER.info("[Grid Delivery] Step 1/2: Processing mode change")
        await intercept_service_call(
            shield,
            domain,
            service,
            {"params": mode_params},
            original_call,
            blocking,
            context,
        )

        _LOGGER.info("[Grid Delivery] Step 2/2: Processing limit change")
        await intercept_service_call(
            shield,
            domain,
            service,
            {"params": limit_params},
            original_call,
            blocking,
            context,
        )

        _LOGGER.info("[Grid Delivery] Both calls queued successfully")
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

    if not expected_entities:
        _LOGGER.debug("Intercept: no expected entities; returning early")
        await shield._log_event(
            "skipped",
            service_name,
            {"params": params, "entities": {}},
            reason="Není co měnit – požadované hodnoty již nastaveny",
            context=context,
        )
        return

    new_expected_set = frozenset(expected_entities.items())

    _LOGGER.debug("Dedup: checking for duplicates")
    _LOGGER.debug("Dedup: new service=%s", service_name)
    _LOGGER.debug("Dedup: new params=%s", params)
    _LOGGER.debug("Dedup: new expected=%s", expected_entities)
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

    duplicate_found = False
    duplicate_location = None
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
            duplicate_found = True
            duplicate_location = "queue"
            _LOGGER.debug("Dedup: duplicate found in queue")
            _LOGGER.debug(
                "Dedup: matching service=%s params=%s expected=%s", q[0], q[1], q[2]
            )
            break

    if not duplicate_found:
        for pending_service_key, pending_info in shield.pending.items():
            pending_entities = pending_info.get("entities", {})
            pending_expected_set = frozenset(pending_entities.items())

            if (
                pending_service_key == service_name
                and pending_expected_set == new_expected_set
            ):
                duplicate_found = True
                duplicate_location = "pending"
                _LOGGER.debug("Dedup: duplicate found in pending")
                _LOGGER.debug(
                    "Dedup: matching service=%s expected=%s",
                    pending_service_key,
                    pending_entities,
                )
                break

    if duplicate_found:
        _LOGGER.debug(
            "Intercept: service already in %s; returning early", duplicate_location
        )
        await shield._log_event(
            "ignored",
            service_name,
            {"params": params, "entities": expected_entities},
            reason=f"Ignorováno – služba se stejným efektem je již {'ve frontě' if duplicate_location == 'queue' else 'spuštěna'}",
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
        return

    all_ok = True
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
            all_ok = False
            break

    if all_ok:
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
    else:
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
    original_states = {}
    for entity_id in expected_entities.keys():
        state = shield.hass.states.get(entity_id)
        original_states[entity_id] = state.state if state else None

    power_monitor = None
    if service_name == SERVICE_SET_BOX_MODE:
        box_id = None
        if shield.hass.data.get("oig_cloud"):
            for entry_id, entry_data in shield.hass.data["oig_cloud"].items():
                if entry_data.get("service_shield") == shield:
                    coordinator = entry_data.get("coordinator")
                    if coordinator:
                        try:
                            from ..entities.base_sensor import resolve_box_id

                            box_id = resolve_box_id(coordinator)
                        except Exception:
                            box_id = None
                        break

        if not box_id:
            _LOGGER.warning("[OIG Shield] Power monitor: box_id nenalezen!")
        else:
            power_entity = f"sensor.oig_{box_id}_actual_aci_wtotal"
            power_state = shield.hass.states.get(power_entity)

            if not power_state:
                _LOGGER.warning(
                    "[OIG Shield] Power monitor: entita %s neexistuje!",
                    power_entity,
                )
            elif power_state.state in ["unknown", "unavailable"]:
                _LOGGER.warning(
                    "[OIG Shield] Power monitor: entita %s je %s",
                    power_entity,
                    power_state.state,
                )
            else:
                try:
                    current_power = float(power_state.state)
                    target_mode = data.get("value", "").upper()

                    power_monitor = {
                        "entity_id": power_entity,
                        "baseline_power": current_power,
                        "last_power": current_power,
                        "target_mode": target_mode,
                        "is_going_to_home_ups": "HOME UPS" in target_mode,
                        "threshold_kw": 2.5,
                        "started_at": datetime.now(),
                    }
                    _LOGGER.info(
                        "[OIG Shield] Power monitor aktivní pro %s: baseline=%sW, target=%s, going_to_ups=%s",
                        service_name,
                        current_power,
                        target_mode,
                        power_monitor["is_going_to_home_ups"],
                    )
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "[OIG Shield] Nelze inicializovat power monitor: %s",
                        err,
                    )

    shield.pending[service_name] = {
        "entities": expected_entities,
        "original_states": original_states,
        "params": data,
        "called_at": datetime.now(),
        "power_monitor": power_monitor,
    }

    shield.running = service_name
    shield.queue_metadata.pop((service_name, str(data)), None)

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

    shield._notify_state_change()

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

    await original_call(
        domain, service, service_data=data, blocking=blocking, context=context
    )

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

    shield._setup_state_listener()


async def safe_call_service(
    shield: Any, service_name: str, service_data: Dict[str, Any]
) -> bool:
    """Safely call service with state verification."""
    try:
        original_states = {}
        if "entity_id" in service_data:
            entity_id = service_data["entity_id"]
            original_states[entity_id] = shield.hass.states.get(entity_id)

        await shield.hass.services.async_call("oig_cloud", service_name, service_data)

        await asyncio.sleep(2)

        if "entity_id" in service_data:
            entity_id = service_data["entity_id"]

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

            elif "mode" in service_data:
                expected_value = service_data["mode"]
                if shield._check_entity_state_change(entity_id, expected_value):
                    shield._logger.info(
                        "✅ Entita %s změněna na %s", entity_id, expected_value
                    )
                    return True

        return True

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

    message = None

    is_limit_change = entity_id and entity_id.endswith("_invertor_prm1_p_max_feed_grid")

    if event_type == "queued":
        message = f"Zařazeno do fronty – {friendly_name}: čeká na změnu"
    elif event_type == "started":
        message = f"Spuštěno – {friendly_name}: zahajuji změnu"
    elif event_type == "completed":
        if is_limit_change:
            message = (
                f"Dokončeno – {friendly_name}: limit nastaven na {expected_value}W"
            )
        else:
            message = f"Dokončeno – {friendly_name}: změna na '{expected_value}'"
    elif event_type == "timeout":
        if is_limit_change:
            message = f"Časový limit vypršel – {friendly_name}: limit stále není {expected_value}W"
        else:
            message = (
                f"Časový limit vypršel – {friendly_name} stále není '{expected_value}' "
                f"(aktuální: '{from_value}')"
            )
    elif event_type == "released":
        message = f"Semafor uvolněn – služba {service} dokončena"
    elif event_type == "cancelled":
        message = f"Zrušeno uživatelem – {friendly_name}: očekávaná změna na '{expected_value}' nebyla provedena"
    else:
        message = f"{event_type} – {service}"

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

    _LOGGER.debug(
        "[OIG Shield] Event: %s | Entity: %s | From: '%s' → To: '%s' | Reason: %s",
        event_type,
        entity_id,
        from_value,
        expected_value,
        reason or "-",
    )
