"""Grid charging plan sensor extracted from legacy battery forecast."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ...const import DOMAIN

MODE_LABEL_HOME_UPS = "Home UPS"

_LOGGER = logging.getLogger(__name__)


class OigCloudGridChargingPlanSensor(CoordinatorEntity, SensorEntity):
    """Sensor pro plánované nabíjení ze sítě - odvozený z battery_forecast."""

    def __init__(
        self,
        coordinator: Any,
        sensor_type: str,
        device_info: Dict[str, Any],
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._attr_device_info = device_info

        from ...sensor_types import SENSOR_TYPES

        self._config = SENSOR_TYPES.get(sensor_type, {})

        try:
            from ...entities.base_sensor import resolve_box_id

            self._box_id = resolve_box_id(coordinator)
        except Exception:
            self._box_id = "unknown"
        self._attr_unique_id = f"oig_cloud_{self._box_id}_{sensor_type}"
        self.entity_id = f"sensor.oig_{self._box_id}_{sensor_type}"

        name_cs = self._config.get("name_cs")
        name_en = self._config.get("name")
        self._attr_name = name_cs or name_en or sensor_type

        self._attr_native_unit_of_measurement = self._config.get("unit")
        self._attr_icon = self._config.get("icon", "mdi:battery-charging")

        device_class = self._config.get("device_class")
        if device_class:
            self._attr_device_class = SensorDeviceClass(device_class)

        entity_category = self._config.get("entity_category")
        if entity_category:
            self._attr_entity_category = EntityCategory(entity_category)

        state_class = self._config.get("state_class")
        if state_class:
            self._attr_state_class = SensorStateClass(state_class)

        self._last_offset_start = None
        self._last_offset_end = None
        self._cached_ups_blocks: List[Dict[str, Any]] = []
        self._log_rl_last: Dict[str, float] = {}

    def _log_rate_limited(
        self,
        key: str,
        level: str,
        msg: str,
        *args: Any,
        cooldown_s: float = 3600.0,
    ) -> None:
        """Log at most once per cooldown for the given key."""
        now = time.monotonic()
        last = self._log_rl_last.get(key, 0.0)
        if now - last < cooldown_s:
            return
        self._log_rl_last[key] = now
        log_fn = getattr(_LOGGER, level, _LOGGER.debug)
        log_fn(msg, *args)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        await self._load_ups_blocks()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if self.hass:
            self.hass.async_create_task(self._load_ups_blocks())
        super()._handle_coordinator_update()

    async def _load_ups_blocks(self) -> None:
        """Load UPS blocks from precomputed storage (async)."""
        plan_key = self._get_active_plan_key()
        self._cached_ups_blocks = await self._get_home_ups_blocks_from_detail_tabs(
            plan=plan_key
        )
        _LOGGER.debug(
            "[GridChargingPlan] Loaded %s UPS blocks into cache",
            len(self._cached_ups_blocks),
        )
        self.async_write_ha_state()

    async def _get_home_ups_blocks_from_detail_tabs(
        self, plan: str = "hybrid"
    ) -> List[Dict[str, Any]]:
        """Načte HOME UPS bloky z precomputed storage."""
        try:
            if not self.hass:
                return []

            battery_sensor = None
            component = self.hass.data.get("entity_components", {}).get("sensor")
            if component:
                for entity in component.entities:
                    if (
                        hasattr(entity, "_precomputed_store")
                        and self._box_id in entity.entity_id
                        and "battery_forecast" in entity.entity_id
                    ):
                        battery_sensor = entity
                        break

            if not battery_sensor:
                _LOGGER.warning("[GridChargingPlan] BatteryForecastSensor not found")
                return []

            precomputed = await battery_sensor._precomputed_store.async_load()
            if not precomputed:
                _LOGGER.debug("[GridChargingPlan] No precomputed data yet")
                return []

            _ = plan  # legacy parameter (dual-planner removed)
            detail_tabs = precomputed.get("detail_tabs", {}) or precomputed.get(
                "detail_tabs_hybrid", {}
            )
            if not detail_tabs:
                _LOGGER.debug("[GridChargingPlan] No detail tabs data available")
                return []

            now = dt_util.now()
            current_time = now.strftime("%H:%M")

            ups_blocks = []

            today = detail_tabs.get("today", {})
            today_blocks = today.get("mode_blocks", [])

            for block in today_blocks:
                mode_hist = block.get("mode_historical", "")
                mode_plan = block.get("mode_planned", "")
                if "HOME UPS" not in mode_hist and "HOME UPS" not in mode_plan:
                    continue

                status = block.get("status", "")
                end_time = block.get("end_time", "")

                if status == "completed" and end_time < current_time:
                    continue

                ups_blocks.append(
                    {
                        "time_from": block.get("start_time", ""),
                        "time_to": end_time,
                        "day": "today",
                        "mode": MODE_LABEL_HOME_UPS,
                        "status": status,
                        "grid_charge_kwh": block.get("grid_import_total_kwh", 0.0),
                        "cost_czk": block.get(
                            (
                                "cost_historical"
                                if status == "completed"
                                else "cost_planned"
                            ),
                            0.0,
                        ),
                        "battery_start_kwh": block.get("battery_soc_start", 0.0),
                        "battery_end_kwh": block.get("battery_soc_end", 0.0),
                        "interval_count": block.get("interval_count", 0),
                        "duration_hours": block.get("duration_hours", 0.0),
                    }
                )

            tomorrow = detail_tabs.get("tomorrow", {})
            tomorrow_blocks = tomorrow.get("mode_blocks", [])

            for block in tomorrow_blocks:
                mode_plan = block.get("mode_planned", "")
                if "HOME UPS" not in mode_plan:
                    continue

                ups_blocks.append(
                    {
                        "time_from": block.get("start_time", ""),
                        "time_to": block.get("end_time", ""),
                        "day": "tomorrow",
                        "mode": MODE_LABEL_HOME_UPS,
                        "status": "planned",
                        "grid_charge_kwh": block.get("grid_import_total_kwh", 0.0),
                        "cost_czk": block.get("cost_planned", 0.0),
                        "battery_start_kwh": block.get("battery_soc_start", 0.0),
                        "battery_end_kwh": block.get("battery_soc_end", 0.0),
                        "interval_count": block.get("interval_count", 0),
                        "duration_hours": block.get("duration_hours", 0.0),
                    }
                )

            _LOGGER.debug(
                "[GridChargingPlan] Found %s active/future UPS blocks (today + tomorrow)",
                len(ups_blocks),
            )
            return ups_blocks

        except Exception as err:
            _LOGGER.error("[GridChargingPlan] Error: %s", err, exc_info=True)
            return []

    def _get_active_plan_key(self) -> str:
        """Return active plan key (single-planner)."""
        return "hybrid"

    def _calculate_charging_intervals(
        self,
    ) -> tuple[List[Dict[str, Any]], float, float]:
        """Vypočítá intervaly nabíjení ze sítě z CACHED detail_tabs dat."""
        charging_intervals = self._cached_ups_blocks

        if not charging_intervals:
            return [], 0.0, 0.0

        total_energy = sum(block["grid_charge_kwh"] for block in charging_intervals)
        total_cost = sum(block["cost_czk"] for block in charging_intervals)

        return charging_intervals, total_energy, total_cost

    def _get_dynamic_offset(self, from_mode: str, to_mode: str) -> float:
        """Získá dynamický offset z ModeTransitionTracker."""
        try:
            if not self.hass:
                self._log_rate_limited(
                    f"grid_offset_missing_hass_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] hass not available for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            config_entry = self.coordinator.config_entry
            if not config_entry:
                self._log_rate_limited(
                    f"grid_offset_missing_entry_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] No config_entry for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            entry_data = self.hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
            if not entry_data:
                self._log_rate_limited(
                    f"grid_offset_missing_entry_data_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] No entry data for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            service_shield = entry_data.get("service_shield")
            if not service_shield or not hasattr(service_shield, "mode_tracker"):
                self._log_rate_limited(
                    f"grid_offset_missing_tracker_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] ServiceShield/mode_tracker not available for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            mode_tracker = service_shield.mode_tracker
            if not mode_tracker:
                self._log_rate_limited(
                    f"grid_offset_tracker_uninit_{from_mode}_{to_mode}",
                    "debug",
                    "[GridChargingPlan] Mode tracker not initialized for offset %s→%s, using fallback 300s",
                    from_mode,
                    to_mode,
                    cooldown_s=3600.0,
                )
                return 300.0

            offset_seconds = mode_tracker.get_offset_for_scenario(from_mode, to_mode)

            self._log_rate_limited(
                f"grid_offset_ok_{from_mode}_{to_mode}",
                "debug",
                "[GridChargingPlan] Dynamic offset %s→%s: %ss (from tracker)",
                from_mode,
                to_mode,
                offset_seconds,
                cooldown_s=3600.0,
            )

            return offset_seconds

        except Exception as err:
            _LOGGER.warning(
                "[GridChargingPlan] ❌ Error getting offset %s→%s, using fallback 300s: %s",
                from_mode,
                to_mode,
                err,
                exc_info=True,
            )
            return 300.0

    @property
    def native_value(self) -> str:
        """Vrátí ON pokud právě běží nebo brzy začne HOME UPS (s offsetem)."""
        charging_intervals, _, _ = self._calculate_charging_intervals()

        if not charging_intervals:
            return "off"

        now = dt_util.now()
        current_mode = self._get_current_mode()

        sorted_blocks = sorted(
            charging_intervals,
            key=lambda b: (0 if b.get("day") == "today" else 1, b.get("time_from", "")),
        )

        for i, block in enumerate(sorted_blocks):
            start_time_str = block.get("time_from", "00:00")
            end_time_str = block.get("time_to", "23:59")
            day = block.get("day", "today")

            try:
                start_hour, start_min = map(int, start_time_str.split(":"))
                end_hour, end_min = map(int, end_time_str.split(":"))

                start_time = now.replace(
                    hour=start_hour, minute=start_min, second=0, microsecond=0
                )
                end_time = now.replace(
                    hour=end_hour, minute=end_min, second=0, microsecond=0
                )

                if day == "tomorrow":
                    start_time = start_time + timedelta(days=1)
                    end_time = end_time + timedelta(days=1)

                if end_time <= start_time:
                    end_time = end_time + timedelta(days=1)

            except (ValueError, AttributeError):
                _LOGGER.warning(
                    "[GridChargingPlan] Invalid time format: %s - %s",
                    start_time_str,
                    end_time_str,
                )
                continue

            offset_on = self._get_dynamic_offset(current_mode, "HOME UPS")
            start_time_with_offset = start_time - timedelta(seconds=offset_on)

            next_block_is_ups = False
            if i + 1 < len(sorted_blocks):
                next_block = sorted_blocks[i + 1]
                next_start = next_block.get("time_from", "")
                if (
                    next_start == end_time_str
                    or abs(
                        (
                            self._parse_time_to_datetime(
                                next_start, next_block.get("day")
                            )
                            - end_time
                        ).total_seconds()
                    )
                    <= 60
                ):
                    next_block_is_ups = True

            if next_block_is_ups:
                offset_off = 0
            else:
                next_mode = self._get_next_mode_after_ups(block, sorted_blocks, i)
                offset_off = self._get_dynamic_offset("HOME UPS", next_mode)

            end_time_with_offset = end_time - timedelta(seconds=offset_off)

            if start_time_with_offset <= now <= end_time_with_offset:
                _LOGGER.debug(
                    "[GridChargingPlan] Sensor ON: now=%s, block=%s-%s, "
                    "offset_on=%ss, offset_off=%ss",
                    now.strftime("%H:%M:%S"),
                    start_time_str,
                    end_time_str,
                    offset_on,
                    offset_off,
                )
                return "on"

        return "off"

    def _get_current_mode(self) -> str:
        """Získá aktuální režim z coordinator data."""
        if not self.coordinator or not self.coordinator.data:
            return "HOME I"

        box_data = self.coordinator.data.get(self._box_id, {})
        current_mode = box_data.get("current_mode", "HOME I")
        return current_mode

    def _get_next_mode_after_ups(
        self, current_block: Dict, all_blocks: List[Dict], current_idx: int
    ) -> str:
        """Získá režim následující po UPS bloku."""
        if current_idx + 1 < len(all_blocks):
            next_block = all_blocks[current_idx + 1]
            next_mode = next_block.get("mode_planned", "HOME I")
            if "HOME UPS" not in next_mode:
                return next_mode

        return "HOME I"

    def _parse_time_to_datetime(self, time_str: str, day: str) -> datetime:
        """Parse time string to datetime."""
        now = dt_util.now()
        try:
            hour, minute = map(int, time_str.split(":"))
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if day == "tomorrow":
                dt = dt + timedelta(days=1)
            return dt
        except (ValueError, AttributeError):
            return now

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Vrátí atributy senzoru - nabíjecí bloky z detail_tabs API."""
        charging_intervals, total_energy, total_cost = (
            self._calculate_charging_intervals()
        )

        if not charging_intervals:
            return {
                "charging_blocks": [],
                "total_energy_kwh": 0.0,
                "total_cost_czk": 0.0,
                "next_charging_time_range": None,
                "next_charging_duration": None,
                "is_charging_planned": False,
            }

        next_charging_block = None
        for interval in charging_intervals:
            if interval.get("status") == "planned":
                next_charging_block = interval
                break

        next_charging_time_range = None
        next_charging_duration = None
        if next_charging_block:
            day_label = (
                "zítra" if next_charging_block.get("day") == "tomorrow" else "dnes"
            )
            next_charging_time_range = (
                f"{day_label} {next_charging_block['time_from']} - "
                f"{next_charging_block['time_to']}"
            )
            duration_hours = next_charging_block.get("duration_hours", 0)
            duration_minutes = int(duration_hours * 60)
            next_charging_duration = f"{duration_minutes} min"

        charging_blocks = []
        for interval in charging_intervals:
            block = {
                "time_from": interval["time_from"],
                "time_to": interval["time_to"],
                "day": interval["day"],
                "mode": interval["mode"],
                "status": interval["status"],
                "grid_charge_kwh": interval["grid_charge_kwh"],
                "total_cost_czk": interval["cost_czk"],
                "battery_start_kwh": interval["battery_start_kwh"],
                "battery_end_kwh": interval["battery_end_kwh"],
                "interval_count": interval["interval_count"],
                "is_charging_battery": True,
                "avg_spot_price_czk": (
                    round(interval["cost_czk"] / interval["grid_charge_kwh"], 2)
                    if interval["grid_charge_kwh"] > 0
                    else 0.0
                ),
            }
            charging_blocks.append(block)

        return {
            "charging_blocks": charging_blocks,
            "total_energy_kwh": round(total_energy, 2),
            "total_cost_czk": round(total_cost, 2),
            "next_charging_time_range": next_charging_time_range,
            "next_charging_duration": next_charging_duration,
            "is_charging_planned": len(charging_blocks) > 0,
        }
