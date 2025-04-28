from typing import Dict
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

# Import původních skupin senzorů
from custom_components.oig_cloud.sensors.SENSOR_TYPES_ACTUAL import SENSOR_TYPES_ACTUAL
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_OUT import SENSOR_TYPES_AC_OUT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BATT import SENSOR_TYPES_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOILER import SENSOR_TYPES_BOILER
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOX import SENSOR_TYPES_BOX
from custom_components.oig_cloud.sensors.SENSOR_TYPES_MISC import SENSOR_TYPES_MISC
from custom_components.oig_cloud.sensors.SENSOR_TYPES_DC_IN import SENSOR_TYPES_DC_IN
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_IN import SENSOR_TYPES_AC_IN

# Import rozšířených (nových) senzorů
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_BATT import SENSOR_TYPES_EXTENDED_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_FVE import SENSOR_TYPES_EXTENDED_FVE
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_GRID import SENSOR_TYPES_EXTENDED_GRID
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_LOAD import SENSOR_TYPES_EXTENDED_LOAD

# Globální seznam všech typů senzorů
SENSOR_TYPES: Dict[str, Dict[str, str | SensorDeviceClass | SensorStateClass]] = {}

# Původní senzory
SENSOR_TYPES.update(SENSOR_TYPES_AC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_DC_IN)
SENSOR_TYPES.update(SENSOR_TYPES_BOX)
SENSOR_TYPES.update(SENSOR_TYPES_BOILER)
SENSOR_TYPES.update(SENSOR_TYPES_BATT)
SENSOR_TYPES.update(SENSOR_TYPES_ACTUAL)
SENSOR_TYPES.update(SENSOR_TYPES_AC_OUT)
SENSOR_TYPES.update(SENSOR_TYPES_MISC)

# Rozšířené senzory (nové)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_BATT)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_FVE)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_GRID)
SENSOR_TYPES.update(SENSOR_TYPES_EXTENDED_LOAD)
