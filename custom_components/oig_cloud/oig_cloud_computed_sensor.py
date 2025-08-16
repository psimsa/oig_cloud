"""Computed sensor implementation for OIG Cloud integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

_LANGS: Dict[str, Dict[str, str]] = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Vypnuto", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
}


class OigCloudComputedSensor(OigCloudSensor, RestoreEntity):
    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__(coordinator, sensor_type)

        # OPRAVA: Nastavit _box_id a entity_id podle vzoru z OigCloudDataSensor
        if coordinator.data:
            self._box_id = list(coordinator.data.keys())[0]
            self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        else:
            self._box_id = "unknown"
            self.entity_id = f"sensor.oig_{sensor_type}"

        # OPRAVA: Přímý import SENSOR_TYPES místo neexistující funkce
        from .sensor_types import SENSOR_TYPES

        sensor_config = SENSOR_TYPES.get(sensor_type, {})

        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        self._attr_name = name_cs or name_en or sensor_type

        self._last_update: Optional[datetime] = None
        self._attr_extra_state_attributes: Dict[str, Any] = {}

        self._energy: Dict[str, float] = {
            "charge_today": 0.0,
            "charge_month": 0.0,
            "charge_year": 0.0,
            "discharge_today": 0.0,
            "discharge_month": 0.0,
            "discharge_year": 0.0,
            "charge_fve_today": 0.0,
            "charge_fve_month": 0.0,
            "charge_fve_year": 0.0,
            "charge_grid_today": 0.0,
            "charge_grid_month": 0.0,
            "charge_grid_year": 0.0,
        }

        self._last_update_time: Optional[datetime] = None
        self._monitored_sensors: Dict[str, Any] = {}

        # Speciální handling pro real_data_update senzor
        if sensor_type == "real_data_update":
            self._is_real_update_sensor = True
            self._initialize_monitored_sensors()
        else:
            self._is_real_update_sensor = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        async_track_time_change(
            self.hass, self._reset_daily, hour=0, minute=0, second=0
        )

        old_state = await self.async_get_last_state()
        if old_state and old_state.attributes:
            _LOGGER.debug(
                f"[{self.entity_id}] Restoring energy state from previous session"
            )
            for key in self._energy:
                if key in old_state.attributes:
                    self._energy[key] = float(old_state.attributes[key])

    async def _reset_daily(self, *_: Any) -> None:
        now = datetime.utcnow()
        _LOGGER.debug(f"[{self.entity_id}] Resetting daily energy")
        for key in self._energy:
            if key.endswith("today"):
                self._energy[key] = 0.0

        if now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting monthly energy")
            for key in self._energy:
                if key.endswith("month"):
                    self._energy[key] = 0.0

        if now.month == 1 and now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting yearly energy")
            for key in self._energy:
                if key.endswith("year"):
                    self._energy[key] = 0.0

    @property
    def state(self) -> Optional[Union[float, str]]:
        if self.coordinator.data is None:
            return None

        data = self.coordinator.data
        pv_data = list(data.values())[0]

        # OPRAVA: Kontrola existence "actual" dat pouze tam kde jsou potřeba
        if (
            self._sensor_type
            in [
                "time_to_empty",
                "time_to_full",
                "usable_battery_capacity",
                "missing_battery_kwh",
                "remaining_usable_capacity",
            ]
            and "actual" not in pv_data
        ):
            _LOGGER.warning(
                f"[{self.entity_id}] Live Data nejsou zapnutá v OIG aplikaci. "
                f"Zapněte Live Data v mobilní aplikaci OIG pro správnou funkci computed senzorů."
            )
            return None

        # Speciální handling pro real_data_update senzor
        if self._sensor_type == "real_data_update":
            if self._check_for_real_data_changes(pv_data):
                # Používáme lokální čas místo UTC
                self._last_update_time = dt_util.now()
                _LOGGER.debug(
                    f"[{self.entity_id}] Real data update detected at {self._last_update_time}"
                )

            return (
                self._last_update_time.isoformat() if self._last_update_time else None
            )

        if self._sensor_type == "ac_in_aci_wtotal":
            return float(
                pv_data["ac_in"]["aci_wr"]
                + pv_data["ac_in"]["aci_ws"]
                + pv_data["ac_in"]["aci_wt"]
            )
        if self._sensor_type == "actual_aci_wtotal":
            # OPRAVA: Pouze zde kontrola actual
            if "actual" not in pv_data:
                return 0.0
            return float(
                pv_data["actual"]["aci_wr"]
                + pv_data["actual"]["aci_ws"]
                + pv_data["actual"]["aci_wt"]
            )
        if self._sensor_type == "dc_in_fv_total":
            return float(pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])
        if self._sensor_type == "actual_fv_total":
            # OPRAVA: Pouze zde kontrola actual
            if "actual" not in pv_data:
                return 0.0
            return float(pv_data["actual"]["fv_p1"] + pv_data["actual"]["fv_p2"])

        if self._node_id == "boiler" or self._sensor_type == "boiler_current_w":
            return self._get_boiler_consumption(pv_data)

        if self._sensor_type == "batt_batt_comp_p_charge":
            return self._get_batt_power_charge(pv_data)
        if self._sensor_type == "batt_batt_comp_p_discharge":
            return self._get_batt_power_discharge(pv_data)

        if self._sensor_type.startswith("computed_batt_"):
            return self._accumulate_energy(pv_data)

        if self._sensor_type == "extended_fve_current_1":
            return self._get_extended_fve_current_1(self.coordinator)

        if self._sensor_type == "extended_fve_current_2":
            return self._get_extended_fve_current_2(self.coordinator)

        try:
            bat_p = float(pv_data["box_prms"]["p_bat"])

            # OPRAVA: Kontrola actual pouze pro tyto hodnoty
            if "actual" not in pv_data:
                _LOGGER.warning(
                    f"[{self.entity_id}] Live Data nejsou zapnutá v OIG aplikaci. "
                    f"Zapněte Live Data v mobilní aplikaci OIG pro správnou funkci computed senzorů."
                )
                return None

            bat_c = float(pv_data["actual"]["bat_c"])  # Battery charge percentage
            bat_power = float(pv_data["actual"]["bat_p"])  # Battery power

            # 1. Využitelná kapacita baterie
            if self._sensor_type == "usable_battery_capacity":
                value = round((bat_p * 0.8) / 1000, 2)
                return value

            # 2. Kolik kWh chybí do 100%
            if self._sensor_type == "missing_battery_kwh":
                value = round((bat_p * (1 - bat_c / 100)) / 1000, 2)
                return value
            # 3. Zbývající využitelná kapacita
            if self._sensor_type == "remaining_usable_capacity":
                usable = bat_p * 0.8
                missing = bat_p * (1 - bat_c / 100)
                value = round((usable - missing) / 1000, 2)
                return value

            # 4. Doba do nabití
            if self._sensor_type == "time_to_full":
                missing = bat_p * (1 - bat_c / 100)
                if bat_power > 0:
                    return self._format_time(missing / bat_power)
                elif missing == 0:
                    return "Nabito"
                else:
                    return "Vybíjí se"

            # 5. Doba do vybití
            if self._sensor_type == "time_to_empty":
                usable = bat_p * 0.8
                missing = bat_p * (1 - bat_c / 100)
                remaining = usable - missing

                # OPRAVA: Kontrola na plně nabitou baterii (100%)
                if bat_c >= 100:
                    return "Nabito"
                elif bat_power < 0:
                    return self._format_time(remaining / abs(bat_power))
                elif remaining == 0:
                    return "Vybito"
                else:
                    return "Nabíjí se"

        except Exception as e:
            _LOGGER.error(
                f"[{{self.entity_id}}] Error computing value: {e}", exc_info=True
            )

        return None

    def _accumulate_energy(self, pv_data: Dict[str, Any]) -> Optional[float]:
        try:
            # OPRAVA: Kontrola existence "actual" dat
            if "actual" not in pv_data:
                _LOGGER.warning(
                    f"[{self.entity_id}] Live Data nejsou zapnutá v OIG aplikaci. "
                    f"Energy tracking senzory potřebují Live Data pro správnou funkci. "
                    f"Zapněte Live Data v mobilní aplikaci OIG."
                )
                return None

            now = datetime.utcnow()

            bat_power = float(pv_data["actual"]["bat_p"])
            fv_power = float(pv_data["actual"]["fv_p1"]) + float(
                pv_data["actual"]["fv_p2"]
            )

            if self._last_update is not None:
                delta_seconds = (now - self._last_update).total_seconds()
                wh_increment = (abs(bat_power) * delta_seconds) / 3600.0

                if bat_power > 0:
                    self._energy["charge_today"] += wh_increment
                    self._energy["charge_month"] += wh_increment
                    self._energy["charge_year"] += wh_increment

                    if fv_power > 50:
                        from_fve = min(bat_power, fv_power)
                        from_grid = bat_power - from_fve
                    else:
                        from_fve = 0
                        from_grid = bat_power

                    wh_increment_fve = (from_fve * delta_seconds) / 3600.0
                    wh_increment_grid = (from_grid * delta_seconds) / 3600.0

                    self._energy["charge_fve_today"] += wh_increment_fve
                    self._energy["charge_fve_month"] += wh_increment_fve
                    self._energy["charge_fve_year"] += wh_increment_fve

                    self._energy["charge_grid_today"] += wh_increment_grid
                    self._energy["charge_grid_month"] += wh_increment_grid
                    self._energy["charge_grid_year"] += wh_increment_grid

                elif bat_power < 0:
                    self._energy["discharge_today"] += wh_increment
                    self._energy["discharge_month"] += wh_increment
                    self._energy["discharge_year"] += wh_increment

                _LOGGER.debug(
                    f"[{self.entity_id}] Δt={delta_seconds:.1f}s bat={bat_power:.1f}W fv={fv_power:.1f}W -> ΔWh={wh_increment:.4f}"
                )

            self._last_update = now
            self._attr_extra_state_attributes = {
                k: round(v, 3) for k, v in self._energy.items()
            }

            return self._get_energy_value()

        except Exception as e:
            _LOGGER.error(f"Error calculating energy: {e}", exc_info=True)
            return None

    def _get_energy_value(self) -> Optional[float]:
        sensor_map = {
            "computed_batt_charge_energy_today": "charge_today",
            "computed_batt_discharge_energy_today": "discharge_today",
            "computed_batt_charge_energy_month": "charge_month",
            "computed_batt_discharge_energy_month": "discharge_month",
            "computed_batt_charge_energy_year": "charge_year",
            "computed_batt_discharge_energy_year": "discharge_year",
            "computed_batt_charge_fve_energy_today": "charge_fve_today",
            "computed_batt_charge_fve_energy_month": "charge_fve_month",
            "computed_batt_charge_fve_energy_year": "charge_fve_year",
            "computed_batt_charge_grid_energy_today": "charge_grid_today",
            "computed_batt_charge_grid_energy_month": "charge_grid_month",
            "computed_batt_charge_grid_energy_year": "charge_grid_year",
        }
        energy_key = sensor_map.get(self._sensor_type)
        if energy_key:
            return round(self._energy[energy_key], 3)
        return None

    def _get_boiler_consumption(self, pv_data: Dict[str, Any]) -> Optional[float]:
        if self._sensor_type != "boiler_current_w":
            return None

        try:
            # OPRAVA: Kontrola existence "actual" dat
            if "actual" not in pv_data:
                _LOGGER.warning(
                    f"[{self.entity_id}] Live Data nejsou zapnutá - nelze vypočítat spotřebu bojleru. "
                    f"Zapněte Live Data v OIG aplikaci."
                )
                return None

            fv_power = float(pv_data["actual"]["fv_p1"]) + float(
                pv_data["actual"]["fv_p2"]
            )
            load_power = float(pv_data["actual"]["aco_p"])
            export_power = (
                float(pv_data["actual"]["aci_wr"])
                + float(pv_data["actual"]["aci_ws"])
                + float(pv_data["actual"]["aci_wt"])
            )
            boiler_p_set = float(pv_data["boiler_prms"].get("p_set", 0))
            boiler_manual = pv_data["boiler_prms"].get("manual", 0) == 1
            bat_power = float(pv_data["actual"]["bat_p"])

            if boiler_manual:
                boiler_power = boiler_p_set
            else:
                if bat_power <= 0:
                    available_power = fv_power - load_power - export_power
                    boiler_power = min(max(available_power, 0), boiler_p_set)
                else:
                    boiler_power = 0

            boiler_power = max(boiler_power, 0)

            _LOGGER.debug(
                f"[{self.entity_id}] Estimated boiler power: FVE={fv_power}W, Load={load_power}W, Export={export_power}W, Set={boiler_p_set}W, Manual={boiler_manual}, Bat_P={bat_power}W => Boiler={boiler_power}W"
            )

            return round(boiler_power, 2)

        except Exception as e:
            _LOGGER.error(f"Error calculating boiler consumption: {e}", exc_info=True)
            return None

    def _get_batt_power_charge(self, pv_data: Dict[str, Any]) -> float:
        if "actual" not in pv_data:
            return 0.0
        return max(float(pv_data["actual"]["bat_p"]), 0)

    def _get_batt_power_discharge(self, pv_data: Dict[str, Any]) -> float:
        if "actual" not in pv_data:
            return 0.0
        return max(-float(pv_data["actual"]["bat_p"]), 0)

    def _get_extended_fve_current_1(self, coordinator: Any) -> Optional[float]:
        try:
            power = float(coordinator.data["extended_fve_power_1"])
            voltage = float(coordinator.data["extended_fve_voltage_1"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_1: {e}", exc_info=True)
            return None

    def _get_extended_fve_current_2(self, coordinator: Any) -> Optional[float]:
        try:
            power = float(coordinator.data["extended_fve_power_2"])
            voltage = float(coordinator.data["extended_fve_voltage_2"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_2: {e}", exc_info=True)
            return None

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    def _format_time(self, hours: float) -> str:
        if hours <= 0:
            return "N/A"

        minutes = int(hours * 60)
        days, remainder = divmod(minutes, 1440)
        hrs, mins = divmod(remainder, 60)

        self._attr_extra_state_attributes = {
            "days": days,
            "hours": hrs,
            "minutes": mins,
        }

        if days >= 1:
            if days == 1:
                return f"{days} den {hrs} hodin {mins} minut"
            elif days in [2, 3, 4]:
                return f"{days} dny {hrs} hodin {mins} minut"
            else:
                return f"{days} dnů {hrs} hodin {mins} minut"
        elif hrs >= 1:
            return f"{hrs} hodin {mins} minut"
        else:
            return f"{mins} minut"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return getattr(self, "_attr_extra_state_attributes", {})

    def _initialize_monitored_sensors(self) -> None:
        """Inicializuje sledované senzory pro real data update."""
        # Klíčové senzory pro sledování změn
        self._key_sensors = [
            "bat_p",
            "bat_c",
            "fv_p1",
            "fv_p2",
            "aco_p",
            "aci_wr",
            "aci_ws",
            "aci_wt",
        ]

    def _check_for_real_data_changes(self, pv_data: Dict[str, Any]) -> bool:
        """Zkontroluje, zda došlo ke skutečné změně v datech."""
        try:
            # OPRAVA: Kontrola existence "actual" dat
            if "actual" not in pv_data:
                _LOGGER.warning(
                    f"[{self.entity_id}] Live Data nejsou zapnutá - real data update nefunguje. "
                    f"Zapněte Live Data v OIG aplikaci."
                )
                return False

            current_values = {}

            # Získej aktuální hodnoty klíčových senzorů
            for sensor_key in self._key_sensors:
                if sensor_key.startswith(("bat_", "fv_", "aco_")):
                    current_values[sensor_key] = pv_data["actual"].get(sensor_key, 0)
                elif sensor_key.startswith("aci_"):
                    current_values[sensor_key] = pv_data["actual"].get(sensor_key, 0)

            # Porovnej s předchozími hodnotami
            has_changes = False
            for key, current_value in current_values.items():
                previous_value = self._monitored_sensors.get(key)
                if (
                    previous_value is None
                    or abs(float(current_value) - float(previous_value)) > 0.1
                ):
                    has_changes = True
                    _LOGGER.debug(
                        f"[{self.entity_id}] Real data change detected: {key} {previous_value} -> {current_value}"
                    )

            # Ulož aktuální hodnoty pro příští porovnání
            self._monitored_sensors = current_values.copy()

            return has_changes

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error checking data changes: {e}")
            return False
