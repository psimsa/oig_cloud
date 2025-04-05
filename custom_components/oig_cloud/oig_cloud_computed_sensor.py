"""Computed sensor implementation for OIG Cloud integration."""
import logging
from typing import Any, Dict, Final, Optional, Union, cast

from .coordinator import OigCloudDataUpdateCoordinator
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

# Language translations
_LANGS: Final[Dict[str, Dict[str, str]]] = {
    "on": {
        "en": "On",
        "cs": "Zapnuto",
    },
    "off": {
        "en": "Off",
        "cs": "Vypnuto",
    },
    "unknown": {
        "en": "Unknown",
        "cs": "Neznámý",
    },
    "changing": {
        "en": "Changing in progress",
        "cs": "Probíhá změna",
    },
}


class OigCloudComputedSensor(OigCloudSensor):
    """Sensor that computes its value from multiple data points in the OIG Cloud API data."""

    @property
    def state(self) -> Optional[Union[float, str]]:
        """Return the state of the sensor."""
        _LOGGER.debug(f"Getting state for computed sensor {self.entity_id}")
        
        # Check if we have data
        if not self.coordinator.data:
            _LOGGER.debug(f"No data available for {self.entity_id}")
            return None
            
        # Get the box data
        box_id = list(self.coordinator.data.keys())[0]
        pv_data = self.coordinator.data[box_id]
        
        # Handle each computed sensor type
        try:
            # Total grid consumption (sum of all lines)
            if self._sensor_type == "ac_in_aci_wtotal":
                return self._compute_ac_in_total(pv_data)
                
            # Total actual grid consumption
            if self._sensor_type == "actual_aci_wtotal":
                return self._compute_actual_ac_in_total(pv_data)
                
            # Total solar production
            if self._sensor_type == "dc_in_fv_total":
                return self._compute_dc_in_total(pv_data)
                
            # Total actual solar production
            if self._sensor_type == "actual_fv_total":
                return self._compute_actual_fv_total(pv_data)
                
            # Boiler consumption
            if self._node_id == "boiler" or self._sensor_type == "boiler_current_w":
                return self._get_boiler_consumption(pv_data)
                
            # Battery charging power
            if self._sensor_type == "batt_batt_comp_p_charge":
                return self._get_batt_power_charge(pv_data)
                
            # Battery discharging power
            if self._sensor_type == "batt_batt_comp_p_discharge":
                return self._get_batt_power_discharge(pv_data)
                
            # CBB consumption (system consumption)
            # if self._sensor_type == "cbb_consumption_w":
            #     return self._get_cbb_consumption(pv_data)
                
            return None
            
        except (KeyError, TypeError, ValueError) as e:
            _LOGGER.warning(f"Error computing value for {self.entity_id}: {e}")
            return None

    def _compute_ac_in_total(self, pv_data: Dict[str, Any]) -> float:
        """Compute the total grid power from all three lines."""
        if "ac_in" not in pv_data or not isinstance(pv_data["ac_in"], dict):
            raise KeyError("ac_in data not available")
            
        return float(
            pv_data["ac_in"]["aci_wr"]
            + pv_data["ac_in"]["aci_ws"]
            + pv_data["ac_in"]["aci_wt"]
        )

    def _compute_actual_ac_in_total(self, pv_data: Dict[str, Any]) -> float:
        """Compute the actual total grid power from all three lines."""
        if "actual" not in pv_data or not isinstance(pv_data["actual"], dict):
            raise KeyError("actual data not available")
            
        return float(
            pv_data["actual"]["aci_wr"]
            + pv_data["actual"]["aci_ws"]
            + pv_data["actual"]["aci_wt"]
        )

    def _compute_dc_in_total(self, pv_data: Dict[str, Any]) -> float:
        """Compute the total solar power production."""
        if "dc_in" not in pv_data or not isinstance(pv_data["dc_in"], dict):
            raise KeyError("dc_in data not available")
            
        return float(pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])

    def _compute_actual_fv_total(self, pv_data: Dict[str, Any]) -> float:
        """Compute the actual total solar power production."""
        if "actual" not in pv_data or not isinstance(pv_data["actual"], dict):
            raise KeyError("actual data not available")
            
        return float(pv_data["actual"]["fv_p1"] + pv_data["actual"]["fv_p2"])

    def _get_cbb_consumption(self, pv_data: Dict[str, Any]) -> float:
        """Compute the CBB (system) consumption based on power flow."""
        # Check required data is available
        if ("dc_in" not in pv_data or "ac_out" not in pv_data or
            "ac_in" not in pv_data or "batt" not in pv_data):
            raise KeyError("Required data for CBB consumption calculation not available")
        
        # Get boiler power if available
        boiler_p: float = 0
        if "boiler" in pv_data and isinstance(pv_data["boiler"], dict) and "p" in pv_data["boiler"]:
            boiler_power = pv_data["boiler"]["p"]
            if boiler_power is not None and boiler_power > 0:
                boiler_p = float(boiler_power)
        
        # Calculate system consumption using power flow equation
        return float(
            # Solar production
            (pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])
            -
            # Boiler consumption
            boiler_p
            -
            # Load consumption
            pv_data["ac_out"]["aco_p"]
            +
            # Grid import/export
            (
                pv_data["ac_in"]["aci_wr"]
                + pv_data["ac_in"]["aci_ws"]
                + pv_data["ac_in"]["aci_wt"]
            )
            +
            # Battery charging/discharging
            (pv_data["batt"]["bat_i"] * pv_data["batt"]["bat_v"] * -1)
        )

    def _get_batt_power_charge(self, pv_data: Dict[str, Any]) -> float:
        """Get the battery charging power (positive values only)."""
        if "actual" not in pv_data or "bat_p" not in pv_data["actual"]:
            raise KeyError("Battery power data not available")
            
        battery_power = float(pv_data["actual"]["bat_p"])
        
        # Return only positive values (charging), otherwise return 0
        return battery_power if battery_power > 0 else 0
            
    def _get_batt_power_discharge(self, pv_data: Dict[str, Any]) -> float:
        """Get the battery discharging power (converted to positive value)."""
        if "actual" not in pv_data or "bat_p" not in pv_data["actual"]:
            raise KeyError("Battery power data not available")
            
        battery_power = float(pv_data["actual"]["bat_p"])
        
        # Return absolute value of negative power (discharging), otherwise return 0
        return abs(battery_power) if battery_power < 0 else 0

    def _get_boiler_consumption(self, pv_data: Dict[str, Any]) -> Optional[float]:
        """Calculate the boiler consumption."""
        # Check if boiler data is available
        if "boiler" not in pv_data or not pv_data["boiler"]:
            return None
            
        if not isinstance(pv_data["boiler"], dict) or "p" not in pv_data["boiler"]:
            return None
            
        boiler_power = pv_data["boiler"]["p"]
        if boiler_power is None:
            return None
            
        # Calculation for boiler_current_w
        if self._sensor_type == "boiler_current_w":
            # Calculate grid power
            if "ac_in" in pv_data and isinstance(pv_data["ac_in"], dict):
                grid_power = (
                    pv_data["ac_in"]["aci_wr"]
                    + pv_data["ac_in"]["aci_ws"]
                    + pv_data["ac_in"]["aci_wt"]
                )
                
                # If we're exporting to grid (negative grid value) and boiler is active
                if boiler_power > 0 and grid_power < 0:
                    # Adjust boiler consumption by grid export
                    return float(boiler_power + grid_power)
                    
            # Default case - just return the boiler power
            return float(boiler_power)
            
        return None

    async def async_update(self) -> None:
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()
