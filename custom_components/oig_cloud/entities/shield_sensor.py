"""ServiceShield senzory pro OIG Cloud integraci."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from ..const import DOMAIN
from .base_sensor import _get_sensor_definition, resolve_box_id

_LOGGER = logging.getLogger(__name__)
SERVICE_PREFIX = f"{DOMAIN}."


def _extract_param_type(entity_id: str) -> str:
    """Extrahuje typ parametru z entity_id pro strukturovaný targets output."""
    if "p_max_feed_grid" in entity_id:
        return "limit"
    elif "prms_to_grid" in entity_id:
        return "mode"
    elif "box_prms_mode" in entity_id:
        return "mode"
    elif "box_prm2_app" in entity_id:
        return "app"
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


if TYPE_CHECKING:

    class _ShieldBase:
        hass: Any
        coordinator: Any
        entity_id: str

        def __init__(self) -> None: ...
        async def async_added_to_hass(self) -> None: ...
        async def async_will_remove_from_hass(self) -> None: ...
        def schedule_update_ha_state(self) -> None: ...

else:
    from homeassistant.components.sensor import SensorEntity as _ShieldBase


class OigCloudShieldSensor(_ShieldBase):
    """Senzor pro ServiceShield monitoring - REAL-TIME bez coordinator delay."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__()

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
    def state(self) -> Optional[Union[str, int, float, datetime]]:
        """Stav senzoru."""
        try:
            shield = self.hass.data[DOMAIN].get("shield")
            if not shield:
                return translate_shield_state("unavailable")
            return _get_shield_state(self._sensor_type, shield)

        except Exception as e:
            _LOGGER.error(f"Error getting shield sensor state: {e}")
            return translate_shield_state("error")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy."""
        attrs = {}

        try:
            shield = self.hass.data[DOMAIN].get("shield")
            if shield:
                attrs.update(
                    _build_shield_attrs(
                        self.hass, shield, sensor_type=self._sensor_type
                    )
                )

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

        box_id: Optional[str] = resolve_box_id(self.coordinator)
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


def _get_shield_state(sensor_type: str, shield: Any) -> Optional[Union[str, int, float, datetime]]:
    if sensor_type == "service_shield_status":
        return translate_shield_state("active")
    if sensor_type == "service_shield_queue":
        queue = getattr(shield, "queue", [])
        pending = getattr(shield, "pending", {})
        return len(queue) + len(pending)
    if sensor_type == "mode_reaction_time":
        return _compute_mode_reaction_time(shield)
    if sensor_type == "service_shield_activity":
        return _compute_shield_activity(shield)
    return translate_shield_state("unknown")


def _compute_mode_reaction_time(shield: Any) -> Optional[float]:
    if not shield.mode_tracker:
        return None
    stats = shield.mode_tracker.get_statistics()
    if not stats:
        return None
    medians = [s["median_seconds"] for s in stats.values() if "median_seconds" in s]
    if not medians:
        return None
    return round(sum(medians) / len(medians), 1)


def _compute_shield_activity(shield: Any) -> str:
    running = getattr(shield, "running", None)
    if not running:
        return translate_shield_state("idle")

    service_short = running.replace(SERVICE_PREFIX, "")
    pending = getattr(shield, "pending", {})
    pending_info = pending.get(running)
    if pending_info:
        entities = pending_info.get("entities", {})
        target_value = next(iter(entities.values()), None) if entities else None
        if target_value:
            return f"{service_short}: {target_value}"
    return service_short


def _build_shield_attrs(
    hass: Any, shield: Any, *, sensor_type: str
) -> Dict[str, Any]:
    queue = getattr(shield, "queue", [])
    running = getattr(shield, "running", None)
    pending = getattr(shield, "pending", {})

    running_requests = _build_running_requests(hass, pending, running)
    queue_items = _build_queue_items(hass, queue, getattr(shield, "queue_metadata", {}))

    base_attrs = {
        "total_requests": len(queue) + len(pending),
        "running_requests": running_requests,
        "primary_running": running.replace(SERVICE_PREFIX, "") if running else None,
        "queued_requests": queue_items,
        "queue_length": len(queue),
        "running_count": len(pending),
    }

    if sensor_type == "mode_reaction_time" and shield.mode_tracker:
        stats = shield.mode_tracker.get_statistics()
        base_attrs["scenarios"] = stats
        base_attrs["total_samples"] = sum(
            s.get("samples", 0) for s in stats.values()
        )
        base_attrs["tracked_scenarios"] = len(stats)

    return base_attrs


def _build_running_requests(
    hass: Any, pending: Dict[str, Any], running: Optional[str]
) -> List[Dict[str, Any]]:
    running_requests = []
    for svc_name, svc_info in pending.items():
        targets = _build_targets(
            hass,
            svc_info.get("entities", {}),
            original_states=svc_info.get("original_states", {}),
        )
        changes = _build_changes(targets, include_current=True)
        service_short = svc_name.replace("oig_cloud.", "")
        params = svc_info.get("params", {})
        description = _build_description(service_short, targets, params)

        running_requests.append(
            {
                "service": service_short,
                "description": description,
                "targets": targets,
                "changes": changes,
                "started_at": (
                    svc_info.get("called_at").isoformat()
                    if svc_info.get("called_at")
                    else None
                ),
                "duration_seconds": (
                    (datetime.now() - svc_info.get("called_at")).total_seconds()
                    if svc_info.get("called_at")
                    else None
                ),
                "is_primary": svc_name == running,
                "grid_delivery_step": params.get("_grid_delivery_step"),
                "box_mode_step": params.get("_box_mode_step"),
            }
        )
    return running_requests


def _build_queue_items(
    hass: Any, queue: List[Any], queue_metadata: Dict[Any, Any]
) -> List[Dict[str, Any]]:
    queue_items = []
    for i, q in enumerate(queue):
        service_name = q[0].replace("oig_cloud.", "")
        params = q[1]
        expected_entities = q[2]
        targets = _build_targets(hass, expected_entities, original_states=None)
        changes = _build_changes(targets, include_current=False)

        queued_at, trace_id = _resolve_queue_meta(queue_metadata, q[0], params)
        duration_seconds = (
            (datetime.now() - queued_at).total_seconds() if queued_at else None
        )
        description = _build_description(service_name, targets, params)

        item = {
            "position": i + 1,
            "service": service_name,
            "description": description,
            "targets": targets,
            "changes": changes,
            "queued_at": queued_at.isoformat() if queued_at else None,
            "duration_seconds": duration_seconds,
            "trace_id": trace_id,
            "params": params,
        }

        # Include grid delivery step info for split flow visibility
        grid_step = params.get("_grid_delivery_step")
        if grid_step:
            item["grid_delivery_step"] = grid_step

        # Include box mode step info for composite split flow visibility
        box_mode_step = params.get("_box_mode_step")
        if box_mode_step:
            item["box_mode_step"] = box_mode_step

        queue_items.append(item)
    return queue_items


def _build_targets(
    hass: Any,
    entities: Dict[str, Any],
    *,
    original_states: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    targets = []
    for entity_id, expected_value in entities.items():
        current_state = hass.states.get(entity_id)
        current_value = current_state.state if current_state else "unknown"
        original_value = (
            original_states.get(entity_id, "unknown") if original_states else current_value
        )
        targets.append(
            {
                "param": _extract_param_type(entity_id),
                "value": expected_value,
                "entity_id": entity_id,
                "from": original_value,
                "to": expected_value,
                "current": current_value,
            }
        )
    return targets


def _build_changes(targets: List[Dict[str, Any]], *, include_current: bool) -> List[str]:
    changes = []
    for target in targets:
        entity_display = _format_entity_display(target["entity_id"])
        if include_current:
            changes.append(
                f"{entity_display}: '{target['from']}' → '{target['to']}' (nyní: '{target['current']}')"
            )
        else:
            changes.append(
                f"{entity_display}: '{target['current']}' → '{target['to']}'"
            )
    return changes


def _format_entity_display(entity_id: str) -> str:
    entity_parts = entity_id.split("_")
    if "p_max_feed_grid" in entity_id:
        return "_".join(entity_parts[-5:])
    if "_" in entity_id:
        return "_".join(entity_parts[-2:])
    return entity_id


def _build_description(service_short: str, targets: List[Dict[str, Any]], params: Optional[Dict[str, Any]] = None) -> str:
    target_value = targets[0]["value"] if targets else None
    if target_value:
        # Add step indicator for grid delivery split flow
        grid_step = params.get("_grid_delivery_step") if params else None
        if grid_step:
            return f"{service_short}: {target_value} (step: {grid_step})"
        # Add step indicator for box mode composite split flow
        box_mode_step = params.get("_box_mode_step") if params else None
        if box_mode_step:
            return f"{service_short}: {target_value} (step: {box_mode_step})"
        return f"{service_short}: {target_value}"
    return f"Změna {service_short.replace('_', ' ')}"


def _resolve_queue_meta(
    queue_metadata: Dict[Any, Any], service_name: str, params: Any
) -> tuple[Optional[datetime], Optional[str]]:
    queue_meta = queue_metadata.get((service_name, str(params)))
    if isinstance(queue_meta, dict):
        return queue_meta.get("queued_at"), queue_meta.get("trace_id")
    return None, queue_meta
