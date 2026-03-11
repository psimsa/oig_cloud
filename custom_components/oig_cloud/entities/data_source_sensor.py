"""Sensor indicating whether OIG Cloud is currently using Local or Cloud data."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from ..const import DEFAULT_NAME, DOMAIN
from ..core.data_source import (
    DATA_SOURCE_HYBRID,
    DATA_SOURCE_LOCAL_ONLY,
    PROXY_LAST_DATA_ENTITY_ID,
    get_data_source_state,
)
from .base_sensor import resolve_box_id

_LOGGER = logging.getLogger(__name__)


class OigCloudDataSourceSensor(SensorEntity):
    """Show whether integration is currently sourcing data from Local or Cloud."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:database-sync"
    _attr_translation_key = "data_source"

    def __init__(self, hass: HomeAssistant, coordinator: Any, entry: Any) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry
        # Použij stejnou autodetekci jako ostatní senzory
        self._box_id = resolve_box_id(coordinator)
        self._attr_name = "Data source"
        self.entity_id = f"sensor.oig_{self._box_id}_data_source"
        self._unsubs: list[callable] = []

    @property
    def unique_id(self) -> str:
        return f"oig_cloud_{self._box_id}_data_source"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._box_id)},
            name=f"{DEFAULT_NAME} {self._box_id}",
            manufacturer="OIG",
            model=DEFAULT_NAME,
        )

    @property
    def state(self) -> str:
        ds = get_data_source_state(self.hass, self.entry.entry_id)
        if (
            ds.effective_mode in (DATA_SOURCE_LOCAL_ONLY, DATA_SOURCE_HYBRID)
            and ds.local_available
        ):
            return "local"
        return "cloud"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        ds = get_data_source_state(self.hass, self.entry.entry_id)
        last_dt: Optional[str] = (
            ds.last_local_data.isoformat() if ds.last_local_data else None
        )
        return {
            "configured_mode": ds.configured_mode,
            "effective_mode": ds.effective_mode,
            "local_available": ds.local_available,
            "last_local_data": last_dt,
            "reason": ds.reason,
        }

    async def async_added_to_hass(self) -> None:
        @callback
        def _refresh(*_: Any) -> None:
            self.async_write_ha_state()

        # refresh on proxy sensor changes
        self._unsubs.append(
            async_track_state_change_event(
                self.hass,
                PROXY_LAST_DATA_ENTITY_ID,
                _refresh,
            )
        )
        # periodic refresh to catch controller changes
        self._unsubs.append(
            async_track_time_interval(self.hass, _refresh, timedelta(seconds=30))
        )
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception as err:
                _LOGGER.debug("Failed to unsubscribe data source listener: %s", err)
        self._unsubs.clear()
        await super().async_will_remove_from_hass()
