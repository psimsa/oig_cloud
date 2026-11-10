"""Linking of OIG service devices (Analytics, ServiceShield) to the main box device.

Home Assistant 2026.8 deprecated ``DeviceInfo["via_device"]`` in favour of
``via_device_id``. When the deprecated key comes from an entity's ``device_info``,
Home Assistant cannot attribute the call to an integration and raises a
``RuntimeError``, so the entity is never added. This module builds the right key
for the running Home Assistant version and keeps older versions working.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info_fields() -> Any:
    """Return the field names of DeviceInfo (a dataclass in HA 2026.11+, a TypedDict before)."""
    return getattr(DeviceInfo, "__dataclass_fields__", None) or getattr(
        DeviceInfo, "__annotations__", {}
    )


SUPPORTS_VIA_DEVICE_ID: bool = "via_device_id" in _device_info_fields() and hasattr(
    dr, "async_get_device_id_by_identifier"
)


def _is_valid_box_id(box_id: Any) -> bool:
    return isinstance(box_id, str) and box_id.isdigit()


def ensure_main_device(
    hass: HomeAssistant, config_entry_id: str, box_id: Any
) -> Optional[str]:
    """Make sure the main box device exists, so service devices can link to it.

    Must run before the sensor platform adds entities. Returns the device id, or
    None when not applicable (older Home Assistant or unknown box id).
    """
    if not SUPPORTS_VIA_DEVICE_ID or not _is_valid_box_id(box_id):
        return None
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry_id,
        identifiers={(DOMAIN, box_id)},
    )
    return device.id


def via_main_device(
    hass: Optional[HomeAssistant], config_entry_id: Optional[str], box_id: Any
) -> Dict[str, Any]:
    """Return the device-info key linking a service device to the main box device.

    Meant to be unpacked into a device-info dict or ``DeviceInfo(...)``. Returns an
    empty dict when the main device can't be resolved; the service device is then
    created without a link instead of failing.
    """
    if not SUPPORTS_VIA_DEVICE_ID:
        return {"via_device": (DOMAIN, box_id)}
    if hass is None or not config_entry_id or not _is_valid_box_id(box_id):
        return {}
    try:
        return {
            "via_device_id": dr.async_get_device_id_by_identifier(
                hass, (DOMAIN, box_id), config_entry_id=config_entry_id
            )
        }
    except ValueError:
        _LOGGER.debug("Main device for box %s not registered yet", box_id)
        return {}


def entity_config_entry_id(entity: Any) -> Optional[str]:
    """Return the config entry id of an entity (platform first, then coordinator)."""
    platform = getattr(entity, "platform", None)
    entry = getattr(platform, "config_entry", None)
    if entry is None:
        entry = getattr(getattr(entity, "coordinator", None), "config_entry", None)
    return getattr(entry, "entry_id", None)
