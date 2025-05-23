from typing import Dict, List, Optional, TypedDict, Final, Union

# Imports for context, as their string representations are often stored in SENSOR_TYPES
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory # For entity_category context

# Import individual sensor type dictionaries
# These imported dictionaries are assumed to conform to Dict[str, OigSensorTypeDescription]
from custom_components.oig_cloud.sensors.SENSOR_TYPES_ACTUAL import SENSOR_TYPES_ACTUAL
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_OUT import SENSOR_TYPES_AC_OUT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BATT import SENSOR_TYPES_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOILER import SENSOR_TYPES_BOILER
from custom_components.oig_cloud.sensors.SENSOR_TYPES_BOX import SENSOR_TYPES_BOX
from custom_components.oig_cloud.sensors.SENSOR_TYPES_MISC import SENSOR_TYPES_MISC
from custom_components.oig_cloud.sensors.SENSOR_TYPES_DC_IN import SENSOR_TYPES_DC_IN
from custom_components.oig_cloud.sensors.SENSOR_TYPES_AC_IN import SENSOR_TYPES_AC_IN

from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_BATT import SENSOR_TYPES_EXTENDED_BATT
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_FVE import SENSOR_TYPES_EXTENDED_FVE
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_GRID import SENSOR_TYPES_EXTENDED_GRID
from custom_components.oig_cloud.sensors.SENSOR_TYPES_EXTENDED_LOAD import SENSOR_TYPES_EXTENDED_LOAD


class OigSensorTypeDescription(TypedDict, total=False):
    """Describes the structure for individual sensor type definitions in SENSOR_TYPES."""
    name: str  # Required: English name
    name_cs: str  # Required: Czech name
    node_id: Optional[str]
    node_key: Optional[str]
    value_path: Optional[str] # Path for nested data, e.g. "data.value"
    icon: Optional[str]
    unit_of_measurement: Optional[str]
    device_class: Optional[str] # String representation of SensorDeviceClass
    state_class: Optional[str]  # String representation of SensorStateClass
    entity_category: Optional[str] # String representation of EntityCategory
    options: Optional[List[str]] # For sensors with predefined options (e.g., select)
    disabled: Optional[bool] # If the entity should be disabled by default (user can enable)
    default_disabled: Optional[bool] # Alternative for disabled, often used by HA itself.
                                     # Prefer 'disabled' for clarity if choosing one.
    multiplier: Optional[Union[float, int]]
    precision: Optional[int]
    # value_func: Optional[Callable[[Any], Any]] # If a function is needed to derive value (not serializable in JSON/YAML)


# Global dictionary for all sensor type definitions.
# Each key is a unique sensor_type string, and the value is an OigSensorTypeDescription.
SENSOR_TYPES: Final[Dict[str, OigSensorTypeDescription]] = {}

# Populate SENSOR_TYPES by updating with imported dictionaries.
# It's assumed that the imported dictionaries conform to Dict[str, OigSensorTypeDescription].
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
