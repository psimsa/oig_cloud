import asyncio
import logging
import time
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

from ..const import DOMAIN
from ..shared.logging import setup_simple_telemetry
from . import dispatch as shield_dispatch
from . import queue as shield_queue
from . import validation as shield_validation

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
        return shield_validation.values_match(current_value, expected_value)

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
        await shield_queue.handle_shield_status(self, call)

    async def _handle_queue_info(self, call: Any) -> None:
        """Handle queue info service call."""
        await shield_queue.handle_queue_info(self, call)

    async def _handle_remove_from_queue(self, call: Any) -> None:
        """Handle remove from queue service call."""
        await shield_queue.handle_remove_from_queue(self, call)

    def get_shield_status(self) -> str:
        """Vrací aktuální stav ServiceShield."""
        return shield_queue.get_shield_status(self)

    def get_queue_info(self) -> Dict[str, Any]:
        """Vrací informace o frontě."""
        return shield_queue.get_queue_info(self)

    def has_pending_mode_change(self, target_mode: Optional[str] = None) -> bool:
        """Zjistí, jestli už probíhá nebo čeká service set_box_mode."""
        return shield_queue.has_pending_mode_change(self, target_mode)

    def _normalize_value(self, val: Any) -> str:
        return shield_validation.normalize_value(val)

    def _get_entity_state(self, entity_id: str) -> Optional[str]:
        return shield_validation.get_entity_state(self.hass, entity_id)

    def _extract_api_info(
        self, service_name: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract API call information from service parameters."""
        return shield_validation.extract_api_info(service_name, params)

    async def intercept_service_call(
        self,
        domain: str,
        service: str,
        data: Dict[str, Any],
        original_call: Callable,
        blocking: bool,
        context: Optional[Context],
    ) -> None:
        await shield_dispatch.intercept_service_call(
            self,
            domain,
            service,
            data,
            original_call,
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
        await shield_dispatch.start_call(
            self,
            service_name,
            data,
            expected_entities,
            original_call,
            domain,
            service,
            blocking,
            context,
        )

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



# Delegated methods (queue/validation/dispatch)
ServiceShield.extract_expected_entities = shield_validation.extract_expected_entities
ServiceShield._check_entity_state_change = shield_validation.check_entity_state_change
ServiceShield._log_event = shield_dispatch.log_event
ServiceShield._safe_call_service = shield_dispatch.safe_call_service
ServiceShield._start_monitoring_task = shield_queue.start_monitoring_task
ServiceShield._check_entities_periodically = shield_queue.check_entities_periodically
ServiceShield._check_loop = shield_queue.check_loop
ServiceShield.start_monitoring = shield_queue.start_monitoring
ServiceShield._async_check_loop = shield_queue.async_check_loop


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
            states = await self.hass.async_add_executor_job(
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
