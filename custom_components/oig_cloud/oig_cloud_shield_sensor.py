"""ServiceShield senzory pro OIG Cloud integraci."""

import logging
from typing import Any, Dict, Optional, Union
from datetime import datetime

from .oig_cloud_sensor import OigCloudSensor, _get_sensor_definition
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

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
    """Senzor pro ServiceShield monitoring."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        # PŘESKOČÍME parent init pro ServiceShield senzory
        if not sensor_type.startswith("service_shield"):
            raise ValueError(
                f"OigCloudShieldSensor can only handle service_shield sensors, got: {sensor_type}"
            )

        # Inicializujeme přímo CoordinatorEntity a SensorEntity, ne OigCloudSensor
        from homeassistant.helpers.update_coordinator import CoordinatorEntity
        from homeassistant.components.sensor import SensorEntity

        CoordinatorEntity.__init__(self, coordinator)
        SensorEntity.__init__(self)

        self.coordinator = coordinator
        self._sensor_type = sensor_type

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

        # Nastavíme box_id a entity_id podle vzoru z OigCloudDataSensor
        self._box_id: str = list(self.coordinator.data.keys())[0]
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        _LOGGER.debug(
            f"✅ Properly initialized ServiceShield sensor: {sensor_type} with entity_id: {self.entity_id}"
        )

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
            elif self._sensor_type == "service_shield_activity":
                running = getattr(shield, "running", None)
                if running:
                    return running.replace("oig_cloud.", "")
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
                    changes = []
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
                        entity_name = (
                            entity_id.split("_")[-2:]
                            if "_" in entity_id
                            else [entity_id]
                        )
                        entity_display = "_".join(entity_name)
                        changes.append(
                            f"{entity_display}: '{original_value}' → '{expected_value}' (nyní: '{current_value}')"
                        )

                    running_requests.append(
                        {
                            "service": svc_name.replace("oig_cloud.", ""),
                            "description": f"Změna {svc_name.replace('oig_cloud.', '').replace('_', ' ')}",
                            "changes": changes,
                            "started_at": (
                                svc_info.get("called_at").strftime("%d.%m.%Y %H:%M:%S")
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

                    changes = []
                    for entity_id, expected_value in expected_entities.items():
                        current_state = self.hass.states.get(entity_id)
                        current_value = (
                            current_state.state if current_state else "unknown"
                        )
                        entity_name = (
                            entity_id.split("_")[-2:]
                            if "_" in entity_id
                            else [entity_id]
                        )
                        entity_display = "_".join(entity_name)
                        changes.append(
                            f"{entity_display}: '{current_value}' → '{expected_value}'"
                        )

                    # Čas zařazení z queue_metadata
                    queued_time = getattr(shield, "queue_metadata", {}).get(
                        (q[0], str(params))
                    )

                    queue_items.append(
                        {
                            "position": i + 1,
                            "service": service_name,
                            "description": f"Změna {service_name.replace('_', ' ')}",
                            "changes": changes,
                            "queued_at": queued_time,
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

                attrs.update(base_attrs)

        except Exception as e:
            _LOGGER.error(f"Error getting shield attributes: {e}")
            attrs["error"] = str(e)

        return attrs

    @property
    def unique_id(self) -> str:
        """Jedinečné ID senzoru."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            # Přidáme verzi do unique_id pro vyřešení unit problému
            return f"oig_cloud_shield_{box_id}_{self._sensor_type}_v2"
        return f"oig_cloud_shield_{self._sensor_type}_v2"

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o zařízení - ServiceShield bude v separátním Shield zařízení."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return {
                "identifiers": {(DOMAIN, f"{box_id}_shield")},
                "name": f"ServiceShield {box_id}",
                "manufacturer": "OIG",
                "model": "Shield",
                "via_device": (DOMAIN, box_id),
            }
        return {
            "identifiers": {(DOMAIN, "shield")},
            "name": "ServiceShield",
            "manufacturer": "OIG",
            "model": "Shield",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # ServiceShield senzory jsou dostupné pokud existuje shield objekt
        shield = self.hass.data[DOMAIN].get("shield")
        return shield is not None
