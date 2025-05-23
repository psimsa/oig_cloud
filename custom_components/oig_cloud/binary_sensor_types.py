from typing import Dict, Optional

# Import TypedDict if using Python < 3.8, otherwise it's in typing
# For Home Assistant, which supports Python 3.9+ (as of core 2022.x),
# TypedDict is directly available from typing.
from typing import TypedDict

# BinarySensorDeviceClass is imported for context, as the 'device_class' strings
# in the TypedDict values will typically correspond to members of this enum.
# However, the type hint in the TypedDict itself will be Optional[str] if raw strings are stored.
from homeassistant.components.binary_sensor import BinarySensorDeviceClass


class OigCloudBinarySensorTypeDescription(TypedDict):
    """Describes the structure for individual binary sensor type definitions."""
    name: str  # Default name (usually English)
    name_cs: str  # Czech name
    node_id: str  # The key for the main data node in the API response (e.g., "summary", "boiler_prms")
    node_key: str  # The specific key within the node_id's data dict
    device_class: Optional[str]  # String representation of BinarySensorDeviceClass, or None


# Constant defining the types of binary sensors provided by the OIG Cloud integration.
# The keys are unique identifiers for the sensor types (e.g., "power_failure", "heating_active").
# The values are dictionaries adhering to the OigCloudBinarySensorTypeDescription structure.
BINARY_SENSOR_TYPES: Dict[str, OigCloudBinarySensorTypeDescription] = {
    # Example entry (actual entries would be specific to the OIG Cloud API):
    # "system_ok": {
    #     "name": "System Status",
    #     "name_cs": "Stav systému",
    #     "node_id": "status_indicators", # Hypothetical API node
    #     "node_key": "overall_ok",       # Hypothetical API key
    #     "device_class": BinarySensorDeviceClass.PROBLEM, # Stored as "problem"
    # },
    # "grid_available": {
    #     "name": "Grid Power",
    #     "name_cs": "Napájení ze sítě",
    #     "node_id": "power_source",
    #     "node_key": "grid_on",
    #     "device_class": BinarySensorDeviceClass.POWER, # Stored as "power"
    # },
    # Actual entries for BINARY_SENSOR_TYPES should be populated here based on
    # the specific binary sensor data points available from the OIG Cloud API.
    # For now, it remains empty as per the original file, but is now correctly typed.
}
