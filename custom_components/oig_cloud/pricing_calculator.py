"""Kalkulator cen elektřiny pro různé tarify a spotové obchodování."""

import logging
from datetime import datetime, time
from typing import Dict, Any, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


class PricingCalculator:
    """Kalkulator pro výpočet cen elektřiny."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Inicializace kalkulátoru s konfigurací."""
        self.config = config
        self.spot_trading_enabled = config.get("spot_trading_enabled", False)
        self.tariff_type = config.get("tariff_type", "dual")
        self.distribution_area = config.get("distribution_area", "PRE")

    def calculate_buy_price(
        self,
        spot_price_czk_kwh: Optional[float] = None,
        current_time: Optional[datetime] = None,
    ) -> float:
        """
        Výpočet nákupní ceny elektřiny.

        Args:
            spot_price_czk_kwh: Spotová cena v CZK/kWh
            current_time: Aktuální čas pro určení tarifu

        Returns:
            Celková nákupní cena v CZK/kWh včetně všech poplatků
        """
        if self.spot_trading_enabled and spot_price_czk_kwh is not None:
            return self._calculate_spot_buy_price(spot_price_czk_kwh)
        else:
            return self._calculate_fixed_buy_price(current_time)

    def calculate_sell_price(self, spot_price_czk_kwh: Optional[float] = None) -> float:
        """
        Výpočet prodejní ceny elektřiny.

        Args:
            spot_price_czk_kwh: Spotová cena v CZK/kWh

        Returns:
            Celková prodejní cena v CZK/kWh po odečtení poplatků
        """
        if self.spot_trading_enabled and spot_price_czk_kwh is not None:
            return self._calculate_spot_sell_price(spot_price_czk_kwh)
        else:
            # Bez spot obchodování obvykle žádný výkup
            return 0.0

    def _calculate_spot_buy_price(self, spot_price: float) -> float:
        """Výpočet spotové nákupní ceny."""
        # Základní spotová cena
        base_price = spot_price

        # Aplikace procentního poplatku podle znaménka ceny
        if spot_price >= 0:
            percent_multiplier = (
                self.config.get("spot_buy_percent_positive", 110.0) / 100.0
            )
        else:
            percent_multiplier = (
                self.config.get("spot_buy_percent_negative", 90.0) / 100.0
            )

        # Aplikace procentního poplatku
        price_with_percent = base_price * percent_multiplier

        # Přidání fixního poplatku
        fixed_fee = self.config.get("spot_buy_fixed_fee", 0.0)

        if self.config.get("spot_buy_combined_enabled", False):
            # Kombinovaný režim - oboje se aplikuje
            final_commodity_price = price_with_percent + fixed_fee
        else:
            # Buď procenta nebo fixní poplatek
            if fixed_fee > 0:
                final_commodity_price = base_price + fixed_fee
            else:
                final_commodity_price = price_with_percent

        # Přidání distribučních poplatků a daní
        distribution_costs = self._calculate_distribution_costs("buy")

        total_price = final_commodity_price + distribution_costs

        _LOGGER.debug(
            f"Spot buy price calculation: base={spot_price:.4f}, "
            f"commodity={final_commodity_price:.4f}, distribution={distribution_costs:.4f}, "
            f"total={total_price:.4f} CZK/kWh"
        )

        return max(0.0, total_price)

    def _calculate_spot_sell_price(self, spot_price: float) -> float:
        """Výpočet spotové prodejní ceny."""
        # Základní spotová cena
        base_price = spot_price

        # Aplikace procentního poplatku podle znaménka ceny
        if spot_price >= 0:
            percent_multiplier = (
                self.config.get("spot_sell_percent_positive", 85.0) / 100.0
            )
        else:
            percent_multiplier = (
                self.config.get("spot_sell_percent_negative", 100.0) / 100.0
            )

        # Aplikace procentního poplatku
        price_with_percent = base_price * percent_multiplier

        # Odečtení fixního poplatku
        fixed_fee = self.config.get("spot_sell_fixed_fee", 0.0)

        if self.config.get("spot_sell_combined_enabled", False):
            # Kombinovaný režim - oboje se aplikuje
            final_price = price_with_percent - fixed_fee
        else:
            # Buď procenta nebo fixní poplatek
            if fixed_fee > 0:
                final_price = base_price - fixed_fee
            else:
                final_price = price_with_percent

        _LOGGER.debug(
            f"Spot sell price calculation: base={spot_price:.4f}, "
            f"final={final_price:.4f} CZK/kWh"
        )

        return max(0.0, final_price)

    def _calculate_fixed_buy_price(
        self, current_time: Optional[datetime] = None
    ) -> float:
        """Výpočet fixní nákupní ceny."""
        if current_time is None:
            current_time = datetime.now()

        if self.tariff_type == "single":
            # Jednotný tarif
            commodity_price = self.config.get("fixed_price_single", 4.0)
        else:
            # Duální tarif - určení VT/NT
            is_high_tariff = self._is_high_tariff_time(current_time)
            if is_high_tariff:
                commodity_price = self.config.get("fixed_price_vt", 4.5)
            else:
                commodity_price = self.config.get("fixed_price_nt", 3.2)

        # Přidání distribučních poplatků
        distribution_costs = self._calculate_distribution_costs("buy")

        total_price = commodity_price + distribution_costs

        _LOGGER.debug(
            f"Fixed buy price calculation: commodity={commodity_price:.4f}, "
            f"distribution={distribution_costs:.4f}, total={total_price:.4f} CZK/kWh"
        )

        return total_price

    def _calculate_distribution_costs(self, operation: str) -> float:
        """Výpočet distribučních nákladů."""
        # Distribuční poplatek za kWh
        distribution_rate = self.config.get(
            "distribution_rate_vt", 0.85
        )  # Zjednodušeno - použijeme VT

        # Ostatní poplatky
        system_services = self.config.get("system_services_fee", 0.50)
        renewable_fee = self.config.get("renewable_fee", 0.10)
        electricity_tax = self.config.get("electricity_tax", 0.298)
        ote_fee = self.config.get("ote_fee", 0.004)

        total_distribution = (
            distribution_rate
            + system_services
            + renewable_fee
            + electricity_tax
            + ote_fee
        )

        # Pro prodej se distribuční náklady neplatí
        if operation == "sell":
            return 0.0

        return total_distribution

    def _is_high_tariff_time(self, dt: datetime) -> bool:
        """Určení, zda je aktuálně vysoký tarif (VT)."""
        # Zjednodušená logika VT/NT
        # VT: pondělí-pátek 6:00-22:00, kromě státních svátků
        # NT: ostatní časy

        weekday = dt.weekday()  # 0 = pondělí, 6 = neděle
        hour = dt.hour

        # Víkend = NT
        if weekday >= 5:  # sobota, neděle
            return False

        # Pracovní den 6:00-22:00 = VT
        if 6 <= hour < 22:
            return True

        # Ostatní časy = NT
        return False

    def get_monthly_fixed_costs(self) -> float:
        """Výpočet měsíčních fixních nákladů."""
        monthly_fee = self.config.get("distribution_monthly_fee", 89.0)
        breaker_fee = self.config.get("distribution_breaker_fee", 44.9)

        return monthly_fee + breaker_fee

    def get_pricing_info(self) -> Dict[str, Any]:
        """Získání informací o aktuálním nastavení cen."""
        return {
            "spot_trading_enabled": self.spot_trading_enabled,
            "tariff_type": self.tariff_type,
            "distribution_area": self.distribution_area,
            "monthly_fixed_costs": self.get_monthly_fixed_costs(),
            "spot_buy_config": {
                "fixed_fee": self.config.get("spot_buy_fixed_fee", 0.0),
                "percent_positive": self.config.get("spot_buy_percent_positive", 110.0),
                "percent_negative": self.config.get("spot_buy_percent_negative", 90.0),
                "combined_enabled": self.config.get("spot_buy_combined_enabled", False),
            },
            "spot_sell_config": {
                "fixed_fee": self.config.get("spot_sell_fixed_fee", 0.0),
                "percent_positive": self.config.get("spot_sell_percent_positive", 85.0),
                "percent_negative": self.config.get(
                    "spot_sell_percent_negative", 100.0
                ),
                "combined_enabled": self.config.get(
                    "spot_sell_combined_enabled", False
                ),
            },
            "distribution_costs_breakdown": {
                "distribution_rate": self.config.get("distribution_rate_vt", 0.85),
                "system_services": self.config.get("system_services_fee", 0.50),
                "renewable_fee": self.config.get("renewable_fee", 0.10),
                "electricity_tax": self.config.get("electricity_tax", 0.298),
                "ote_fee": self.config.get("ote_fee", 0.004),
            },
        }

    def calculate_savings_potential(
        self, hourly_spot_prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """Výpočet potenciálních úspor při přechodu na spot."""
        if not hourly_spot_prices:
            return {}

        # Simulace nákladů pro fixní vs. spotový tarif
        fixed_costs = []
        spot_costs = []

        for time_str, spot_price in hourly_spot_prices.items():
            try:
                hour_time = datetime.fromisoformat(
                    time_str.replace("T", " ").replace("Z", "")
                )

                # Fixní tarif
                fixed_price = self._calculate_fixed_buy_price(hour_time)
                fixed_costs.append(fixed_price)

                # Spotový tarif
                spot_price_total = self._calculate_spot_buy_price(spot_price)
                spot_costs.append(spot_price_total)

            except Exception:
                continue

        if not fixed_costs or not spot_costs:
            return {}

        avg_fixed = sum(fixed_costs) / len(fixed_costs)
        avg_spot = sum(spot_costs) / len(spot_costs)

        savings_czk_kwh = avg_fixed - avg_spot
        savings_percent = (savings_czk_kwh / avg_fixed) * 100 if avg_fixed > 0 else 0

        return {
            "average_fixed_price": round(avg_fixed, 4),
            "average_spot_price": round(avg_spot, 4),
            "savings_czk_kwh": round(savings_czk_kwh, 4),
            "savings_percent": round(savings_percent, 2),
            "recommendation": "spot" if savings_czk_kwh > 0 else "fixed",
        }

    def get_optimized_attributes(self) -> Dict[str, Any]:
        """Získání optimalizovaných atributů - menší velikost pro databázi."""
        return {
            "spot_enabled": self.spot_trading_enabled,
            "tariff": self.tariff_type,
            "area": self.distribution_area,
            "monthly_costs": round(self.get_monthly_fixed_costs(), 2),
            "distribution_vt": self.config.get("distribution_rate_vt", 0.85),
            "distribution_nt": self.config.get("distribution_rate_nt", 0.42),
            "data_source": "spotovaelektrina.cz",
            "price_units": "CZK/kWh",  # Dokumentace jednotekk
            "conversion_note": "API data: halíře/MWh -> CZK/kWh (÷1000)",
        }
