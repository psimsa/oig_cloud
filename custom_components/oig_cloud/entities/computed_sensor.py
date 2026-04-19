"""Computed sensor implementation for OIG Cloud integration."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Dict, Iterable, Optional, Union, cast

from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..core.box_mode_composite import canonical_extended_state, parse_app_value
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
_energy_restore_tasks: Dict[str, asyncio.Task[None]] = {}
PROXY_LAST_DATA_ENTITY_ID = "sensor.oig_local_oig_proxy_proxy_status_last_data"

_LANGS: Dict[str, Dict[str, str]] = {
    "on": {"en": "On", "cs": "Zapnuto"},
    "off": {"en": "Vypnuto", "cs": "Vypnuto"},
    "unknown": {"en": "Unknown", "cs": "Neznámý"},
    "changing": {"en": "Changing in progress", "cs": "Probíhá změna"},
}


if TYPE_CHECKING:

    class _ComputedBase:
        coordinator: Any
        hass: Any
        entity_id: str
        _box_id: str
        _sensor_type: str

        def __init__(self, coordinator: Any, sensor_type: str) -> None: ...
        async def async_added_to_hass(self) -> None: ...
        async def async_will_remove_from_hass(self) -> None: ...
        async def async_get_last_state(self) -> Any: ...
        def async_write_ha_state(self) -> None: ...
        async def async_update(self) -> None: ...

else:
    from homeassistant.helpers.restore_state import RestoreEntity

    class _ComputedBase(OigCloudSensor, RestoreEntity):
        pass


class OigCloudComputedSensor(_ComputedBase):
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
        self._daily_reset_unsub: Optional[Any] = None

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
            dt = st.last_changed
            if dt is None:
                return None
            return self._normalize_timestamp(dt)
        except Exception:
            return None

    @staticmethod
    def _normalize_timestamp(dt: datetime) -> datetime:
        return dt_util.as_utc(dt) if dt.tzinfo else dt.replace(tzinfo=dt_util.UTC)

    def _parse_state_timestamp(self, state_value: str) -> Optional[datetime]:
        try:
            parsed = dt_util.parse_datetime(state_value) or datetime.fromisoformat(
                state_value
            )
        except Exception:
            return None
        if parsed is None:
            return None  # pragma: no cover
        return self._normalize_timestamp(parsed)

    def _get_entity_timestamp(self, entity_id: str) -> Optional[datetime]:
        if not getattr(self, "hass", None):
            return None
        st = self.hass.states.get(entity_id)
        if not st or st.state in (None, "unknown", "unavailable", ""):
            return None
        if isinstance(st.state, str):
            parsed = self._parse_state_timestamp(st.state)
            if parsed is not None:
                return parsed
        try:
            dt = st.last_updated or st.last_changed
            if dt is None:
                return None
            return self._normalize_timestamp(dt)
        except Exception:
            return None

    def _iter_oig_states(self, domain: str, box: str) -> Iterable[Any]:
        states_obj = getattr(self.hass, "states", None)
        async_all = getattr(states_obj, "async_all", None)
        if not callable(async_all):
            return []
        prefix = f"{domain}.oig_{box}_"
        raw_states = cast(list[Any], async_all(domain))
        return [
            st
            for st in raw_states
            if getattr(st, "entity_id", "").startswith(prefix)
            and st.state not in (None, "unknown", "unavailable", "")
        ]

    def _get_latest_oig_entity_update(self) -> Optional[datetime]:
        if not getattr(self, "hass", None):
            return None
        box = self._box_id
        if not (isinstance(box, str) and box.isdigit()):
            return None
        latest: Optional[datetime] = None
        for domain in ("sensor", "binary_sensor"):
            for st in self._iter_oig_states(domain, box):
                dt = st.last_changed
                if dt is None:
                    continue
                dt_utc = self._normalize_timestamp(dt)
                latest = dt_utc if latest is None else max(latest, dt_utc)
        return latest

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

    def _has_numeric_box(self) -> bool:
        return isinstance(self._box_id, str) and self._box_id.isdigit()

    def _state_real_data_update(self) -> Optional[str]:
        candidates = [
            self._get_oig_last_updated("batt_batt_comp_p"),
            self._get_oig_last_updated("batt_bat_c"),
            self._get_oig_last_updated("device_lastcall"),
            self._get_entity_timestamp(PROXY_LAST_DATA_ENTITY_ID),
            self._get_latest_oig_entity_update(),
        ]
        latest = max((dt for dt in candidates if dt), default=None)
        return dt_util.as_local(latest).isoformat() if latest else None

    def _sum_three_phase(self, base: str) -> Optional[float]:
        wr = self._get_oig_number(f"{base}_wr")
        ws = self._get_oig_number(f"{base}_ws")
        wt = self._get_oig_number(f"{base}_wt")
        if wr is None or ws is None or wt is None:
            return None
        return float(wr + ws + wt)

    def _sum_two_phase(self, base: str) -> Optional[float]:
        p1 = self._get_oig_number(f"{base}_p1")
        p2 = self._get_oig_number(f"{base}_p2")
        if p1 is None or p2 is None:
            return None
        return float(p1 + p2)

    def _get_battery_params(self) -> Optional[Dict[str, float]]:
        try:
            bat_p_wh = float(
                self._get_oig_number("installed_battery_capacity_kwh") or 0.0
            )
            bat_min_percent = float(self._get_oig_number("batt_bat_min") or 20.0)
            bat_c = float(self._get_oig_number("batt_bat_c") or 0.0)
            bat_power = float(self._get_oig_number("batt_batt_comp_p") or 0.0)
            return {
                "bat_p_wh": bat_p_wh,
                "bat_min_percent": bat_min_percent,
                "bat_c": bat_c,
                "bat_power": bat_power,
            }
        except Exception as err:
            _LOGGER.debug("[%s] Error computing value: %s", self.entity_id, err)
            return None

    def _state_battery_metrics(self) -> Optional[Union[float, str]]:
        params = self._get_battery_params()
        if not params:
            return None

        bat_p_wh = params["bat_p_wh"]
        usable_percent = (100 - params["bat_min_percent"]) / 100
        bat_c = params["bat_c"]
        bat_power = params["bat_power"]
        remaining = self._remaining_capacity(bat_p_wh, usable_percent, bat_c)
        missing = self._missing_capacity(bat_p_wh, bat_c)

        if self._sensor_type == "usable_battery_capacity":
            return round((bat_p_wh * usable_percent) / 1000, 2)
        if self._sensor_type == "missing_battery_kwh":
            return round(missing / 1000, 2)
        if self._sensor_type == "remaining_usable_capacity":
            usable = bat_p_wh * usable_percent
            return round((usable - missing) / 1000, 2)
        if self._sensor_type == "time_to_full":
            return self._time_to_full(missing, bat_power)
        if self._sensor_type == "time_to_empty":
            return self._time_to_empty(remaining, bat_c, bat_power)
        return None

    @staticmethod
    def _missing_capacity(bat_p_wh: float, bat_c: float) -> float:
        return bat_p_wh * (1 - bat_c / 100)

    @staticmethod
    def _remaining_capacity(
        bat_p_wh: float, usable_percent: float, bat_c: float
    ) -> float:
        usable = bat_p_wh * usable_percent
        missing = bat_p_wh * (1 - bat_c / 100)
        return usable - missing

    def _time_to_full(self, missing: float, bat_power: float) -> str:
        if bat_power > 0:
            return self._format_time(missing / bat_power)
        if missing == 0:
            return "Nabito"
        return "Vybíjí se"

    def _time_to_empty(self, remaining: float, bat_c: float, bat_power: float) -> str:
        if bat_c >= 100:
            return "Nabito"
        if bat_power < 0:
            return self._format_time(remaining / abs(bat_power))
        if remaining == 0:
            return "Vybito"
        return "Nabíjí se"

    def _get_energy_value_key(self) -> Optional[str]:
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
        return sensor_map.get(self._sensor_type)

    def _update_shared_energy_cache(self) -> None:
        if self._box_id and self._box_id != "unknown":
            cached = _energy_data_cache.get(self._box_id)
            if cached is not None:
                self._energy = cached
            else:
                _energy_data_cache[self._box_id] = self._energy

    def _get_last_energy_update(self) -> Optional[datetime]:
        if self._box_id and self._box_id != "unknown":
            return _energy_last_update_cache.get(self._box_id)
        return self._last_update

    def _set_last_energy_update(self, now: datetime) -> None:
        if self._box_id and self._box_id != "unknown":
            _energy_last_update_cache[self._box_id] = now
        self._last_update = now

    def _apply_charge_delta(
        self, wh_increment: float, delta_seconds: float, bat_power: float, fv_power: float
    ) -> None:
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

    def _apply_discharge_delta(self, wh_increment: float) -> None:
        self._energy["discharge_today"] += wh_increment
        self._energy["discharge_month"] += wh_increment
        self._energy["discharge_year"] += wh_increment

    def _maybe_schedule_energy_save(self) -> None:
        if not hasattr(self, "hass") or not self.hass:
            return
        coro = self._save_energy_to_storage()
        task = self.hass.async_create_task(coro)
        if task is None or asyncio.iscoroutine(task) or not asyncio.isfuture(task):
            coro.close()

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
        await self._schedule_startup_restore()

    async def _schedule_startup_restore(self) -> None:
        if not getattr(self, "hass", None):
            return

        async def _startup_restore() -> None:
            await self._ensure_energy_initialized()
            self.async_write_ha_state()

        create_task = getattr(self.hass, "async_create_task", None)
        if not callable(create_task):
            await _startup_restore()
            return
        task = create_task(_startup_restore())
        if task is None:
            return

    async def _ensure_energy_initialized(self) -> None:
        box_id = self._box_id
        if not box_id or box_id == "unknown":
            await self._restore_energy_from_state()
            return

        if _energy_cache_loaded.get(box_id):
            cached = _energy_data_cache.get(box_id)
            if isinstance(cached, dict):
                self._energy = cached
            return

        existing_task = _energy_restore_tasks.get(box_id)
        if existing_task is not None:
            await existing_task
            cached = _energy_data_cache.get(box_id)
            if isinstance(cached, dict):
                self._energy = cached
            return

        async def _restore_shared_energy() -> None:
            loaded_from_storage = await self._load_energy_from_storage()
            if not loaded_from_storage:
                await self._restore_energy_from_state()
            _energy_cache_loaded[box_id] = True

        create_task = getattr(self.hass, "async_create_task", None)
        if not callable(create_task):
            await _restore_shared_energy()
            return
        restore_task = create_task(_restore_shared_energy())
        if restore_task is None:
            return
        if not isinstance(restore_task, Awaitable):
            await _restore_shared_energy()
            return

        typed_restore_task = cast(asyncio.Task[None], restore_task)
        _energy_restore_tasks[box_id] = typed_restore_task
        try:
            await typed_restore_task
        finally:
            if _energy_restore_tasks.get(box_id) is typed_restore_task:
                _energy_restore_tasks.pop(box_id, None)
        cached = _energy_data_cache.get(box_id)
        if isinstance(cached, dict):
            self._energy = cached

    async def _restore_energy_from_state(self) -> None:
        old_state = await self.async_get_last_state()
        if not old_state or not old_state.attributes:
            return  # pragma: no cover

        max_val = self._max_energy_attribute(old_state.attributes)
        if max_val <= 0.0:
            max_val = self._restore_from_entity_state(old_state)

        if max_val <= 0.0:
            _LOGGER.warning(
                "[%s] ⚠️ Restore state has zeroed/invalid data (max=%s), keeping defaults",
                self.entity_id,
                max_val,
            )
            return

        _LOGGER.info(
            "[%s] 📥 Restoring from HA state (storage empty): max=%s",
            self.entity_id,
            max_val,
        )
        self._apply_restored_energy(old_state.attributes)
        if self._box_id and self._box_id != "unknown":
            _energy_cache_loaded[self._box_id] = True
        await self._save_energy_to_storage(force=True)

    def _max_energy_attribute(self, attributes: Dict[str, Any]) -> float:
        max_val = 0.0
        for key in self._energy:
            try:
                value = float(attributes.get(key, 0.0))
            except (TypeError, ValueError):
                continue
            if value > max_val:
                max_val = value
        return max_val

    def _restore_from_entity_state(self, old_state: Any) -> float:
        key = self._get_energy_value_key()
        if not key:
            return 0.0  # pragma: no cover
        try:
            value = float(old_state.state)
        except (TypeError, ValueError):
            return 0.0
        if value <= 0.0:
            return 0.0  # pragma: no cover
        self._energy[key] = value
        return value

    def _apply_restored_energy(self, attributes: Dict[str, Any]) -> None:
        if self._box_id and self._box_id != "unknown":
            energy = _energy_data_cache.get(self._box_id)
            if not isinstance(energy, dict):
                _energy_data_cache[self._box_id] = self._energy
                energy = self._energy
            self._energy = energy

        for key in self._energy:
            try:
                if key in attributes:
                    self._energy[key] = float(attributes[key])
            except (TypeError, ValueError):
                continue

    async def _reset_daily(self, now: Optional[datetime] = None, *_: Any) -> None:
        if now is None:
            now = dt_util.now()
        _LOGGER.debug(f"[{self.entity_id}] Resetting daily energy")
        self._reset_energy_by_suffix("today")

        if now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting monthly energy")
            self._reset_energy_by_suffix("month")

        if now.month == 1 and now.day == 1:
            _LOGGER.debug(f"[{self.entity_id}] Resetting yearly energy")
            self._reset_energy_by_suffix("year")

        # Force save after reset
        await self._save_energy_to_storage(force=True)

    def _reset_energy_by_suffix(self, suffix: str) -> None:
        for key in self._energy:
            if key.endswith(suffix):
                self._energy[key] = 0.0

    @property
    def state(self) -> Optional[Union[float, str]]:  # noqa: C901
        if not self._has_numeric_box():
            return None

        state = self._state_from_mapping()
        if state is not None:
            return state

        battery_state = self._state_battery_metrics()
        if battery_state is not None:
            return battery_state

        return None

    def _state_from_mapping(self) -> Optional[Union[float, str]]:
        if self._sensor_type == "real_data_update":
            return self._state_real_data_update()
        handler = self._sensor_mapping().get(self._sensor_type)
        if handler:
            return handler()
        if self._sensor_type.startswith("computed_batt_"):
            return self._accumulate_energy()
        return None

    def _sensor_mapping(self) -> Dict[str, Any]:
        return {
            "ac_in_aci_wtotal": lambda: self._sum_three_phase("ac_in_aci"),
            "actual_aci_wtotal": lambda: self._sum_three_phase("actual_aci"),
            "dc_in_fv_total": lambda: self._sum_two_phase("dc_in_fv"),
            "actual_fv_total": lambda: self._sum_two_phase("actual_fv"),
            "boiler_current_w": self._get_boiler_consumption_from_entities,
            "batt_batt_comp_p_charge": self._state_batt_comp_charge,
            "batt_batt_comp_p_discharge": self._state_batt_comp_discharge,
            "box_mode_extended": self._state_box_mode_extended,
        }

    def _state_batt_comp_charge(self) -> Optional[float]:
        bat_p = self._get_oig_number("batt_batt_comp_p")
        if bat_p is None:
            return None
        return float(bat_p) if bat_p > 0 else 0.0

    def _state_batt_comp_discharge(self) -> Optional[float]:
        bat_p = self._get_oig_number("batt_batt_comp_p")
        if bat_p is None:
            return None
        return float(-bat_p) if bat_p < 0 else 0.0

    def _accumulate_energy(self) -> Optional[float]:
        self._update_shared_energy_cache()
        try:
            now = datetime.now(timezone.utc)

            power_values = self._get_power_values()
            if power_values is None:
                return None
            bat_power, fv_power = power_values
            last_update = self._get_last_energy_update()

            if last_update is not None:
                self._apply_energy_accumulation(now, last_update, bat_power, fv_power)

            self._set_last_energy_update(now)
            self._attr_extra_state_attributes = {
                k: round(v, 3) for k, v in self._energy.items()
            }
            if self._box_id and self._box_id != "unknown":
                _energy_data_cache[self._box_id] = self._energy

            # Periodic save to persistent storage (throttled)
            self._maybe_schedule_energy_save()

            return self._get_energy_value()

        except Exception as err:
            _LOGGER.error("Error calculating energy: %s", err, exc_info=True)
            return None

    def _get_power_values(self) -> Optional[tuple[float, float]]:
        bat_power_val = self._get_oig_number("batt_batt_comp_p")
        if bat_power_val is None:
            return None
        bat_power = float(bat_power_val)

        fv_p1 = float(self._get_oig_number("actual_fv_p1") or 0.0)
        fv_p2 = float(self._get_oig_number("actual_fv_p2") or 0.0)
        fv_power = fv_p1 + fv_p2
        return bat_power, fv_power

    def _apply_energy_accumulation(
        self,
        now: datetime,
        last_update: datetime,
        bat_power: float,
        fv_power: float,
    ) -> None:
        delta_seconds = (now - last_update).total_seconds()
        wh_increment = (abs(bat_power) * delta_seconds) / 3600.0

        if bat_power > 0:
            self._apply_charge_delta(wh_increment, delta_seconds, bat_power, fv_power)
        elif bat_power < 0:
            self._apply_discharge_delta(wh_increment)

        _LOGGER.debug(
            f"[{self.entity_id}] Δt={delta_seconds:.1f}s bat={bat_power:.1f}W fv={fv_power:.1f}W -> ΔWh={wh_increment:.4f}"
        )

    def _get_energy_value(self) -> Optional[float]:
        # Always read from the shared cache when available (multiple sensors per box).
        energy = (
            _energy_data_cache.get(self._box_id)
            if self._box_id and self._box_id != "unknown"
            else None
        )
        if isinstance(energy, dict):
            self._energy = energy

        energy_key = self._get_energy_value_key()
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
            export_power = self._grid_export_power()
            boiler_p_set = float(self._get_oig_number("boiler_install_power") or 0.0)
            bat_power = float(self._get_oig_number("batt_batt_comp_p") or 0.0)

            boiler_power = self._compute_boiler_power(
                boiler_p_set=boiler_p_set,
                fv_power=fv_power,
                load_power=load_power,
                export_power=export_power,
                bat_power=bat_power,
            )

            return round(float(max(boiler_power, 0.0)), 2)
        except Exception as e:
            _LOGGER.debug("Error calculating boiler consumption: %s", e)
            return None

    def _grid_export_power(self) -> float:
        grid_p1 = float(self._get_oig_number("actual_aci_wr") or 0.0)
        grid_p2 = float(self._get_oig_number("actual_aci_ws") or 0.0)
        grid_p3 = float(self._get_oig_number("actual_aci_wt") or 0.0)
        return grid_p1 + grid_p2 + grid_p3

    def _compute_boiler_power(
        self,
        *,
        boiler_p_set: float,
        fv_power: float,
        load_power: float,
        export_power: float,
        bat_power: float,
    ) -> float:
        if self._is_boiler_manual():
            return boiler_p_set

        if bat_power <= 0:
            available_power = fv_power - load_power - export_power
            return min(max(available_power, 0), boiler_p_set)

        return 0.0

    def _is_boiler_manual(self) -> bool:
        if (
            not getattr(self, "hass", None)
            or not self._box_id
            or self._box_id == "unknown"
        ):
            return False  # pragma: no cover

        st = self.hass.states.get(f"sensor.oig_{self._box_id}_boiler_manual_mode")
        manual_state = st.state if st else None
        manual_s = str(manual_state).strip().lower() if manual_state is not None else ""
        return manual_s in {
            "1",
            "on",
            "zapnuto",
            "manual",
            "manuální",
            "manualni",
        } or manual_s.startswith("manu")

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

    def _state_box_mode_extended(self) -> Optional[str]:
        """Compute extended box mode from box_prm2_app sensor."""
        raw_app = self._get_box_prm2_app()
        if raw_app is None:
            self._attr_extra_state_attributes = {
                "raw_app": None,
                "home_grid_v": False,
                "home_grid_vi": False,
                "flexibilita": False,
            }
            return "unknown"
        state = parse_app_value(int(raw_app))
        canonical = canonical_extended_state(state)
        self._attr_extra_state_attributes = {
            "raw_app": int(raw_app),
            "home_grid_v": state.home_grid_v if state else False,
            "home_grid_vi": state.home_grid_vi if state else False,
            "flexibilita": state.flexibilita if state else False,
        }
        return canonical

    def _get_box_prm2_app(self) -> Optional[float]:
        """Get raw value from box_prm2_app sensor."""
        box_id = self._box_id
        if not (isinstance(box_id, str) and box_id.isdigit()):
            return None
        entity_id = f"sensor.oig_{box_id}_box_prm2_app"
        if not getattr(self, "hass", None):
            return None
        st = self.hass.states.get(entity_id)
        if not st:
            return None
        raw = str(st.state)
        if raw in ("unavailable", "", "unknown", "none"):
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

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
            current_values = self._extract_real_data_values(pv_data)
            if current_values is None:
                return False

            has_changes = self._detect_real_data_changes(current_values)
            self._monitored_sensors = current_values.copy()
            return has_changes

        except Exception as err:
            _LOGGER.error(
                "[%s] Error checking data changes: %s", self.entity_id, err
            )
            return False

    def _extract_real_data_values(
        self, pv_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if "actual" not in pv_data:
            _LOGGER.warning(
                "[%s] Live Data nejsou zapnutá - real data update nefunguje. "
                "Zapněte Live Data v OIG aplikaci.",
                self.entity_id,
            )
            return None

        actual = pv_data["actual"]
        current_values = {}
        for sensor_key in self._key_sensors:
            if sensor_key.startswith(("bat_", "fv_", "aco_", "aci_")):
                current_values[sensor_key] = actual.get(sensor_key, 0)
        return current_values

    def _detect_real_data_changes(self, current_values: Dict[str, Any]) -> bool:
        has_changes = False
        for key, current_value in current_values.items():
            previous_value = self._monitored_sensors.get(key)
            if (
                previous_value is None
                or abs(float(current_value) - float(previous_value)) > 0.1
            ):
                has_changes = True
                _LOGGER.debug(
                    "[%s] Real data change detected: %s %s -> %s",
                    self.entity_id,
                    key,
                    previous_value,
                    current_value,
                )
        return has_changes

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        self._cancel_reset()

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
