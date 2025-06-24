from datetime import datetime, timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import callback, HomeAssistant, Context
from homeassistant.components import logbook
from homeassistant.util.dt import now as dt_now
import logging
import uuid
from typing import Dict, List, Tuple, Optional, Any, Callable

_LOGGER = logging.getLogger(__name__)

TIMEOUT_MINUTES = 15
CHECK_INTERVAL_SECONDS = 15


class ServiceShield:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass: HomeAssistant = hass
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.queue: List[
            Tuple[
                str,
                Dict[str, Any],
                Dict[str, str],
                Callable,
                str,
                str,
                bool,
                Optional[Context],
            ]
        ] = []
        self.running: Optional[str] = None
        self.queue_metadata: Dict[Tuple[str, str], str] = {}
        self.last_checked_entity_id: Optional[str] = None

    async def start(self) -> None:
        _LOGGER.debug("[OIG Shield] Inicializace – čištění fronty")
        self.pending.clear()
        self.queue.clear()
        self.queue_metadata.clear()
        self.running = None

        async_track_time_interval(
            self.hass, self._check_loop, timedelta(seconds=CHECK_INTERVAL_SECONDS)
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

        _LOGGER.debug(
            "[OIG Shield] [%s] Intercepting %s – params: %s, expected_entities: %s",
            trace_id,
            service_name,
            params,
            expected_entities,
        )

        if not expected_entities:
            fallback_entity = self.last_checked_entity_id
            fallback_entities = (
                {fallback_entity: self._get_entity_state(fallback_entity)}
                if fallback_entity
                else {}
            )

            await self._log_event(
                "skipped",
                service_name,
                {"params": params, "entities": fallback_entities},
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
            await self._log_event(
                "ignored",
                service_name,
                {"params": params, "entities": expected_entities},
                reason="Ignorováno – služba se stejným efektem je již ve frontě",
                context=context,
            )
            return

        # 🚫 Běží aktuálně stejná služba se stejným parametrem?
        if self.running == service_name:
            pending = self.pending.get(service_name)
            if pending and frozenset(pending["entities"].items()) == new_expected_set:
                await self._log_event(
                    "ignored",
                    service_name,
                    {"params": params, "entities": expected_entities},
                    reason="Ignorováno – požadavek již běží",
                    context=context,
                )
                return

            # 🔍 Možná už běžící služba plní tento cíl
            all_ok = True
            for entity_id, expected_value in expected_entities.items():
                state = self.hass.states.get(entity_id)
                try:
                    if "limit" in params:
                        current = round(float(state.state))
                        expected = round(float(expected_value))
                    else:
                        current = self._normalize_value(state.state)
                        expected = self._normalize_value(expected_value)
                except Exception:
                    all_ok = False
                    break

                if current != expected:
                    all_ok = False
                    break

            if all_ok:
                await self._log_event(
                    "skipped",
                    service_name,
                    {"params": params, "entities": expected_entities},
                    reason="Změna již bude provedena aktuálně běžící službou",
                    context=context,
                )
                return

            # ⏳ Není ještě splněno → přidat do fronty
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
            self.queue_metadata[(service_name, str(params))] = dt_now().isoformat()
            await self._log_event(
                "queued",
                service_name,
                {"params": params, "entities": expected_entities},
                reason="Přidáno do fronty – čeká na předchozí službu",
                context=context,
            )
            return

        # ✅ Není co frontovat, ale už hotovo?
        all_ok = True
        for entity_id, expected_value in expected_entities.items():
            state = self.hass.states.get(entity_id)
            current = self._normalize_value(state.state if state else None)
            expected = self._normalize_value(expected_value)
            if current != expected:
                all_ok = False
                break

        if all_ok:
            await self._log_event(
                "skipped",
                service_name,
                {"params": params, "entities": expected_entities},
                reason="Změna již provedena – není co volat",
                context=context,
            )
            return

        # 🚀 Spustíme hned
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
        finished = []

        for service_name, info in self.pending.items():
            if datetime.now() - info["called_at"] > timedelta(minutes=TIMEOUT_MINUTES):
                await self._log_event("timeout", service_name, info["params"])
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
                    break

            if all_ok:
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

        for svc in finished:
            del self.pending[svc]
            if svc == self.running:
                self.running = None

        if self.running is None and self.queue:
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
