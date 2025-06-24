"""Senzory pro výpočet cen elektřiny podle různých tarifů."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.dt import now as dt_now

from .oig_cloud_sensor import OigCloudSensor
from .pricing_calculator import PricingCalculator
from .sensors.SENSOR_TYPES_PRICING import SENSOR_TYPES_PRICING

_LOGGER = logging.getLogger(__name__)


class PricingSensor(OigCloudSensor, RestoreEntity):
    """Senzor pro výpočet cen elektřiny."""

    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__(coordinator, sensor_type)

        self._sensor_type = sensor_type
        self._sensor_config = SENSOR_TYPES_PRICING.get(sensor_type, {})

        # Načteme konfiguraci z config_entry
        self._load_pricing_config()

        # Vytvoříme kalkulator
        self._calculator = PricingCalculator(self._pricing_config)

    def _load_pricing_config(self) -> None:
        """Načtení cenové konfigurace z config_entry."""
        # Pro začátek použijeme základní konfiguraci
        # Později bude načítána z config_entry.options
        self._pricing_config = {
            "spot_trading_enabled": False,
            "tariff_type": "dual",
            "distribution_area": "PRE",
            "fixed_price_vt": 4.50,
            "fixed_price_nt": 3.20,
            "fixed_price_single": 4.00,
            "distribution_rate_vt": 0.85,
            "distribution_rate_nt": 0.42,
            "system_services_fee": 0.50,
            "renewable_fee": 0.10,
            "electricity_tax": 0.298,
            "ote_fee": 0.004,
            "distribution_monthly_fee": 89.0,
            "distribution_breaker_fee": 44.9,
        }

    @property
    def name(self) -> str:
        """Jméno senzoru."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return f"OIG {box_id} {self._sensor_config.get('name', self._sensor_type)}"
        return f"OIG {self._sensor_config.get('name', self._sensor_type)}"

    @property
    def icon(self) -> str:
        """Ikona senzoru."""
        return self._sensor_config.get("icon", "mdi:currency-eur")

    @property
    def unit_of_measurement(self) -> Optional[str]:
        """Jednotka měření."""
        return self._sensor_config.get("unit_of_measurement")

    @property
    def device_class(self) -> Optional[str]:
        """Třída zařízení."""
        return self._sensor_config.get("device_class")

    @property
    def state_class(self) -> Optional[str]:
        """Třída stavu."""
        return self._sensor_config.get("state_class")

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Hlavní stav senzoru."""
        try:
            now = dt_now()

            # Pokud máme spotové senzory, získáme aktuální spotovou cenu
            spot_price = self._get_current_spot_price()

            if self._sensor_type == "electricity_buy_price_current":
                return self._calculator.calculate_buy_price(spot_price, now)
            elif self._sensor_type == "electricity_sell_price_current":
                return self._calculator.calculate_sell_price(spot_price)
            elif self._sensor_type == "electricity_monthly_fixed_costs":
                return self._calculator.get_monthly_fixed_costs()
            elif self._sensor_type == "electricity_tariff_type":
                return self._get_current_tariff_type(now)

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error calculating price: {e}")
            return None

        return None

    def _get_current_spot_price(self) -> Optional[float]:
        """Získání aktuální spotové ceny z jiných senzorů."""
        try:
            # Pokusíme se najít spotový senzor v HA registry
            if self.hass and self.coordinator.data:
                box_id = list(self.coordinator.data.keys())[0]
                spot_sensor_id = f"sensor.oig_{box_id}_spot_price_current_czk_kwh"

                # Získat stav senzoru z Home Assistant
                spot_state = self.hass.states.get(spot_sensor_id)
                if spot_state and spot_state.state not in ["unknown", "unavailable"]:
                    return float(spot_state.state)

            return None
        except Exception:
            return None

    def _get_current_tariff_type(self, current_time: datetime) -> str:
        """Určení aktuálního typu tarifu."""
        if self._pricing_config.get("tariff_type") == "single":
            return "Jednotný"
        else:
            is_high_tariff = self._calculator._is_high_tariff_time(current_time)
            return "VT" if is_high_tariff else "NT"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatečné atributy senzoru - optimalizované pro velikost."""
        attrs = {}

        now = dt_now()
        spot_price = self._get_current_spot_price()

        if self._sensor_type == "electricity_buy_price_current":
            attrs.update(
                {
                    "commodity_price": round(
                        self._get_commodity_price("buy", spot_price, now), 4
                    ),
                    "distribution_costs": round(
                        self._calculator._calculate_distribution_costs("buy"), 4
                    ),
                    "tariff_type": self._get_current_tariff_type(now),
                    "spot_enabled": self._pricing_config.get(
                        "spot_trading_enabled", False
                    ),
                    "spot_price": spot_price,
                }
            )

        elif self._sensor_type == "electricity_sell_price_current":
            attrs.update(
                {
                    "commodity_price": round(
                        self._get_commodity_price("sell", spot_price, now), 4
                    ),
                    "spot_enabled": self._pricing_config.get(
                        "spot_trading_enabled", False
                    ),
                    "spot_price": spot_price,
                }
            )

        elif self._sensor_type == "electricity_monthly_fixed_costs":
            attrs.update(
                {
                    "monthly_fee": self._pricing_config.get(
                        "distribution_monthly_fee", 89.0
                    ),
                    "breaker_fee": self._pricing_config.get(
                        "distribution_breaker_fee", 44.9
                    ),
                    "area": self._pricing_config.get("distribution_area", "PRE"),
                }
            )

        elif self._sensor_type == "electricity_tariff_type":
            attrs.update(
                {
                    "system": self._pricing_config.get("tariff_type", "dual"),
                    "hour": now.hour,
                    "weekend": now.weekday() >= 5,
                }
            )

        # Pouze základní info - optimalizace velikosti
        attrs.update(self._calculator.get_optimized_attributes())

        return attrs

    def _get_commodity_price(
        self, operation: str, spot_price: Optional[float], current_time: datetime
    ) -> float:
        """Získání pouze komoditní ceny bez distribuce."""
        if (
            self._pricing_config.get("spot_trading_enabled", False)
            and spot_price is not None
        ):
            if operation == "buy":
                return self._calculator._calculate_spot_buy_price(
                    spot_price
                ) - self._calculator._calculate_distribution_costs("buy")
            else:
                return self._calculator._calculate_spot_sell_price(spot_price)
        else:
            # Fixní tarif
            if operation == "sell":
                return 0.0

            if self._pricing_config.get("tariff_type") == "single":
                return self._pricing_config.get("fixed_price_single", 4.0)
            else:
                is_high_tariff = self._calculator._is_high_tariff_time(current_time)
                if is_high_tariff:
                    return self._pricing_config.get("fixed_price_vt", 4.5)
                else:
                    return self._pricing_config.get("fixed_price_nt", 3.2)

    @property
    def unique_id(self) -> str:
        """Jedinečné ID senzoru."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return f"{box_id}_{self._sensor_type}"
        return f"pricing_{self._sensor_type}"

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informace o zařízení."""
        if self.coordinator.data:
            box_id = list(self.coordinator.data.keys())[0]
            return {
                "identifiers": {("oig_cloud", f"{box_id}_statistics")},
                "name": f"OIG {box_id} Statistics",
                "manufacturer": "OIG",
                "model": "Analytics & Predictions",
                "via_device": ("oig_cloud", box_id),
            }
        return {
            "identifiers": {("oig_cloud", "statistics")},
            "name": "OIG Statistics",
            "manufacturer": "OIG",
            "model": "Analytics & Predictions",
        }

    @property
    def should_poll(self) -> bool:
        """Nepoužívat polling."""
        return False

    async def async_update(self) -> None:
        """Update senzoru."""
        self.async_write_ha_state()
