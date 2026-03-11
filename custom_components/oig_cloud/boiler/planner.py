"""Plánovač ohřevu bojleru s optimalizací nákladů."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import BATTERY_SOC_OVERFLOW_THRESHOLD
from .models import BoilerPlan, BoilerProfile, BoilerSlot, EnergySource

_LOGGER = logging.getLogger(__name__)


class BoilerPlanner:
    """Plánovač ohřevu s optimalizací nákladů."""

    def __init__(
        self,
        hass: HomeAssistant,
        slot_minutes: int = 15,
        alt_cost_kwh: float = 0.0,
        has_alternative: bool = False,
    ) -> None:
        """
        Inicializace plánovače.

        Args:
            hass: Home Assistant instance
            slot_minutes: Délka slotu v minutách (15)
            alt_cost_kwh: Cena alternativního zdroje [Kč/kWh]
            has_alternative: Je k dispozici alternativní zdroj?
        """
        self.hass = hass
        self.slot_minutes = slot_minutes
        self.alt_cost_kwh = alt_cost_kwh
        self.has_alternative = has_alternative

    async def async_create_plan(
        self,
        profile: BoilerProfile,
        spot_prices: dict[datetime, float],
        overflow_windows: list[tuple[datetime, datetime]],
        deadline_time: str = "06:00",
    ) -> BoilerPlan:
        """
        Vytvoří plán na 24 hodin s optimalizací nákladů.

        Args:
            profile: Profil spotřeby
            spot_prices: Spotové ceny {datetime: Kč/kWh}
            overflow_windows: FVE overflow okna [(start, end), ...]
            deadline_time: Čas do kdy má být ohřev hotový (HH:MM)

        Returns:
            BoilerPlan s doporučenými zdroji
        """
        _ = deadline_time
        now = dt_util.now()
        plan_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        plan_end = plan_start + timedelta(days=1)

        plan = BoilerPlan(
            created_at=now,
            valid_until=plan_end,
            slots=[],
        )

        # Generovat sloty po 15 minutách
        current_time = plan_start
        while current_time < plan_end:
            slot_end = current_time + timedelta(minutes=self.slot_minutes)

            # Průměrná spotřeba za hodinu z profilu
            hour = current_time.hour
            hourly_consumption, confidence = profile.get_consumption(hour)

            # Přepočítat na 15min slot
            slot_consumption = hourly_consumption * (self.slot_minutes / 60.0)

            # Kontrola FVE overflow
            overflow_available = self._is_in_overflow_window(
                current_time, slot_end, overflow_windows
            )

            # Spotová cena (interpolace pokud chybí)
            spot_price = self._get_spot_price(current_time, spot_prices)

            # Doporučený zdroj (priorita: FVE → Grid → Alt)
            recommended_source = self._recommend_source(
                overflow_available=overflow_available,
                spot_price=spot_price,
                alt_price=self.alt_cost_kwh,
            )

            slot = BoilerSlot(
                start=current_time,
                end=slot_end,
                avg_consumption_kwh=slot_consumption,
                confidence=confidence,
                recommended_source=recommended_source,
                spot_price_kwh=spot_price,
                alt_price_kwh=self.alt_cost_kwh if self.has_alternative else None,
                overflow_available=overflow_available,
            )

            plan.slots.append(slot)
            current_time = slot_end

        # Vypočítat agregované hodnoty
        self._calculate_plan_totals(plan)

        _LOGGER.info(
            "Plán vytvořen: %s slotů, %.2f kWh celkem, %.2f Kč odhadovaná cena",
            len(plan.slots),
            plan.total_consumption_kwh,
            plan.estimated_cost_czk,
        )

        return plan

    def _is_in_overflow_window(
        self,
        start: datetime,
        end: datetime,
        overflow_windows: list[tuple[datetime, datetime]],
    ) -> bool:
        """Kontrola, zda je slot v overflow okně."""
        for window_start, window_end in overflow_windows:
            # Překryv: slot začíná před koncem okna a končí po začátku okna
            if start < window_end and end > window_start:
                return True
        return False

    def _get_spot_price(
        self,
        time: datetime,
        spot_prices: dict[datetime, float],
    ) -> Optional[float]:
        """
        Získá spotovou cenu pro daný čas (s interpolací).

        Args:
            time: Časový okamžik
            spot_prices: Dostupné ceny {datetime: Kč/kWh}

        Returns:
            Cena nebo None
        """
        # Přímý match
        if time in spot_prices:
            return spot_prices[time]

        # Interpolace - najít nejbližší záznam
        hour_start = time.replace(minute=0, second=0, microsecond=0)
        if hour_start in spot_prices:
            return spot_prices[hour_start]

        # Fallback - průměr za den
        if spot_prices:
            return sum(spot_prices.values()) / len(spot_prices)

        return None

    def _recommend_source(
        self,
        overflow_available: bool,
        spot_price: Optional[float],
        alt_price: float,
    ) -> EnergySource:
        """
        Doporučí zdroj podle priority a ceny.

        Priorita:
        1. FVE overflow (zdarma) - pokud dostupné
        2. Grid vs Alternative - podle ceny

        Args:
            overflow_available: Je FVE overflow k dispozici?
            spot_price: Spotová cena ze sítě [Kč/kWh]
            alt_price: Cena alternativního zdroje [Kč/kWh]

        Returns:
            Doporučený zdroj
        """
        # Priorita 1: FVE overflow (0 Kč)
        if overflow_available:
            return EnergySource.FVE

        # Priorita 2: Porovnat Grid vs Alternative
        if not self.has_alternative:
            return EnergySource.GRID

        if spot_price is None:
            # Bez spotové ceny - použít alternativu pokud dostupná
            return EnergySource.ALTERNATIVE if alt_price > 0 else EnergySource.GRID

        # Porovnat ceny
        if alt_price > 0 and alt_price < spot_price:
            return EnergySource.ALTERNATIVE

        return EnergySource.GRID

    def _calculate_plan_totals(self, plan: BoilerPlan) -> None:
        """
        Vypočítá agregované hodnoty plánu.

        Args:
            plan: Plán k aktualizaci (in-place)
        """
        total_consumption = 0.0
        total_cost = 0.0
        fve_kwh = 0.0
        grid_kwh = 0.0
        alt_kwh = 0.0

        for slot in plan.slots:
            consumption = slot.avg_consumption_kwh
            total_consumption += consumption

            if slot.recommended_source == EnergySource.FVE:
                fve_kwh += consumption
                # FVE je zdarma
            elif slot.recommended_source == EnergySource.GRID:
                grid_kwh += consumption
                if slot.spot_price_kwh is not None:
                    total_cost += consumption * slot.spot_price_kwh
            elif slot.recommended_source == EnergySource.ALTERNATIVE:
                alt_kwh += consumption
                if slot.alt_price_kwh is not None:
                    total_cost += consumption * slot.alt_price_kwh

        plan.total_consumption_kwh = total_consumption
        plan.estimated_cost_czk = total_cost
        plan.fve_kwh = fve_kwh
        plan.grid_kwh = grid_kwh
        plan.alt_kwh = alt_kwh

    async def async_get_overflow_windows(
        self,
        battery_forecast_data: Optional[dict],
    ) -> list[tuple[datetime, datetime]]:
        """
        Extrahuje overflow okna z battery_forecast.

        Args:
            battery_forecast_data: Data z battery_forecast coordinatoru

        Returns:
            List [(start, end)] datetime dvojic
        """
        if not battery_forecast_data:
            _LOGGER.debug("Battery forecast data nejsou dostupná")
            return []

        overflow_windows = battery_forecast_data.get("overflow_windows", [])

        # Filtrovat okna s SOC >= 100%
        filtered_windows = []
        for window in overflow_windows:
            soc = window.get("soc", 0.0)
            if soc >= BATTERY_SOC_OVERFLOW_THRESHOLD:
                start = window.get("start")
                end = window.get("end")

                if start and end:
                    # Konverze na datetime pokud string
                    if isinstance(start, str):
                        start = dt_util.parse_datetime(start)
                    if isinstance(end, str):
                        end = dt_util.parse_datetime(end)

                    if start and end:
                        filtered_windows.append((start, end))

        _LOGGER.debug("Nalezeno %s overflow oken (SOC >= 100%%)", len(filtered_windows))
        return filtered_windows
