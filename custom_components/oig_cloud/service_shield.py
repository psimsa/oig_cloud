import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util.dt import now as dt_now

from .const import DOMAIN
from .shared.logging import setup_simple_telemetry

_LOGGER = logging.getLogger(__name__)

TIMEOUT_MINUTES = 15
CHECK_INTERVAL_SECONDS = 30  # Zvýšeno z 15 na 30 sekund - slouží jen jako backup
SERVICE_SET_BOX_MODE = "oig_cloud.set_box_mode"


class ServiceShield:
    """OIG Cloud Service Shield - ochrana před neočekávanými změnami."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass: HomeAssistant = hass
        self.entry: ConfigEntry = entry
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._active_tasks: Dict[str, Dict[str, Any]] = {}
        self._telemetry_handler: Optional[Any] = None

        # Inicializace základních atributů
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.queue: List[
            Tuple[
                str,  # service_name
                Dict[str, Any],  # params
                Dict[str, str],  # expected_entities
                Callable,  # original_call
                str,  # domain
                str,  # service
                bool,  # blocking
                Optional[Context],  # context
            ]
        ] = []
        # OPRAVA: queue_metadata nyní ukládá slovník s trace_id a queued_at pro live duration
        self.queue_metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.running: Optional[str] = None
        self.last_checked_entity_id: Optional[str] = None

        # Event-based monitoring
        self._state_listener_unsub: Optional[Callable] = None
        self._is_checking: bool = False  # Lock pro prevenci concurrent execution

        # Callbacks pro okamžitou aktualizaci senzorů
        self._state_change_callbacks: List[Callable[[], None]] = []

        # Atributy pro telemetrii (pro zpětnou kompatibilitu)
        self.telemetry_handler: Optional[Any] = None
        self.telemetry_logger: Optional[Any] = None

        # Mode Transition Tracker (bude inicializován později s box_id)
        self.mode_tracker: Optional[Any] = None

        # Setup telemetrie pouze pro ServiceShield
        if not entry.options.get("no_telemetry", False):
            self._setup_telemetry()

    def _setup_telemetry(self) -> None:
        """Nastavit telemetrii pouze pro ServiceShield."""
        try:
            import hashlib

            username = self.entry.data.get("username", "")
            email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
            hass_id = hashlib.sha256(
                self.hass.data["core.uuid"].encode("utf-8")
            ).hexdigest()

            # Použijeme setup_simple_telemetry místo setup_otel_logging
            self._telemetry_handler = setup_simple_telemetry(email_hash, hass_id)

            # Nastavit i pro zpětnou kompatibilitu
            self.telemetry_handler = self._telemetry_handler

            self._logger.info("ServiceShield telemetry initialized successfully")

        except Exception as e:
            self._logger.debug(f"Failed to setup ServiceShield telemetry: {e}")
            # Pokud telemetrie selže, pokračujeme bez ní
            self.telemetry_handler = None
            self.telemetry_logger = None

    def _log_security_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Zalogovat bezpečnostní událost do telemetrie."""
        if self._telemetry_handler:
            security_logger = logging.getLogger(
                "custom_components.oig_cloud.service_shield.security"
            )
            security_logger.info(
                f"SHIELD_SECURITY: {event_type}",
                extra={
                    "shield_event_type": event_type,
                    "task_id": details.get("task_id"),
                    "service": details.get("service"),
                    "entity": details.get("entity"),
                    "expected_value": details.get("expected_value"),
                    "actual_value": details.get("actual_value"),
                    "status": details.get("status"),
                    "timestamp": dt_now().isoformat(),
                },
            )

    async def _log_telemetry(
        self, event_type: str, service_name: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log telemetry event using SimpleTelemetry."""
        try:
            _LOGGER.debug(
                "Telemetry log start: event_type=%s service=%s",
                event_type,
                service_name,
            )
            _LOGGER.debug(
                "Telemetry handler available: %s", self._telemetry_handler is not None
            )

            if self._telemetry_handler:
                # Připravíme telemetrii data
                telemetry_data: Dict[str, Any] = {
                    "timestamp": dt_now().isoformat(),
                    "component": "service_shield",
                }

                if data:
                    telemetry_data.update(data)

                _LOGGER.debug(
                    "Telemetry data prepared: %s",
                    telemetry_data,
                )

                # Odešleme do SimpleTelemetry
                await self._telemetry_handler.send_event(
                    event_type=event_type,
                    service_name=service_name,
                    data=telemetry_data,
                )

                _LOGGER.debug("Telemetry sent successfully")
            else:
                _LOGGER.debug("Telemetry handler missing; skipping send")

        except Exception as e:
            _LOGGER.error("Failed to log telemetry: %s", e, exc_info=True)

    def register_state_change_callback(self, callback: Callable[[], None]) -> None:
        """Registruje callback, který se zavolá při změně shield stavu."""
        if callback not in self._state_change_callbacks:
            self._state_change_callbacks.append(callback)
            _LOGGER.debug("[OIG Shield] Registrován callback pro aktualizaci senzoru")

    def unregister_state_change_callback(self, callback: Callable[[], None]) -> None:
        """Odregistruje callback."""
        if callback in self._state_change_callbacks:
            self._state_change_callbacks.remove(callback)
            _LOGGER.debug("[OIG Shield] Odregistrován callback")

    def _notify_state_change(self) -> None:
        """Zavolá všechny registrované callbacky při změně stavu."""
        _LOGGER.debug(
            f"[OIG Shield] Notifikuji {len(self._state_change_callbacks)} callbacků o změně stavu"
        )
        for cb in self._state_change_callbacks:
            try:
                result = cb()
                # Pokud callback vrátí coroutine, naplánuj ji
                if result is not None and hasattr(result, "__await__"):
                    self.hass.async_create_task(result)
                # Pokud vrátí None (synchronní callback), nic nedělej
            except Exception as e:
                _LOGGER.error(f"[OIG Shield] Chyba při volání callback: {e}")

    def _values_match(self, current_value: Any, expected_value: Any) -> bool:
        """Porovná dvě hodnoty s normalizací."""
        try:
            # Pro číselné hodnoty
            if str(expected_value).replace(".", "").replace("-", "").isdigit():
                return float(current_value or 0) == float(expected_value)
            # Pro textové hodnoty
            return self._normalize_value(current_value) == self._normalize_value(
                expected_value
            )
        except (ValueError, TypeError):
            return str(current_value) == str(expected_value)

    async def start(self) -> None:
        _LOGGER.debug("[OIG Shield] Inicializace – čištění fronty")
        self.pending.clear()
        self.queue.clear()
        self.queue_metadata.clear()
        self.running = None

        # Registrace shield services
        await self.register_services()

        # Časový backup interval - slouží jako fallback, event-based monitoring je primární
        _LOGGER.info(
            f"[OIG Shield] Spouštím backup check_loop každých {CHECK_INTERVAL_SECONDS} sekund (primárně event-based)"
        )

        async_track_time_interval(
            self.hass, self._check_loop, timedelta(seconds=CHECK_INTERVAL_SECONDS)
        )

    def _setup_state_listener(self) -> None:
        """Nastaví posluchač změn stavů pro entity v pending."""
        # Zrušíme starý listener, pokud existuje
        if self._state_listener_unsub:
            self._state_listener_unsub()
            self._state_listener_unsub = None

        # Pokud nejsou žádné pending služby, nemusíme poslouchat
        if not self.pending:
            _LOGGER.debug(
                "[OIG Shield] Žádné pending služby, state listener nepotřebný"
            )
            return

        # Získáme všechny entity, které sledujeme
        entity_ids = []
        for service_info in self.pending.values():
            entity_ids.extend(service_info.get("entities", {}).keys())

            # Přidat power monitor entity pokud existuje
            power_monitor = service_info.get("power_monitor")
            if power_monitor:
                power_entity = power_monitor.get("entity_id")
                if power_entity and power_entity not in entity_ids:
                    entity_ids.append(power_entity)

        if not entity_ids:
            _LOGGER.debug("[OIG Shield] Žádné entity ke sledování")
            return

        _LOGGER.info(
            f"[OIG Shield] Nastavuji state listener pro {len(entity_ids)} entit: {entity_ids}"
        )

        # Nastavíme posluchač pro všechny sledované entity
        self._state_listener_unsub = async_track_state_change_event(
            self.hass, entity_ids, self._on_entity_state_changed
        )

    @callback
    def _on_entity_state_changed(self, event: Event) -> None:
        """Callback když se změní stav sledované entity - SYNC verze."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        if not new_state:
            return

        _LOGGER.debug(
            f"[OIG Shield] Detekována změna entity {entity_id} na '{new_state.state}' - spouštím kontrolu"
        )

        # KRITICKÁ OPRAVA: @callback NESMÍ být async!
        # Naplánujeme _check_loop() jako async job v event loop
        self.hass.async_create_task(self._check_loop(datetime.now()))

    async def register_services(self) -> None:
        """Registruje služby ServiceShield."""
        _LOGGER.info("[OIG Shield] Registering ServiceShield services")

        try:
            # Registrace služby pro status ServiceShield
            self.hass.services.async_register(
                "oig_cloud",
                "shield_status",
                self._handle_shield_status,
                schema=vol.Schema({}),
            )

            # Registrace služby pro queue info
            self.hass.services.async_register(
                "oig_cloud",
                "shield_queue_info",
                self._handle_queue_info,
                schema=vol.Schema({}),
            )

            # Registrace služby pro smazání z fronty
            self.hass.services.async_register(
                "oig_cloud",
                "shield_remove_from_queue",
                self._handle_remove_from_queue,
                schema=vol.Schema(
                    {
                        vol.Required("position"): int,
                    }
                ),
            )

            _LOGGER.info("[OIG Shield] ServiceShield services registered successfully")

        except Exception as e:
            _LOGGER.error(
                f"[OIG Shield] Failed to register services: {e}", exc_info=True
            )
            raise

    async def _handle_shield_status(self, call: Any) -> None:
        """Handle shield status service call."""
        status = self.get_shield_status()
        _LOGGER.info(f"[OIG Shield] Current status: {status}")

        # Emit event with status
        self.hass.bus.async_fire(
            "oig_cloud_shield_status",
            {"status": status, "timestamp": dt_now().isoformat()},
        )

    async def _handle_queue_info(self, call: Any) -> None:
        """Handle queue info service call."""
        queue_info = self.get_queue_info()
        _LOGGER.info(f"[OIG Shield] Queue info: {queue_info}")

        # Emit event with queue info
        self.hass.bus.async_fire(
            "oig_cloud_shield_queue_info",
            {**queue_info, "timestamp": dt_now().isoformat()},
        )

    async def _handle_remove_from_queue(self, call: Any) -> None:
        """Handle remove from queue service call."""
        position = call.data.get("position")

        # OPRAVA: Position může být:
        # - 1 = running služba (v self.pending)
        # - 2+ = čekající služby (v self.queue)
        total_items = len(self.pending) + len(self.queue)

        if position < 1 or position > total_items:
            _LOGGER.error(
                f"[OIG Shield] Neplatná pozice: {position} (pending: {len(self.pending)}, queue: {len(self.queue)})"
            )
            return

        # Position 1 = running služba
        if position == 1 and len(self.pending) > 0:
            # Nemůžeme smazat RUNNING službu - ta už běží v API!
            _LOGGER.warning(
                f"[OIG Shield] Nelze smazat běžící službu na pozici 1 (running: {self.running})"
            )
            return

        # Position 2+ = čekající ve frontě
        # Pozice je 1-based (1=running, 2=queue[0], 3=queue[1], ...)
        # Pro queue potřebujeme position-2 (protože position 1 je running)
        queue_index = position - 1 - len(self.pending)

        if queue_index < 0 or queue_index >= len(self.queue):
            _LOGGER.error(
                f"[OIG Shield] Chyba výpočtu indexu: position={position}, queue_index={queue_index}, queue_len={len(self.queue)}"
            )
            return

        removed_item = self.queue[queue_index]
        service_name = removed_item[0]
        params = removed_item[1]
        expected_entities = removed_item[2]

        # Smažeme položku z fronty
        del self.queue[queue_index]

        # Smažeme i metadata
        self.queue_metadata.pop((service_name, str(params)), None)

        _LOGGER.info(
            f"[OIG Shield] Odstraněna položka z fronty na pozici {position}: {service_name}"
        )

        # LOGBOOK: Zapíšeme informaci o zrušení služby
        await self._log_event(
            "cancelled",
            service_name,
            {
                "params": params,
                "entities": expected_entities,
            },
            reason=f"Uživatel zrušil požadavek z fronty (pozice {position})",
            context=call.context,
        )

        # KRITICKÉ: Notifikuj senzory o změně
        self._notify_state_change()

        # Fire event
        self.hass.bus.async_fire(
            "oig_cloud_shield_queue_removed",
            {
                "position": position,
                "service": service_name,
                "remaining": len(self.queue),
                "timestamp": dt_now().isoformat(),
            },
        )

    def get_shield_status(self) -> str:
        """Vrací aktuální stav ServiceShield."""
        if self.running:
            return f"Běží: {self.running}"
        elif self.queue:
            return f"Ve frontě: {len(self.queue)} služeb"
        else:
            return "Neaktivní"

    def get_queue_info(self) -> Dict[str, Any]:
        """Vrací informace o frontě."""
        return {
            "running": self.running,
            "queue_length": len(self.queue),
            "pending_count": len(self.pending),
            "queue_services": [item[0] for item in self.queue],
        }

    def has_pending_mode_change(self, target_mode: Optional[str] = None) -> bool:
        """Zjistí, jestli už probíhá nebo čeká service set_box_mode."""

        def _matches_target(entities: Dict[str, str]) -> bool:
            if not entities:
                return False
            if not target_mode:
                return True

            normalized_target = self._normalize_value(target_mode)
            for value in entities.values():
                if self._normalize_value(value) == normalized_target:
                    return True
            return False

        # Pending (běžící) služby
        for service_name, info in self.pending.items():
            if service_name == SERVICE_SET_BOX_MODE and _matches_target(
                info.get("entities", {})
            ):
                return True

        # Queue (čekající) služby
        for service_name, _params, expected_entities, *_ in self.queue:
            if service_name == SERVICE_SET_BOX_MODE and _matches_target(
                expected_entities
            ):
                return True

        # Běží, ale pending záznam není? (defenzivní kontrola)
        if self.running == SERVICE_SET_BOX_MODE:
            return True

        return False

    def _normalize_value(self, val: Any) -> str:
        val = (
            str(val or "")
            .strip()
            .lower()
            .replace(" ", "")
            .replace("/", "")
            .replace("_", "")
        )
        mapping = {
            "vypnutoon": "vypnuto",
            "vypnuto": "vypnuto",
            "off": "vypnuto",
            "zapnutoon": "zapnuto",
            "zapnuto": "zapnuto",
            "on": "zapnuto",
            "somezenimlimited": "omezeno",
            "limited": "omezeno",
            "omezeno": "omezeno",
            "manuální": "manualni",
            "manual": "manualni",
            "cbb": "cbb",
        }
        return mapping.get(val, val)

    def _get_entity_state(self, entity_id: str) -> Optional[str]:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def _extract_api_info(
        self, service_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract API call information from service parameters."""
        api_info = {}

        if service_name == "oig_cloud.set_boiler_mode":
            mode = params.get("mode")
            mode_key = str(mode or "").strip().lower()
            api_info = {
                "api_endpoint": "Device.Set.Value.php",
                "api_table": "boiler_prms",
                "api_column": "manual",
                "api_value": 1 if mode_key in {"manual", "manuální"} else 0,
                "api_description": f"Set boiler mode to {mode}",
            }
        elif service_name == SERVICE_SET_BOX_MODE:
            mode = params.get("mode")
            api_info = {
                "api_endpoint": "Device.Set.Value.php",
                "api_table": "box_prms",
                "api_column": "mode",
                "api_value": mode,
                "api_description": f"Set box mode to {mode}",
            }
        elif service_name == "oig_cloud.set_grid_delivery":
            if "limit" in params:
                api_info = {
                    "api_endpoint": "Device.Set.Value.php",
                    "api_table": "invertor_prm1",
                    "api_column": "p_max_feed_grid",
                    "api_value": params["limit"],
                    "api_description": f"Set grid delivery limit to {params['limit']}W",
                }
            elif "mode" in params:
                api_info = {
                    "api_endpoint": "Device.Set.Value.php",
                    "api_table": "invertor_prms",
                    "api_column": "to_grid",
                    "api_value": params["mode"],
                    "api_description": f"Set grid delivery mode to {params['mode']}",
                }

        return api_info

    async def intercept_service_call(
        self,
        domain: str,
        service: str,
        data: Dict[str, Any],
        original_call: Callable,
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        service_name = f"{domain}.{service}"
        params = data["params"]
        trace_id = str(uuid.uuid4())[:8]

        # SPECIÁLNÍ LOGIKA: set_grid_delivery s mode + limit současně
        # Rozdělíme na 2 samostatné volání (serializace)
        if (
            service_name == "oig_cloud.set_grid_delivery"
            and "mode" in params
            and "limit" in params
        ):
            _LOGGER.info(
                "[Grid Delivery] Detected mode + limit together, splitting into 2 calls"
            )

            # Vytvoříme 2 samostatné volání
            # 1. Mode (pokud se liší od aktuálního)
            mode_params = {k: v for k, v in params.items() if k != "limit"}
            # 2. Limit (pokud se liší od aktuálního)
            limit_params = {k: v for k, v in params.items() if k != "mode"}

            # Zavoláme intercept rekurzivně pro každý parametr
            _LOGGER.info("[Grid Delivery] Step 1/2: Processing mode change")
            await self.intercept_service_call(
                domain,
                service,
                {"params": mode_params},
                original_call,
                blocking,
                context,
            )

            _LOGGER.info("[Grid Delivery] Step 2/2: Processing limit change")
            await self.intercept_service_call(
                domain,
                service,
                {"params": limit_params},
                original_call,
                blocking,
                context,
            )

            _LOGGER.info("[Grid Delivery] Both calls queued successfully")
            return

        expected_entities = self.extract_expected_entities(service_name, params)
        api_info = self._extract_api_info(service_name, params)

        _LOGGER.debug("Intercept service: %s", service_name)
        _LOGGER.debug("Intercept expected entities: %s", expected_entities)
        _LOGGER.debug("Intercept queue length: %s", len(self.queue))
        _LOGGER.debug("Intercept running: %s", self.running)

        # OPRAVA: Pouze security event, ne telemetrie na začátku
        self._log_security_event(
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
            await self._log_event(
                "skipped",
                service_name,
                {"params": params, "entities": {}},
                reason="Není co měnit – požadované hodnoty již nastaveny",
                context=context,
            )
            return

        new_expected_set = frozenset(expected_entities.items())

        # Debug: Vypsat frontu a pending před kontrolou deduplikace
        _LOGGER.debug("Dedup: checking for duplicates")
        _LOGGER.debug("Dedup: new service=%s", service_name)
        _LOGGER.debug("Dedup: new params=%s", params)
        _LOGGER.debug("Dedup: new expected=%s", expected_entities)
        _LOGGER.debug("Dedup: queue length=%s", len(self.queue))
        _LOGGER.debug("Dedup: pending length=%s", len(self.pending))
        for i, q in enumerate(self.queue):
            _LOGGER.debug(
                "Dedup: queue[%s] service=%s params=%s expected=%s", i, q[0], q[1], q[2]
            )
        for service_key, pending_info in self.pending.items():
            _LOGGER.debug(
                "Dedup: pending service=%s entities=%s",
                service_key,
                pending_info.get("entities", {}),
            )

        # Čeká už ve frontě nebo běží v pending stejná služba se stejným cílem?
        # OPRAVA: Kontrolujeme jak queue, tak pending
        duplicate_found = False
        duplicate_location = None
        new_params_set = frozenset(params.items()) if params else frozenset()

        # 1. Kontrola QUEUE (čekající služby)
        for q in self.queue:
            queue_service = q[0]
            queue_params = q[1]
            queue_expected = q[2]

            queue_params_set = (
                frozenset(queue_params.items()) if queue_params else frozenset()
            )
            queue_expected_set = frozenset(queue_expected.items())

            # Duplikát = stejná služba + stejné parametry + stejný očekávaný výsledek
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

        # 2. Kontrola PENDING (běžící služby) - pouze pokud nebyl nalezen v queue
        if not duplicate_found:
            for pending_service_key, pending_info in self.pending.items():
                pending_entities = pending_info.get("entities", {})
                pending_expected_set = frozenset(pending_entities.items())

                # Duplikát v pending = stejná služba + stejný očekávaný výsledek
                # (parametry u pending nemáme uložené, takže kontrolujeme jen expected entities)
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
            await self._log_event(
                "ignored",
                service_name,
                {"params": params, "entities": expected_entities},
                reason=f"Ignorováno – služba se stejným efektem je již {'ve frontě' if duplicate_location == 'queue' else 'spuštěna'}",
                context=context,
            )
            await self._log_telemetry(
                "ignored",
                service_name,
                {
                    "params": params,
                    "entities": expected_entities,
                    "reason": f"duplicate_in_{duplicate_location}",
                },
            )
            return

        # ✅ Není co frontovat, ale už hotovo?
        all_ok = True
        for entity_id, expected_value in expected_entities.items():
            state = self.hass.states.get(entity_id)
            current = self._normalize_value(state.state if state else None)
            expected = self._normalize_value(expected_value)
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
            # OPRAVA: Logujeme telemetrii i pro skipped požadavky
            await self._log_telemetry(
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
            await self._log_event(
                "skipped",
                service_name,
                {"params": params, "entities": expected_entities},
                reason="Změna již provedena – není co volat",
                context=context,
            )
            return

        # ߚࠓpustíme hned
        _LOGGER.debug("Intercept: will execute service; logging telemetry")
        # TELEMETRIE: Zde se odešle telemetrie při skutečném volání služby
        await self._log_telemetry(
            "change_requested",
            service_name,
            {
                "trace_id": trace_id,
                "params": params,
                "entities": expected_entities,
                **api_info,  # Přidáme API informace
            },
        )

        # KRITICKÁ OPRAVA: Kontrola, jestli už něco běží
        # Shield NESMÍ pouštět služby paralelně!
        if self.running is not None:
            # Už něco běží → přidáme do FRONTY
            _LOGGER.info(
                f"[OIG Shield] Služba {service_name} přidána do fronty (běží: {self.running})"
            )
            self.queue.append(
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
            # OPRAVA: Uložíme metadata s trace_id A časem zařazení pro live duration
            self.queue_metadata[(service_name, str(params))] = {
                "trace_id": trace_id,
                "queued_at": datetime.now(),
            }

            # Track mode transition pokud je to set_box_mode
            if service_name == "set_box_mode" and self.mode_tracker:
                from_mode = params.get("current_value")
                to_mode = params.get("value")
                if from_mode and to_mode:
                    self.mode_tracker.track_request(trace_id, from_mode, to_mode)

            # Notifikuj senzory o nové položce ve frontě
            self._notify_state_change()

            await self._log_event(
                "queued",
                service_name,
                {"params": params, "entities": expected_entities},
                reason=f"Přidáno do fronty (běží: {self.running})",
                context=context,
            )
        else:
            # Nic neběží → spustíme HNED
            _LOGGER.info(
                f"[OIG Shield] Spouštím službu {service_name} (fronta prázdná)"
            )

            # Track mode transition pokud je to set_box_mode
            if service_name == "set_box_mode" and self.mode_tracker:
                from_mode = params.get("current_value")
                to_mode = params.get("value")
                if from_mode and to_mode:
                    self.mode_tracker.track_request(trace_id, from_mode, to_mode)

            await self._start_call(
                service_name,
                params,
                expected_entities,
                original_call,
                domain,
                service,
                blocking,
                context,
            )

    async def _start_call(
        self,
        service_name: str,
        data: Dict[str, Any],
        expected_entities: Dict[str, str],
        original_call: Callable,
        domain: str,
        service: str,
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        # OPRAVA: Uložíme původní stavy entit před změnou
        original_states = {}
        for entity_id in expected_entities.keys():
            state = self.hass.states.get(entity_id)
            original_states[entity_id] = state.state if state else None

        # Příprava power monitoring pro set_box_mode
        power_monitor = None
        if service_name == SERVICE_SET_BOX_MODE:
            # Získat box_id z konfigurace
            box_id = None
            if self.hass.data.get("oig_cloud"):
                for entry_id, entry_data in self.hass.data["oig_cloud"].items():
                    if entry_data.get("service_shield") == self:
                        coordinator = entry_data.get("coordinator")
                        if coordinator:
                            try:
                                from .oig_cloud_sensor import resolve_box_id

                                box_id = resolve_box_id(coordinator)
                            except Exception:
                                box_id = None
                            break

            if not box_id:
                _LOGGER.warning("[OIG Shield] Power monitor: box_id nenalezen!")
            else:
                power_entity = f"sensor.oig_{box_id}_actual_aci_wtotal"
                power_state = self.hass.states.get(power_entity)

                if not power_state:
                    _LOGGER.warning(
                        f"[OIG Shield] Power monitor: entita {power_entity} neexistuje!"
                    )
                elif power_state.state in ["unknown", "unavailable"]:
                    _LOGGER.warning(
                        f"[OIG Shield] Power monitor: entita {power_entity} je {power_state.state}"
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
                            f"[OIG Shield] Power monitor aktivní pro {service_name}: "
                            f"baseline={current_power}W, target={target_mode}, "
                            f"going_to_ups={power_monitor['is_going_to_home_ups']}"
                        )
                    except (ValueError, TypeError) as e:
                        _LOGGER.warning(
                            f"[OIG Shield] Nelze inicializovat power monitor: {e}"
                        )

        # OPRAVA: Přidáme do pending PŘED voláním API, aby se okamžitě zobrazilo ve frontě
        self.pending[service_name] = {
            "entities": expected_entities,
            "original_states": original_states,
            "params": data,
            "called_at": datetime.now(),
            "power_monitor": power_monitor,  # Nový field pro sledování výkonu
        }

        # OPRAVA: Nastavíme running AŽ NYNÍ, aby se okamžitě zobrazilo
        self.running = service_name

        # Odstraňme metadata z fronty
        self.queue_metadata.pop((service_name, str(data)), None)

        # OPRAVA: Fire event pro okamžitou aktualizaci UI
        self.hass.bus.async_fire(
            "oig_cloud_shield_queue_info",
            {
                "running": self.running,
                "queue_length": len(self.queue),
                "pending_count": len(self.pending),
                "queue_services": [item[0] for item in self.queue],
                "timestamp": dt_now().isoformat(),
            },
        )

        # Notifikuj senzory o změně stavu
        self._notify_state_change()

        await self._log_event(
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

        await self._log_event(
            "started",
            service_name,
            {
                "params": data,
                "entities": expected_entities,
                "original_states": original_states,
            },
            context=context,
        )

        # OPRAVA: Volání API až NYNÍ, když už je služba v pending a UI se aktualizovalo
        await original_call(
            domain, service, service_data=data, blocking=blocking, context=context
        )

        # KRITICKÁ OPRAVA: Po API volání OKAMŽITĚ refreshneme coordinator
        # Bez toho by Shield čekal na další scheduled update (30-120s)!
        try:
            from .const import DOMAIN

            coordinator = (
                self.hass.data.get(DOMAIN, {})
                .get(self.entry.entry_id, {})
                .get("coordinator")
            )
            if coordinator:
                _LOGGER.debug(
                    f"[OIG Shield] Vynucuji okamžitou aktualizaci coordinatoru po API volání pro {service_name}"
                )
                await coordinator.async_request_refresh()
                _LOGGER.debug(
                    "[OIG Shield] Coordinator refreshnut - entity by měly být aktuální"
                )
            else:
                _LOGGER.warning(
                    "[OIG Shield] Coordinator nenalezen - entity se aktualizují až při příštím scheduled update!"
                )
        except Exception as e:
            _LOGGER.error(
                f"[OIG Shield] Chyba při refreshu coordinatoru: {e}", exc_info=True
            )

        # Po volání služby nastavíme state listener pro sledování změn
        self._setup_state_listener()

    @callback
    async def _check_loop(self, _now: datetime) -> None:  # noqa: C901
        # Lock mechanismus - prevence concurrent execution
        if self._is_checking:
            _LOGGER.debug("[OIG Shield] Check loop již běží, přeskakuji")
            return

        self._is_checking = True
        try:
            # OPRAVA: Explicitní debug log na začátku každé kontroly
            _LOGGER.debug(
                f"[OIG Shield] Check loop tick - pending: {len(self.pending)}, queue: {len(self.queue)}, running: {self.running}"
            )

            if not self.pending and not self.queue and not self.running:
                _LOGGER.debug("[OIG Shield] Check loop - vše prázdné, žádná akce")
                # Zrušíme state listener, pokud není co sledovat
                if self._state_listener_unsub:
                    self._state_listener_unsub()
                    self._state_listener_unsub = None
                return

            finished = []

            for service_name, info in self.pending.items():
                _LOGGER.debug(f"[OIG Shield] Kontroluji pending službu: {service_name}")

                # OPRAVA: Speciální timeout pro formating_mode - 2 minuty místo 15 minut
                timeout_minutes = (
                    2
                    if service_name == "oig_cloud.set_formating_mode"
                    else TIMEOUT_MINUTES
                )

                if datetime.now() - info["called_at"] > timedelta(
                    minutes=timeout_minutes
                ):
                    if service_name == "oig_cloud.set_formating_mode":
                        _LOGGER.info(
                            "[OIG Shield] Formating mode dokončeno po 2 minutách (automaticky)"
                        )
                        # Pro formating_mode považujeme timeout za úspěšné dokončení
                        await self._log_event(
                            "completed",
                            service_name,
                            {
                                "params": info["params"],
                                "entities": info["entities"],
                                "original_states": info.get("original_states", {}),
                            },
                            reason="Formátování dokončeno (automaticky po 2 min)",
                        )
                        await self._log_telemetry(
                            "completed",
                            service_name,
                            {
                                "params": info["params"],
                                "entities": info["entities"],
                                "reason": "auto_timeout",
                            },
                        )
                    else:
                        _LOGGER.warning(
                            f"[OIG Shield] Timeout pro službu {service_name}"
                        )
                        await self._log_event(
                            "timeout",
                            service_name,
                            {
                                "params": info["params"],
                                "entities": info["entities"],
                                "original_states": info.get("original_states", {}),
                            },
                        )
                        await self._log_telemetry(
                            "timeout",
                            service_name,
                            {"params": info["params"], "entities": info["entities"]},
                        )
                    finished.append(service_name)
                    continue

                # NOVÁ LOGIKA: Kontrola power monitor (alternativa k entity check)
                power_completed = False
                power_monitor = info.get("power_monitor")
                if power_monitor:
                    power_entity = power_monitor["entity_id"]
                    power_state = self.hass.states.get(power_entity)

                    if not power_state:
                        _LOGGER.warning(
                            f"[OIG Shield] Power monitor: entita {power_entity} neexistuje"
                        )
                    elif power_state.state in ["unknown", "unavailable"]:
                        _LOGGER.debug(
                            f"[OIG Shield] Power monitor: entita {power_entity} je {power_state.state}"
                        )
                    else:
                        try:
                            current_power = float(power_state.state)
                            last_power = power_monitor["last_power"]
                            is_going_to_home_ups = power_monitor["is_going_to_home_ups"]
                            threshold_w = (
                                power_monitor["threshold_kw"] * 1000
                            )  # 2.5kW → 2500W

                            # Rozdíl mezi aktuální a poslední hodnotou (po sobě jdoucí updaty)
                            power_delta = current_power - last_power

                            _LOGGER.info(
                                f"[OIG Shield] Power monitor check: current={current_power}W, "
                                f"last={last_power}W, delta={power_delta}W, "
                                f"threshold=±{threshold_w}W, going_to_ups={is_going_to_home_ups}"
                            )

                            # Aktualizovat last_power pro příští check
                            power_monitor["last_power"] = current_power

                            # Detekce skoku
                            if is_going_to_home_ups and power_delta >= threshold_w:
                                _LOGGER.info(
                                    f"[OIG Shield] ✅ POWER JUMP DETECTED! Nárůst {power_delta}W "
                                    f"(>= {threshold_w}W) → HOME UPS aktivní"
                                )
                                power_completed = True
                            elif (
                                not is_going_to_home_ups and power_delta <= -threshold_w
                            ):
                                _LOGGER.info(
                                    f"[OIG Shield] ✅ POWER DROP DETECTED! Pokles {power_delta}W "
                                    f"(<= -{threshold_w}W) → HOME UPS vypnutý"
                                )
                                power_completed = True
                        except (ValueError, TypeError) as e:
                            _LOGGER.warning(
                                f"[OIG Shield] Chyba při parsování power hodnoty: {e}"
                            )

                # Pokud power monitor detekoval dokončení, přeskočíme klasickou kontrolu entit
                if power_completed:
                    _LOGGER.info(
                        f"[SHIELD CHECK] ✅✅✅ Služba {service_name} dokončena pomocí POWER MONITOR!"
                    )
                    await self._log_event(
                        "completed",
                        service_name,
                        {
                            "params": info["params"],
                            "entities": info["entities"],
                            "original_states": info.get("original_states", {}),
                        },
                        reason="Detekován skok výkonu (power monitor)",
                    )
                    await self._log_telemetry(
                        "completed",
                        service_name,
                        {
                            "params": info["params"],
                            "entities": info["entities"],
                            "completion_method": "power_monitor",
                        },
                    )
                    await self._log_event(
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

                # KLASICKÁ LOGIKA: Kontrola změny entity
                all_ok = True
                _LOGGER.info(
                    f"[SHIELD CHECK] Služba: {service_name}, entities: {info['entities']}"
                )
                for entity_id, expected_value in info["entities"].items():
                    # OPRAVA: Pro fiktivní formating entity nikdy nebudou "dokončené" před timeoutem
                    if entity_id.startswith("fake_formating_mode_"):
                        all_ok = False
                        _LOGGER.debug(
                            f"[OIG Shield] Formating mode - čekám na timeout (zbývá {timeout_minutes - (datetime.now() - info['called_at']).total_seconds() / 60:.1f} min)"
                        )
                        break

                    state = self.hass.states.get(entity_id)
                    current_value = state.state if state else None

                    if entity_id and entity_id.endswith(
                        "_invertor_prm1_p_max_feed_grid"
                    ):
                        try:
                            norm_expected = str(round(float(expected_value)))
                            norm_current = str(round(float(current_value)))
                        except (ValueError, TypeError):
                            norm_expected = str(expected_value)
                            norm_current = str(current_value or "")
                    elif entity_id and entity_id.endswith("_invertor_prms_to_grid"):
                        norm_expected = self._normalize_value(expected_value)
                        norm_current = self._normalize_value(current_value)
                        # U binary_sensoru neodlišíme "omezeno" vs "zapnuto"
                        if (
                            entity_id.startswith("binary_sensor.")
                            and norm_expected == "omezeno"
                        ):
                            norm_expected = "zapnuto"
                    else:
                        norm_expected = self._normalize_value(expected_value)
                        norm_current = self._normalize_value(current_value)

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
                        _LOGGER.warning(
                            f"[SHIELD CHECK] ❌ Entity {entity_id} NENÍ v požadovaném stavu! Očekáváno '{norm_expected}', je '{norm_current}'"
                        )
                        break
                    else:
                        _LOGGER.info(
                            f"[SHIELD CHECK] ✅ Entity {entity_id} JE v požadovaném stavu!"
                        )

                if all_ok and not service_name == "oig_cloud.set_formating_mode":
                    _LOGGER.info(
                        f"[SHIELD CHECK] ✅✅✅ Služba {service_name} byla úspěšně dokončena - ZAPISUJI DO LOGBOOKU!"
                    )
                    await self._log_event(
                        "completed",
                        service_name,
                        {
                            "params": info["params"],
                            "entities": info["entities"],
                            "original_states": info.get("original_states", {}),
                        },
                        reason="Změna provedena",
                    )
                    await self._log_telemetry(
                        "completed",
                        service_name,
                        {"params": info["params"], "entities": info["entities"]},
                    )
                    await self._log_event(
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

            # OPRAVA: Explicitní logování při odstraňování dokončených služeb
            for svc in finished:
                _LOGGER.info(f"[OIG Shield] Odstraňuji dokončenou službu: {svc}")
                del self.pending[svc]
                if svc == self.running:
                    _LOGGER.info(f"[OIG Shield] Uvolňuji running slot: {svc}")
                    self.running = None

            # Notifikuj senzory o změně stavu (dokončení služby)
            if finished:
                self._notify_state_change()

            # OPRAVA: Explicitní logování při spouštění dalších služeb z fronty
            if self.running is None and self.queue:
                _LOGGER.info(
                    f"[OIG Shield] Spouštím další službu z fronty (fronta má {len(self.queue)} položek)"
                )
                (
                    next_svc,
                    data,
                    expected,
                    original_call,
                    domain,
                    service,
                    blocking,
                    context,
                ) = self.queue.pop(0)
                _LOGGER.debug(
                    "[OIG Shield] Spouštím další službu z fronty: %s", next_svc
                )
                await self._start_call(
                    next_svc,
                    data,
                    expected,
                    original_call,
                    domain,
                    service,
                    blocking,
                    context,
                )
            elif self.running is None:
                _LOGGER.debug("[OIG Shield] Fronta prázdná, shield neaktivní.")
            else:
                _LOGGER.debug(
                    f"[OIG Shield] Čekám na dokončení běžící služby: {self.running}"
                )

            # Aktualizujeme state listener pro aktuální pending služby
            self._setup_state_listener()

        finally:
            # Vždy uvolníme lock
            self._is_checking = False

    async def _log_event(
        self,
        event_type: str,
        service: str,
        data: Dict[str, Any],
        reason: Optional[str] = None,
        context: Optional[Context] = None,
    ) -> None:
        params = data.get("params", {})
        entities = data.get("entities", {})
        original_states = data.get("original_states", {})
        context = context or data.get("context")

        for entity_id, expected_value in entities.items() or {None: None}.items():
            state = self.hass.states.get(entity_id) if entity_id else None

            # OPRAVA: Pro grid delivery limit použijeme hlavní entitu pro lepší UX
            display_entity_id = entity_id
            if entity_id and "_invertor_prm1_p_max_feed_grid" in entity_id:
                # Najdeme hlavní entitu (_invertor_prms_to_grid)
                main_entity_id = entity_id.replace(
                    "_invertor_prm1_p_max_feed_grid", "_invertor_prms_to_grid"
                )
                main_state = self.hass.states.get(main_entity_id)
                if main_state:
                    display_entity_id = main_entity_id
                    state = main_state

            friendly_name = (
                state.attributes.get("friendly_name", display_entity_id)
                if state and display_entity_id
                else service
            )
            current_value = state.state if state else "neznámá"

            # Pro completed událost použijeme původní stav místo aktuálního
            if event_type == "completed" and entity_id in original_states:
                from_value = original_states[entity_id]
            else:
                from_value = current_value

            # OPRAVA: Pro grid delivery limit upravíme zprávy pro lepší UX
            is_limit_change = (
                entity_id and "_invertor_prm1_p_max_feed_grid" in entity_id
            )

            if event_type == "change_requested":
                if is_limit_change:
                    message = f"Požadavek na změnu {friendly_name} – nastavení limitu na {expected_value}W"
                else:
                    message = f"Požadavek na změnu {friendly_name} z '{from_value}' na '{expected_value}'"
            elif event_type == "completed":
                if is_limit_change:
                    message = f"Změna provedena – {friendly_name} má nastavený limit {expected_value}W"
                else:
                    message = f"Změna provedena – {friendly_name} z '{from_value}' na '{expected_value}'"
            elif event_type == "skipped":
                if is_limit_change:
                    message = f"Změna přeskočena – {friendly_name} má již limit {expected_value}W"
                else:
                    message = f"Změna přeskočena – {friendly_name} má již hodnotu '{expected_value}'"
            elif event_type == "queued":
                if is_limit_change:
                    message = f"Přidáno do fronty – {friendly_name}: nastavení limitu na {expected_value}W"
                else:
                    message = (
                        f"Přidáno do fronty – {friendly_name}: aktuální = '{current_value}', "
                        f"očekávaná = '{expected_value}'"
                    )
            elif event_type == "started":
                if is_limit_change:
                    message = f"Spuštěna služba – {friendly_name}: nastavení limitu na {expected_value}W"
                else:
                    message = f"Spuštěna služba – {friendly_name}: z '{from_value}' na '{expected_value}'"
            elif event_type == "ignored":
                message = (
                    f"Ignorováno – {service} ({reason or 'už běží nebo ve frontě'})"
                )
            elif event_type == "timeout":
                if is_limit_change:
                    message = f"Časový limit vypršel – {friendly_name}: limit stále není {expected_value}W"
                else:
                    message = (
                        f"Časový limit vypršel – {friendly_name} stále není '{expected_value}' "
                        f"(aktuální: '{current_value}')"
                    )
            elif event_type == "released":
                message = f"Semafor uvolněn – služba {service} dokončena"
            elif event_type == "cancelled":
                message = f"Zrušeno uživatelem – {friendly_name}: očekávaná změna na '{expected_value}' nebyla provedena"
            else:
                message = f"{event_type} – {service}"

            # ߪ堌og do HA logbooku
            self.hass.bus.async_fire(
                "logbook_entry",
                {
                    "name": "OIG Shield",
                    "message": message,
                    "domain": "oig_cloud",
                    "entity_id": display_entity_id,  # OPRAVA: Použijeme display_entity_id místo entity_id
                    "when": dt_now(),
                    "source": "OIG Cloud Shield",
                    "source_type": "system",
                },
                context=context,
            )

            # ߓ᠅mitujeme vlastní událost
            self.hass.bus.async_fire(
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

            # ߐebug log do konzole
            _LOGGER.debug(
                "[OIG Shield] Event: %s | Entity: %s | From: '%s' → To: '%s' | Reason: %s",
                event_type,
                entity_id,
                from_value,
                expected_value,
                reason or "-",
            )

    def extract_expected_entities(  # noqa: C901
        self, service_name: str, data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Extrahuje očekávané entity a jejich cílové hodnoty z parametrů služby.

        KLÍČOVÉ: Vrací hodnoty tak, jak je SENZOR skutečně poskytuje (vždy česky),
        protože senzory mají hardcoded "cs" v state() property.
        """
        self.last_checked_entity_id = None

        def _extract_param_type(entity_id: str) -> str:
            """Extrahuje typ parametru z entity_id pro strukturovaný targets output."""
            if "p_max_feed_grid" in entity_id:
                return "limit"
            elif "prms_to_grid" in entity_id:
                return "mode"
            elif "box_prms_mode" in entity_id:
                return "mode"
            elif "boiler_manual_mode" in entity_id:
                return "mode"
            elif "formating_mode" in entity_id:
                return "level"
            else:
                return "value"  # Fallback

        def find_entity(suffix: str) -> str | None:
            _LOGGER.info("[FIND ENTITY] Hledám cloud entitu se suffixem: %s", suffix)

            # Preferuj pouze cloud senzory: sensor.oig_<box_id>_<suffix>
            box_id = None
            for key in ("box_id", "inverter_sn"):
                val = self.entry.options.get(key) or self.entry.data.get(key)
                if isinstance(val, str) and val.isdigit():
                    box_id = val
                    break

            if not box_id:
                try:
                    from .oig_cloud_sensor import resolve_box_id

                    coordinator = None
                    for entry_data in self.hass.data.get(DOMAIN, {}).values():
                        if not isinstance(entry_data, dict):
                            continue
                        if entry_data.get("service_shield") != self:
                            continue
                        coordinator = entry_data.get("coordinator")
                        break
                    if coordinator:
                        resolved = resolve_box_id(coordinator)
                        if isinstance(resolved, str) and resolved.isdigit():
                            box_id = resolved
                except Exception:
                    box_id = None

            if not box_id:
                _LOGGER.warning(
                    "[FIND ENTITY] box_id nelze určit, cloud entitu pro suffix '%s' nelze vybrat",
                    suffix,
                )
                return None

            prefix = f"sensor.oig_{box_id}_"
            matching_entities = [
                entity.entity_id
                for entity in self.hass.states.async_all()
                if entity.entity_id.startswith(prefix)
                and entity.entity_id.endswith(suffix)
            ]

            if matching_entities:
                entity_id = matching_entities[0]
                _LOGGER.info("[FIND ENTITY] Vybrána cloud entita: %s", entity_id)
                return entity_id

            _LOGGER.warning(
                "[FIND ENTITY] NENALEZENA cloud entita %s*%s", prefix, suffix
            )
            return None

        # OPRAVA: Speciální handling pro set_formating_mode - nemá žádný senzor k ověření
        if service_name == "oig_cloud.set_formating_mode":
            # Vytvoříme fiktivní entitu pro 2minutové sledování
            # Použijeme timestamp jako "entity_id" pro unikátnost
            fake_entity_id = f"fake_formating_mode_{int(datetime.now().timestamp())}"
            _LOGGER.info(
                f"[OIG Shield] Formating mode - vytváří fiktivní entitu pro 2min sledování: {fake_entity_id}"
            )
            return {fake_entity_id: "completed_after_timeout"}

        if service_name == SERVICE_SET_BOX_MODE:
            mode_raw = str(data.get("mode") or "").strip()
            expected_value = mode_raw
            if not expected_value or expected_value.lower() == "none":
                return {}
            mode_key = self._normalize_value(mode_raw)
            mode_mapping = {
                "home1": "Home 1",
                "home2": "Home 2",
                "home3": "Home 3",
                "homeups": "Home UPS",
                "home5": "Home 5",
                "home6": "Home 6",
                "0": "Home 1",
                "1": "Home 2",
                "2": "Home 3",
                "3": "Home UPS",
                "4": "Home 5",
                "5": "Home 6",
            }
            expected_value = mode_mapping.get(mode_key, mode_raw)
            entity_id = find_entity("_box_prms_mode")
            if entity_id:
                self.last_checked_entity_id = entity_id
                state = self.hass.states.get(entity_id)
                current = self._normalize_value(state.state if state else None)
                expected = self._normalize_value(expected_value)
                _LOGGER.debug(
                    "[extract] box_mode | current='%s' expected='%s'", current, expected
                )
                if current != expected:
                    return {entity_id: expected_value}
            return {}

        elif service_name == "oig_cloud.set_boiler_mode":
            mode = str(data.get("mode") or "").strip()

            # OPRAVA: Přesné mapování služba → senzor (backend VŽDY česky)
            # Služba přijímá: "CBB", "Manual" (anglicky)
            # Senzor vrací: "CBB", "Manuální" (česky)
            boiler_mode_mapping = {
                "CBB": "CBB",  # Stejné
                "Manual": "Manuální",  # Překlad EN → CS
                "cbb": "CBB",
                "manual": "Manuální",
            }
            expected_value = boiler_mode_mapping.get(mode)
            if not expected_value:
                _LOGGER.warning("[extract] Unknown boiler mode: %s", mode)
                return {}

            entity_id = find_entity("_boiler_manual_mode")
            if entity_id:
                self.last_checked_entity_id = entity_id
                state = self.hass.states.get(entity_id)
                current = self._normalize_value(state.state if state else None)
                expected = self._normalize_value(expected_value)
                _LOGGER.debug(
                    "[extract] boiler_mode | current='%s' expected='%s' (input='%s')",
                    current,
                    expected,
                    mode,
                )
                if current != expected:
                    return {entity_id: expected_value}
            return {}

        elif service_name == "oig_cloud.set_grid_delivery":
            # OPRAVA: Wrapper rozděluje mode + limit na 2 samostatná volání
            # Každé volání má jen JEDEN parametr → vrátíme jen JEDNU entitu

            # PŘÍPAD 1: Pouze LIMIT (bez mode)
            if "limit" in data and "mode" not in data:
                try:
                    expected_value = round(float(data["limit"]))
                except (ValueError, TypeError):
                    expected_value = None

                if expected_value is not None:
                    entity_id = find_entity("_invertor_prm1_p_max_feed_grid")
                    if entity_id:
                        self.last_checked_entity_id = entity_id
                        state = self.hass.states.get(entity_id)

                        try:
                            current_value = round(float(state.state))
                        except (ValueError, TypeError, AttributeError):
                            current_value = None

                        _LOGGER.debug(
                            "[extract] grid_delivery.limit ONLY | current=%s expected=%s",
                            current_value,
                            expected_value,
                        )

                        if current_value != expected_value:
                            # Vrátíme POUZE limit entitu
                            return {entity_id: str(expected_value)}
                        else:
                            _LOGGER.info(
                                f"[extract] Limit již je {expected_value}W - přeskakuji"
                            )
                            return {}

            # PŘÍPAD 2: Pouze MODE (bez limit)
            if "mode" in data and "limit" not in data:
                # OPRAVA: Mode přichází jako STRING ze služby: "Vypnuto / Off", "Zapnuto / On", "S omezením / Limited"
                # Senzor VŽDY vrací ČESKY (hardcoded "cs"): "Vypnuto", "Zapnuto", "Omezeno"
                # KLÍČ: Mapujeme službu → přesná hodnota senzoru (bez hacku "nebo")
                mode_string = str(data["mode"]).strip()

                # OPRAVA: Přesné mapování služba → senzor (backend VŽDY česky)
                mode_mapping = {
                    "Vypnuto / Off": "Vypnuto",  # Přesná shoda
                    "Zapnuto / On": "Zapnuto",  # Přesná shoda (NE "nebo Omezeno"!)
                    "S omezením / Limited": "Omezeno",  # Přesná shoda (NE "Zapnuto nebo"!)
                    "vypnuto / off": "Vypnuto",
                    "zapnuto / on": "Zapnuto",
                    "s omezením / limited": "Omezeno",
                    "off": "Vypnuto",
                    "on": "Zapnuto",
                    "limited": "Omezeno",
                }

                expected_text = mode_mapping.get(mode_string) or mode_mapping.get(
                    mode_string.lower()
                )
                if not expected_text:
                    _LOGGER.warning(
                        f"[extract] Unknown grid delivery mode: {mode_string}"
                    )
                    return {}

                entity_id = find_entity("_invertor_prms_to_grid")
                if entity_id:
                    self.last_checked_entity_id = entity_id
                    state = self.hass.states.get(entity_id)
                    current_text = state.state if state else None

                    _LOGGER.debug(
                        "[extract] grid_delivery.mode ONLY | current='%s' expected='%s' (mode_string='%s')",
                        current_text,
                        expected_text,
                        mode_string,
                    )

                    # OPRAVA: Přesné porovnání (žádné "nebo")
                    if current_text != expected_text:
                        # Vrátíme POUZE mode entitu s přesnou hodnotou
                        return {entity_id: expected_text}
                    else:
                        _LOGGER.info(
                            f"[extract] Mode již je {current_text} - přeskakuji"
                        )
                        return {}

            # PŘÍPAD 3: OBĚ parametry najednou
            # NEMŮŽE NASTAT - wrapper to rozdělí na 2 volání PŘED voláním extract_expected_entities()
            if "mode" in data and "limit" in data:
                _LOGGER.error(
                    "[extract] CHYBA: grid_delivery dostalo mode + limit současně! Wrapper měl rozdělit!"
                )
                return {}

            return {}

        elif service_name == "oig_cloud.set_formating_mode":
            return {}

        return {}

    def _check_entity_state_change(self, entity_id: str, expected_value: Any) -> bool:
        """Zkontroluje, zda se entita změnila na očekávanou hodnotu."""
        current_state = self.hass.states.get(entity_id)
        if not current_state:
            return False

        current_value = current_state.state

        # OPRAVA: Mapování pro nové formáty stavů
        if "boiler_manual_mode" in entity_id:
            # Nové mapování: CBB=0, Manuální=1
            return (expected_value == 0 and current_value == "CBB") or (
                expected_value == 1 and current_value == "Manuální"
            )
        elif "ssr" in entity_id:
            # SSR relé: Vypnuto/Off=0, Zapnuto/On=1
            off_values = {"Vypnuto/Off", "Vypnuto", "Off"}
            on_values = {"Zapnuto/On", "Zapnuto", "On"}
            return (expected_value == 0 and current_value in off_values) or (
                expected_value == 1 and current_value in on_values
            )
        elif "box_prms_mode" in entity_id:
            # OPRAVA: Přidání nových režimů Home 5 a Home 6 + podpora slug/label
            mode_mapping = {
                0: "Home 1",
                1: "Home 2",
                2: "Home 3",
                3: "Home UPS",
                4: "Home 5",
                5: "Home 6",
            }
            if isinstance(expected_value, str):
                if self._normalize_value(current_value) == self._normalize_value(
                    expected_value
                ):
                    return True
                if expected_value.isdigit():
                    expected_value = int(expected_value)
            if isinstance(expected_value, int):
                return current_value == mode_mapping.get(expected_value)
        elif "invertor_prms_to_grid" in entity_id:
            # Grid delivery mode: expected_value je TEXT ("Vypnuto", "Zapnuto", "Omezeno")
            # current_value je TEXT ze senzoru nebo "on/off" u binary_sensoru
            norm_expected = self._normalize_value(expected_value)
            norm_current = self._normalize_value(current_value)
            if isinstance(expected_value, int) or str(expected_value).isdigit():
                norm_expected = "zapnuto" if int(expected_value) == 1 else "vypnuto"
            if norm_expected == "vypnuto":
                return norm_current in {"vypnuto"}
            if norm_expected == "zapnuto":
                if entity_id.startswith("binary_sensor."):
                    return norm_current in {"zapnuto", "omezeno"}
                return norm_current == "zapnuto"
            if norm_expected == "omezeno":
                # U binary_sensoru neodlišíme "omezeno" vs "zapnuto"
                if entity_id.startswith("binary_sensor."):
                    return norm_current in {"zapnuto", "omezeno"}
                return norm_current == "omezeno"
            return False
        elif "p_max_feed_grid" in entity_id:
            # Grid delivery limit: porovnání čísel (W)
            try:
                current_num = round(float(current_value))
                expected_num = round(float(expected_value))
                if current_num == expected_num:
                    return True
            except (ValueError, TypeError):
                pass
        else:
            # Pro ostatní entity porovnáme přímo
            try:
                if float(current_value) == float(expected_value):
                    return True
            except (ValueError, TypeError):
                if str(current_value) == str(expected_value):
                    return True

        return False

    async def _safe_call_service(
        self, service_name: str, service_data: Dict[str, Any]
    ) -> bool:
        """Bezpečné volání služby s ověřením stavu."""
        try:
            # Získáme původní stavy entit před voláním
            original_states = {}
            if "entity_id" in service_data:
                entity_id = service_data["entity_id"]
                original_states[entity_id] = self.hass.states.get(entity_id)

            # Zavoláme službu
            await self.hass.services.async_call("oig_cloud", service_name, service_data)

            # Počkáme na změnu stavu
            await asyncio.sleep(2)

            # Ověříme změnu pro známé entity
            if "entity_id" in service_data:
                entity_id = service_data["entity_id"]

                # Pro set_boiler_mode kontrolujeme změnu manual_mode
                if service_name == "set_boiler_mode":
                    mode_value = service_data.get("mode", "CBB")
                    expected_value = 1 if mode_value == "Manual" else 0

                    # Najdeme odpovídající manual_mode entitu
                    boiler_entities = [
                        entity_id
                        for entity_id in self.hass.states.async_entity_ids()
                        if "boiler_manual_mode" in entity_id
                    ]

                    for boiler_entity in boiler_entities:
                        if self._check_entity_state_change(
                            boiler_entity, expected_value
                        ):
                            self._logger.info(f"✅ Boiler mode změněn na {mode_value}")
                            return True

                # Pro ostatní služby standardní kontrola
                elif "mode" in service_data:
                    expected_value = service_data["mode"]
                    if self._check_entity_state_change(entity_id, expected_value):
                        self._logger.info(
                            f"✅ Entita {entity_id} změněna na {expected_value}"
                        )
                        return True

            return True  # Pokud nelze ověřit, považujeme za úspěšné

        except Exception as e:
            self._logger.error(f"❌ Chyba při volání služby {service_name}: {e}")
            return False

    def _start_monitoring_task(
        self, task_id: str, expected_entities: Dict[str, str], timeout: int
    ) -> None:
        """Spustí úlohu monitorování."""
        self._active_tasks[task_id] = {
            "expected_entities": expected_entities,
            "timeout": timeout,
            "start_time": time.time(),
            "status": "monitoring",
        }

        # Log monitoring start
        self._log_security_event(
            "MONITORING_STARTED",
            {
                "task_id": task_id,
                "expected_entities": str(expected_entities),
                "timeout": timeout,
                "status": "started",
            },
        )

    async def _check_entities_periodically(self, task_id: str) -> None:
        """Periodicky kontroluje entity dokud nejsou splněny podmínky nebo nevyprší timeout."""
        while task_id in self._active_tasks:
            task_info = self._active_tasks[task_id]
            expected_entities = task_info["expected_entities"]

            all_conditions_met = True
            for entity_id, expected_value in expected_entities.items():
                current_value = self._get_entity_state(entity_id)
                if not self._values_match(current_value, expected_value):
                    all_conditions_met = False
                    # Log verification failure
                    self._log_security_event(
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
                # Log successful completion
                self._log_security_event(
                    "MONITORING_SUCCESS",
                    {
                        "task_id": task_id,
                        "status": "completed",
                        "duration": time.time() - task_info["start_time"],
                    },
                )
                # TELEMETRIE: Úspěšné dokončení monitorování
                self._log_security_event(
                    "MONITORING_SUCCESS",
                    {
                        "task_id": task_id,
                        "status": "completed",
                        "duration": time.time() - task_info["start_time"],
                    },
                )
                break

            # Check timeout
            if time.time() - task_info["start_time"] > task_info["timeout"]:
                # Log timeout
                self._log_security_event(
                    "MONITORING_TIMEOUT",
                    {
                        "task_id": task_id,
                        "status": "timeout",
                        "duration": task_info["timeout"],
                    },
                )
                # TELEMETRIE: Timeout monitorování
                self._log_security_event(
                    "MONITORING_TIMEOUT",
                    {
                        "task_id": task_id,
                        "status": "timeout",
                        "duration": task_info["timeout"],
                    },
                )
                break

    async def cleanup(self) -> None:
        """Vyčistí ServiceShield při ukončení."""
        # Cleanup mode tracker
        if self.mode_tracker:
            await self.mode_tracker.cleanup()
            self._logger.info("[OIG Shield] Mode tracker cleaned up")

        # Zrušíme state listener
        if self._state_listener_unsub:
            self._state_listener_unsub()
            self._state_listener_unsub = None
            _LOGGER.info("[OIG Shield] State listener zrušen při cleanup")

        if self._telemetry_handler:
            try:
                # Odeslat závěrečnou telemetrii
                if self.telemetry_logger:
                    self.telemetry_logger.info(
                        "ServiceShield cleanup initiated",
                        extra={
                            "shield_data": {
                                "event": "cleanup",
                                "final_queue_length": len(self.queue),
                                "final_pending_count": len(self.pending),
                                "timestamp": dt_now().isoformat(),
                            }
                        },
                    )

                # Zavřít handler
                if hasattr(self._telemetry_handler, "close"):
                    await self._telemetry_handler.close()

                # Odstranit handler z loggerů
                shield_logger = logging.getLogger(
                    "custom_components.oig_cloud.service_shield"
                )
                if self._telemetry_handler in shield_logger.handlers:
                    shield_logger.removeHandler(self._telemetry_handler)

            except Exception as e:
                self._logger.debug(f"Error cleaning up telemetry: {e}")

        self._logger.debug("[OIG Shield] ServiceShield cleaned up")

    def start_monitoring(self) -> None:
        """Spustí monitoring task pro zpracování služeb."""
        if self.check_task is None or self.check_task.done():
            _LOGGER.info("[OIG Shield] Spouštím monitoring task")

            # OPRAVA: Debug informace o task
            if self.check_task and self.check_task.done():
                _LOGGER.warning(
                    f"[OIG Shield] Předchozí task byl dokončen: {self.check_task}"
                )

            self.check_task = asyncio.create_task(self._async_check_loop())

            # OPRAVA: Ověření, že task skutečně běží
            _LOGGER.info(f"[OIG Shield] Task vytvořen: {self.check_task}")
            _LOGGER.info(f"[OIG Shield] Task done: {self.check_task.done()}")
            _LOGGER.info(f"[OIG Shield] Task cancelled: {self.check_task.cancelled()}")
        else:
            _LOGGER.debug("[OIG Shield] Monitoring task již běží")

    async def _async_check_loop(self) -> None:
        """Asynchronní smyčka pro kontrolu a zpracování služeb."""
        _LOGGER.debug("[OIG Shield] Monitoring loop spuštěn")

        while True:
            try:
                # Hlavní logika smyčky pro zpracování služeb
                await self._check_loop(datetime.now())

                # OPRAVA: Přidání krátkého spánku, aby se předešlo přetížení CPU
                await asyncio.sleep(1)

            except Exception as e:
                _LOGGER.error(
                    f"[OIG Shield] Chyba v monitoring smyčce: {e}", exc_info=True
                )
                # OPRAVA: Přidání spánku při chybě, aby se předešlo opakovanému selhání
                await asyncio.sleep(5)


class ModeTransitionTracker:
    """Sleduje dobu reakce střídače na změny režimu (box_prms_mode)."""

    def __init__(self, hass: HomeAssistant, box_id: str):
        """Initialize the tracker.

        Args:
            hass: Home Assistant instance
            box_id: Box ID pro identifikaci senzoru
        """
        self.hass = hass
        self.box_id = box_id
        self._logger = logging.getLogger(__name__)

        # Tracking aktivních transakcí: key = trace_id, value = {from_mode, to_mode, start_time}
        self._active_transitions: Dict[str, Dict[str, Any]] = {}

        # Statistiky přechodů: key = "from_mode→to_mode", value = list of durations (seconds)
        self._transition_history: Dict[str, List[float]] = {}

        # Max samples per scenario (limitovat memory)
        self._max_samples = 100

        # Listener pro změny stavu box_prms_mode
        self._state_listener_unsub: Optional[Callable] = None

        self._logger.info(f"[ModeTracker] Initialized for box {box_id}")

    async def async_setup(self) -> None:
        """Setup state change listener and load historical data."""
        sensor_id = f"sensor.oig_{self.box_id}_box_prms_mode"

        # Poslouchat změny stavu senzoru
        self._state_listener_unsub = async_track_state_change_event(
            self.hass, sensor_id, self._async_mode_changed
        )

        self._logger.info(f"[ModeTracker] Listening to {sensor_id}")

        # Načíst historická data z recorderu (async)
        await self._async_load_historical_data(sensor_id)

    def track_request(self, trace_id: str, from_mode: str, to_mode: str) -> None:
        """Track začátek transakce (když ServiceShield přidá do fronty).

        Args:
            trace_id: Unique ID transakce
            from_mode: Počáteční režim
            to_mode: Cílový režim
        """
        if from_mode == to_mode:
            # Ignorovat same→same transakce
            return

        self._active_transitions[trace_id] = {
            "from_mode": from_mode,
            "to_mode": to_mode,
            "start_time": dt_now(),
        }

        self._logger.debug(
            f"[ModeTracker] Tracking {trace_id}: {from_mode} → {to_mode}"
        )

    @callback
    def _async_mode_changed(self, event: Event) -> None:
        """Callback when box_prms_mode state changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state or not old_state:
            return

        new_mode = new_state.state
        old_mode = old_state.state

        if new_mode == old_mode:
            return

        # Najít aktivní transakci která odpovídá této změně
        for trace_id, transition in list(self._active_transitions.items()):
            if (
                transition["from_mode"] == old_mode
                and transition["to_mode"] == new_mode
            ):

                # Spočítat dobu trvání
                duration = (dt_now() - transition["start_time"]).total_seconds()

                # Uložit do historie
                scenario_key = f"{old_mode}→{new_mode}"
                if scenario_key not in self._transition_history:
                    self._transition_history[scenario_key] = []

                # Přidat vzorek (limitovat na max_samples)
                self._transition_history[scenario_key].append(duration)
                if len(self._transition_history[scenario_key]) > self._max_samples:
                    self._transition_history[scenario_key].pop(0)  # Remove oldest

                self._logger.info(
                    f"[ModeTracker] ✅ Completed {scenario_key} in {duration:.1f}s"
                )

                # Odstranit z aktivních
                del self._active_transitions[trace_id]
                break

    def get_statistics(self) -> Dict[str, Any]:
        """Získat statistiky všech scénářů.

        Returns:
            Dict with scenario statistics:
            {
                "Home 1→Home UPS": {
                    "median_seconds": 5.2,
                    "p95_seconds": 8.1,
                    "samples": 45,
                    "min": 3.1,
                    "max": 12.5
                }
            }
        """
        import statistics

        result = {}

        for scenario, durations in self._transition_history.items():
            if not durations:
                continue

            try:
                result[scenario] = {
                    "median_seconds": round(statistics.median(durations), 1),
                    "p95_seconds": (
                        round(
                            statistics.quantiles(durations, n=20)[18],
                            1,  # 95th percentile
                        )
                        if len(durations) >= 20
                        else round(max(durations), 1)
                    ),
                    "samples": len(durations),
                    "min": round(min(durations), 1),
                    "max": round(max(durations), 1),
                }
            except Exception as e:
                self._logger.error(
                    f"[ModeTracker] Error calculating stats for {scenario}: {e}"
                )

        return result

    def get_offset_for_scenario(self, from_mode: str, to_mode: str) -> float:
        """Získat doporučený offset (v sekundách) pro daný scénář.

        Args:
            from_mode: Počáteční režim
            to_mode: Cílový režim

        Returns:
            Doporučený offset v sekundách (95. percentil, nebo fallback 10s)
        """
        scenario_key = f"{from_mode}→{to_mode}"
        stats = self.get_statistics()

        if scenario_key in stats and stats[scenario_key]["samples"] >= 2:
            # Použít 95. percentil pokud máme alespoň 2 vzorky
            offset = stats[scenario_key]["p95_seconds"]
            self._logger.debug(
                f"[ModeTracker] Using offset for {scenario_key}: {offset}s "
                f"(samples={stats[scenario_key]['samples']})"
            )
            return offset

        # Fallback: 10 sekund
        self._logger.debug(
            f"[ModeTracker] No data for {scenario_key}, using fallback 10s"
        )
        return 10.0

    async def _async_load_historical_data(self, sensor_id: str) -> None:
        """Načte historická data z recorderu a analyzuje přechody mezi režimy.

        Args:
            sensor_id: ID senzoru (sensor.oig_<box_id>_box_prms_mode)
        """
        try:
            self._logger.info(
                f"[ModeTracker] Loading historical data for {sensor_id}..."
            )

            # Načíst 30 dní zpátky
            end_time = dt_now()
            start_time = end_time - timedelta(days=30)

            # Načíst změny stavu z recorderu
            from homeassistant.components import recorder

            # Run v executoru aby to neblokovalo event loop
            states = await recorder.get_instance(self.hass).async_add_executor_job(
                recorder.history.state_changes_during_period,
                self.hass,
                start_time,
                end_time,
                sensor_id,
            )

            if not states or sensor_id not in states:
                self._logger.warning(
                    f"[ModeTracker] No historical data found for {sensor_id}"
                )
                return

            state_list = states[sensor_id]
            self._logger.info(
                f"[ModeTracker] Found {len(state_list)} historical states"
            )

            # Analyzovat přechody
            transitions_found = 0

            for i in range(1, len(state_list)):
                prev_state = state_list[i - 1]
                curr_state = state_list[i]

                prev_mode = prev_state.state
                curr_mode = curr_state.state

                # Pokud se režim změnil
                if (
                    prev_mode != curr_mode
                    and prev_mode != "unknown"
                    and curr_mode != "unknown"
                ):
                    # Spočítat dobu od posledního požadavku
                    # Hledáme změnu requested_mode v předchozích stavech
                    curr_state.attributes.get("requested_mode")

                    # Jednoduchá heuristika: když se state změnil, předpokládáme že
                    # změna proběhla od posledního stavu
                    duration = (
                        curr_state.last_changed - prev_state.last_changed
                    ).total_seconds()

                    # Filtrovat rozumné hodnoty (0.1s - 5min)
                    if 0.1 < duration < 300:
                        scenario_key = f"{prev_mode}→{curr_mode}"

                        if scenario_key not in self._transition_history:
                            self._transition_history[scenario_key] = []

                        self._transition_history[scenario_key].append(duration)
                        transitions_found += 1

            # Oříznout na max_samples
            for scenario_key in self._transition_history:
                if len(self._transition_history[scenario_key]) > self._max_samples:
                    self._transition_history[scenario_key] = self._transition_history[
                        scenario_key
                    ][-self._max_samples :]

            self._logger.info(
                f"[ModeTracker] Loaded {transitions_found} transitions from history, "
                f"scenarios: {len(self._transition_history)}"
            )

            # Vypsat statistiky
            stats = self.get_statistics()
            for scenario, data in stats.items():
                self._logger.debug(
                    f"[ModeTracker] {scenario}: median={data['median_seconds']}s, "
                    f"p95={data['p95_seconds']}s, samples={data['samples']}"
                )

        except Exception as e:
            self._logger.error(
                f"[ModeTracker] Error loading historical data: {e}", exc_info=True
            )

    async def async_cleanup(self) -> None:
        """Cleanup listeners."""
        if self._state_listener_unsub:
            self._state_listener_unsub()
            self._state_listener_unsub = None
