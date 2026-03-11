"""Planner recommended mode sensor extracted from legacy battery forecast."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ...const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OigCloudPlannerRecommendedModeSensor(
    RestoreEntity, CoordinatorEntity, SensorEntity
):
    """Text sensor exposing the planner's recommended mode for the current interval."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        config_entry: ConfigEntry,
        device_info: Dict[str, Any],
        hass: Optional[HomeAssistant] = None,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._config_entry = config_entry
        self._hass: Optional[HomeAssistant] = hass or getattr(coordinator, "hass", None)
        self._attr_device_info = device_info

        from ...sensor_types import SENSOR_TYPES

        self._config = SENSOR_TYPES.get(sensor_type, {})

        try:
            from ...entities.base_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"

        self._precomputed_store: Optional[Store] = None
        self._precomputed_payload: Optional[Dict[str, Any]] = None
        if self._hass:
            self._precomputed_store = Store(
                self._hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )

        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        name_cs = self._config.get("name_cs")
        name_en = self._config.get("name")
        self._attr_name = name_cs or name_en or sensor_type
        self._attr_icon = self._config.get("icon", "mdi:robot")
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

        entity_category = self._config.get("entity_category")
        if entity_category:
            self._attr_entity_category = EntityCategory(entity_category)

        self._attr_native_value: Optional[str] = None
        self._attr_extra_state_attributes: Dict[str, Any] = {}
        self._last_signature: Optional[str] = None
        self._unsubs: list[callable] = []

    async def _async_refresh_precomputed_payload(self) -> None:
        if not self._precomputed_store:
            return
        try:
            precomputed = await self._precomputed_store.async_load()
        except Exception:
            return
        if not isinstance(precomputed, dict):
            return
        timeline = precomputed.get("timeline") or precomputed.get("timeline_hybrid")
        detail_tabs = precomputed.get("detail_tabs") or precomputed.get(
            "detail_tabs_hybrid"
        )
        if not isinstance(timeline, list) or not timeline:
            return
        self._precomputed_payload = {
            "timeline_data": timeline,
            "calculation_time": precomputed.get("last_update"),
            "detail_tabs": detail_tabs if isinstance(detail_tabs, dict) else None,
        }

    def _get_forecast_payload(self) -> Optional[Dict[str, Any]]:
        # Prefer precomputed payload to stay aligned with detail_tabs output.
        if isinstance(self._precomputed_payload, dict):
            return self._precomputed_payload
        data = getattr(self.coordinator, "battery_forecast_data", None)
        if isinstance(data, dict) and isinstance(data.get("timeline_data"), list):
            return data
        return None

    def _parse_local_start(self, ts: Any) -> Optional[datetime]:
        if not ts:
            return None
        try:
            dt_obj = dt_util.parse_datetime(str(ts)) or datetime.fromisoformat(str(ts))
        except Exception:
            return None
        if dt_obj.tzinfo is None:
            return dt_obj.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_local(dt_obj)

    def _parse_interval_time(
        self, ts: Any, date_hint: Optional[str] = None
    ) -> Optional[datetime]:
        if not ts:
            return None
        ts_str = str(ts)
        if "T" not in ts_str and date_hint:
            ts_str = f"{date_hint}T{ts_str}:00"
        return self._parse_local_start(ts_str)

    def _normalize_mode_label(
        self, mode_name: Optional[str], mode_code: Optional[int]
    ) -> Optional[str]:
        if mode_name:
            upper = str(mode_name).strip().upper()
            if "UPS" in upper:
                return "Home UPS"
            if "HOME III" in upper:
                return "Home 3"
            if "HOME II" in upper:
                return "Home 2"
            if "HOME I" in upper:
                return "Home 1"
            if upper in {"HOME 1", "HOME 2", "HOME 3", "HOME UPS"}:
                return str(mode_name).title()

        if isinstance(mode_code, int):
            if mode_code == 0:
                return "Home 1"
            if mode_code == 1:
                return "Home 2"
            if mode_code == 2:
                return "Home 3"
            if mode_code == 3:
                return "Home UPS"
        return None

    def _get_auto_switch_lead_seconds(
        self, from_mode: Optional[str], to_mode: Optional[str]
    ) -> float:
        fallback = 180.0
        if self._config_entry and self._config_entry.options:
            fallback = float(
                self._config_entry.options.get(
                    "auto_mode_switch_lead_seconds",
                    self._config_entry.options.get(
                        "autonomy_switch_lead_seconds", 180.0
                    ),
                )
            )
        if not from_mode or not to_mode or not self._hass or not self._config_entry:
            return fallback
        try:
            entry = self._hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
            service_shield = entry.get("service_shield")
            mode_tracker = getattr(service_shield, "mode_tracker", None)
            if not mode_tracker:
                return fallback
            offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)
            if offset_seconds is None or offset_seconds <= 0:
                return fallback
            return float(offset_seconds)
        except Exception:
            return fallback

    def _compute_state_and_attrs(self) -> tuple[Optional[str], Dict[str, Any], str]:
        """Compute recommended mode + attributes and return signature for change detection."""
        attrs: Dict[str, Any] = {}
        payload = self._get_forecast_payload() or {}
        detail_tabs = (
            payload.get("detail_tabs")
            if isinstance(payload.get("detail_tabs"), dict)
            else None
        )
        timeline = payload.get("timeline_data")
        attrs["last_update"] = payload.get("calculation_time")
        detail_intervals: Optional[list[Dict[str, Any]]] = None
        detail_date: Optional[str] = None
        if isinstance(detail_tabs, dict):
            today_tab = detail_tabs.get("today") or {}
            if isinstance(today_tab, dict):
                detail_intervals = today_tab.get("intervals")
                detail_date = today_tab.get("date")

        source_intervals = (
            detail_intervals if isinstance(detail_intervals, list) else timeline
        )
        attrs["points_count"] = (
            len(source_intervals) if isinstance(source_intervals, list) else 0
        )

        if not isinstance(source_intervals, list) or not source_intervals:
            sig = json.dumps({"v": None, "a": attrs}, sort_keys=True, default=str)
            return None, attrs, sig

        now = dt_util.now()
        current_idx: Optional[int] = None
        current_mode: Optional[str] = None
        current_mode_code: Optional[int] = None
        current_start: Optional[datetime] = None

        if detail_intervals and isinstance(detail_intervals, list):

            def _planned_mode(
                interval: Dict[str, Any],
            ) -> tuple[Optional[str], Optional[int]]:
                planned = interval.get("planned") or {}
                mode_label = self._normalize_mode_label(
                    planned.get("mode_name"), planned.get("mode")
                )
                mode_code = (
                    planned.get("mode")
                    if isinstance(planned.get("mode"), int)
                    else None
                )
                return mode_label, mode_code

            for i, item in enumerate(detail_intervals):
                start = self._parse_interval_time(
                    item.get("time") or item.get("timestamp"), detail_date
                )
                if not start:
                    continue
                end = start + timedelta(minutes=15)
                mode_label, mode_code = _planned_mode(item)
                if not mode_label:
                    continue
                if start <= now < end:
                    current_idx = i
                    current_start = start
                    current_mode = mode_label
                    current_mode_code = mode_code
                    break
                if start <= now:
                    current_idx = i
                    current_start = start
                    current_mode = mode_label
                    current_mode_code = mode_code
                if start > now and current_idx is not None:
                    break

            if current_mode is None and isinstance(timeline, list):
                for i, item in enumerate(timeline):
                    start = self._parse_local_start(
                        item.get("time") or item.get("timestamp")
                    )
                    if not start:
                        continue
                    end = start + timedelta(minutes=15)
                    if start <= now < end:
                        current_idx = i
                        current_start = start
                        current_mode = self._normalize_mode_label(
                            item.get("mode_name"), item.get("mode")
                        )
                        current_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                        break
                    if start <= now:
                        current_idx = i
                        current_start = start
                        current_mode = self._normalize_mode_label(
                            item.get("mode_name"), item.get("mode")
                        )
                        current_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                    if start > now and current_idx is not None:
                        break
        else:
            for i, item in enumerate(source_intervals):
                start = self._parse_local_start(
                    item.get("time") or item.get("timestamp")
                )
                if not start:
                    continue
                end = start + timedelta(minutes=15)
                if start <= now < end:
                    current_idx = i
                    current_start = start
                    current_mode = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    current_mode_code = (
                        item.get("mode") if isinstance(item.get("mode"), int) else None
                    )
                    break
                if start <= now:
                    current_idx = i
                    current_start = start
                    current_mode = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    current_mode_code = (
                        item.get("mode") if isinstance(item.get("mode"), int) else None
                    )
                if start > now and current_idx is not None:
                    break

        attrs["recommended_interval_start"] = (
            current_start.isoformat() if isinstance(current_start, datetime) else None
        )

        next_change_at: Optional[datetime] = None
        next_mode: Optional[str] = None
        next_mode_code: Optional[int] = None
        if current_idx is not None and current_mode:
            if detail_intervals and isinstance(detail_intervals, list):
                for item in detail_intervals[current_idx + 1 :]:
                    start = self._parse_interval_time(
                        item.get("time") or item.get("timestamp"), detail_date
                    )
                    if not start:
                        continue
                    planned = item.get("planned") or {}
                    candidate = self._normalize_mode_label(
                        planned.get("mode_name"), planned.get("mode")
                    )
                    if candidate and candidate != current_mode:
                        next_change_at = start
                        next_mode = candidate
                        next_mode_code = (
                            planned.get("mode")
                            if isinstance(planned.get("mode"), int)
                            else None
                        )
                        break
            else:
                for item in source_intervals[current_idx + 1 :]:
                    start = self._parse_local_start(
                        item.get("time") or item.get("timestamp")
                    )
                    if not start:
                        continue
                    candidate = self._normalize_mode_label(
                        item.get("mode_name"), item.get("mode")
                    )
                    if candidate and candidate != current_mode:
                        next_change_at = start
                        next_mode = candidate
                        next_mode_code = (
                            item.get("mode")
                            if isinstance(item.get("mode"), int)
                            else None
                        )
                        break

        attrs["next_mode_change_at"] = (
            next_change_at.isoformat() if next_change_at else None
        )
        attrs["next_mode"] = next_mode
        attrs["next_mode_code"] = next_mode_code

        effective_mode = current_mode
        effective_mode_code = current_mode_code
        lead_seconds: Optional[float] = 0.0
        effective_from: Optional[datetime] = None
        if next_change_at and next_mode and current_mode:
            lead_seconds = self._get_auto_switch_lead_seconds(current_mode, next_mode)
            if lead_seconds and lead_seconds > 0:
                effective_from = next_change_at - timedelta(seconds=lead_seconds)
            else:
                lead_seconds = 0.0

        attrs["planned_interval_mode"] = current_mode
        attrs["planned_interval_mode_code"] = current_mode_code
        attrs["recommended_mode"] = effective_mode
        attrs["recommended_mode_code"] = effective_mode_code
        attrs["recommended_effective_from"] = (
            effective_from.isoformat() if effective_from else None
        )
        attrs["auto_switch_lead_seconds"] = lead_seconds

        sig = json.dumps(
            {
                "v": effective_mode,
                "c": effective_mode_code,
                "cv": current_mode,
                "cc": current_mode_code,
                "s": attrs.get("recommended_interval_start"),
                "n": attrs.get("next_mode_change_at"),
                "nv": next_mode,
                "nc": next_mode_code,
                "ef": attrs.get("recommended_effective_from"),
                "ls": lead_seconds,
                "lu": attrs.get("last_update"),
                "pc": attrs.get("points_count"),
            },
            sort_keys=True,
            default=str,
        )
        return effective_mode, attrs, sig

    async def _async_recompute(self) -> None:
        try:
            await self._async_refresh_precomputed_payload()
            value, attrs, sig = self._compute_state_and_attrs()
            if sig == self._last_signature:
                return
            self._last_signature = sig
            self._attr_native_value = value
            self._attr_extra_state_attributes = attrs
            if self.hass:
                self.async_write_ha_state()
        except Exception:
            return

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._precomputed_store and self.hass:
            self._precomputed_store = Store(
                self.hass,
                version=1,
                key=f"oig_cloud.precomputed_data_{self._box_id}",
            )

        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from homeassistant.helpers.event import async_track_time_change

        signal_name = f"oig_cloud_{self._box_id}_forecast_updated"

        async def _on_forecast_updated() -> None:
            self.hass.async_create_task(self._async_recompute())

        try:
            self._unsubs.append(
                async_dispatcher_connect(self.hass, signal_name, _on_forecast_updated)
            )
        except Exception:  # nosec B110
            pass

        async def _on_tick(_now: datetime) -> None:
            self.hass.async_create_task(self._async_recompute())

        try:
            for minute in [0, 15, 30, 45]:
                self._unsubs.append(
                    async_track_time_change(
                        self.hass, _on_tick, minute=minute, second=2
                    )
                )
        except Exception:  # nosec B110
            pass

        await self._async_recompute()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in getattr(self, "_unsubs", []) or []:
            try:
                unsub()
            except Exception:  # nosec B110
                pass
        self._unsubs = []
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return bool(self._attr_extra_state_attributes.get("points_count"))

    @property
    def native_value(self) -> Optional[str]:
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return dict(self._attr_extra_state_attributes)

    def _handle_coordinator_update(self) -> None:
        return
