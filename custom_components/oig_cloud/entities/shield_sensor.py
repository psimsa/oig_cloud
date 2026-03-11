"""ServiceShield senzory pro OIG Cloud integraci."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

from ..const import DOMAIN
from .base_sensor import OigCloudSensor, _get_sensor_definition, resolve_box_id

_LOGGER = logging.getLogger(__name__)


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


# OPRAVA: České překlady pro ServiceShield stavy
SERVICESHIELD_STATE_TRANSLATIONS: Dict[str, str] = {
    "active": "aktivní",
    "idle": "nečinný",
    "monitoring": "monitoruje",
    "protecting": "chrání",
    "disabled": "zakázán",
    "error": "chyba",
    "starting": "spouští se",
    "stopping": "zastavuje se",
    "unknown": "neznámý",
    "unavailable": "nedostupný",
}


def translate_shield_state(state: str) -> str:
    """Přeloží ServiceShield stav do češtiny."""
    return SERVICESHIELD_STATE_TRANSLATIONS.get(state.lower(), state)


class OigCloudShieldSensor(OigCloudSensor):
    """Senzor pro ServiceShield monitoring - REAL-TIME bez coordinator delay."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        # KRITICKÁ OPRAVA: Shield senzory NESMÍ dědit z CoordinatorEntity!
        # CoordinatorEntity má built-in debounce (30s interval), který zpozdí updates.
        # Shield senzory potřebují OKAMŽITÉ updaty (<100ms), proto používáme jen SensorEntity.
        from homeassistant.components.sensor import SensorEntity

        SensorEntity.__init__(self)

        self.coordinator = coordinator  # Uložíme pro přístup k box_id
        self._sensor_type = sensor_type
        self._shield_callback_registered = False

        # Nastavíme potřebné atributy pro entity
        sensor_def = _get_sensor_definition(sensor_type)

        # OPRAVA: Zjednodušit na stejnou logiku jako ostatní senzory
        name_cs = sensor_def.get("name_cs")
        name_en = sensor_def.get("name")

        self._attr_name = name_cs or name_en or sensor_type

        self._attr_native_unit_of_measurement = sensor_def.get("unit_of_measurement")
        self._attr_icon = sensor_def.get("icon")
        self._attr_device_class = sensor_def.get("device_class")
        self._attr_state_class = sensor_def.get("state_class")

        # OPRAVA: Bezpečné získání box_id s fallback (stejně jako v OigCloudSensor)
        self._box_id: str = resolve_box_id(coordinator)
        if self._box_id == "unknown":
            _LOGGER.warning(
                f"No coordinator data available for {sensor_type}, using fallback box_id"
            )

        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        _LOGGER.debug(
            f"✅ Properly initialized ServiceShield sensor: {sensor_type} with entity_id: {self.entity_id}"
        )

    @property
    def should_poll(self) -> bool:
        """Shield senzor je čistě event-driven.

        Updates přicházejí:
        - Okamžitě přes callback když se změní fronta/pending
        - Automaticky při coordinator refresh (30-120s)
        - Ihned po API volání díky coordinator.async_request_refresh()
        """
        return False

    async def async_added_to_hass(self) -> None:
        """Když je senzor přidán do Home Assistant."""
        # OPRAVA: Nevoláme super() protože už nejsme CoordinatorEntity
        # Shield senzory jsou event-driven a nepotřebují coordinator updates

        # Registrujeme callback pro okamžitou aktualizaci při změně shield stavu
        shield = self.hass.data.get(DOMAIN, {}).get("shield")
        if shield and not self._shield_callback_registered:
            shield.register_state_change_callback(self._on_shield_state_changed)
            self._shield_callback_registered = True
            _LOGGER.info(f"[Shield Sensor] Registrován callback pro {self.entity_id}")

    async def async_will_remove_from_hass(self) -> None:
        """Když je senzor odstraněn z Home Assistant."""
        # Odregistrujeme callback
        shield = self.hass.data.get(DOMAIN, {}).get("shield")
        if shield and self._shield_callback_registered:
            shield.unregister_state_change_callback(self._on_shield_state_changed)
            self._shield_callback_registered = False
            _LOGGER.info(f"[Shield Sensor] Odregistrován callback pro {self.entity_id}")

        # OPRAVA: Nevoláme super() protože už nejsme CoordinatorEntity

    def _on_shield_state_changed(self) -> None:
        """Callback volaný při změně shield stavu - THREAD-SAFE verze."""
        _LOGGER.debug(
            f"[Shield Sensor] Shield stav změněn - aktualizuji {self.entity_id}"
        )
        # KRITICKÁ OPRAVA: Callback může být volán z jiného vlákna
        # async_write_ha_state() NESMÍ být voláno z jiného vlákna - crashuje HA
        # schedule_update_ha_state() je thread-safe a naplánuje update v event loop
        self.schedule_update_ha_state()

    @property
    def name(self) -> str:
        """Jméno senzoru."""
        # OPRAVA: Zjednodušit na stejnou logiku jako ostatní senzory
        sensor_def = _get_sensor_definition(self._sensor_type)

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        name_cs = sensor_def.get("name_cs")
        name_en = sensor_def.get("name")

        return name_cs or name_en or self._sensor_type

    @property
    def icon(self) -> str:
        """Ikona senzoru."""
        # Použijeme definice z SENSOR_TYPES místo hardcodovaných ikon
        sensor_def = _get_sensor_definition(self._sensor_type)
        return sensor_def.get("icon", "mdi:shield")

    @property
    def unit_of_measurement(self) -> Optional[str]:
        """Jednotka měření."""
        # Použijeme definice z SENSOR_TYPES
        sensor_def = _get_sensor_definition(self._sensor_type)
        return sensor_def.get("unit_of_measurement")

    @property
    def device_class(self) -> Optional[str]:
        """Třída zařízení."""
        # Použijeme definice z SENSOR_TYPES
        sensor_def = _get_sensor_definition(self._sensor_type)
        return sensor_def.get("device_class")

    @property
    def state(self) -> Optional[Union[str, int, datetime]]:
        """Stav senzoru."""
        try:
            shield = self.hass.data[DOMAIN].get("shield")
            if not shield:
                return translate_shield_state("unavailable")

            if self._sensor_type == "service_shield_status":
                return translate_shield_state("active")
            elif self._sensor_type == "service_shield_queue":
                # Celkový počet: čekající ve frontě + všechny pending služby
                queue = getattr(shield, "queue", [])
                pending = getattr(shield, "pending", {})
                return len(queue) + len(pending)
            elif self._sensor_type == "mode_reaction_time":
                # Průměrná doba reakce napříč všemi scénáři
                if shield.mode_tracker:
                    stats = shield.mode_tracker.get_statistics()
                    if stats:
                        # Spočítat průměrný medián ze všech scénářů
                        medians = [
                            s["median_seconds"]
                            for s in stats.values()
                            if "median_seconds" in s
                        ]
                        if medians:
                            return round(sum(medians) / len(medians), 1)
                return None
            elif self._sensor_type == "service_shield_activity":
                running = getattr(shield, "running", None)
                if running:
                    # OPRAVA: Vrátit formát "service: target" pro frontend parsing
                    # Frontend parseShieldActivity() očekává: "set_box_mode: Home 5"
                    service_short = running.replace("oig_cloud.", "")

                    # Získáme target hodnotu z pending
                    pending = getattr(shield, "pending", {})
                    pending_info = pending.get(running)

                    if pending_info:
                        entities = pending_info.get("entities", {})
                        # Vezmeme první expected_value jako target
                        if entities:
                            target_value = next(iter(entities.values()), None)
                            if target_value:
                                return f"{service_short}: {target_value}"

                    # Fallback - jen název služby
                    return service_short
                else:
                    return translate_shield_state("idle")

        except Exception as e:
            _LOGGER.error(f"Error getting shield sensor state: {e}")
            return translate_shield_state("error")

        return translate_shield_state("unknown")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy."""
        attrs = {}

        try:
            shield = self.hass.data[DOMAIN].get("shield")
            if shield:
                queue = getattr(shield, "queue", [])
                running = getattr(shield, "running", None)
                pending = getattr(shield, "pending", {})

                # Všechny běžící služby (všechno v pending)
                running_requests = []
                for svc_name, svc_info in pending.items():
                    # OPRAVA: Strukturovaný targets output pro Frontend
                    targets = []

                    for entity_id, expected_value in svc_info.get(
                        "entities", {}
                    ).items():
                        current_state = self.hass.states.get(entity_id)
                        current_value = (
                            current_state.state if current_state else "unknown"
                        )
                        original_value = svc_info.get("original_states", {}).get(
                            entity_id, "unknown"
                        )

                        # Strukturovaný target objekt
                        targets.append(
                            {
                                "param": _extract_param_type(
                                    entity_id
                                ),  # "mode", "limit", "level"
                                "value": expected_value,  # Cílová hodnota (vždy česky ze senzoru)
                                "entity_id": entity_id,  # Pro identifikaci
                                "from": original_value,  # Odkud
                                "to": expected_value,  # Kam (stejné jako value)
                                "current": current_value,  # Aktuální stav
                            }
                        )

                    # Legacy: Zachovat changes pro zpětnou kompatibilitu
                    changes = []
                    for target in targets:
                        # OPRAVA: Pro grid limit potřebujeme více částí entity_id
                        entity_parts = target["entity_id"].split("_")
                        if "p_max_feed_grid" in target["entity_id"]:
                            # Pro grid limit: vezmi posledních 5 částí = "prm1_p_max_feed_grid"
                            entity_display = "_".join(entity_parts[-5:])
                        else:
                            # Pro ostatní: vezmi poslední 2 části
                            entity_display = (
                                "_".join(entity_parts[-2:])
                                if "_" in target["entity_id"]
                                else target["entity_id"]
                            )

                        changes.append(
                            f"{entity_display}: '{target['from']}' → '{target['to']}' (nyní: '{target['current']}')"
                        )

                    # Description pro frontend parsing (backward compatible)
                    service_short = svc_name.replace("oig_cloud.", "")
                    target_value = targets[0]["value"] if targets else None
                    if target_value:
                        description = f"{service_short}: {target_value}"
                    else:
                        # Fallback pokud není target (např. formating_mode)
                        description = f"Změna {service_short.replace('_', ' ')}"

                    running_requests.append(
                        {
                            "service": service_short,
                            "description": description,
                            "targets": targets,  # ← NOVÝ: Strukturovaná data pro Frontend!
                            "changes": changes,  # ← LEGACY: Zachovat pro kompatibilitu
                            "started_at": (
                                svc_info.get("called_at").isoformat()
                                if svc_info.get("called_at")
                                else None
                            ),
                            "duration_seconds": (
                                (
                                    datetime.now() - svc_info.get("called_at")
                                ).total_seconds()
                                if svc_info.get("called_at")
                                else None
                            ),
                            "is_primary": svc_name
                            == running,  # Označíme hlavní běžící službu
                        }
                    )

                # Čekající ve frontě
                queue_items = []
                for i, q in enumerate(queue):
                    service_name = q[0].replace("oig_cloud.", "")
                    params = q[1]
                    expected_entities = q[2]

                    # OPRAVA: Strukturovaný targets output pro Frontend
                    targets = []

                    for entity_id, expected_value in expected_entities.items():
                        current_state = self.hass.states.get(entity_id)
                        current_value = (
                            current_state.state if current_state else "unknown"
                        )

                        # Strukturovaný target objekt (pro queue nemáme original_states)
                        targets.append(
                            {
                                "param": _extract_param_type(
                                    entity_id
                                ),  # "mode", "limit", "level"
                                "value": expected_value,  # Cílová hodnota (vždy česky)
                                "entity_id": entity_id,  # Pro identifikaci
                                "from": current_value,  # Pro queue = current
                                "to": expected_value,  # Kam
                                "current": current_value,  # Aktuální stav
                            }
                        )

                    # Legacy: Zachovat changes pro zpětnou kompatibilitu
                    changes = []
                    for target in targets:
                        # OPRAVA: Pro grid limit potřebujeme více částí entity_id
                        entity_parts = target["entity_id"].split("_")
                        if "p_max_feed_grid" in target["entity_id"]:
                            # Pro grid limit: vezmi posledních 5 částí = "prm1_p_max_feed_grid"
                            entity_display = "_".join(entity_parts[-5:])
                        else:
                            # Pro ostatní: vezmi poslední 2 části
                            entity_display = (
                                "_".join(entity_parts[-2:])
                                if "_" in target["entity_id"]
                                else target["entity_id"]
                            )

                        changes.append(
                            f"{entity_display}: '{target['current']}' → '{target['to']}'"
                        )

                    # Čas zařazení z queue_metadata (nyní slovník s trace_id a queued_at)
                    queue_meta = getattr(shield, "queue_metadata", {}).get(
                        (q[0], str(params))
                    )

                    # Zpětná kompatibilita: queue_meta může být string (starý formát) nebo dict (nový)
                    if isinstance(queue_meta, dict):
                        queued_at = queue_meta.get("queued_at")
                        trace_id = queue_meta.get("trace_id")
                    else:
                        # Starý formát - jen trace_id jako string
                        queued_at = None
                        trace_id = queue_meta

                    # Vypočítáme duration pokud máme queued_at
                    duration_seconds = None
                    if queued_at:
                        duration_seconds = (datetime.now() - queued_at).total_seconds()

                    # Description pro frontend parsing (backward compatible)
                    target_value = targets[0]["value"] if targets else None
                    if target_value:
                        description = f"{service_name}: {target_value}"
                    else:
                        description = f"Změna {service_name.replace('_', ' ')}"

                    queue_items.append(
                        {
                            "position": i + 1,
                            "service": service_name,
                            "description": description,
                            "targets": targets,  # ← NOVÝ: Strukturovaná data!
                            "changes": changes,  # ← LEGACY: Kompatibilita
                            "queued_at": queued_at.isoformat() if queued_at else None,
                            "duration_seconds": duration_seconds,
                            "trace_id": trace_id,
                            "params": params,
                        }
                    )

                base_attrs = {
                    "total_requests": len(queue) + len(pending),
                    "running_requests": running_requests,  # Všechny běžící (může být více)
                    "primary_running": (
                        running.replace("oig_cloud.", "") if running else None
                    ),
                    "queued_requests": queue_items,
                    "queue_length": len(queue),
                    "running_count": len(pending),
                }

                # Speciální atributy pro mode_reaction_time
                if self._sensor_type == "mode_reaction_time" and shield.mode_tracker:
                    stats = shield.mode_tracker.get_statistics()
                    base_attrs["scenarios"] = stats
                    base_attrs["total_samples"] = sum(
                        s.get("samples", 0) for s in stats.values()
                    )
                    base_attrs["tracked_scenarios"] = len(stats)

                attrs.update(base_attrs)

        except Exception as e:
            _LOGGER.error(f"Error getting shield attributes: {e}")
            attrs["error"] = str(e)

        return attrs

    @property
    def unique_id(self) -> str:
        """Jedinečné ID senzoru."""
        box_id = self._resolve_box_id()
        # Přidáme verzi do unique_id pro vyřešení unit problému
        return f"oig_cloud_shield_{box_id}_{self._sensor_type}_v2"

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o zařízení - ServiceShield bude v separátním Shield zařízení."""
        box_id = self._resolve_box_id()
        return {
            "identifiers": {(DOMAIN, f"{box_id}_shield")},
            "name": f"ServiceShield {box_id}",
            "manufacturer": "OIG",
            "model": "Shield",
            "via_device": (DOMAIN, box_id),
        }

    def _resolve_box_id(self) -> str:
        """Return stable box_id/inverter_sn (avoid spot_prices/unknown)."""
        from .base_sensor import resolve_box_id

        box_id = resolve_box_id(self.coordinator)
        if not box_id or box_id == "unknown":
            try:
                import re

                title = (
                    getattr(
                        getattr(self.coordinator, "config_entry", None), "title", ""
                    )
                    or ""
                )
                m = re.search(r"(\\d{6,})", title)
                if m:
                    box_id = m.group(1)
            except Exception:
                box_id = None
        return box_id or "unknown"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # ServiceShield senzory jsou dostupné pokud existuje shield objekt
        shield = self.hass.data[DOMAIN].get("shield")
        return shield is not None
