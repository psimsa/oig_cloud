import logging
from typing import Any, Dict, Optional, Union

from .oig_cloud_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

_LANGS = {
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
    @property
    def state(self) -> Optional[Union[float, str]]:
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None
        language: str = self.hass.config.language
        data: Dict[str, Any] = self.coordinator.data
        vals = data.values()
        pv_data: Dict[str, Any] = list(vals)[0]

        # computed values
        if self._sensor_type == "ac_in_aci_wtotal":
            return float(
                pv_data["ac_in"]["aci_wr"]
                + pv_data["ac_in"]["aci_ws"]
                + pv_data["ac_in"]["aci_wt"]
            )

        if self._sensor_type == "actual_aci_wtotal":
            return float(
                pv_data["actual"]["aci_wr"]
                + pv_data["actual"]["aci_ws"]
                + pv_data["actual"]["aci_wt"]
            )

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

        # Spotreba CBB
        # if self._sensor_type == "cbb_consumption_w":
        #     return self._get_cbb_consumption(pv_data)

        return None

    def _get_cbb_consumption(self, pv_data: Dict[str, Any]) -> float:
        boiler_p: float = 0
        if (
            len(pv_data["boiler"]) > 0
            and pv_data["boiler"]["p"] is not None
            and pv_data["boiler"]["p"] > 0
        ):
            boiler_p = pv_data["boiler"]["p"]
        return float(
            # Výkon FVE
            (pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])
            -
            # Spotřeba bojleru
            boiler_p
            -
            # Spotřeba zátěž
            pv_data["ac_out"]["aco_p"]
            +
            # Odběr ze sítě
            (
                pv_data["ac_in"]["aci_wr"]
                + pv_data["ac_in"]["aci_ws"]
                + pv_data["ac_in"]["aci_wt"]
            )
            +
            # Nabíjení/vybíjení baterie
            (pv_data["batt"]["bat_i"] * pv_data["batt"]["bat_v"] * -1)
        )

    def _get_batt_power_charge(self, pv_data: Dict[str, Any]) -> float:
        if (pv_data["actual"]["bat_p"] > 0):
            return float(pv_data["actual"]["bat_p"])
        else:
            return 0
            
    def _get_batt_power_discharge(self, pv_data: Dict[str, Any]) -> float:
        if (pv_data["actual"]["bat_p"] < 0):
            return float(pv_data["actual"]["bat_p"]*-1)
        else:
            return 0

    def _get_boiler_consumption(self, pv_data: Dict[str, Any]) -> Optional[float]:
        if len(pv_data["boiler"]) > 0 and pv_data["boiler"]["p"] is not None:
            # Spotreba bojleru
            if (
                self._sensor_type == "boiler_current_w"
                and pv_data["boiler"]["p"] > 0
                and (
                    pv_data["ac_in"]["aci_wr"]
                    + pv_data["ac_in"]["aci_ws"]
                    + pv_data["ac_in"]["aci_wt"]
                )
                < 0
            ):
                return float(
                    pv_data["boiler"]["p"]
                    + (
                        pv_data["ac_in"]["aci_wr"]
                        + pv_data["ac_in"]["aci_ws"]
                        + pv_data["ac_in"]["aci_wt"]
                    )
                )
            elif self._sensor_type == "boiler_current_w":
                return float(pv_data["boiler"]["p"])
        return None

    async def async_update(self) -> None:
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()
