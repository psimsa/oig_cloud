import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .const import (
    DEFAULT_NAME,
    DOMAIN,
)
from .sensor_types import SENSOR_TYPES
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)

LANGS = {
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
}


class OigCloudSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, sensor_type):
        if not isinstance(sensor_type, str):
            raise TypeError("sensor_type must be a string")

        self.coordinator = coordinator
        self._sensor_type = sensor_type
        self._attr_state_class = SENSOR_TYPES[sensor_type]["state_class"]
        self._node_id = SENSOR_TYPES[sensor_type]["node_id"]
        self._node_key = SENSOR_TYPES[sensor_type]["node_key"]
        self._box_id = list(self.coordinator.data.keys())[0]
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"
        _LOGGER.debug(f"Created sensor {self.entity_id}")

    @property
    def name(self):
        """Return the name of the sensor."""
        language = self.hass.config.language
        if language == "cs":
            return SENSOR_TYPES[self._sensor_type]["name_cs"]
        return SENSOR_TYPES[self._sensor_type]["name"]

    @property
    def device_class(self):
        return SENSOR_TYPES[self._sensor_type]["device_class"]

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

        # Spotreba CBB
        if self._sensor_type == "cbb_consumption_w":
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
        
        try:
            node_value = pv_data[self._node_id][self._node_key]

            # special cases
            if self._sensor_type == "box_prms_mode":
                if node_value == 0:
                    return "Home 1"
                elif node_value == 1:
                    return "Home 2"
                elif node_value == 2:
                    return "Home 3"
                elif node_value == 3:
                    return "Home UPS"
                return LANGS["unknown"][language]

            # return node_value
            try:
                return float(node_value)
            except ValueError:
                return node_value
        except KeyError:
            return None

    @property
    def unit_of_measurement(self):
        return SENSOR_TYPES[self._sensor_type]["unit_of_measurement"]

    @property
    def unique_id(self):
        return f"oig_cloud_{self._box_id}_{self._sensor_type}"

    @property
    def entity_category(self):
        return SENSOR_TYPES[self._sensor_type].get("entity_category")

    @property
    def should_poll(self):
        # DataUpdateCoordinator handles polling
        return False

    @property
    def state_class(self):
        """Return the state class of the sensor."""
        return SENSOR_TYPES[self._sensor_type]["state_class"]

    @property
    def device_info(self):
        data = self.coordinator.data
        vals = data.values()
        pv_data = list(vals)[0]
        is_queen = pv_data["queen"]
        if is_queen:
            model_name = f"{DEFAULT_NAME} Queen"
        else:
            model_name = f"{DEFAULT_NAME} Home"

        return {
            "identifiers": {(DOMAIN, self._box_id)},
            "name": f"{model_name} {self._box_id}",
            "manufacturer": "OIG",
            "model": model_name,
        }

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    async def async_update(self):
        # Request the coordinator to fetch new data and update the entity's state
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.debug("async_setup_entry")

    oig_cloud: OigCloudApi = hass.data[DOMAIN][config_entry.entry_id]

    async def update_data():
        """Fetch data from API endpoint."""
        return await oig_cloud.get_stats()

    # We create a new DataUpdateCoordinator.
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="sensor",
        update_method=update_data,
        update_interval=timedelta(seconds=60),
    )

    # Fetch initial data so we have data when entities subscribe.
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("First refresh done, will add entities")

    # Add common entities
    async_add_entities(
        OigCloudSensor(coordinator, sensor_type)
        for sensor_type in SENSOR_TYPES
        if not "requires" in SENSOR_TYPES[sensor_type].keys()
    )

    box_id = list(oig_cloud.last_state.keys())[0]
    # Add entities that require 'boiler'
    if len(oig_cloud.last_state[box_id]["boiler"]) > 0:
        async_add_entities(
            OigCloudSensor(coordinator, sensor_type)
            for sensor_type in SENSOR_TYPES
            if "requires" in SENSOR_TYPES[sensor_type].keys()
            and "boiler" in SENSOR_TYPES[sensor_type]["requires"]
        )

    _LOGGER.debug("async_setup_entry done")
