"""Senzory pro bojlerový modul."""

import logging
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from .coordinator import BoilerCoordinator

_LOGGER = logging.getLogger(__name__)


class BoilerSensorBase(CoordinatorEntity[BoilerCoordinator], SensorEntity):
    """Základní třída pro bojlerové senzory."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BoilerCoordinator,
        unique_id_suffix: str,
        name: str,
    ) -> None:
        """Inicializace senzoru."""
        super().__init__(coordinator)
        self._attr_unique_id = f"oig_bojler_{unique_id_suffix}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "oig_bojler")},
            name="OIG Bojler",
            manufacturer="OIG",
            model="Boiler Control",
        )


# ========== TEPLOTNÍ SENZORY ==========


class BoilerUpperZoneTempSensor(BoilerSensorBase):
    """Teplota horní zóny."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-high"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "upper_zone_temp", "Horní zóna teplota")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí teplotu horní zóny."""
        temps = self.coordinator.data.get("temperatures", {})
        return temps.get("upper_zone")


class BoilerLowerZoneTempSensor(BoilerSensorBase):
    """Teplota dolní zóny."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-low"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "lower_zone_temp", "Dolní zóna teplota")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí teplotu dolní zóny."""
        temps = self.coordinator.data.get("temperatures", {})
        return temps.get("lower_zone")


class BoilerAvgTempSensor(BoilerSensorBase):
    """Průměrná teplota bojleru."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "avg_temp", "Průměrná teplota")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí průměrnou teplotu."""
        energy_state = self.coordinator.data.get("energy_state", {})
        return energy_state.get("avg_temp")


# ========== ENERGETICKÉ SENZORY ==========


class BoilerEnergyNeededSensor(BoilerSensorBase):
    """Energie potřebná k cílové teplotě."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "energy_needed", "Energie potřebná")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí energii potřebnou k ohřevu."""
        energy_state = self.coordinator.data.get("energy_state", {})
        return energy_state.get("energy_needed_kwh")


class BoilerTotalEnergySensor(BoilerSensorBase):
    """Celková energie dnes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "total_energy", "Celková energie dnes")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí celkovou energii."""
        tracking = self.coordinator.data.get("energy_tracking", {})
        return tracking.get("total_kwh")


class BoilerFVEEnergySensor(BoilerSensorBase):
    """Energie z FVE dnes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "fve_energy", "Energie z FVE dnes")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí energii z FVE."""
        tracking = self.coordinator.data.get("energy_tracking", {})
        return tracking.get("fve_kwh")


class BoilerGridEnergySensor(BoilerSensorBase):
    """Energie ze sítě dnes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "grid_energy", "Energie ze sítě dnes")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí energii ze sítě."""
        tracking = self.coordinator.data.get("energy_tracking", {})
        return tracking.get("grid_kwh")


class BoilerAltEnergySensor(BoilerSensorBase):
    """Energie z alternativy dnes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "alt_energy", "Energie z alternativy dnes")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí alternativní energii."""
        tracking = self.coordinator.data.get("energy_tracking", {})
        return tracking.get("alt_kwh")


# ========== PLÁNOVACÍ SENZORY ==========


class BoilerCurrentSourceSensor(BoilerSensorBase):
    """Aktuální zdroj energie."""

    _attr_icon = "mdi:power-plug"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "current_source", "Aktuální zdroj")

    @property
    def native_value(self) -> Optional[str]:
        """Vrátí aktuální zdroj."""
        tracking = self.coordinator.data.get("energy_tracking", {})
        source = tracking.get("current_source", "grid")

        # Překlad do češtiny
        source_map = {
            "fve": "FVE",
            "grid": "Síť",
            "alternative": "Alternativa",
        }
        return source_map.get(source, source)


class BoilerRecommendedSourceSensor(BoilerSensorBase):
    """Doporučený zdroj energie."""

    _attr_icon = "mdi:lightbulb-on"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "recommended_source", "Doporučený zdroj")

    @property
    def native_value(self) -> Optional[str]:
        """Vrátí doporučený zdroj."""
        recommended = self.coordinator.data.get("recommended_source")
        if not recommended:
            return None

        source_map = {
            "fve": "FVE",
            "grid": "Síť",
            "alternative": "Alternativa",
        }
        return source_map.get(recommended, recommended)


class BoilerChargingRecommendedSensor(BoilerSensorBase):
    """Je doporučeno ohřívat?"""

    _attr_icon = "mdi:fire-circle"
    _attr_device_class = None

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "charging_recommended", "Ohřev doporučen")

    @property
    def native_value(self) -> str:
        """Vrátí ano/ne."""
        recommended = self.coordinator.data.get("charging_recommended", False)
        return "ano" if recommended else "ne"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributy s detaily aktuálního slotu."""
        current_slot = self.coordinator.data.get("current_slot")
        if not current_slot:
            return {}

        return {
            "start": current_slot.start.isoformat(),
            "end": current_slot.end.isoformat(),
            "consumption_kwh": round(current_slot.avg_consumption_kwh, 3),
            "confidence": round(current_slot.confidence, 2),
            "spot_price": current_slot.spot_price_kwh,
            "overflow_available": current_slot.overflow_available,
        }


class BoilerPlanEstimatedCostSensor(BoilerSensorBase):
    """Odhadovaná cena ohřevu dnes."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CZK"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "estimated_cost", "Odhadovaná cena dnes")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí odhadovanou cenu."""
        plan = self.coordinator.data.get("plan")
        if not plan:
            return None
        return round(plan.estimated_cost_czk, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributy s rozpisem plánu."""
        plan = self.coordinator.data.get("plan")
        if not plan:
            return {}

        return {
            "total_consumption_kwh": round(plan.total_consumption_kwh, 2),
            "fve_kwh": round(plan.fve_kwh, 2),
            "grid_kwh": round(plan.grid_kwh, 2),
            "alt_kwh": round(plan.alt_kwh, 2),
            "created_at": plan.created_at.isoformat(),
            "valid_until": plan.valid_until.isoformat(),
        }


# ========== PROFILE SENSOR ==========


class BoilerProfileConfidenceSensor(BoilerSensorBase):
    """Kvalita profilu."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BoilerCoordinator) -> None:
        """Inicializace."""
        super().__init__(coordinator, "profile_confidence", "Kvalita profilu")

    @property
    def native_value(self) -> Optional[float]:
        """Vrátí průměrnou confidence profilu."""
        profile = self.coordinator.data.get("profile")
        if not profile or not profile.confidence:
            return None

        avg_conf = sum(profile.confidence.values()) / len(profile.confidence)
        return round(avg_conf * 100, 1)  # 0-100%

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atributy profilu."""
        profile = self.coordinator.data.get("profile")
        if not profile:
            return {}

        return {
            "category": profile.category,
            "hours_with_data": len(profile.hourly_avg),
            "total_samples": sum(profile.sample_count.values()),
            "last_updated": (
                profile.last_updated.isoformat() if profile.last_updated else None
            ),
        }


# ========== REGISTRACE SENZORŮ ==========


def get_boiler_sensors(coordinator: BoilerCoordinator) -> list[SensorEntity]:
    """Vrátí všechny bojlerové senzory."""
    return [
        # Teploty
        BoilerUpperZoneTempSensor(coordinator),
        BoilerLowerZoneTempSensor(coordinator),
        BoilerAvgTempSensor(coordinator),
        # Energie
        BoilerEnergyNeededSensor(coordinator),
        BoilerTotalEnergySensor(coordinator),
        BoilerFVEEnergySensor(coordinator),
        BoilerGridEnergySensor(coordinator),
        BoilerAltEnergySensor(coordinator),
        # Plánování
        BoilerCurrentSourceSensor(coordinator),
        BoilerRecommendedSourceSensor(coordinator),
        BoilerChargingRecommendedSensor(coordinator),
        BoilerPlanEstimatedCostSensor(coordinator),
        # Diagnostika
        BoilerProfileConfidenceSensor(coordinator),
    ]
