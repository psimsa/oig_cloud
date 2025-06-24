"""Computed sensor implementation for OIG Cloud integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class OigCloudComputedSensor(SensorEntity, RestoreEntity):
    """Computed sensor for OIG Cloud data."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        device_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the computed sensor."""
        from .sensor_types import get_sensor_types

        sensor_types = get_sensor_types()
        SENSOR_TYPES_COMPUTED = sensor_types.get("computed", {})

        self.coordinator = coordinator
        self._sensor_type = sensor_type
        self._device_info = device_info or {}
        self._sensor_config = SENSOR_TYPES_COMPUTED.get(sensor_type, {})

        # Získání data_key z coordinator
        self._data_key = "unknown"
        if hasattr(coordinator, "config_entry") and coordinator.config_entry:
            if (
                hasattr(coordinator.config_entry, "data")
                and coordinator.config_entry.data
            ):
                self._data_key = coordinator.config_entry.data.get(
                    "inverter_sn", "unknown"
                )

        # Fallback - zkusit získat z device_info
        if self._data_key == "unknown" and "identifiers" in self._device_info:
            for identifier_set in self._device_info["identifiers"]:
                if len(identifier_set) > 1:
                    self._data_key = identifier_set[1]
                    break

        # Nastavení základních atributů
        self._attr_name = self._sensor_config.get(
            "name_cs", self._sensor_config.get("name", sensor_type)
        )
        self._attr_unique_id = f"{self._data_key}_{sensor_type}"
        self._attr_icon = self._sensor_config.get("icon")
        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")

        # Správné nastavení device_class
        device_class = self._sensor_config.get("device_class")
        if isinstance(device_class, str):
            try:
                self._attr_device_class = getattr(
                    SensorDeviceClass, device_class.upper()
                )
            except AttributeError:
                self._attr_device_class = device_class
        else:
            self._attr_device_class = device_class

        # Správné nastavení state_class
        state_class = self._sensor_config.get("state_class")
        if isinstance(state_class, str):
            try:
                self._attr_state_class = getattr(SensorStateClass, state_class.upper())
            except AttributeError:
                self._attr_state_class = state_class
        else:
            self._attr_state_class = state_class

        # Správné nastavení entity_category
        self._attr_entity_category = self._sensor_config.get("entity_category")

        # Inicializace pro energy tracking
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

        _LOGGER.debug(f"[{self.entity_id}] Initialized computed sensor: {sensor_type}")

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device info."""
        return self._device_info

    async def async_added_to_hass(self) -> None:
        """Called when entity is added to hass."""
        await super().async_added_to_hass()

        # Registrace reset handlerů pro energy senzory
        if self._sensor_type.startswith("computed_batt_"):
            async_track_time_change(
                self.hass, self._reset_daily, hour=0, minute=0, second=0
            )

            # Restore energy state
            old_state = await self.async_get_last_state()
            if old_state and old_state.attributes:
                _LOGGER.debug(
                    f"[{self.entity_id}] Restoring energy state from previous session"
                )
                for key in self._energy:
                    if key in old_state.attributes:
                        self._energy[key] = float(old_state.attributes[key])

    async def _reset_daily(self, *_: Any) -> None:
        """Reset daily/monthly/yearly energy counters."""
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
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        try:
            return self._calculate_value()
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error calculating value: {e}")
            return None

    def _calculate_value(self) -> Optional[Union[float, str]]:
        """Calculate the computed value based on sensor type."""
        data = list(self.coordinator.data.values())[0]

        # Speciální handling pro real_data_update senzor
        if self._sensor_type == "real_data_update":
            if self._check_for_real_data_changes(data):
                self._last_update_time = dt_util.now()
                _LOGGER.debug(
                    f"[{self.entity_id}] Real data update detected at {self._last_update_time}"
                )
            return (
                self._last_update_time.isoformat() if self._last_update_time else None
            )

        # Power totals
        if self._sensor_type == "ac_in_aci_wtotal":
            return float(
                data["ac_in"]["aci_wr"]
                + data["ac_in"]["aci_ws"]
                + data["ac_in"]["aci_wt"]
            )
        if self._sensor_type == "actual_aci_wtotal":
            return float(
                data["actual"]["aci_wr"]
                + data["actual"]["aci_ws"]
                + data["actual"]["aci_wt"]
            )
        if self._sensor_type == "dc_in_fv_total":
            return float(data["dc_in"]["fv_p1"] + data["dc_in"]["fv_p2"])
        if self._sensor_type == "actual_fv_total":
            return float(data["actual"]["fv_p1"] + data["actual"]["fv_p2"])

        # Battery power charge/discharge
        if self._sensor_type == "batt_batt_comp_p_charge":
            return self._get_batt_power_charge(data)
        if self._sensor_type == "batt_batt_comp_p_discharge":
            return self._get_batt_power_discharge(data)

        # Energy accumulation sensors
        if self._sensor_type.startswith("computed_batt_"):
            return self._accumulate_energy(data)

        # Extended FVE current calculations
        if self._sensor_type == "extended_fve_current_1":
            return self._get_extended_fve_current_1()
        if self._sensor_type == "extended_fve_current_2":
            return self._get_extended_fve_current_2()

        # Boiler consumption
        if self._sensor_type == "boiler_current_w":
            return self._get_boiler_consumption(data)

        # Battery calculations
        if self._sensor_type == "usable_battery_capacity":
            return self._calculate_usable_battery_capacity(data)
        elif self._sensor_type == "missing_battery_kwh":
            return self._calculate_missing_battery_kwh(data)
        elif self._sensor_type == "remaining_usable_capacity":
            return self._calculate_remaining_usable_capacity(data)
        elif self._sensor_type == "time_to_full":
            return self._calculate_time_to_full(data)
        elif self._sensor_type == "time_to_empty":
            return self._calculate_time_to_empty(data)
        else:
            _LOGGER.warning(
                f"[{self.entity_id}] Unknown computed sensor type: {self._sensor_type}"
            )
            return None

    def _get_batt_power_charge(self, data: Dict[str, Any]) -> float:
        """Get battery charging power (positive values only)."""
        return max(float(data["actual"]["bat_p"]), 0)

    def _get_batt_power_discharge(self, data: Dict[str, Any]) -> float:
        """Get battery discharging power (absolute values)."""
        return max(-float(data["actual"]["bat_p"]), 0)

    def _accumulate_energy(self, data: Dict[str, Any]) -> Optional[float]:
        """Accumulate energy over time for battery energy sensors."""
        try:
            now = datetime.utcnow()

            bat_power = float(data["actual"]["bat_p"])
            fv_power = float(data["actual"]["fv_p1"]) + float(data["actual"]["fv_p2"])

            if self._last_update is not None:
                delta_seconds = (now - self._last_update).total_seconds()
                wh_increment = (abs(bat_power) * delta_seconds) / 3600.0

                if bat_power > 0:  # Charging
                    self._energy["charge_today"] += wh_increment
                    self._energy["charge_month"] += wh_increment
                    self._energy["charge_year"] += wh_increment

                    # Determine source of charging power
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

                elif bat_power < 0:  # Discharging
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
        """Get the appropriate energy value for this sensor type."""
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

    def _get_boiler_consumption(self, data: Dict[str, Any]) -> Optional[float]:
        """Calculate estimated boiler power consumption."""
        try:
            fv_power = float(data["actual"]["fv_p1"]) + float(data["actual"]["fv_p2"])
            load_power = float(data["actual"]["aco_p"])
            export_power = (
                float(data["actual"]["aci_wr"])
                + float(data["actual"]["aci_ws"])
                + float(data["actual"]["aci_wt"])
            )
            boiler_p_set = float(data["boiler_prms"].get("p_set", 0))
            boiler_manual = data["boiler_prms"].get("manual", 0) == 1
            bat_power = float(data["actual"]["bat_p"])

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

    def _get_extended_fve_current_1(self) -> Optional[float]:
        """Calculate extended FVE current for string 1."""
        try:
            power = float(self.coordinator.data["extended_fve_power_1"])
            voltage = float(self.coordinator.data["extended_fve_voltage_1"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_1: {e}", exc_info=True)
            return None

    def _get_extended_fve_current_2(self) -> Optional[float]:
        """Calculate extended FVE current for string 2."""
        try:
            power = float(self.coordinator.data["extended_fve_power_2"])
            voltage = float(self.coordinator.data["extended_fve_voltage_2"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_2: {e}", exc_info=True)
            return None

    def _calculate_usable_battery_capacity(
        self, data: Dict[str, Any]
    ) -> Optional[float]:
        """Calculate usable battery capacity in kWh."""
        try:
            bat_p = float(data["box_prms"]["p_bat"])
            value = round((bat_p * 0.8) / 1000, 2)
            return value
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.debug(
                f"[{self.entity_id}] Error calculating usable battery capacity: {e}"
            )
            return None

    def _calculate_missing_battery_kwh(self, data: Dict[str, Any]) -> Optional[float]:
        """Calculate missing battery energy to reach 100% SOC."""
        try:
            bat_p = float(data["box_prms"]["p_bat"])
            bat_c = float(data["actual"]["bat_c"])
            value = round((bat_p * (1 - bat_c / 100)) / 1000, 2)
            return value
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.debug(
                f"[{self.entity_id}] Error calculating missing battery kWh: {e}"
            )
            return None

    def _calculate_remaining_usable_capacity(
        self, data: Dict[str, Any]
    ) -> Optional[float]:
        """Calculate remaining usable battery capacity."""
        try:
            bat_p = float(data["box_prms"]["p_bat"])
            bat_c = float(data["actual"]["bat_c"])
            usable = bat_p * 0.8
            missing = bat_p * (1 - bat_c / 100)
            value = round((usable - missing) / 1000, 2)
            return value
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.debug(
                f"[{self.entity_id}] Error calculating remaining usable capacity: {e}"
            )
            return None

    def _calculate_time_to_full(self, data: Dict[str, Any]) -> Optional[str]:
        """Calculate time to full charge."""
        try:
            bat_p = float(data["box_prms"]["p_bat"])
            bat_c = float(data["actual"]["bat_c"])
            bat_power = float(data["actual"].get("bat_p", 0))

            missing = bat_p * (1 - bat_c / 100)
            if bat_power > 0:
                return self._format_time(missing / bat_power)
            elif missing == 0:
                return "Nabito"
            else:
                return "Vybíjí se"
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            _LOGGER.debug(f"[{self.entity_id}] Error calculating time to full: {e}")
            return None

    def _calculate_time_to_empty(self, data: Dict[str, Any]) -> Optional[str]:
        """Calculate time to empty battery."""
        try:
            bat_p = float(data["box_prms"]["p_bat"])
            bat_c = float(data["actual"]["bat_c"])
            bat_power = float(data["actual"].get("bat_p", 0))

            usable = bat_p * 0.8
            missing = bat_p * (1 - bat_c / 100)
            remaining = usable - missing

            if bat_power < 0:
                return self._format_time(remaining / abs(bat_power))
            elif remaining == 0:
                return "Vybito"
            else:
                return "Nabíjí se"
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            _LOGGER.debug(f"[{self.entity_id}] Error calculating time to empty: {e}")
            return None

    def _format_time(self, hours: float) -> str:
        """Format time duration in Czech."""
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

    def _initialize_monitored_sensors(self) -> None:
        """Initialize monitored sensors for real data update."""
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

    def _check_for_real_data_changes(self, data: Dict[str, Any]) -> bool:
        """Check for real data changes in key sensors."""
        try:
            current_values = {}

            # Get current values of key sensors
            for sensor_key in self._key_sensors:
                if sensor_key.startswith(("bat_", "fv_", "aco_")):
                    current_values[sensor_key] = data["actual"].get(sensor_key, 0)
                elif sensor_key.startswith("aci_"):
                    current_values[sensor_key] = data["actual"].get(sensor_key, 0)

            # Compare with previous values
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

            # Save current values for next comparison
            self._monitored_sensors = current_values.copy()

            return has_changes

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error checking data changes: {e}")
            return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        return getattr(self, "_attr_extra_state_attributes", {})
