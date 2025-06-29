from datetime import datetime, timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import callback, HomeAssistant, Context
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import logbook
from homeassistant.util.dt import now as dt_now
import logging
import uuid
import time
import asyncio
import voluptuous as vol
from typing import Dict, List, Tuple, Optional, Any, Callable

from .shared.logging import setup_otel_logging

_LOGGER = logging.getLogger(__name__)

TIMEOUT_MINUTES = 15
CHECK_INTERVAL_SECONDS = 15


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
        self.queue_metadata: Dict[Tuple[str, str], str] = {}
        self.running: Optional[str] = None
        self.last_checked_entity_id: Optional[str] = None

        # Atributy pro telemetrii (pro zpětnou kompatibilitu)
        self.telemetry_handler: Optional[Any] = None
        self.telemetry_logger: Optional[Any] = None

        # Setup telemetrie pouze pro ServiceShield
        if not entry.options.get("no_telemetry", False):
            self._setup_telemetry()

    def _setup_telemetry(self) -> None:
        """Nastavit telemetrii pouze pro ServiceShield."""
        try:
            from .shared.logging import setup_otel_logging
            import hashlib

            username = self.entry.data.get("username", "")
            email_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()
            hass_id = hashlib.sha256(
                self.hass.data["core.uuid"].encode("utf-8")
            ).hexdigest()

            self._telemetry_handler = setup_otel_logging(email_hash, hass_id)

            # Nastavit i pro zpětnou kompatibilitu s _log_telemetry metodou
            self.telemetry_handler = self._telemetry_handler

            # Připojit handler k ServiceShield loggeru
            shield_logger = logging.getLogger(
                "custom_components.oig_cloud.service_shield"
            )
            shield_logger.addHandler(self._telemetry_handler)
            shield_logger.setLevel(logging.INFO)

            # Vytvoříme i telemetry_logger pro zpětnou kompatibilitu
            self.telemetry_logger = logging.getLogger(
                "custom_components.oig_cloud.service_shield.telemetry"
            )
            self.telemetry_logger.addHandler(self._telemetry_handler)
            self.telemetry_logger.setLevel(logging.INFO)

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

    def _log_telemetry(
        self, event_type: str, service_name: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log telemetry event."""
        try:
            _LOGGER.debug(
                f"[TELEMETRY DEBUG] Starting telemetry log: {event_type} for {service_name}"
            )
            _LOGGER.debug(
                f"[TELEMETRY DEBUG] Handler available: {self._telemetry_handler is not None}"
            )

            if self._telemetry_handler:
                # Příprava shield_data pro extra field
                shield_data: Dict[str, Any] = {
                    "event_type": event_type,
                    "service_name": service_name,
                    "timestamp": dt_now().isoformat(),
                    "component": "service_shield",
                }

                if data:
                    shield_data.update(data)

                _LOGGER.debug(f"[TELEMETRY DEBUG] Shield data prepared: {shield_data}")

                # OPRAVA: Vytvoříme LogRecord a pošleme přímo do handleru
                message = f"ServiceShield {event_type}: {service_name}"

                # Vytvoření custom log record
                record = logging.LogRecord(
                    name="custom_components.oig_cloud.telemetry",
                    level=logging.INFO,
                    pathname="",
                    lineno=0,
                    msg=message,
                    args=(),
                    exc_info=None,
                )

                # Přidání shield_data jako extra attribute
                record.shield_data = shield_data

                _LOGGER.debug(f"[TELEMETRY DEBUG] About to emit record to handler")

                # OPRAVA: Pošleme přímo do handleru
                self._telemetry_handler.emit(record)

                _LOGGER.debug(f"[TELEMETRY DEBUG] Record emitted successfully")
            else:
                _LOGGER.debug(f"[TELEMETRY DEBUG] No telemetry handler available!")

        except Exception as e:
            # OPRAVA: Logujeme chybu místo tichého selhání
            _LOGGER.error(
                f"[TELEMETRY DEBUG ERROR] Failed to log telemetry: {e}", exc_info=True
            )

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

        # OPRAVA: Přidání debug logování pro ověření, že se check_loop spouští
        _LOGGER.info(
            f"[OIG Shield] Spouštím check_loop každých {CHECK_INTERVAL_SECONDS} sekund"
        )

        async_track_time_interval(
            self.hass, self._check_loop, timedelta(seconds=CHECK_INTERVAL_SECONDS)
        )

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

    def _normalize_value(self, val: Any) -> str:
        val = str(val or "").strip().lower().replace(" ", "").replace("/", "")
        mapping = {
            "vypnutoon": "vypnuto",
            "zapnutoon": "zapnuto",
            "somezenimlimited": "somezenim",
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
            api_info = {
                "api_endpoint": "Device.Set.Value.php",
                "api_table": "boiler_prms",
                "api_column": "manual",
                "api_value": 1 if mode == "Manual" else 0,
                "api_description": f"Set boiler mode to {mode}",
            }
        elif service_name == "oig_cloud.set_box_mode":
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

        expected_entities = self.extract_expected_entities(service_name, params)
        api_info = self._extract_api_info(service_name, params)

        _LOGGER.info(f"[INTERCEPT DEBUG] Service: {service_name}")
        _LOGGER.info(f"[INTERCEPT DEBUG] Expected entities: {expected_entities}")
        _LOGGER.info(f"[INTERCEPT DEBUG] Queue length: {len(self.queue)}")
        _LOGGER.info(f"[INTERCEPT DEBUG] Running: {self.running}")

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
            _LOGGER.info(f"[INTERCEPT DEBUG] No expected entities - returning early")
            await self._log_event(
                "skipped",
                service_name,
                {"params": params, "entities": {}},
                reason="Není co měnit – požadované hodnoty již nastaveny",
                context=context,
            )
            return

        new_expected_set = frozenset(expected_entities.items())

        # 🚫 Je už ve frontě stejná služba se stejným cílem?
        if any(
            q[0] == service_name and frozenset(q[2].items()) == new_expected_set
            for q in self.queue
        ):
            _LOGGER.info(
                f"[INTERCEPT DEBUG] Service already in queue - returning early"
            )
            await self._log_event(
                "ignored",
                service_name,
                {"params": params, "entities": expected_entities},
                reason="Ignorováno – služba se stejným efektem je již ve frontě",
                context=context,
            )
            self._log_telemetry(
                "ignored",
                service_name,
                {
                    "params": params,
                    "entities": expected_entities,
                    "reason": "duplicate_in_queue",
                },
            )
            return

        # ✅ Není co frontovat, ale už hotovo?
        all_ok = True
        for entity_id, expected_value in expected_entities.items():
            state = self.hass.states.get(entity_id)
            current = self._normalize_value(state.state if state else None)
            expected = self._normalize_value(expected_value)
            _LOGGER.info(
                f"[INTERCEPT DEBUG] Entity {entity_id}: current='{current}' expected='{expected}'"
            )
            if current != expected:
                all_ok = False
                break

        if all_ok:
            _LOGGER.info(
                f"[INTERCEPT DEBUG] All entities already match - returning early"
            )
            # OPRAVA: Logujeme telemetrii i pro skipped požadavky
            self._log_telemetry(
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

        # 🚀 Spustíme hned
        _LOGGER.info(f"[INTERCEPT DEBUG] Will execute service - logging telemetry")
        self._log_telemetry(
            "change_requested",
            service_name,
            {
                "trace_id": trace_id,
                "params": params,
                "entities": expected_entities,
                **api_info,  # Přidáme API informace
            },
        )

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
        self.running = service_name

        # Uložíme původní stavy entit před změnou
        original_states = {}
        for entity_id in expected_entities.keys():
            state = self.hass.states.get(entity_id)
            original_states[entity_id] = state.state if state else None

        self.pending[service_name] = {
            "entities": expected_entities,
            "original_states": original_states,
            "params": data,
            "called_at": datetime.now(),
        }

        # 🧹 Vymažeme metadata z fronty
        self.queue_metadata.pop((service_name, str(data)), None)

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

        await self._log_event("started", service_name, data, context=context)

        await original_call(
            domain, service, service_data=data, blocking=blocking, context=context
        )

    @callback
    async def _check_loop(self, _now: datetime) -> None:
        # OPRAVA: Explicitní debug log na začátku každé kontroly
        _LOGGER.debug(
            f"[OIG Shield] Check loop tick - pending: {len(self.pending)}, queue: {len(self.queue)}, running: {self.running}"
        )

        if not self.pending and not self.queue and not self.running:
            _LOGGER.debug("[OIG Shield] Check loop - vše prázdné, žádná akce")
            return

        finished = []

        for service_name, info in self.pending.items():
            _LOGGER.debug(f"[OIG Shield] Kontroluji pending službu: {service_name}")

            if datetime.now() - info["called_at"] > timedelta(minutes=TIMEOUT_MINUTES):
                _LOGGER.warning(f"[OIG Shield] Timeout pro službu {service_name}")
                await self._log_event("timeout", service_name, info["params"])
                # 📡 Telemetrie pro timeout
                self._log_telemetry(
                    "timeout",
                    service_name,
                    {"params": info["params"], "entities": info["entities"]},
                )
                finished.append(service_name)
                continue

            all_ok = True
            for entity_id, expected_value in info["entities"].items():
                state = self.hass.states.get(entity_id)
                current_value = state.state if state else None

                if entity_id and entity_id.endswith("_invertor_prm1_p_max_feed_grid"):
                    try:
                        norm_expected = str(round(float(expected_value)))
                        norm_current = str(round(float(current_value)))
                    except (ValueError, TypeError):
                        norm_expected = str(expected_value)
                        norm_current = str(current_value or "")
                else:
                    norm_expected = (
                        str(expected_value or "").strip().lower().replace(" ", "")
                    )
                    norm_current = (
                        str(current_value or "").strip().lower().replace(" ", "")
                    )

                _LOGGER.debug(
                    "[OIG Shield] Kontrola %s: aktuální='%s', očekávaná='%s' (normalizace: '%s' vs '%s')",
                    entity_id,
                    current_value,
                    expected_value,
                    norm_current,
                    norm_expected,
                )

                if norm_current != norm_expected:
                    all_ok = False
                    _LOGGER.debug(
                        f"[OIG Shield] Entity {entity_id} ještě není v požadovaném stavu"
                    )
                    break

            if all_ok:
                _LOGGER.info(
                    f"[OIG Shield] Služba {service_name} byla úspěšně dokončena"
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
                # 📡 Telemetrie pro dokončené požadavky
                self._log_telemetry(
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
            _LOGGER.debug("[OIG Shield] Spouštím další službu z fronty: %s", next_svc)
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
            friendly_name = (
                state.attributes.get("friendly_name", entity_id)
                if state and entity_id
                else service
            )
            current_value = state.state if state else "neznámá"

            # Pro completed událost použijeme původní stav místo aktuálního
            if event_type == "completed" and entity_id in original_states:
                from_value = original_states[entity_id]
            else:
                from_value = current_value

            if event_type == "change_requested":
                message = f"Požadavek na změnu {friendly_name} z '{from_value}' na '{expected_value}'"
            elif event_type == "completed":
                message = f"Změna provedena – {friendly_name} z '{from_value}' na '{expected_value}'"
            elif event_type == "skipped":
                message = f"Změna přeskočena – {friendly_name} má již hodnotu '{expected_value}'"
            elif event_type == "queued":
                message = (
                    f"Přidáno do fronty – {friendly_name}: aktuální = '{current_value}', "
                    f"očekávaná = '{expected_value}'"
                )
            elif event_type == "started":
                message = f"Spuštěna služba – {service}"
            elif event_type == "ignored":
                message = (
                    f"Ignorováno – {service} ({reason or 'už běží nebo ve frontě'})"
                )
            elif event_type == "timeout":
                message = (
                    f"Časový limit vypršel – {friendly_name} stále není '{expected_value}' "
                    f"(aktuální: '{current_value}')"
                )
            elif event_type == "released":
                message = f"Semafor uvolněn – služba {service} dokončena"
            else:
                message = f"{event_type} – {service}"

            # 🪵 Log do HA logbooku
            self.hass.bus.async_fire(
                "logbook_entry",
                {
                    "name": "OIG Shield",
                    "message": message,
                    "domain": "oig_cloud",
                    "entity_id": entity_id,
                    "when": dt_now(),
                    "source": "OIG Cloud Shield",
                    "source_type": "system",
                },
                context=context,
            )

            # 📡 Emitujeme vlastní událost
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

            # 🐞 Debug log do konzole
            _LOGGER.debug(
                "[OIG Shield] Event: %s | Entity: %s | From: '%s' → To: '%s' | Reason: %s",
                event_type,
                entity_id,
                from_value,
                expected_value,
                reason or "-",
            )

    def extract_expected_entities(
        self, service_name: str, data: Dict[str, Any]
    ) -> Dict[str, str]:
        self.last_checked_entity_id = None

        def find_entity(suffix: str) -> str | None:
            for entity in self.hass.states.async_all():
                if entity.entity_id.endswith(suffix):
                    return entity.entity_id
            return None

        if service_name == "oig_cloud.set_box_mode":
            expected_value = str(data.get("mode") or "").strip()
            if not expected_value or expected_value.lower() == "none":
                return {}
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
            if mode not in ("CBB", "Manual"):
                return {}
            expected_value = "Manuální" if mode == "Manual" else "CBB"
            entity_id = find_entity("_boiler_manual_mode")
            if entity_id:
                self.last_checked_entity_id = entity_id
                state = self.hass.states.get(entity_id)
                current = self._normalize_value(state.state if state else None)
                expected = self._normalize_value(expected_value)
                _LOGGER.debug(
                    "[extract] boiler_mode | current='%s' expected='%s'",
                    current,
                    expected,
                )
                if current != expected:
                    return {entity_id: expected_value}
            return {}

        elif service_name == "oig_cloud.set_grid_delivery":
            if "limit" in data:
                try:
                    expected_value = round(float(data["limit"]))
                except (ValueError, TypeError):
                    return {}

                entity_id = find_entity("_invertor_prm1_p_max_feed_grid")
                if entity_id:
                    self.last_checked_entity_id = entity_id
                    state = self.hass.states.get(entity_id)

                    try:
                        current_value = round(float(state.state))
                    except (ValueError, TypeError, AttributeError):
                        current_value = None

                    _LOGGER.debug(
                        "[extract] grid_delivery.limit | current=%s expected=%s",
                        current_value,
                        expected_value,
                    )

                    if current_value != expected_value:
                        return {
                            entity_id: str(expected_value)
                        }  # hodnotu zpět převedeme na string kvůli entitě
                return {}

            if "mode" in data:
                expected_value = str(data["mode"] or "").strip()
                if not expected_value or expected_value.lower() == "none":
                    return {}
                entity_id = find_entity("_invertor_prms_to_grid")
                if entity_id:
                    self.last_checked_entity_id = entity_id
                    state = self.hass.states.get(entity_id)
                    current = self._normalize_value(state.state if state else None)
                    expected = self._normalize_value(expected_value)
                    _LOGGER.debug(
                        "[extract] grid_delivery.mode | current='%s' expected='%s'",
                        current,
                        expected,
                    )
                    if current != expected:
                        return {entity_id: expected_value}
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
            if expected_value == 0 and current_value == "CBB":
                return True
            elif expected_value == 1 and current_value == "Manuální":
                return True
        elif "ssr" in entity_id:
            # SSR relé: Vypnuto/Off=0, Zapnuto/On=1
            if expected_value == 0 and current_value in [
                "Vypnuto/Off",
                "Vypnuto",
                "Off",
            ]:
                return True
            elif expected_value == 1 and current_value in [
                "Zapnuto/On",
                "Zapnuto",
                "On",
            ]:
                return True
        elif "box_prms_mode" in entity_id:
            # Režim Battery Box: Home 1=0, Home 2=1, Home 3=2, Home UPS=3
            mode_mapping = {0: "Home 1", 1: "Home 2", 2: "Home 3", 3: "Home UPS"}
            if current_value == mode_mapping.get(expected_value):
                return True
        elif "invertor_prms_to_grid" in entity_id:
            # Grid delivery: složitější logika podle typu zařízení
            # Můžeme použít přibližnou kontrolu podle textu
            if expected_value == 0 and "Vypnuto" in current_value:
                return True
            elif expected_value == 1 and (
                "Zapnuto" in current_value or "On" in current_value
            ):
                return True
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
                # ...existing code...

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
                # ...existing code...

    async def cleanup(self) -> None:
        """Vyčistí ServiceShield při ukončení."""
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
