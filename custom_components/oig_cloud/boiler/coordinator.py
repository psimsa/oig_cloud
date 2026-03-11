"""Coordinator pro bojlerový modul."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_BOILER_ALT_COST_KWH,
    CONF_BOILER_ALT_ENERGY_SENSOR,
    CONF_BOILER_DEADLINE_TIME,
    CONF_BOILER_HAS_ALTERNATIVE_HEATING,
    CONF_BOILER_PLAN_SLOT_MINUTES,
    CONF_BOILER_SPOT_PRICE_SENSOR,
    CONF_BOILER_TEMP_SENSOR_BOTTOM,
    CONF_BOILER_TEMP_SENSOR_POSITION,
    CONF_BOILER_TEMP_SENSOR_TOP,
    CONF_BOILER_TWO_ZONE_SPLIT_RATIO,
    CONF_BOILER_VOLUME_L,
    DEFAULT_BOILER_DEADLINE_TIME,
    DEFAULT_BOILER_PLAN_SLOT_MINUTES,
    DEFAULT_BOILER_TEMP_SENSOR_POSITION,
    DEFAULT_BOILER_TWO_ZONE_SPLIT_RATIO,
)
from .models import BoilerPlan, BoilerProfile, EnergySource
from .planner import BoilerPlanner
from .profiler import BoilerProfiler
from .utils import (
    calculate_energy_to_heat,
    calculate_stratified_temp,
    estimate_residual_energy,
    validate_temperature_sensor,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=5)
PROFILE_UPDATE_INTERVAL = timedelta(hours=24)


class BoilerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator pro bojlerový modul - update každých 5 minut."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
    ) -> None:
        """
        Inicializace coordinatoru.

        Args:
            hass: Home Assistant instance
            config: Konfigurace z config_flow
        """
        super().__init__(
            hass,
            _LOGGER,
            name="OIG Boiler",
            update_interval=UPDATE_INTERVAL,
        )

        self.config = config
        self._last_profile_update: Optional[datetime] = None
        self._current_profile: Optional[BoilerProfile] = None
        self._current_plan: Optional[BoilerPlan] = None

        # Inicializace komponent
        self.profiler = BoilerProfiler(
            hass=hass,
            energy_sensor="sensor.oig_2206237016_boiler_day_w",  # OIG energy sensor (Wh)
            lookback_days=60,
        )

        self.planner = BoilerPlanner(
            hass=hass,
            slot_minutes=config.get(
                CONF_BOILER_PLAN_SLOT_MINUTES, DEFAULT_BOILER_PLAN_SLOT_MINUTES
            ),
            alt_cost_kwh=config.get(CONF_BOILER_ALT_COST_KWH, 0.0),
            has_alternative=config.get(CONF_BOILER_HAS_ALTERNATIVE_HEATING, False),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Update každých 5 minut.

        Returns:
            Data pro senzory
        """
        try:
            now = dt_util.now()

            # 1. Update profilu (1× denně)
            if self._should_update_profile(now):
                await self._update_profile()

            # 2. Načíst aktuální teploty
            temperatures = await self._read_temperatures()

            # 3. Vypočítat energetický stav
            energy_state = self._calculate_energy_state(temperatures)

            # 4. Trackování energie
            energy_tracking = await self._track_energy_sources()

            # 5. Update plánu (pokud je profil dostupný)
            if self._current_profile:
                await self._update_plan()

            # 6. Aktuální slot a doporučení
            current_slot = None
            charging_recommended = False
            recommended_source = None

            if self._current_plan:
                current_slot = self._current_plan.get_current_slot(now)
                if current_slot:
                    charging_recommended = True
                    recommended_source = current_slot.recommended_source.value

            # Sestavit data
            data = {
                "temperatures": temperatures,
                "energy_state": energy_state,
                "energy_tracking": energy_tracking,
                "profile": self._current_profile,
                "plan": self._current_plan,
                "current_slot": current_slot,
                "charging_recommended": charging_recommended,
                "recommended_source": recommended_source,
                "last_update": now,
            }

            return data

        except Exception as err:
            _LOGGER.error("Chyba při update bojleru: %s", err, exc_info=True)
            raise UpdateFailed(f"Update selhal: {err}") from err

    def _should_update_profile(self, now: datetime) -> bool:
        """Kontrola, zda je potřeba aktualizovat profil."""
        if self._last_profile_update is None:
            return True

        time_since_update = now - self._last_profile_update
        return time_since_update >= PROFILE_UPDATE_INTERVAL

    async def _update_profile(self) -> None:
        """Aktualizuje profilování z SQL historie."""
        _LOGGER.info("Aktualizace profilů bojleru...")
        try:
            profiles = await self.profiler.async_update_profiles()

            # Vybrat profil pro aktuální čas
            now = dt_util.now()
            self._current_profile = self.profiler.get_profile_for_datetime(now)

            self._last_profile_update = now
            _LOGGER.info("Profily aktualizovány, celkem kategorií: %s", len(profiles))

        except Exception as err:
            _LOGGER.error("Chyba při aktualizaci profilů: %s", err)

    async def _read_temperatures(self) -> dict[str, Optional[float]]:
        """Načte teploty z teploměrů."""
        config = self.config

        top_sensor = config.get(CONF_BOILER_TEMP_SENSOR_TOP)
        bottom_sensor = config.get(CONF_BOILER_TEMP_SENSOR_BOTTOM)
        sensor_position = config.get(
            CONF_BOILER_TEMP_SENSOR_POSITION, DEFAULT_BOILER_TEMP_SENSOR_POSITION
        )

        temp_top = None
        temp_bottom = None

        # Horní senzor
        if top_sensor:
            state = self.hass.states.get(top_sensor)
            temp_top = validate_temperature_sensor(state, top_sensor)

        # Dolní senzor
        if bottom_sensor:
            state = self.hass.states.get(bottom_sensor)
            temp_bottom = validate_temperature_sensor(state, bottom_sensor)

        # Stratifikace pokud jen jeden senzor
        temp_upper_zone = None
        temp_lower_zone = None

        if temp_top is not None and temp_bottom is None:
            # Extrapolace z horního
            split_ratio = config.get(
                CONF_BOILER_TWO_ZONE_SPLIT_RATIO, DEFAULT_BOILER_TWO_ZONE_SPLIT_RATIO
            )
            temp_upper_zone, temp_lower_zone = calculate_stratified_temp(
                measured_temp=temp_top,
                sensor_position=sensor_position,
                mode="two_zone",
                split_ratio=split_ratio,
            )
        elif temp_top is not None and temp_bottom is not None:
            # Dva senzory - použít přímo
            temp_upper_zone = temp_top
            temp_lower_zone = temp_bottom

        return {
            "top": temp_top,
            "bottom": temp_bottom,
            "upper_zone": temp_upper_zone,
            "lower_zone": temp_lower_zone,
        }

    def _calculate_energy_state(
        self, temperatures: dict[str, Optional[float]]
    ) -> dict[str, float]:
        """Vypočítá energetický stav bojleru."""
        volume_l = self.config.get(CONF_BOILER_VOLUME_L, 200.0)
        target_temp = self.config.get("boiler_target_temp_c", 60.0)

        temp_upper = temperatures.get("upper_zone")
        temp_lower = temperatures.get("lower_zone")

        energy_needed_kwh = 0.0
        avg_temp = None

        if temp_upper is not None and temp_lower is not None:
            avg_temp = (temp_upper + temp_lower) / 2.0

            # Energie potřebná k ohřevu
            energy_needed_kwh = calculate_energy_to_heat(
                volume_liters=volume_l,
                temp_current=avg_temp,
                temp_target=target_temp,
            )

        return {
            "avg_temp": avg_temp or 0.0,
            "energy_needed_kwh": energy_needed_kwh,
        }

    async def _track_energy_sources(self) -> dict[str, float]:
        """Trackuje energii z jednotlivých zdrojů."""
        # OIG senzory
        manual_mode_entity = "sensor.oig_2206237016_boiler_manual_mode"
        current_cbb_entity = "sensor.oig_2206237016_boiler_current_cbb_w"
        day_energy_entity = "sensor.oig_2206237016_boiler_day_w"

        # User alternativní senzor
        alt_energy_sensor = self.config.get(CONF_BOILER_ALT_ENERGY_SENSOR)

        # Načíst stavy
        manual_mode_state = self.hass.states.get(manual_mode_entity)
        current_cbb_state = self.hass.states.get(current_cbb_entity)
        day_energy_state = self.hass.states.get(day_energy_entity)

        # Detekce zdroje
        current_source = EnergySource.GRID  # default

        if manual_mode_state and manual_mode_state.state == "Zapnuto":
            current_source = EnergySource.FVE
        elif current_cbb_state:
            try:
                cbb_w = float(current_cbb_state.state)
                if cbb_w > 0:
                    current_source = EnergySource.FVE
            except ValueError:
                pass

        # Celková energie dnes
        total_energy_wh = 0.0
        if day_energy_state:
            try:
                total_energy_wh = float(day_energy_state.state)
            except ValueError:
                pass

        total_energy_kwh = total_energy_wh / 1000.0

        # FVE a Grid energie (placeholder - potřeba trackování v čase)
        fve_kwh = 0.0
        grid_kwh = 0.0

        # Alternativní energie
        alt_kwh = 0.0
        if alt_energy_sensor:
            alt_state = self.hass.states.get(alt_energy_sensor)
            if alt_state:
                try:
                    alt_kwh = float(alt_state.state)
                    # Konverze Wh → kWh pokud potřeba
                    if alt_state.attributes.get("unit_of_measurement") == "Wh":
                        alt_kwh /= 1000.0
                except ValueError:
                    pass

        # Residuální výpočet (pokud není user senzor)
        if not alt_energy_sensor:
            alt_kwh = estimate_residual_energy(total_energy_kwh, fve_kwh, grid_kwh)

        return {
            "current_source": current_source.value,
            "total_kwh": total_energy_kwh,
            "fve_kwh": fve_kwh,
            "grid_kwh": grid_kwh,
            "alt_kwh": alt_kwh,
        }

    async def _update_plan(self) -> None:
        """Aktualizuje plán ohřevu."""
        if not self._current_profile:
            return

        try:
            # Načíst spotové ceny
            spot_prices = await self._get_spot_prices()

            # Načíst overflow okna z battery_forecast
            overflow_windows = await self._get_overflow_windows()

            # Deadline
            deadline_time = self.config.get(
                CONF_BOILER_DEADLINE_TIME, DEFAULT_BOILER_DEADLINE_TIME
            )

            # Vytvořit plán
            self._current_plan = await self.planner.async_create_plan(
                profile=self._current_profile,
                spot_prices=spot_prices,
                overflow_windows=overflow_windows,
                deadline_time=deadline_time,
            )

        except Exception as err:
            _LOGGER.error("Chyba při tvorbě plánu: %s", err)

    async def _get_spot_prices(self) -> dict[datetime, float]:
        """Načte spotové ceny ze senzoru."""
        spot_sensor = self.config.get(CONF_BOILER_SPOT_PRICE_SENSOR)
        if not spot_sensor:
            return {}

        state = self.hass.states.get(spot_sensor)
        if not state:
            return {}

        # Očekáváme atribut 'prices' jako list [{datetime, price}, ...]
        prices_attr = state.attributes.get("prices", [])

        result = {}
        for entry in prices_attr:
            if isinstance(entry, dict):
                dt_str = entry.get("datetime")
                price = entry.get("price")

                if dt_str and price is not None:
                    dt_obj = dt_util.parse_datetime(dt_str)
                    if dt_obj:
                        result[dt_obj] = float(price)

        return result

    async def _get_overflow_windows(self) -> list[tuple[datetime, datetime]]:
        """Načte overflow okna z battery_forecast coordinatoru."""
        # Pokus o získání dat z battery_forecast coordinatoru
        battery_coordinator = self.hass.data.get("oig_cloud", {}).get(
            "battery_forecast_coordinator"
        )

        if not battery_coordinator:
            _LOGGER.debug("Battery forecast coordinator není dostupný")
            return []

        battery_data = battery_coordinator.data
        return await self.planner.async_get_overflow_windows(battery_data)
