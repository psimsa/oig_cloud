import logging
from datetime import datetime, timedelta

from homeassistant.helpers.event import async_track_time_change
from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

_LANGS = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Vypnuto", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
}

class OigCloudComputedSensor(OigCloudSensor):
    def __init__(self, coordinator, sensor_type: str):
        super().__init__(coordinator, sensor_type)
        self._last_update = None

        self._energy = {
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

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        async_track_time_change(self.hass, self._reset_daily, hour=0, minute=0, second=0)

    async def _reset_daily(self, *_):
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
    def state(self):
        if self.coordinator.data is None:
            return None

        data = self.coordinator.data
        pv_data = list(data.values())[0]

        if self._sensor_type == "ac_in_aci_wtotal":
            return float(pv_data["ac_in"]["aci_wr"] + pv_data["ac_in"]["aci_ws"] + pv_data["ac_in"]["aci_wt"])
        if self._sensor_type == "actual_aci_wtotal":
            return float(pv_data["actual"]["aci_wr"] + pv_data["actual"]["aci_ws"] + pv_data["actual"]["aci_wt"])
        if self._sensor_type == "dc_in_fv_total":
            return float(pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])
        if self._sensor_type == "actual_fv_total":
            return float(pv_data["actual"]["fv_p1"] + pv_data["actual"]["fv_p2"])

        if self._node_id == "boiler" or self._sensor_type == "boiler_current_w":
            return self._get_boiler_consumption(pv_data)

        if self._sensor_type == "batt_batt_comp_p_charge":
            return self._get_batt_power_charge(pv_data)
        if self._sensor_type == "batt_batt_comp_p_discharge":
            return self._get_batt_power_discharge(pv_data)

        if self._sensor_type.startswith("computed_batt_"):
            return self._accumulate_energy(pv_data)

        return None

    def _accumulate_energy(self, pv_data):
        try:
            now = datetime.utcnow()

            bat_power = float(pv_data["actual"]["bat_p"])
            fv_power = float(pv_data["actual"]["fv_p1"]) + float(pv_data["actual"]["fv_p2"])
            grid_power = float(pv_data["actual"]["aci_wr"]) + float(pv_data["actual"]["aci_ws"]) + float(pv_data["actual"]["aci_wt"])

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

                _LOGGER.debug(f"[{self.entity_id}] Δt={delta_seconds:.1f}s bat={bat_power:.1f}W fv={fv_power:.1f}W -> ΔWh={wh_increment:.4f}")

            self._last_update = now

            # Vybereme výstup podle typu senzoru
            return self._get_energy_value()

        except Exception as e:
            _LOGGER.error(f"Error calculating energy: {e}", exc_info=True)
            return None

    def _get_energy_value(self):
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

    def _get_boiler_consumption(self, pv_data):
        if self._sensor_type != "boiler_current_w":
            return None
        try:
            fv_power = float(pv_data["actual"]["fv_p1"]) + float(pv_data["actual"]["fv_p2"])
            load_power = float(pv_data["actual"]["aco_p"])
            export_power = float(pv_data["actual"]["aci_wr"]) + float(pv_data["actual"]["aci_ws"]) + float(pv_data["actual"]["aci_wt"])
            net_power = fv_power - load_power - export_power
            boiler_power = max(net_power, 0)
            _LOGGER.debug(f"[{self.entity_id}] Estimated boiler power: FVE={fv_power}W, Load={load_power}W, Export={export_power}W -> Boiler={boiler_power}W")
            return round(boiler_power, 2)
        except Exception as e:
            _LOGGER.error(f"Error calculating boiler consumption: {e}", exc_info=True)
            return None

    def _get_batt_power_charge(self, pv_data) -> float:
        return max(float(pv_data["actual"]["bat_p"]), 0)

    def _get_batt_power_discharge(self, pv_data) -> float:
        return max(-float(pv_data["actual"]["bat_p"]), 0)

    async def async_update(self):
        await self.coordinator.async_request_refresh()