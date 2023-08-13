import logging

from custom_components.oig_cloud.oig_cloud_binary_sensor import OigCloudBinarySensor

from custom_components.oig_cloud.const import (
    DOMAIN,
)
from custom_components.oig_cloud.binary_sensor_types import BINARY_SENSOR_TYPES
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)


class OigCloudComputedBinarySensor(OigCloudBinarySensor):
    @property
    def state(self):
        _LOGGER.debug(f"Getting state for {self.entity_id}")
        if self.coordinator.data is None:
            _LOGGER.debug(f"Data is None for {self.entity_id}")
            return None
        # data = self.coordinator.data

        if self._sensor_type == "oig_cloud_call_pending":
            oig_api: OigCloudApi = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]
            return oig_api.call_in_progress