import logging

from custom_components.oig_cloud.oig_cloud_sensor import OigCloudSensor

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
    def state(self):
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None
        language = self.hass.config.language
        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]

        # computed values
        if self._sensor_type == "ac_in_aci_wtotal":
            return float(
                pv_data["ac_in"]["aci_wr"]
                + pv_data["ac_in"]["aci_ws"]
                + pv_data["ac_in"]["aci_wt"]
            )

        if self._sensor_type == "batt_batt_comp_p":
            return float(pv_data["batt"]["bat_i"] * pv_data["batt"]["bat_v"] * -1)

        if self._sensor_type == "dc_in_fv_total":
            return float(pv_data["dc_in"]["fv_p1"] + pv_data["dc_in"]["fv_p2"])

        if self._node_id == "boiler" or self._sensor_type == "boiler_current_w":
            return self._get_boiler_consumption(pv_data)

        # Spotreba CBB
        if self._sensor_type == "cbb_consumption_w":
            return self._get_cbb_consumption(pv_data)

        return None

    def _get_cbb_consumption(self, pv_data) -> float:
        boiler_p = 0
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

    def _get_boiler_consumption(self, pv_data):
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
        else:
            return None

    async def async_update(self):
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()
