from datetime import datetime, timedelta
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.core import callback
from homeassistant.components import logbook
from homeassistant.util.dt import now as dt_now
import logging
import uuid

_LOGGER = logging.getLogger(__name__)

TIMEOUT_MINUTES = 15
CHECK_INTERVAL_SECONDS = 15


class ServiceShield:
    def __init__(self, hass):
        self.hass = hass
        self.pending = {}
        self.queue = []
        self.running = None
        self.queue_metadata = {}
        self.last_checked_entity_id = None

    async def start(self):
        _LOGGER.debug("[OIG Shield] Inicializace – čištění fronty")
        self.pending.clear()
        self.queue.clear()
        self.queue_metadata.clear()
        self.running = None

        async_track_time_interval(
            self.hass, self._check_loop, timedelta(seconds=CHECK_INTERVAL_SECONDS)
        )

    def _normalize_value(self, val: str) -> str:
        val = str(val or "").strip().lower().replace(" ", "").replace("/", "")
        mapping = {
            "vypnutoon": "vypnuto",
            "zapnutoon": "zapnuto",
            "somezenimlimited": "somezenim",
        }
        return mapping.get(val, val)

    def _get_entity_state(self, entity_id):
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    async def intercept_service_call(
        self,
        domain,
        service,
        data,
        original_call,
        blocking,
        context,
    ):
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
        service_name,
        data,
        expected_entities,
        original_call,
        domain,
        service,
        blocking,
        context,
    ):
        self.running = service_name
        self.pending[service_name] = {
            "entities": expected_entities,
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
            },
            reason="Požadavek odeslán do API",
            context=context,
        )

        await self._log_event("started", service_name, data, context=context)

        await original_call(
            domain, service, service_data=data, blocking=blocking, context=context
        )

    @callback
    async def _check_loop(self, _now):
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
                    },
                    reason="Změna provedena",
                )
                await self._log_event(
                    "released",
                    service_name,
                    {
                        "params": info["params"],
                        "entities": info["entities"],
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

    async def _log_event(self, event_type, service, data, reason=None, context=None):
        params = data.get("params", {})
        entities = data.get("entities", {})
        context = context or data.get("context")

        for entity_id, expected_value in entities.items() or {None: None}.items():
            state = self.hass.states.get(entity_id) if entity_id else None
            friendly_name = (
                state.attributes.get("friendly_name", entity_id)
                if state and entity_id
                else service
            )
            current_value = state.state if state else "neznámá"

            if event_type == "change_requested":
                message = f"Požadavek na změnu {friendly_name} z '{current_value}' na '{expected_value}'"
            elif event_type == "completed":
                message = f"Změna provedena – {friendly_name} z '{current_value}' na '{expected_value}'"
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
                    "from": current_value,
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
                current_value,
                expected_value,
                reason or "-",
            )

    def extract_expected_entities(
        self, service_name: str, data: dict
    ) -> dict[str, str]:
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
            expected_value = "Zapnuto/On" if mode == "Manual" else "Vypnuto/Off"
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
