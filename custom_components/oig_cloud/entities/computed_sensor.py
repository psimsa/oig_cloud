"""Computed sensor implementation for OIG Cloud integration."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..sensor_types import SENSOR_TYPES
from .base_sensor import OigCloudSensor

_LOGGER = logging.getLogger(__name__)

# Shared storage for all energy sensors per box
# Key: oig_cloud.energy_data_{box_id}
# Structure: {"energy": {...}, "last_save": "ISO timestamp", "version": 1}
ENERGY_STORAGE_VERSION = 1
_energy_stores: Dict[str, Store] = {}
_energy_data_cache: Dict[str, Dict[str, float]] = {}
_energy_last_update_cache: Dict[str, datetime] = {}
_energy_cache_loaded: Dict[str, bool] = {}

_LANGS: Dict[str, Dict[str, str]] = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Vypnuto", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
}


class OigCloudComputedSensor(OigCloudSensor, RestoreEntity):
    def __init__(self, coordinator: Any, sensor_type: str) -> None:
        super().__init__(coordinator, sensor_type)

        sensor_config = SENSOR_TYPES.get(sensor_type, {})

        name_cs = sensor_config.get("name_cs")
        name_en = sensor_config.get("name")

        # Preferujeme český název, fallback na anglický, fallback na sensor_type
        self._attr_name = name_cs or name_en or sensor_type

        self._last_update: Optional[datetime] = None
        self._attr_extra_state_attributes: Dict[str, Any] = {}

        self._energy: Dict[str, float] = {
            "charge_today": 0.0,
            "charge_month": 0.0,
            "charge_year": 0.0,
            "discharge_today": 0.0,
            "discharge_month": 0.0,
            "discharge_year": 0.0,
            "charge_fve_today": 0.0,
            "charge_fve_month": 0.0,
            "charge_fve_year": 0.0,
            "charge_grid_today": 0.0,
            "charge_grid_month": 0.0,
            "charge_grid_year": 0.0,
        }

        self._last_update_time: Optional[datetime] = None
        self._monitored_sensors: Dict[str, Any] = {}

        # Persistent storage flag - will save periodically
        self._last_storage_save: Optional[datetime] = None
        self._storage_save_interval = timedelta(minutes=5)

        # Speciální handling pro real_data_update senzor
        if sensor_type == "real_data_update":
            self._is_real_update_sensor = True
            self._initialize_monitored_sensors()
        else:
            self._is_real_update_sensor = False

        # Unsubscribe handle for daily reset callback
        self._daily_reset_unsub = None

    def _get_entity_number(self, entity_id: str) -> Optional[float]:
        """Read numeric value from HA state."""
        if not getattr(self, "hass", None):
            return None
        st = self.hass.states.get(entity_id)
        if not st or st.state in (None, "unknown", "unavailable", ""):
            return None
        try:
            return float(st.state)
        except (ValueError, TypeError):
            return None

    def _get_oig_number(self, sensor_type: str) -> Optional[float]:
        box = self._box_id
        if not (isinstance(box, str) and box.isdigit()):
            return None
        return self._get_entity_number(f"sensor.oig_{box}_{sensor_type}")

    def _get_oig_last_updated(self, sensor_type: str) -> Optional[datetime]:
        if not getattr(self, "hass", None):
            return None
        box = self._box_id
        if not (isinstance(box, str) and box.isdigit()):
            return None
        st = self.hass.states.get(f"sensor.oig_{box}_{sensor_type}")
        if not st:
            return None
        try:
            dt = st.last_updated or st.last_changed
            if dt is None:
                return None
            return dt_util.as_utc(dt) if dt.tzinfo else dt.replace(tzinfo=dt_util.UTC)
        except Exception:
            return None

    def _get_energy_store(self) -> Optional[Store]:
        """Get or create the shared energy store for this box."""
        if self._box_id not in _energy_stores and hasattr(self, "hass") and self.hass:
            _energy_stores[self._box_id] = Store(
                self.hass,
                version=ENERGY_STORAGE_VERSION,
                key=f"oig_cloud.energy_data_{self._box_id}",
            )
            _LOGGER.debug(
                f"✅ Initialized Energy Storage: oig_cloud.energy_data_{self._box_id}"
            )
        return _energy_stores.get(self._box_id)

    async def _load_energy_from_storage(self) -> bool:
        """Load energy data from persistent storage. Returns True if data was loaded."""
        # Already loaded for this box?
        if self._box_id in _energy_data_cache and _energy_cache_loaded.get(
            self._box_id
        ):
            cached = _energy_data_cache[self._box_id]
            for key in self._energy:
                cached.setdefault(key, 0.0)
            self._energy = cached
            _LOGGER.debug(f"[{self.entity_id}] ✅ Loaded energy from cache")
            return True

        store = self._get_energy_store()
        if not store:
            return False

        try:
            data = await store.async_load()
            if data and "energy" in data:
                raw = data["energy"] or {}
                stored_energy: Dict[str, float] = {}
                for key in self._energy:
                    try:
                        stored_energy[key] = float(raw.get(key, 0.0))
                    except (TypeError, ValueError):
                        stored_energy[key] = 0.0

                # Cache for other sensors (shared dict instance)
                _energy_data_cache[self._box_id] = stored_energy
                self._energy = stored_energy
                _energy_cache_loaded[self._box_id] = True

                last_save = data.get("last_save", "unknown")
                _LOGGER.info(
                    f"[{self.entity_id}] ✅ Loaded energy from storage (saved: {last_save}): "
                    f"charge_month={stored_energy.get('charge_month', 0):.0f} Wh"
                )
                return True
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error loading energy from storage: {e}")
        return False

    async def _save_energy_to_storage(self, force: bool = False) -> None:
        """Save energy data to persistent storage (throttled to every 5 min unless forced)."""
        now = datetime.now(timezone.utc)

        # Throttle saves unless forced
        if not force and self._last_storage_save:
            elapsed = now - self._last_storage_save
            if elapsed < self._storage_save_interval:
                return

        store = self._get_energy_store()
        if not store:
            return

        try:
            # Ensure cache points to the current shared dict
            _energy_data_cache[self._box_id] = self._energy

            data = {
                "version": ENERGY_STORAGE_VERSION,
                "energy": self._energy.copy(),
                "last_save": now.isoformat(),
            }
            await store.async_save(data)
            self._last_storage_save = now
            _LOGGER.debug(
                f"[{self.entity_id}] 💾 Saved energy to storage: "
                f"charge_month={self._energy.get('charge_month', 0):.0f} Wh"
            )
        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error saving energy to storage: {e}")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Keep unsubscribe handle so we can cleanly remove the entity during reloads.
        self._daily_reset_unsub = async_track_time_change(
            self.hass, self._reset_daily, hour=0, minute=0, second=0
        )

        # Priority 1: Load from persistent storage (more reliable than restore_state)
        loaded_from_storage = await self._load_energy_from_storage()

        # Priority 2: Fallback to restore_state if storage was empty
        if not loaded_from_storage:
            old_state = await self.async_get_last_state()
            if old_state and old_state.attributes:
                # Restore if any of the tracked keys has a non-zero value.
                max_val = 0.0
                for key in self._energy:
                    try:
                        v = float(old_state.attributes.get(key, 0.0))
                        if v > max_val:
                            max_val = v
                    except (TypeError, ValueError):
                        continue

                # Fallback: some previous versions didn't persist the full energy dict in attributes.
                # If attributes look empty but the entity state is numeric, restore that into the right key.
                if max_val <= 0.0:
                    sensor_map = {
                        "computed_batt_charge_energy_today": "charge_today",
                        "computed_batt_discharge_energy_today": "discharge_today",
                        "computed_batt_charge_energy_month": "charge_month",
                        "computed_batt_discharge_energy_month": "discharge_month",
                        "computed_batt_charge_energy_year": "charge_year",
                        "computed_batt_discharge_energy_year": "discharge_year",
                        "computed_batt_charge_fve_energy_today": "charge_fve_today",
                        "computed_batt_charge_fve_energy_month": "charge_fve_month",
                        "computed_batt_charge_fve_energy_year": "charge_fve_year",
                        "computed_batt_charge_grid_energy_today": "charge_grid_today",
                        "computed_batt_charge_grid_energy_month": "charge_grid_month",
                        "computed_batt_charge_grid_energy_year": "charge_grid_year",
                    }
                    key = sensor_map.get(self._sensor_type)
                    if key:
                        try:
                            v = float(old_state.state)
                            if v > 0.0:
                                self._energy[key] = v
                                max_val = v
                        except (TypeError, ValueError):
                            pass

                if max_val > 0.0:
                    _LOGGER.info(
                        f"[{self.entity_id}] 📥 Restoring from HA state (storage empty): max={max_val}"
                    )

                    # Ensure we're writing into the shared per-box dict (if available).
                    if self._box_id and self._box_id != "unknown":
                        energy = _energy_data_cache.get(self._box_id)
                        if not isinstance(energy, dict):
                            _energy_data_cache[self._box_id] = self._energy
                            energy = self._energy
                        self._energy = energy

                    for key in self._energy:
                        try:
                            if key in old_state.attributes:
                                self._energy[key] = float(old_state.attributes[key])
                        except (TypeError, ValueError):
                            continue

                    if self._box_id and self._box_id != "unknown":
                        _energy_cache_loaded[self._box_id] = True
                    # Save to storage for future
                    await self._save_energy_to_storage(force=True)
                else:
                    _LOGGER.warning(
                        f"[{self.entity_id}] ⚠️ Restore state has zeroed/invalid data "
                        f"(max={max_val}), keeping defaults"
                    )

        # Po inicializaci (load/restore + dependency listeners) hned přepiš stav,
        # aby se uživatelům neukazovala dočasná nula po restartu.
        self.async_write_ha_state()

    async def _reset_daily(self, now: Optional[datetime] = None, *_: Any) -> None:
        if now is None:
            now = dt_util.now()
        _LOGGER.debug(f"[{self.entity_id}] Resetting daily energy")
        for key in self._energy:
            if key.endswith("today"):
                self._energy[key] = 0.0

        if now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting monthly energy")
            for key in self._energy:
                if key.endswith("month"):
                    self._energy[key] = 0.0

        if now.month == 1 and now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting yearly energy")
            for key in self._energy:
                if key.endswith("year"):
                    self._energy[key] = 0.0

        # Force save after reset
        await self._save_energy_to_storage(force=True)

    @property
    def state(self) -> Optional[Union[float, str]]:  # noqa: C901
        box = self._box_id
        if not (isinstance(box, str) and box.isdigit()):
            return None

        if self._sensor_type == "real_data_update":
            dt = (
                self._get_oig_last_updated("batt_batt_comp_p")
                or self._get_oig_last_updated("batt_bat_c")
                or self._get_oig_last_updated("device_lastcall")
            )
            return dt_util.as_local(dt).isoformat() if dt else None

        if self._sensor_type == "ac_in_aci_wtotal":
            wr = self._get_oig_number("ac_in_aci_wr")
            ws = self._get_oig_number("ac_in_aci_ws")
            wt = self._get_oig_number("ac_in_aci_wt")
            if wr is None or ws is None or wt is None:
                return None
            return float(wr + ws + wt)

        if self._sensor_type == "actual_aci_wtotal":
            wr = self._get_oig_number("actual_aci_wr")
            ws = self._get_oig_number("actual_aci_ws")
            wt = self._get_oig_number("actual_aci_wt")
            if wr is None or ws is None or wt is None:
                return None
            return float(wr + ws + wt)

        if self._sensor_type == "dc_in_fv_total":
            p1 = self._get_oig_number("dc_in_fv_p1")
            p2 = self._get_oig_number("dc_in_fv_p2")
            if p1 is None or p2 is None:
                return None
            return float(p1 + p2)

        if self._sensor_type == "actual_fv_total":
            p1 = self._get_oig_number("actual_fv_p1")
            p2 = self._get_oig_number("actual_fv_p2")
            if p1 is None or p2 is None:
                return None
            return float(p1 + p2)

        if self._sensor_type == "boiler_current_w":
            return self._get_boiler_consumption_from_entities()

        if self._sensor_type == "batt_batt_comp_p_charge":
            bat_p = self._get_oig_number("batt_batt_comp_p")
            if bat_p is None:
                return None
            return float(bat_p) if bat_p > 0 else 0.0

        if self._sensor_type == "batt_batt_comp_p_discharge":
            bat_p = self._get_oig_number("batt_batt_comp_p")
            if bat_p is None:
                return None
            return float(-bat_p) if bat_p < 0 else 0.0

        if self._sensor_type.startswith("computed_batt_"):
            return self._accumulate_energy()

        try:
            bat_p_wh = float(
                self._get_oig_number("installed_battery_capacity_kwh") or 0.0
            )
            bat_min_percent = float(self._get_oig_number("batt_bat_min") or 20.0)
            usable_percent = (100 - bat_min_percent) / 100
            bat_c = float(self._get_oig_number("batt_bat_c") or 0.0)
            bat_power = float(self._get_oig_number("batt_batt_comp_p") or 0.0)

            if self._sensor_type == "usable_battery_capacity":
                return round((bat_p_wh * usable_percent) / 1000, 2)

            if self._sensor_type == "missing_battery_kwh":
                return round((bat_p_wh * (1 - bat_c / 100)) / 1000, 2)

            if self._sensor_type == "remaining_usable_capacity":
                usable = bat_p_wh * usable_percent
                missing = bat_p_wh * (1 - bat_c / 100)
                return round((usable - missing) / 1000, 2)

            if self._sensor_type == "time_to_full":
                missing = bat_p_wh * (1 - bat_c / 100)
                if bat_power > 0:
                    return self._format_time(missing / bat_power)
                if missing == 0:
                    return "Nabito"
                return "Vybíjí se"

            if self._sensor_type == "time_to_empty":
                usable = bat_p_wh * usable_percent
                missing = bat_p_wh * (1 - bat_c / 100)
                remaining = usable - missing
                if bat_c >= 100:
                    return "Nabito"
                if bat_power < 0:
                    return self._format_time(remaining / abs(bat_power))
                if remaining == 0:
                    return "Vybito"
                return "Nabíjí se"

        except Exception as e:
            _LOGGER.debug("[%s] Error computing value: %s", self.entity_id, e)

        return None

    def _accumulate_energy(self) -> Optional[float]:
        # Use shared per-box cache so multiple computed energy sensors don't double-count.
        if self._box_id and self._box_id != "unknown":
            cached = _energy_data_cache.get(self._box_id)
            if cached is not None:
                self._energy = cached
            else:
                _energy_data_cache[self._box_id] = self._energy

        try:
            now = datetime.now(timezone.utc)

            bat_power_val = self._get_oig_number("batt_batt_comp_p")
            if bat_power_val is None:
                return None
            bat_power = float(bat_power_val)

            fv_p1 = float(self._get_oig_number("actual_fv_p1") or 0.0)
            fv_p2 = float(self._get_oig_number("actual_fv_p2") or 0.0)
            fv_power = fv_p1 + fv_p2

            last_update = (
                _energy_last_update_cache.get(self._box_id)
                if self._box_id and self._box_id != "unknown"
                else self._last_update
            )

            if last_update is not None:
                delta_seconds = (now - last_update).total_seconds()
                wh_increment = (abs(bat_power) * delta_seconds) / 3600.0

                if bat_power > 0:
                    self._energy["charge_today"] += wh_increment
                    self._energy["charge_month"] += wh_increment
                    self._energy["charge_year"] += wh_increment

                    if fv_power > 50:
                        from_fve = min(bat_power, fv_power)
                        from_grid = bat_power - from_fve
                    else:
                        from_fve = 0
                        from_grid = bat_power

                    wh_increment_fve = (from_fve * delta_seconds) / 3600.0
                    wh_increment_grid = (from_grid * delta_seconds) / 3600.0

                    self._energy["charge_fve_today"] += wh_increment_fve
                    self._energy["charge_fve_month"] += wh_increment_fve
                    self._energy["charge_fve_year"] += wh_increment_fve

                    self._energy["charge_grid_today"] += wh_increment_grid
                    self._energy["charge_grid_month"] += wh_increment_grid
                    self._energy["charge_grid_year"] += wh_increment_grid

                elif bat_power < 0:
                    self._energy["discharge_today"] += wh_increment
                    self._energy["discharge_month"] += wh_increment
                    self._energy["discharge_year"] += wh_increment

                _LOGGER.debug(
                    f"[{self.entity_id}] Δt={delta_seconds:.1f}s bat={bat_power:.1f}W fv={fv_power:.1f}W -> ΔWh={wh_increment:.4f}"
                )

            if self._box_id and self._box_id != "unknown":
                _energy_last_update_cache[self._box_id] = now
            self._last_update = now
            self._attr_extra_state_attributes = {
                k: round(v, 3) for k, v in self._energy.items()
            }
            if self._box_id and self._box_id != "unknown":
                _energy_data_cache[self._box_id] = self._energy

            # Periodic save to persistent storage (throttled)
            if hasattr(self, "hass") and self.hass:
                coro = self._save_energy_to_storage()
                task = self.hass.async_create_task(coro)
                if task is None or asyncio.iscoroutine(task) or not asyncio.isfuture(task):
                    coro.close()

            return self._get_energy_value()

        except Exception as e:
            _LOGGER.error(f"Error calculating energy: {e}", exc_info=True)
            return None

    def _get_energy_value(self) -> Optional[float]:
        # Always read from the shared cache when available (multiple sensors per box).
        energy = (
            _energy_data_cache.get(self._box_id)
            if self._box_id and self._box_id != "unknown"
            else None
        )
        if isinstance(energy, dict):
            self._energy = energy

        sensor_map = {
            "computed_batt_charge_energy_today": "charge_today",
            "computed_batt_discharge_energy_today": "discharge_today",
            "computed_batt_charge_energy_month": "charge_month",
            "computed_batt_discharge_energy_month": "discharge_month",
            "computed_batt_charge_energy_year": "charge_year",
            "computed_batt_discharge_energy_year": "discharge_year",
            "computed_batt_charge_fve_energy_today": "charge_fve_today",
            "computed_batt_charge_fve_energy_month": "charge_fve_month",
            "computed_batt_charge_fve_energy_year": "charge_fve_year",
            "computed_batt_charge_grid_energy_today": "charge_grid_today",
            "computed_batt_charge_grid_energy_month": "charge_grid_month",
            "computed_batt_charge_grid_energy_year": "charge_grid_year",
        }
        energy_key = sensor_map.get(self._sensor_type)
        if energy_key:
            return round(self._energy[energy_key], 3)
        return None

    def _get_boiler_consumption_from_entities(self) -> Optional[float]:
        """Estimate boiler power using only `sensor.oig_{box}_*` entities."""
        if self._sensor_type != "boiler_current_w":
            return None
        try:
            fv_power = float(self._get_oig_number("actual_fv_p1") or 0.0) + float(
                self._get_oig_number("actual_fv_p2") or 0.0
            )
            load_power = float(self._get_oig_number("actual_aco_p") or 0.0)
            grid_p1 = float(self._get_oig_number("actual_aci_wr") or 0.0)
            grid_p2 = float(self._get_oig_number("actual_aci_ws") or 0.0)
            grid_p3 = float(self._get_oig_number("actual_aci_wt") or 0.0)
            export_power = grid_p1 + grid_p2 + grid_p3

            boiler_p_set = float(self._get_oig_number("boiler_install_power") or 0.0)
            bat_power = float(self._get_oig_number("batt_batt_comp_p") or 0.0)

            manual_state = None
            if (
                getattr(self, "hass", None)
                and self._box_id
                and self._box_id != "unknown"
            ):
                st = self.hass.states.get(
                    f"sensor.oig_{self._box_id}_boiler_manual_mode"
                )
                manual_state = st.state if st else None
            manual_s = (
                str(manual_state).strip().lower() if manual_state is not None else ""
            )
            boiler_manual = manual_s in {
                "1",
                "on",
                "zapnuto",
                "manual",
                "manuální",
                "manualni",
            } or manual_s.startswith("manu")

            if boiler_manual:
                boiler_power = boiler_p_set
            else:
                if bat_power <= 0:
                    available_power = fv_power - load_power - export_power
                    boiler_power = min(max(available_power, 0), boiler_p_set)
                else:
                    boiler_power = 0.0

            return round(float(max(boiler_power, 0.0)), 2)
        except Exception as e:
            _LOGGER.debug("Error calculating boiler consumption: %s", e)
            return None

    def _get_boiler_consumption(self, pv_data: Dict[str, Any]) -> Optional[float]:
        """Backward-compatible wrapper (legacy call sites)."""
        return self._get_boiler_consumption_from_entities()

    def _get_batt_power_charge(self, pv_data: Dict[str, Any]) -> float:
        if "actual" not in pv_data:
            return 0.0
        return max(float(pv_data["actual"]["bat_p"]), 0)

    def _get_batt_power_discharge(self, pv_data: Dict[str, Any]) -> float:
        if "actual" not in pv_data:
            return 0.0
        return max(-float(pv_data["actual"]["bat_p"]), 0)

    def _get_extended_fve_current_1(self, coordinator: Any) -> Optional[float]:
        try:
            power = float(coordinator.data["extended_fve_power_1"])
            voltage = float(coordinator.data["extended_fve_voltage_1"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_1: {e}", exc_info=True)
            return None

    def _get_extended_fve_current_2(self, coordinator: Any) -> Optional[float]:
        try:
            power = float(coordinator.data["extended_fve_power_2"])
            voltage = float(coordinator.data["extended_fve_voltage_2"])
            if voltage != 0:
                return power / voltage
            else:
                return 0.0
        except (KeyError, TypeError, ZeroDivisionError) as e:
            _LOGGER.error(f"Error getting extended_fve_current_2: {e}", exc_info=True)
            return None

    async def async_update(self) -> None:
        await self.coordinator.async_request_refresh()

    def _format_time(self, hours: float) -> str:
        if hours <= 0:
            return "N/A"

        minutes = int(hours * 60)
        days, remainder = divmod(minutes, 1440)
        hrs, mins = divmod(remainder, 60)

        self._attr_extra_state_attributes = {
            "days": days,
            "hours": hrs,
            "minutes": mins,
        }

        if days >= 1:
            if days == 1:
                return f"{days} den {hrs} hodin {mins} minut"
            elif days in [2, 3, 4]:
                return f"{days} dny {hrs} hodin {mins} minut"
            else:
                return f"{days} dnů {hrs} hodin {mins} minut"
        elif hrs >= 1:
            return f"{hrs} hodin {mins} minut"
        else:
            return f"{mins} minut"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return getattr(self, "_attr_extra_state_attributes", {})

    def _initialize_monitored_sensors(self) -> None:
        """Inicializuje sledované senzory pro real data update."""
        # Klíčové senzory pro sledování změn
        self._key_sensors = [
            "bat_p",
            "bat_c",
            "fv_p1",
            "fv_p2",
            "aco_p",
            "aci_wr",
            "aci_ws",
            "aci_wt",
        ]

    def _check_for_real_data_changes(self, pv_data: Dict[str, Any]) -> bool:
        """Zkontroluje, zda došlo ke skutečné změně v datech."""
        try:
            # OPRAVA: Kontrola existence "actual" dat
            if "actual" not in pv_data:
                _LOGGER.warning(
                    f"[{self.entity_id}] Live Data nejsou zapnutá - real data update nefunguje. "
                    f"Zapněte Live Data v OIG aplikaci."
                )
                return False

            current_values = {}

            # Získej aktuální hodnoty klíčových senzorů
            for sensor_key in self._key_sensors:
                if sensor_key.startswith(("bat_", "fv_", "aco_", "aci_")):
                    current_values[sensor_key] = pv_data["actual"].get(sensor_key, 0)

            # Porovnej s předchozími hodnotami
            has_changes = False
            for key, current_value in current_values.items():
                previous_value = self._monitored_sensors.get(key)
                if (
                    previous_value is None
                    or abs(float(current_value) - float(previous_value)) > 0.1
                ):
                    has_changes = True
                    _LOGGER.debug(
                        f"[{self.entity_id}] Real data change detected: {key} {previous_value} -> {current_value}"
                    )

            # Ulož aktuální hodnoty pro příští porovnání
            self._monitored_sensors = current_values.copy()

            return has_changes

        except Exception as e:
            _LOGGER.error(f"[{self.entity_id}] Error checking data changes: {e}")
            return False

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self._cancel_reset()
        return

    def _cancel_reset(self) -> None:
        unsub = getattr(self, "_daily_reset_unsub", None)
        if unsub:
            try:
                unsub()
            except Exception as err:
                _LOGGER.debug(
                    "[%s] Failed to cancel daily reset listener: %s",
                    self.entity_id,
                    err,
                )
            self._daily_reset_unsub = None
