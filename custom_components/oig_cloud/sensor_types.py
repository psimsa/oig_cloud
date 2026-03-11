import logging
from typing import Dict

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_IN import SENSOR_TYPES_AC_IN
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_OUT import SENSOR_TYPES_AC_OUT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_ACTUAL import SENSOR_TYPES_ACTUAL
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BATT import SENSOR_TYPES_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOILER import SENSOR_TYPES_BOILER
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOX import SENSOR_TYPES_BOX
from custom_components.oig_cloud.sensors.SENSOR_TYPES_CHMU import SENSOR_TYPES_CHMU
from custom_components.oig_cloud.sensors.SENSOR_TYPES_COMPUTED import (
    SENSOR_TYPES_COMPUTED,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_DC_IN import SENSOR_TYPES_DC_IN
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_BATT import (
    SENSOR_TYPES_EXTENDED_BATT,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_FVE import (
    SENSOR_TYPES_EXTENDED_FVE,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_GRID import (
    SENSOR_TYPES_EXTENDED_GRID,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_LOAD import (
    SENSOR_TYPES_EXTENDED_LOAD,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_MISC import SENSOR_TYPES_MISC
from custom_components.oig_cloud.sensors.SENSOR_TYPES_SHIELD import SENSOR_TYPES_SHIELD
from custom_components.oig_cloud.sensors.SENSOR_TYPES_SOLAR_FORECAST import (
    SENSOR_TYPES_SOLAR_FORECAST,
)
from custom_components.oig_cloud.sensors.SENSOR_TYPES_SPOT import SENSOR_TYPES_SPOT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_STATISTICS import (
    SENSOR_TYPES_STATISTICS,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {}
SENSOR_TYPES.update(SENSOR_TYPES_COMPUTED)
SENSOR_TYPES.update(SENSOR_TYPES_AC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_DC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_BOX)
SENSOR_TYPES.update(SENSOR_TYPES_BOILER)
SENSOR_TYPES.update(SENSOR_TYPES_BATT)
SENSOR_TYPES.update(SENSOR_TYPES_ACTUAL)
SENSOR_TYPES.update(SENSOR_TYPES_AC_OUT)
SENSOR_TYPES.update(SENSOR_TYPES_MISC)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_BATT)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_FVE)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_GRID)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_LOAD)
SENSOR_TYPES.update(SENSOR_TYPES_SOLAR_FORECAST)
SENSOR_TYPES.update(SENSOR_TYPES_STATISTICS)
SENSOR_TYPES.update(SENSOR_TYPES_SPOT)
SENSOR_TYPES.update(SENSOR_TYPES_CHMU)
SENSOR_TYPES.update(SENSOR_TYPES_SHIELD)
STATISTICS_SENSOR_TYPES = SENSOR_TYPES_STATISTICS

_LOGGER.debug("Loaded %s sensor types total", len(SENSOR_TYPES))
