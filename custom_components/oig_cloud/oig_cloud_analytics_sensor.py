"""Analytics senzor pro spotové ceny a další analytické funkce."""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .oig_cloud_coordinator import OigCloudCoordinator

_LOGGER = logging.getLogger(__name__)


class OigCloudAnalyticsSensor(CoordinatorEntity[OigCloudCoordinator], SensorEntity):
    """Analytics senzor pro spotové ceny a analytické funkce."""

    def __init__(
        self,
        coordinator: OigCloudCoordinator,
        sensor_type: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the analytics sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._entry = entry

        # Získáme konfiguraci senzoru z SENSOR_TYPES_SPOT
        from .sensors.SENSOR_TYPES_SPOT import SENSOR_TYPES_SPOT

        self._sensor_config = SENSOR_TYPES_SPOT.get(sensor_type, {})

        # KLÍČOVÁ OPRAVA: Používat stejnou logiku jako OigCloudDataSensor!
        # Nejdřív získáme inverter_sn pro unique_id
        if coordinator.data:
            inverter_sn = list(coordinator.data.keys())[0]
            self._attr_unique_id = f"oig_{inverter_sn}_{sensor_type}"
        else:
            self._attr_unique_id = f"oig_{sensor_type}"

        # OPRAVA: Český název přímo z konfigurace
        self._friendly_name = self._sensor_config.get("name", sensor_type)

        self._attr_icon = self._sensor_config.get("icon", "mdi:currency-eur")
        self._attr_unit_of_measurement = self._sensor_config.get("unit_of_measurement")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")

        # Device info pro Analytics module - stejná logika jako u ostatních
        inverter_sn = "unknown"
        if coordinator.data:
            inverter_sn = list(coordinator.data.keys())[0]

        self._attr_device_info = {
            "identifiers": {("oig_cloud_analytics", inverter_sn)},
            "name": f"Analytics & Predictions {inverter_sn}",
            "manufacturer": "OIG",
            "model": "Analytics Module",
            "via_device": ("oig_cloud", inverter_sn),
            "entry_type": "service",
        }

    @property
    def name(self) -> str:
        """Return the friendly name of the sensor."""
        return self._friendly_name

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # OPRAVA: Načíst spotové ceny z coordinator.data místo ote_api.spot_data
        if self.coordinator.data and "spot_prices" in self.coordinator.data:
            spot_data = self.coordinator.data["spot_prices"]
            return self._get_spot_price_value(spot_data)

        return None

    def _get_spot_price_value(self, spot_data: Dict[str, Any]) -> Optional[float]:
        """Získat hodnotu podle typu spotového senzoru s finálním přepočtem."""
        if not spot_data:
            return None

        # Načíst konfiguraci cenového modelu
        pricing_model = self._entry.options.get("spot_pricing_model", "percentage")
        positive_fee_percent = self._entry.options.get(
            "spot_positive_fee_percent", 15.0
        )
        negative_fee_percent = self._entry.options.get("spot_negative_fee_percent", 9.0)
        fixed_fee_mwh = self._entry.options.get("spot_fixed_fee_mwh", 500.0)
        distribution_fee_kwh = self._entry.options.get("distribution_fee_kwh", 1.2)

        def calculate_final_price(spot_price_czk: float) -> float:
            """Vypočítat finální cenu včetně obchodních a distribučních poplatků."""
            if pricing_model == "percentage":
                if spot_price_czk >= 0:
                    commercial_price = spot_price_czk * (
                        1 + positive_fee_percent / 100.0
                    )
                else:
                    commercial_price = spot_price_czk * (
                        1 - negative_fee_percent / 100.0
                    )
            else:  # fixed
                fixed_fee_kwh = fixed_fee_mwh / 1000.0  # MWh -> kWh
                commercial_price = spot_price_czk + fixed_fee_kwh

            return commercial_price + distribution_fee_kwh

        # OPRAVA: Přizpůsobit klíče podle struktury OTE API dat s finálním přepočtem
        if self._sensor_type == "spot_price_current_czk_kwh":
            from datetime import datetime

            now = datetime.now()
            current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
            prices_czk = spot_data.get("prices_czk_kwh", {})
            spot_price = prices_czk.get(current_hour_key)
            return calculate_final_price(spot_price) if spot_price is not None else None

        elif self._sensor_type == "spot_price_current_eur_mwh":
            # EUR/MWh ponechat hrubé (referenční ceny)
            from datetime import datetime

            now = datetime.now()
            current_hour_key = f"{now.strftime('%Y-%m-%d')}T{now.hour:02d}:00:00"
            prices_eur = spot_data.get("prices_eur_mwh", {})
            return prices_eur.get(current_hour_key)

        elif self._sensor_type == "spot_price_today_avg":
            today_stats = spot_data.get("today_stats", {})
            spot_avg = today_stats.get("avg_czk")
            return calculate_final_price(spot_avg) if spot_avg is not None else None

        elif self._sensor_type == "spot_price_today_min":
            today_stats = spot_data.get("today_stats", {})
            spot_min = today_stats.get("min_czk")
            return calculate_final_price(spot_min) if spot_min is not None else None

        elif self._sensor_type == "spot_price_today_max":
            today_stats = spot_data.get("today_stats", {})
            spot_max = today_stats.get("max_czk")
            return calculate_final_price(spot_max) if spot_max is not None else None

        elif self._sensor_type == "spot_price_tomorrow_avg":
            tomorrow_stats = spot_data.get("tomorrow_stats")
            if tomorrow_stats:
                spot_avg = tomorrow_stats.get("avg_czk")
                return calculate_final_price(spot_avg) if spot_avg is not None else None
            return None

        elif self._sensor_type == "eur_czk_exchange_rate":
            return spot_data.get("eur_czk_rate")

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        attrs = {}

        if self.coordinator.data and "spot_prices" in self.coordinator.data:
            spot_data = self.coordinator.data["spot_prices"]
            if spot_data and self._sensor_type == "spot_price_hourly_all":
                attrs["hourly_prices_czk"] = spot_data.get("prices_czk_kwh", {})
                attrs["hours_count"] = spot_data.get("hours_count", 0)
                attrs["date_range"] = spot_data.get("date_range", {})

            # Přidat informace o použité konfiguraci pro všechny CZK senzory
            if (
                "czk" in self._sensor_type
                and self._sensor_type != "eur_czk_exchange_rate"
            ):
                pricing_model = self._entry.options.get(
                    "spot_pricing_model", "percentage"
                )
                attrs["pricing_model"] = (
                    "Procentní model"
                    if pricing_model == "percentage"
                    else "Fixní poplatek"
                )
                attrs["distribution_fee_kwh"] = self._entry.options.get(
                    "distribution_fee_kwh", 1.2
                )

                if pricing_model == "percentage":
                    attrs["positive_fee_percent"] = self._entry.options.get(
                        "spot_positive_fee_percent", 15.0
                    )
                    attrs["negative_fee_percent"] = self._entry.options.get(
                        "spot_negative_fee_percent", 9.0
                    )
                else:
                    attrs["fixed_fee_mwh"] = self._entry.options.get(
                        "spot_fixed_fee_mwh", 500.0
                    )
                    attrs["fixed_fee_kwh"] = (
                        self._entry.options.get("spot_fixed_fee_mwh", 500.0) / 1000.0
                    )

        # NOVÉ: Přidat friendly_name jako atribut pro správné zobrazení
        attrs["friendly_name"] = self._friendly_name

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def sensor_type(self) -> str:
        """Return sensor type for compatibility."""
        return self._sensor_type
