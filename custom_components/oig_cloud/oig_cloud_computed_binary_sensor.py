import logging
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi
from custom_components.oig_cloud.const import DOMAIN

from custom_components.oig_cloud.oig_cloud_binary_sensor import OigCloudBinarySensor


_LOGGER = logging.getLogger(__name__)


class OigCloudComputedBinarySensor(OigCloudBinarySensor):
    """A binary sensor that computes its state based on other data.

    This binary sensor extends the `OigCloudBinarySensor` class and computes its state based on the
    type of sensor specified in the `sensor_type` attribute. If the sensor type is "oig_cloud_call_pending",
    the state will be True if there is a call in progress, and False otherwise. If the sensor type is
    not recognized, the state will be None.

    Attributes:
        coordinator (DataUpdateCoordinator): The data coordinator for the OigCloud API.
        sensor_type (str): The type of sensor to compute the state for.
        entity_id (str): The entity ID for the binary sensor.
        name (str): The name of the binary sensor.
    """
    @property
    def state(self):
        _LOGGER.debug("Getting state for %s", self.entity_id)
        if self.coordinator.data is None:
            _LOGGER.debug("Data is None for %s", self.entity_id)
            return None

        if self._sensor_type == "oig_cloud_call_pending":
            oig_api: OigCloudApi = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]
            return oig_api.call_in_progress
            
        return None