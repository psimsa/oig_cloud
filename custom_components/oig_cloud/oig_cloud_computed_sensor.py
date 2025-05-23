"""Computed sensor implementation for OIG Cloud integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union, Callable, Awaitable

from homeassistant.core import HomeAssistant, State, callback # For async_get_last_state, hass type
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
# Assuming OigCloudDataUpdateCoordinator is the correct name from .coordinator
from .coordinator import OigCloudDataUpdateCoordinator
from .oig_cloud_sensor import OigCloudSensor # Base class
# Assuming SENSOR_TYPES and a TypedDict for its structure (e.g., OigSensorTypeDescription) might come from here
# from .sensor_types import SENSOR_TYPES, OigSensorTypeDescription 

# Import your data models if pv_data is to be an instance of OigCloudDeviceData
from .models import OigCloudDeviceData # If coordinator.data provides this structure

_LOGGER = logging.getLogger(__name__)

# _LANGS seems unused in this specific file snippet, if used by base class or other parts, keep it.
# For now, commenting out as per current file's direct usage.
# _LANGS = {
#     "on": {"en": "On", "cs": "Zapnuto"},
#     "off": {"en": "Vypnuto", "cs": "Vypnuto"},
#     "unknown": {"en": "Unknown", "cs": "Neznámý"},
#     "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
# }

# Define CoordinatorDataType to match what OigCloudDataUpdateCoordinator provides
# This was Dict[str, Any] in coordinator.py, ideally it's Dict[str, OigCloudDeviceData]
CoordinatorDataType = Dict[str, Any] # Or Dict[str, OigCloudDeviceData]

class OigCloudComputedSensor(OigCloudSensor, RestoreEntity):
    """Computed sensor for OIG Cloud data that requires calculations or historical data."""

    # Attributes related to HA SensorEntity that might be set by base or here
    # _attr_entity_category: Optional[EntityCategory] = None # Example
    # _attr_device_class: Optional[SensorDeviceClass] = None # Example
    # _attr_state_class: Optional[SensorStateClass] = None # Example
    # _attr_native_unit_of_measurement: Optional[str] = None # Example

    def __init__(
        self,
        coordinator: OigCloudDataUpdateCoordinator, # Use specific coordinator type
        sensor_type: str,
    ) -> None:
        """Initialize the computed sensor."""
        super().__init__(coordinator, sensor_type)
        self._last_update: Optional[datetime] = None
        # Ensure _attr_extra_state_attributes is initialized as a Dict for safety
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
        # self.hass is available from SensorEntity, typed as HomeAssistant

    async def async_added_to_hass(self) -> Awaitable[None]: # Explicit return type
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        # Register callback for midnight to reset daily counters
        # HomeAssistant is available as self.hass
        async_track_time_change(
            self.hass, self._reset_daily_counters, hour=0, minute=0, second=0
        )

        # Restore the previous state of energy counters
        old_state: Optional[State] = await self.async_get_last_state()
        if old_state and old_state.attributes:
            _LOGGER.debug(
                f"[{self.entity_id}] Restoring energy state from previous session"
            )
            for key in self._energy:
                if key in old_state.attributes:
                    try:
                        self._energy[key] = float(old_state.attributes[key])
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            f"[{self.entity_id}] Could not restore attribute {key} "
                            f"with value {old_state.attributes[key]}, defaulting to 0.0"
                        )
                        self._energy[key] = 0.0
        return None # Explicitly return None

    @callback # Mark as callback if it's directly updating HA state or listening to events
    def _reset_daily_counters(self, now: datetime) -> None: # Parameter 'now' is passed by async_track_time_change
        """Reset daily, monthly, and yearly energy counters at appropriate times."""
        _LOGGER.debug(f"[{self.entity_id}] Resetting daily energy at {now}")
        for key in self._energy:
            if key.endswith("today"):
                self._energy[key] = 0.0

        if now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting monthly energy at {now}")
            for key in self._energy:
                if key.endswith("month"):
                    self._energy[key] = 0.0

        if now.month == 1 and now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting yearly energy at {now}")
            for key in self._energy:
                if key.endswith("year"):
                    self._energy[key] = 0.0
        # After resetting, if the sensor is active, schedule an update
        if self.hass and self.enabled:
             self.async_schedule_update_ha_state(True)


    @property
    def native_value(self) -> Optional[Union[float, str]]: # More specific than 'state' property
        """Return the state of the sensor."""
        # self.coordinator is OigCloudDataUpdateCoordinator
        if self.coordinator.data is None:
            _LOGGER.debug(f"[{self.entity_id}] No data from coordinator for sensor {self._sensor_type}")
            return None

        # Assuming coordinator.data is Dict[str, Dict[str, Any]] or Dict[str, OigCloudDeviceData]
        # For safety, check if data is not empty and get the first device's data
        # This pattern `list(data.values())[0]` is unsafe if data can be empty.
        all_devices_data: CoordinatorDataType = self.coordinator.data
        if not isinstance(all_devices_data, dict) or not all_devices_data:
            _LOGGER.debug(f"[{self.entity_id}] Coordinator data is not a non-empty dict.")
            return None
        
        # Assuming one box_id or using the first one.
        # This might need refinement if multiple boxes are supported and identified differently.
        # pv_data: Dict[str, Any] or OigCloudDeviceData
        # It's safer to get box_id from self if available (set in base class OigCloudSensor)
        box_id_to_use = getattr(self, "_box_id", None)
        if box_id_to_use and box_id_to_use in all_devices_data:
            pv_data = all_devices_data[box_id_to_use]
        else:
            # Fallback to first device data, log warning
            _LOGGER.debug(f"[{self.entity_id}] box_id {box_id_to_use} not found, defaulting to first device data.")
            pv_data = next(iter(all_devices_data.values()))


        # TODO: Consider refactoring pv_data access using OigCloudDeviceData models
        # e.g., pv_data.ac_in.aci_wr instead of pv_data["ac_in"]["aci_wr"]
        # This requires coordinator to store OigCloudDeviceData instances.
        # For now, sticking to dict access as per original code structure.

        try:
            if self._sensor_type == "ac_in_aci_wtotal":
                ac_in_data = pv_data.get("ac_in", {})
                return float(
                    ac_in_data.get("aci_wr", 0.0) +
                    ac_in_data.get("aci_ws", 0.0) +
                    ac_in_data.get("aci_wt", 0.0)
                )
            if self._sensor_type == "actual_aci_wtotal":
                actual_data = pv_data.get("actual", {})
                return float(
                    actual_data.get("aci_wr", 0.0) +
                    actual_data.get("aci_ws", 0.0) +
                    actual_data.get("aci_wt", 0.0)
                )
            if self._sensor_type == "dc_in_fv_total":
                dc_in_data = pv_data.get("dc_in", {})
                return float(dc_in_data.get("fv_p1", 0.0) + dc_in_data.get("fv_p2", 0.0))
            if self._sensor_type == "actual_fv_total":
                actual_data = pv_data.get("actual", {})
                return float(actual_data.get("fv_p1", 0.0) + actual_data.get("fv_p2", 0.0))

            # Assuming self._node_id is set in the base class OigCloudSensor
            node_id = getattr(self, "_node_id", "")
            if node_id == "boiler" or self._sensor_type == "boiler_current_w":
                return self._get_boiler_consumption(pv_data)

            if self._sensor_type == "batt_batt_comp_p_charge":
                return self._get_batt_power_charge(pv_data)
            if self._sensor_type == "batt_batt_comp_p_discharge":
                return self._get_batt_power_discharge(pv_data)

            if self._sensor_type.startswith("computed_batt_"):
                return self._accumulate_energy(pv_data)

            # Existing computed logic, ensure safe access with .get()
            box_prms_data = pv_data.get("box_prms", {})
            actual_data = pv_data.get("actual", {})
            
            bat_p = float(box_prms_data.get("p_bat", 0.0))
            bat_c = float(actual_data.get("bat_c", 0.0))
            bat_power = float(actual_data.get("bat_p", 0.0))

            if self._sensor_type == "usable_battery_capacity":
                return round((bat_p * 0.8) / 1000, 2)
            if self._sensor_type == "missing_battery_kwh":
                return round((bat_p * (1 - bat_c / 100)) / 1000, 2)
            if self._sensor_type == "remaining_usable_capacity":
                usable = bat_p * 0.8
                missing = bat_p * (1 - bat_c / 100)
                return round((usable - missing) / 1000, 2)

            if self._sensor_type == "time_to_full":
                missing_kwh = bat_p * (1 - bat_c / 100) # This is Wh, not kWh
                if bat_power > 0:
                    return self._format_time(missing_kwh / bat_power) # hours = Wh / W
                return "Nabito" if missing_kwh == 0 else "Vybíjí se"
            if self._sensor_type == "time_to_empty":
                # Assuming bat_p is capacity in Wh. usable is 80% of capacity.
                usable_wh = bat_p * 0.8 
                # current_charge_wh = bat_p * (bat_c / 100)
                # remaining_from_100_to_20 = current_charge_wh - (bat_p * 0.2)
                # This calculation was: remaining = usable - (bat_p * (1-bat_c/100))
                # Simplified: remaining_usable_wh = bat_p * (bat_c/100) - bat_p * 0.2 if bat_c > 20 else 0
                # Or, based on original: remaining_wh = (bat_p * 0.8) - (bat_p * (1 - bat_c / 100))
                remaining_wh = bat_p * (bat_c / 100 - 0.2) # Energy from current SoC down to 20%
                remaining_wh = max(0, remaining_wh)

                if bat_power < 0: # Discharging
                    return self._format_time(remaining_wh / abs(bat_power)) # hours = Wh / W
                return "Vybito" if remaining_wh == 0 else "Nabíjí se"

        except KeyError as e:
            _LOGGER.warning(f"[{self.entity_id}] KeyError when computing state for {self._sensor_type}: {e}")
        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error computing value for {self._sensor_type}: {e}", exc_info=True
            )
        return None # Default return if any error or condition not met

    def _accumulate_energy(self, pv_data: Dict[str, Any]) -> Optional[float]:
        """Accumulate energy values based on battery power and time delta."""
        try:
            now = datetime.utcnow()
            actual_data = pv_data.get("actual", {})
            bat_power = float(actual_data.get("bat_p", 0.0))
            fv_power = float(actual_data.get("fv_p1", 0.0)) + float(actual_data.get("fv_p2", 0.0))

            if self._last_update is not None:
                delta_seconds = (now - self._last_update).total_seconds()
                if delta_seconds <= 0: # Ensure time moves forward
                    _LOGGER.debug(f"[{self.entity_id}] Delta seconds is not positive ({delta_seconds}), skipping accumulation.")
                    return self._get_energy_value() # Return current value without accumulation

                wh_increment = (abs(bat_power) * delta_seconds) / 3600.0

                if bat_power > 0: # Charging
                    self._energy["charge_today"] += wh_increment
                    self._energy["charge_month"] += wh_increment
                    self._energy["charge_year"] += wh_increment

                    # Simplified FVE/Grid contribution for charging
                    from_fve = min(bat_power, fv_power) if fv_power > 50 else 0
                    from_grid = bat_power - from_fve
                    
                    wh_increment_fve = (from_fve * delta_seconds) / 3600.0
                    wh_increment_grid = (from_grid * delta_seconds) / 3600.0

                    self._energy["charge_fve_today"] += wh_increment_fve
                    self._energy["charge_fve_month"] += wh_increment_fve
                    self._energy["charge_fve_year"] += wh_increment_fve
                    self._energy["charge_grid_today"] += wh_increment_grid
                    self._energy["charge_grid_month"] += wh_increment_grid
                    self._energy["charge_grid_year"] += wh_increment_grid
                elif bat_power < 0: # Discharging
                    self._energy["discharge_today"] += wh_increment
                    self._energy["discharge_month"] += wh_increment
                    self._energy["discharge_year"] += wh_increment
                
                _LOGGER.debug(
                    f"[{self.entity_id}] Δt={delta_seconds:.1f}s bat={bat_power:.1f}W "
                    f"fv={fv_power:.1f}W -> ΔWh={wh_increment:.4f}"
                )

            self._last_update = now
            # Update extra_state_attributes directly
            current_attributes = {k: round(v, 3) for k, v in self._energy.items()}
            # Preserve other attributes if _format_time was called
            self._attr_extra_state_attributes.update(current_attributes)


            return self._get_energy_value()
        except KeyError as e:
            _LOGGER.warning(f"[{self.entity_id}] KeyError during energy accumulation for {self._sensor_type}: {e}")
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error calculating energy for {self._sensor_type}: {e}", exc_info=True)
        return None

    def _get_energy_value(self) -> Optional[float]:
        """Get the specific energy value based on sensor type."""
        # This map should ideally be part of SENSOR_TYPES config or a class constant
        sensor_map: Dict[str, str] = {
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
        if energy_key and energy_key in self._energy:
            return round(self._energy[energy_key], 3)
        _LOGGER.debug(f"[{self.entity_id}] No energy value found for sensor type {self._sensor_type}")
        return None

    def _get_boiler_consumption(self, pv_data: Dict[str, Any]) -> Optional[float]:
        """Estimate boiler power consumption."""
        # This sensor type check is good, but ensure _sensor_type is always valid
        if self._sensor_type != "boiler_current_w":
            _LOGGER.debug(f"[{self.entity_id}] _get_boiler_consumption called for wrong sensor type: {self._sensor_type}")
            return None

        try:
            actual_data = pv_data.get("actual", {})
            boiler_prms_data = pv_data.get("boiler_prms", {})

            fv_power = float(actual_data.get("fv_p1", 0.0)) + float(actual_data.get("fv_p2", 0.0))
            load_power = float(actual_data.get("aco_p", 0.0))
            export_power = (
                float(actual_data.get("aci_wr", 0.0)) +
                float(actual_data.get("aci_ws", 0.0)) +
                float(actual_data.get("aci_wt", 0.0))
            )
            boiler_p_set = float(boiler_prms_data.get("p_set", 0.0))
            boiler_manual = boiler_prms_data.get("manual", 0) == 1
            bat_power = float(actual_data.get("bat_p", 0.0))

            boiler_power: float
            if boiler_manual:
                boiler_power = boiler_p_set
            else:
                if bat_power <= 0: # Battery not charging or discharging to grid
                    available_power = fv_power - load_power - export_power
                    boiler_power = min(max(available_power, 0.0), boiler_p_set)
                else: # Battery is charging from grid or FVE, don't use excess for boiler
                    boiler_power = 0.0
            
            boiler_power = max(boiler_power, 0.0) # Ensure non-negative

            _LOGGER.debug(
                f"[{self.entity_id}] Estimated boiler power: FVE={fv_power}W, Load={load_power}W, "
                f"Export={export_power}W, Set={boiler_p_set}W, Manual={boiler_manual}, "
                f"Bat_P={bat_power}W => Boiler={boiler_power}W"
            )
            return round(boiler_power, 2)
        except KeyError as e:
            _LOGGER.warning(f"[{self.entity_id}] KeyError during boiler consumption calculation for {self._sensor_type}: {e}")
        except Exception as e:
            _LOGGER.error(
                f"[{self.entity_id}] Error calculating boiler consumption for {self._sensor_type}: {e}", exc_info=True
            )
        return None

    def _get_batt_power_charge(self, pv_data: Dict[str, Any]) -> float:
        """Get battery charging power (positive value)."""
        actual_data = pv_data.get("actual", {})
        return max(float(actual_data.get("bat_p", 0.0)), 0.0)

    def _get_batt_power_discharge(self, pv_data: Dict[str, Any]) -> float:
        """Get battery discharging power (positive value)."""
        actual_data = pv_data.get("actual", {})
        return max(-float(actual_data.get("bat_p", 0.0)), 0.0)

    async def async_update(self) -> Awaitable[None]: # Type hint for async method
        """Request a refresh from the coordinator."""
        # This method is often not needed if the sensor relies on CoordinatorEntity updates.
        # If this is for a service call or specific refresh, it's fine.
        # Ensure OigCloudSensor or its base calls _handle_coordinator_update
        await self.coordinator.async_request_refresh()
        return None # Explicitly return None

    def _format_time(self, hours: float) -> str:
        """Format hours into a human-readable string (days, hours, minutes)."""
        # Reset extra attributes specific to time formatting here
        self._attr_extra_state_attributes = {
            k: v for k, v in self._attr_extra_state_attributes.items()
            if k not in ["days", "hours", "minutes"]
        }

        if hours < 0: # Should not happen if logic is correct before calling
            return "N/A"
        if hours == 0: # Explicitly handle zero duration
             # Could also be "0 minut" or specific state like "Nabito" / "Vybito"
             # This function is for formatting duration, so "0 minut" is more accurate.
            self._attr_extra_state_attributes.update({"days": 0, "hours": 0, "minutes": 0})
            return "0 minut"


        minutes_total = int(hours * 60)
        days, remainder_minutes = divmod(minutes_total, 1440) # 24 * 60
        hrs, mins = divmod(remainder_minutes, 60)

        self._attr_extra_state_attributes.update({
            "days": days,
            "hours": hrs,
            "minutes": mins,
        })
        
        parts = []
        if days > 0:
            parts.append(f"{days} den{'y' if days != 1 else ''}") # Basic pluralization
        if hrs > 0:
            parts.append(f"{hrs} hodin")
        if mins > 0 or not parts: # Show minutes if it's the only unit or non-zero
            parts.append(f"{mins} minut")
        
        return " ".join(parts) if parts else "0 minut"


    # This property was overridden. Ensure its definition matches the base if any, or is intentional.
    # The base OigCloudSensor likely provides a more generic extra_state_attributes.
    # This computed sensor adds energy and time components.
    @property
    def extra_state_attributes(self) -> Dict[str, Any]: # Return type should be Dict, not Optional
        """Return the state attributes."""
        # Ensure base attributes are preserved if OigCloudSensor defines any
        # For now, assuming this class fully manages its extra attributes.
        return self._attr_extra_state_attributes # Already updated by _accumulate_energy or _format_time
