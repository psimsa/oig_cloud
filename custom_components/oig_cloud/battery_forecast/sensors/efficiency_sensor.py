"""Battery efficiency sensor extracted from legacy battery forecast."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class OigCloudBatteryEfficiencySensor(RestoreEntity, CoordinatorEntity, SensorEntity):
    """
    Battery round-trip efficiency calculator.

    Calculates battery efficiency using existing monthly sensors:
    - sensor.computed_batt_charge_energy_month
    - sensor.computed_batt_discharge_energy_month
    - sensor.remaining_usable_capacity

    State = Last COMPLETE month efficiency (%)
    Attributes = Current month (partial) efficiency and metrics

    Updates:
    - Daily at 23:55: Update current month partial data
    - Monthly on 1st at 00:10: Calculate last month and save to state

    Formula:
    efficiency = (effective_discharge / charge) * 100
    where: effective_discharge = discharge - (battery_end - battery_start)

    NOTE: RestoreEntity není třeba - všechna data jsou v extra_state_attributes
    které HA automaticky ukládá.
    """

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
    ) -> None:
        """Initialize the battery efficiency sensor."""
        CoordinatorEntity.__init__(self, coordinator)

        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)

        # Stabilní box_id resolution (config entry → proxy → coordinator numeric keys)
        try:
            from ...entities.base_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        # Set device info early - type: ignore because DeviceInfo is a TypedDict
        self._attr_device_info = device_info  # type: ignore[assignment]

        # Entity setup
        self._attr_unique_id = f"oig_cloud_{self._box_id}_battery_efficiency"
        self.entity_id = f"sensor.oig_{self._box_id}_battery_efficiency"
        self._attr_icon = "mdi:battery-sync"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Načíst název ze sensor types
        from ...sensors.SENSOR_TYPES_STATISTICS import SENSOR_TYPES_STATISTICS

        sensor_config = SENSOR_TYPES_STATISTICS.get(sensor_type, {})
        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")
        self._attr_name = name_cs or name_en or "Efektivita baterie (měsíc)"

        # State tracking
        self._efficiency_last_month: Optional[float] = None  # State = minulý měsíc
        self._battery_kwh_month_start: Optional[float] = None
        self._current_month_partial: Dict[str, Any] = {}
        self._last_month_data: Dict[str, Any] = {}  # Kompletní data minulého měsíce
        self._loading_history: bool = False  # Flag aby se načítání neopakovalo

        # Initialize extra state attributes
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Při přidání do HA - restore state from attributes."""
        await CoordinatorEntity.async_added_to_hass(self)
        self._hass = self.hass

        # Try to restore from last state (HA automatically stores extra_state_attributes)
        last_state = await self.async_get_last_state()
        if last_state:
            # Restore efficiency minulého měsíce (state)
            try:
                if last_state.state not in ["unknown", "unavailable"]:
                    self._efficiency_last_month = float(last_state.state)
            except (ValueError, TypeError):
                self._efficiency_last_month = None

            # Restore tracking data from attributes
            if last_state.attributes:
                self._battery_kwh_month_start = last_state.attributes.get(
                    "_battery_kwh_month_start"
                )
                self._current_month_partial = last_state.attributes.get(
                    "_current_month_partial", {}
                )
                self._last_month_data = last_state.attributes.get(
                    "_last_month_data", {}
                )
                _LOGGER.info(
                    "🔋 Restored battery efficiency state: "
                    "last_month=%s%%, month_start=%s kWh",
                    self._efficiency_last_month,
                    self._battery_kwh_month_start,
                )

        # Initialize if None
        # Pro první deployment: inicializuj i uprostřed měsíce (data nebudou přesná)
        # Po 1. listopadu to můžeme změnit aby čekalo na začátek měsíce
        now = datetime.now()
        if self._battery_kwh_month_start is None:
            battery_now = self._get_sensor("remaining_usable_capacity") or 0
            self._battery_kwh_month_start = battery_now

            if now.day <= 2:
                _LOGGER.info(
                    "🔋 Battery efficiency sensor initialized (beginning of month): "
                    "month_start=%.2f kWh",
                    battery_now,
                )
            else:
                _LOGGER.warning(
                    "🔋 Battery efficiency sensor initialized mid-month (day %s): "
                    "month_start=%.2f kWh. Current month data will be PARTIAL and may "
                    "be inaccurate. Full accuracy starts from 1st November.",
                    now.day,
                    battery_now,
                )

        # Schedule monthly calculation on 1st day at 00:10
        from homeassistant.helpers.event import async_track_utc_time_change

        # Monthly: 1. den v měsíci v 00:10 UTC
        async_track_utc_time_change(
            self.hass, self._monthly_calculation, hour=0, minute=10, second=0
        )

        # Daily: každý den v 23:55 UTC
        async_track_utc_time_change(
            self.hass, self._daily_update, hour=23, minute=55, second=0
        )

        # Initial update
        await self._daily_update()

    async def async_will_remove_from_hass(self) -> None:
        """Při odebrání z HA."""
        await CoordinatorEntity.async_will_remove_from_hass(self)

    async def _monthly_calculation(self, now: datetime) -> None:
        """
        1. den měsíce - spočítat efficiency MINULÉHO měsíce.

        Vezme data uložená včera večer v _daily_update a uloží jako state.
        """
        # Kontrola zda je to opravdu 1. den
        if now.day != 1:
            return

        _LOGGER.info("🔋 Monthly calculation: Computing last month efficiency")

        # Použít data z včerejška (uložená v _daily_update)
        charge_last_month = self._current_month_partial.get("charge", 0)
        discharge_last_month = self._current_month_partial.get("discharge", 0)
        battery_month_end = self._current_month_partial.get("battery_end", 0)
        battery_month_start = self._current_month_partial.get("battery_start", 0)

        # Snížený limit z 20 na 5 kWh - umožní výpočet i pro částečná data
        if charge_last_month < 5.0 or discharge_last_month < 5.0:
            _LOGGER.warning(
                "🔋 Insufficient data for last month: charge=%.2f, discharge=%.2f",
                charge_last_month,
                discharge_last_month,
            )
            self._efficiency_last_month = None
        else:
            # Výpočet
            delta = battery_month_end - battery_month_start
            effective_discharge = discharge_last_month - delta

            if (
                effective_discharge > 0
                and effective_discharge <= charge_last_month * 1.1
            ):
                efficiency = (effective_discharge / charge_last_month) * 100
                losses_kwh = charge_last_month - effective_discharge
                losses_pct = (losses_kwh / charge_last_month) * 100

                self._efficiency_last_month = round(efficiency, 1)

                # Uložit kompletní data minulého měsíce
                self._last_month_data = {
                    "efficiency_pct": round(efficiency, 1),
                    "losses_kwh": round(losses_kwh, 2),
                    "losses_pct": round(losses_pct, 1),
                    "charge_kwh": round(charge_last_month, 2),
                    "discharge_kwh": round(discharge_last_month, 2),
                    "effective_discharge_kwh": round(effective_discharge, 2),
                    "delta_kwh": round(delta, 2),
                    "battery_start_kwh": round(battery_month_start, 2),
                    "battery_end_kwh": round(battery_month_end, 2),
                }

                _LOGGER.info(
                    "🔋 Last month: efficiency=%s%%, losses=%.2f kWh (%.1f%%), "
                    "charge=%.2f, discharge=%.2f, delta=%.2f",
                    self._efficiency_last_month,
                    losses_kwh,
                    losses_pct,
                    charge_last_month,
                    discharge_last_month,
                    delta,
                )
            else:
                _LOGGER.warning(
                    "🔋 Invalid effective discharge: %.2f kWh", effective_discharge
                )
                self._efficiency_last_month = None

        # Reset pro nový měsíc
        battery_now = self._get_sensor("remaining_usable_capacity") or 0
        self._battery_kwh_month_start = battery_now
        self._current_month_partial = {}

        _LOGGER.info("🔋 New month started with %.2f kWh", battery_now)

        # Update state
        self._attr_native_value = self._efficiency_last_month
        self.async_write_ha_state()

    async def _daily_update(self, now: Optional[datetime] = None) -> None:
        """
        Denně v 23:55 - aktualizovat průběžná data TOHOTO měsíce.
        """
        _LOGGER.debug("🔋 Daily update: Computing current month (partial) efficiency")

        # Pokud nemáme month_start, nemůžeme počítat efektivitu
        if self._battery_kwh_month_start is None:
            _LOGGER.warning(
                "🔋 Cannot compute efficiency - battery_kwh_month_start not initialized. "
                "Waiting for next month to start."
            )
            self._attr_native_value = self._efficiency_last_month
            self._update_extra_state_attributes()
            self.async_write_ha_state()
            return

        # Číst aktuální měsíční data
        charge_month_wh = self._get_sensor("computed_batt_charge_energy_month") or 0
        discharge_month_wh = (
            self._get_sensor("computed_batt_discharge_energy_month") or 0
        )
        battery_now = self._get_sensor("remaining_usable_capacity") or 0

        charge_month = charge_month_wh / 1000
        discharge_month = discharge_month_wh / 1000

        # Uložit snapshot pro monthly calculation
        self._current_month_partial = {
            "charge": round(charge_month, 2),
            "discharge": round(discharge_month, 2),
            "battery_start": round(self._battery_kwh_month_start, 2),
            "battery_end": round(battery_now, 2),
            "timestamp": datetime.now().isoformat(),
        }

        # Vypočítat průběžnou efficiency (jen pro atributy)
        if charge_month >= 1.0 and discharge_month >= 1.0:
            delta = battery_now - self._battery_kwh_month_start
            effective_discharge = discharge_month - delta

            if effective_discharge > 0 and effective_discharge <= charge_month * 1.2:
                efficiency_current = (effective_discharge / charge_month) * 100
                self._current_month_partial["efficiency"] = round(efficiency_current, 1)
                self._current_month_partial["delta"] = round(delta, 2)
                self._current_month_partial["effective_discharge"] = round(
                    effective_discharge, 2
                )

        # Update extra state attributes
        self._update_extra_state_attributes()

        # State: Zobraz minulý měsíc pokud máme, jinak aktuální měsíc (partial)
        if self._efficiency_last_month is not None:
            self._attr_native_value = self._efficiency_last_month
        else:
            # Fallback na current month pokud nemáme last month
            self._attr_native_value = self._current_month_partial.get("efficiency")

        self.async_write_ha_state()

    def _update_extra_state_attributes(self) -> None:
        """Update extra state attributes with current data."""
        now = datetime.now()

        # Pokud nemáme kompletní data za minulý měsíc (chybí kWh hodnoty), zkusit načíst z historie
        # Kontrolujeme charge_kwh protože to je klíčová hodnota pro zobrazení v dashboardu
        # A ZÁROVEŇ kontrolujeme flag aby se načítání neopakovalo
        if (
            not self._last_month_data or not self._last_month_data.get("charge_kwh")
        ) and not self._loading_history:
            # Nastavit flag aby se loading neopakoval
            self._loading_history = True
            # Asynchronně spustit načtení (ale nevyčkávat na výsledek)
            self.hass.async_create_task(self._try_load_last_month_from_history())

        # Průběžná data tohoto měsíce
        current_efficiency = self._current_month_partial.get("efficiency")
        current_charge = self._current_month_partial.get("charge")
        current_discharge = self._current_month_partial.get("discharge")
        current_delta = self._current_month_partial.get("delta")
        current_effective_discharge = self._current_month_partial.get(
            "effective_discharge"
        )

        # Výpočet ztrát pro aktuální měsíc
        current_losses_kwh = None
        current_losses_pct = None
        if current_charge and current_effective_discharge:
            current_losses_kwh = round(current_charge - current_effective_discharge, 2)
            current_losses_pct = round((current_losses_kwh / current_charge) * 100, 1)

        # Výpočet ztrát pro minulý měsíc (z uložených dat nebo z efficiency)
        last_month_losses_kwh = self._last_month_data.get("losses_kwh")
        last_month_losses_pct = self._last_month_data.get("losses_pct")
        if last_month_losses_pct is None and self._efficiency_last_month is not None:
            # Fallback pokud nemáme uložená data (starší verze)
            last_month_losses_pct = round(100 - self._efficiency_last_month, 1)

        # Status podle stavu inicializace
        if self._battery_kwh_month_start is None:
            current_month_status = (
                f"not initialized (day {now.day}) - waiting for next month"
            )
        else:
            current_month_status = f"partial ({now.day} days)"

        self._attr_extra_state_attributes = {
            # Minulý měsíc (kompletní) - to je STATE
            "efficiency_last_month_pct": self._efficiency_last_month,
            "losses_last_month_kwh": last_month_losses_kwh,
            "losses_last_month_pct": last_month_losses_pct,
            "last_month_charge_kwh": self._last_month_data.get("charge_kwh"),
            "last_month_discharge_kwh": self._last_month_data.get("discharge_kwh"),
            "last_month_status": "complete",
            # Tento měsíc (průběžné)
            "efficiency_current_month_pct": current_efficiency,
            "losses_current_month_kwh": current_losses_kwh,
            "losses_current_month_pct": current_losses_pct,
            "current_month_charge_kwh": current_charge,
            "current_month_discharge_kwh": current_discharge,
            "current_month_delta_kwh": current_delta,
            "current_month_days": now.day,
            "current_month_status": current_month_status,
            # Battery tracking
            "battery_kwh_month_start": (
                round(self._battery_kwh_month_start, 2)
                if self._battery_kwh_month_start
                else None
            ),
            "battery_kwh_now": round(
                self._get_sensor("remaining_usable_capacity") or 0, 2
            ),
            # Metadata
            "last_daily_update": self._current_month_partial.get("timestamp"),
            "next_monthly_calculation": "1st day of next month at 00:10",
            "calculation_method": "Energy balance with SoC correction",
            "data_source": "computed_batt_charge/discharge_energy_month",
            "formula": "(discharge - ΔE_battery) / charge * 100",
            "formula_losses": "charge - (discharge - ΔE_battery)",
            # Internal (for restore)
            "_battery_kwh_month_start": self._battery_kwh_month_start,
            "_current_month_partial": self._current_month_partial,
            "_last_month_data": self._last_month_data,
        }

    async def _try_load_last_month_from_history(self) -> None:  # noqa: C901
        """
        Pokus o načtení dat za minulý měsíc z historie HA.
        Použije monthly sensors k vypočtení efficiency za minulý měsíc.
        """
        try:
            from homeassistant.components.recorder.history import get_significant_states
        except ImportError:
            _LOGGER.warning("🔋 Recorder component not available")
            return

        _LOGGER.info("🔋 Attempting to load last month efficiency from history...")

        try:
            # Zjistit datum minulého měsíce
            now = datetime.now()
            if now.month == 1:
                last_month_year = now.year - 1
                last_month = 12
            else:
                last_month_year = now.year
                last_month = now.month - 1

            # Poslední den minulého měsíce v 23:59
            import calendar
            from datetime import timezone

            last_day = calendar.monthrange(last_month_year, last_month)[1]
            end_time = datetime(
                last_month_year, last_month, last_day, 23, 59, 59, tzinfo=timezone.utc
            )

            # První den minulého měsíce v 00:00
            start_time = datetime(
                last_month_year, last_month, 1, 0, 0, 0, tzinfo=timezone.utc
            )

            _LOGGER.debug(
                "🔋 Looking for history between %s and %s", start_time, end_time
            )

            # Načíst historii pro monthly sensors
            charge_sensor = (
                f"sensor.oig_{self._box_id}_computed_batt_charge_energy_month"
            )
            discharge_sensor = (
                f"sensor.oig_{self._box_id}_computed_batt_discharge_energy_month"
            )
            battery_sensor = f"sensor.oig_{self._box_id}_remaining_usable_capacity"

            # Získat stavy na konci měsíce
            history = await self.hass.async_add_executor_job(
                get_significant_states,
                self.hass,
                end_time - timedelta(hours=1),
                end_time,
                [charge_sensor, discharge_sensor, battery_sensor],
            )

            _LOGGER.debug(
                "🔋 History result type: %s, keys: %s",
                type(history),
                history.keys() if history else "None",
            )
            if history:
                for key, values in history.items():
                    _LOGGER.debug("🔋 History[%s]: %s entries", key, len(values))

            if not history:
                _LOGGER.warning(
                    "🔋 No history found for %s/%s", last_month, last_month_year
                )
                return

            # Parse hodnoty
            charge_wh = None
            discharge_wh = None
            battery_end = None

            if charge_sensor in history and history[charge_sensor]:
                for item in reversed(history[charge_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            charge_wh = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            if discharge_sensor in history and history[discharge_sensor]:
                for item in reversed(history[discharge_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            discharge_wh = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            if battery_sensor in history and history[battery_sensor]:
                for item in reversed(history[battery_sensor]):
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            battery_end = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            # Načíst stav baterie na začátku měsíce
            history_start = await self.hass.async_add_executor_job(
                get_significant_states,
                self.hass,
                start_time,
                start_time + timedelta(hours=1),
                [battery_sensor],
            )

            battery_start = None
            if battery_sensor in history_start and history_start[battery_sensor]:
                for item in history_start[battery_sensor]:
                    if isinstance(item, dict):
                        state_value = item.get("state")
                    else:
                        state_value = item.state
                    if state_value not in ["unknown", "unavailable", None]:
                        try:
                            battery_start = float(state_value)
                            break
                        except (ValueError, TypeError):
                            continue

            # Vypočítat efficiency
            if (
                charge_wh
                and discharge_wh
                and battery_start is not None
                and battery_end is not None
            ):
                charge_kwh = charge_wh / 1000
                discharge_kwh = discharge_wh / 1000
                delta_kwh = battery_end - battery_start
                effective_discharge = discharge_kwh - delta_kwh

                if effective_discharge > 0 and charge_kwh > 0:
                    efficiency = (effective_discharge / charge_kwh) * 100
                    losses_kwh = charge_kwh - effective_discharge
                    losses_pct = (losses_kwh / charge_kwh) * 100

                    self._efficiency_last_month = round(efficiency, 1)
                    self._last_month_data = {
                        "efficiency_pct": round(efficiency, 1),
                        "losses_kwh": round(losses_kwh, 2),
                        "losses_pct": round(losses_pct, 1),
                        "charge_kwh": round(charge_kwh, 2),
                        "discharge_kwh": round(discharge_kwh, 2),
                        "effective_discharge_kwh": round(effective_discharge, 2),
                        "delta_kwh": round(delta_kwh, 2),
                        "battery_start_kwh": round(battery_start, 2),
                        "battery_end_kwh": round(battery_end, 2),
                    }

                    _LOGGER.info(
                        "🔋 Loaded %s/%s from history: efficiency=%.1f%%, charge=%.2f kWh, "
                        "discharge=%.2f kWh, delta=%.2f kWh",
                        last_month,
                        last_month_year,
                        efficiency,
                        charge_kwh,
                        discharge_kwh,
                        delta_kwh,
                    )

                    # Uložit state do HA aby přežil restart
                    self._update_extra_state_attributes()
                    self.async_write_ha_state()
                    _LOGGER.info("🔋 Last month data saved to state storage")
                else:
                    _LOGGER.warning(
                        "🔋 Invalid data for %s/%s: effective_discharge=%.2f, charge=%.2f",
                        last_month,
                        last_month_year,
                        effective_discharge,
                        charge_kwh,
                    )
            else:
                _LOGGER.warning(
                    "🔋 Incomplete data for %s/%s: charge=%s, discharge=%s, "
                    "battery_start=%s, battery_end=%s",
                    last_month,
                    last_month_year,
                    charge_wh,
                    discharge_wh,
                    battery_start,
                    battery_end,
                )

        except Exception as e:
            _LOGGER.error("🔋 Error loading history: %s", e, exc_info=True)
        finally:
            # Vždy resetovat flag aby se mohl zkusit loading znovu při dalším update
            self._loading_history = False

    def _get_sensor(self, sensor_type: str) -> Optional[float]:
        """Získat hodnotu z existujícího sensoru."""
        if not self._hass:
            return None

        sensor_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        state = self._hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None
