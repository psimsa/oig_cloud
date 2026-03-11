"""History helpers extracted from legacy battery forecast."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

from ..types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    SERVICE_MODE_HOME_1,
    SERVICE_MODE_HOME_2,
    SERVICE_MODE_HOME_3,
    SERVICE_MODE_HOME_UPS,
)

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
DATE_FMT = "%Y-%m-%d"
LOG_DATETIME_FMT = "%Y-%m-%d %H:%M"

_LOGGER = logging.getLogger(__name__)


def _as_utc(dt_value: datetime) -> datetime:
    return dt_value.astimezone(timezone.utc) if dt_value.tzinfo else dt_value


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_history_entity_ids(box_id: str) -> list[str]:
    return [
        f"sensor.oig_{box_id}_ac_out_en_day",
        f"sensor.oig_{box_id}_ac_in_ac_ad",
        f"sensor.oig_{box_id}_ac_in_ac_pd",
        f"sensor.oig_{box_id}_dc_in_fv_ad",
        f"sensor.oig_{box_id}_batt_bat_c",
        f"sensor.oig_{box_id}_box_prms_mode",
        f"sensor.oig_{box_id}_spot_price_current_15min",
        f"sensor.oig_{box_id}_export_price_current_15min",
    ]


def _select_interval_states(
    entity_states: list[Any], start_time: datetime, end_time: datetime
) -> list[Any]:
    if not entity_states:
        return []

    start_utc = _as_utc(start_time)
    end_utc = _as_utc(end_time)

    interval_states = [
        s
        for s in entity_states
        if start_utc <= s.last_updated.astimezone(timezone.utc) <= end_utc
    ]
    if interval_states:
        return interval_states

    before_states = [
        s for s in entity_states if s.last_updated.astimezone(timezone.utc) < start_utc
    ]
    after_states = [
        s for s in entity_states if s.last_updated.astimezone(timezone.utc) > end_utc
    ]
    if before_states and after_states:
        return [before_states[-1], after_states[0]]
    return []


def _calc_delta_kwh(
    entity_states: list[Any], start_time: datetime, end_time: datetime
) -> float:
    interval_states = _select_interval_states(entity_states, start_time, end_time)
    if len(interval_states) < 2:
        return 0.0

    start_val = _safe_float(interval_states[0].state)
    end_val = _safe_float(interval_states[-1].state)
    if start_val is None or end_val is None:
        return 0.0

    delta_wh = end_val - start_val
    if delta_wh < 0:
        delta_wh = end_val
    return delta_wh / 1000.0


def _get_value_at_end(entity_states: list[Any], end_time: datetime) -> Any:
    if not entity_states:
        return None

    end_utc = _as_utc(end_time)
    closest_state = min(
        entity_states,
        key=lambda s: abs(
            (s.last_updated.astimezone(timezone.utc) - end_utc).total_seconds()
        ),
    )
    return closest_state.state


def _get_last_value(entity_states: list[Any]) -> Any:
    if not entity_states:
        return None
    return entity_states[-1].state


def _parse_interval_start(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    start_dt = dt_util.parse_datetime(ts)
    if start_dt is None:
        try:
            start_dt = datetime.fromisoformat(ts)
        except Exception:
            return None
    if start_dt.tzinfo is None:
        start_dt = dt_util.as_local(start_dt)
    return start_dt


def _build_actual_interval_entry(
    interval_time: datetime, actual_data: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "time": interval_time.isoformat(),
        "solar_kwh": round(actual_data.get("solar_kwh", 0), 4),
        "consumption_kwh": round(actual_data.get("consumption_kwh", 0), 4),
        "battery_soc": round(actual_data.get("battery_soc", 0), 2),
        "battery_capacity_kwh": round(actual_data.get("battery_capacity_kwh", 0), 2),
        "grid_import_kwh": round(actual_data.get("grid_import", 0), 4),
        "grid_export_kwh": round(actual_data.get("grid_export", 0), 4),
        "net_cost": round(actual_data.get("net_cost", 0), 2),
        "spot_price": round(actual_data.get("spot_price", 0), 2),
        "export_price": round(actual_data.get("export_price", 0), 2),
        "mode": actual_data.get("mode", 0),
        "mode_name": actual_data.get("mode_name", "N/A"),
    }


async def _patch_existing_actual(
    sensor: Any, existing_actual: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    patched_existing: List[Dict[str, Any]] = []
    for interval in existing_actual:
        if interval.get("net_cost") is not None:
            patched_existing.append(interval)
            continue
        start_dt = _parse_interval_start(interval.get("time"))
        if start_dt is None:
            patched_existing.append(interval)
            continue
        interval_end = start_dt + timedelta(minutes=15)
        historical_patch = await fetch_interval_from_history(
            sensor, start_dt, interval_end
        )
        if historical_patch:
            interval = {
                **interval,
                "net_cost": round(historical_patch.get("net_cost", 0), 2),
                "spot_price": round(historical_patch.get("spot_price", 0), 2),
                "export_price": round(historical_patch.get("export_price", 0), 2),
            }
        patched_existing.append(interval)
    return patched_existing


async def _build_new_actual_intervals(
    sensor: Any,
    start_time: datetime,
    now: datetime,
    existing_times: set[str],
) -> List[Dict[str, Any]]:
    current_time = start_time
    new_intervals: List[Dict[str, Any]] = []

    while current_time <= now:
        interval_time_str = current_time.isoformat()
        if interval_time_str in existing_times:
            current_time += timedelta(minutes=15)
            continue

        actual_data = await fetch_interval_from_history(
            sensor, current_time, current_time + timedelta(minutes=15)
        )
        if actual_data:
            new_intervals.append(
                _build_actual_interval_entry(current_time, actual_data)
            )

        current_time += timedelta(minutes=15)
    return new_intervals


def _normalize_mode_history(mode_history: List[Dict[str, Any]]) -> list[dict[str, Any]]:
    mode_changes: list[dict[str, Any]] = []
    for mode_entry in mode_history:
        time_key = mode_entry.get("time", "")
        if not time_key:
            continue
        try:
            dt_value = datetime.fromisoformat(time_key)
            if dt_value.tzinfo is None:
                dt_value = dt_util.as_local(dt_value)
        except Exception:  # nosec B112
            continue
        mode_changes.append(
            {
                "time": dt_value,
                "mode": mode_entry.get("mode"),
                "mode_name": mode_entry.get("mode_name"),
            }
        )
    mode_changes.sort(key=lambda x: x["time"])
    return mode_changes


def _expand_modes_to_intervals(
    mode_changes: list[dict[str, Any]],
    day_start: datetime,
    fetch_end: datetime,
) -> Dict[str, Dict[str, Any]]:
    historical_modes_lookup: Dict[str, Dict[str, Any]] = {}
    interval_time = day_start
    while interval_time <= fetch_end:
        active_mode = None
        for change in mode_changes:
            if change["time"] <= interval_time:
                active_mode = change
            else:
                break

        if active_mode:
            interval_time_str = interval_time.strftime(DATETIME_FMT)
            historical_modes_lookup[interval_time_str] = {
                "time": interval_time_str,
                "mode": active_mode["mode"],
                "mode_name": active_mode["mode_name"],
            }

        interval_time += timedelta(minutes=15)
    return historical_modes_lookup


async def fetch_interval_from_history(  # noqa: C901
    sensor: Any, start_time: datetime, end_time: datetime
) -> Optional[Dict[str, Any]]:
    """Load actual data for a 15-min interval from HA history."""
    if not sensor._hass:  # pylint: disable=protected-access
        _LOGGER.debug("[fetch_interval_from_history] No _hass instance")
        return None

    log_rl = getattr(sensor, "_log_rate_limited", None)
    if log_rl:
        log_rl(
            "fetch_interval_range",
            "debug",
            "[fetch_interval_from_history] Fetching sample interval %s - %s",
            start_time,
            end_time,
            cooldown_s=900.0,
        )

    try:
        from homeassistant.components.recorder.history import get_significant_states

        box_id = sensor._box_id  # pylint: disable=protected-access
        entity_ids = _build_history_entity_ids(box_id)

        states = await sensor._hass.async_add_executor_job(  # pylint: disable=protected-access
            get_significant_states,
            sensor._hass,
            start_time,
            end_time,
            entity_ids,
            None,
            True,
        )

        if not states:
            return None

        def _states(entity_id: str) -> list[Any]:
            return states.get(entity_id, [])

        consumption_kwh = _calc_delta_kwh(
            _states(f"sensor.oig_{box_id}_ac_out_en_day"), start_time, end_time
        )
        grid_import_kwh = _calc_delta_kwh(
            _states(f"sensor.oig_{box_id}_ac_in_ac_ad"), start_time, end_time
        )
        grid_export_kwh = _calc_delta_kwh(
            _states(f"sensor.oig_{box_id}_ac_in_ac_pd"), start_time, end_time
        )
        solar_kwh = _calc_delta_kwh(
            _states(f"sensor.oig_{box_id}_dc_in_fv_ad"), start_time, end_time
        )

        battery_soc = _safe_float(
            _get_value_at_end(_states(f"sensor.oig_{box_id}_batt_bat_c"), end_time)
        )
        mode_raw = _get_value_at_end(
            _states(f"sensor.oig_{box_id}_box_prms_mode"), end_time
        )

        battery_kwh = 0.0
        if battery_soc is not None:
            total_capacity = (
                sensor._get_total_battery_capacity() or 0.0
            )  # pylint: disable=protected-access
            if total_capacity > 0:
                battery_kwh = (battery_soc / 100.0) * total_capacity

        spot_price = (
            _safe_float(
                _get_last_value(
                    _states(f"sensor.oig_{box_id}_spot_price_current_15min")
                )
            )
            or 0.0
        )
        export_price = (
            _safe_float(
                _get_last_value(
                    _states(f"sensor.oig_{box_id}_export_price_current_15min")
                )
            )
            or 0.0
        )

        import_cost = grid_import_kwh * spot_price
        export_revenue = grid_export_kwh * export_price
        net_cost = import_cost - export_revenue

        mode = (
            map_mode_name_to_id(str(mode_raw))
            if mode_raw is not None
            else CBB_MODE_HOME_I
        )

        mode_name = CBB_MODE_NAMES.get(mode, "HOME I")

        result = {
            "battery_kwh": round(battery_kwh, 2),
            "battery_soc": round(battery_soc, 1) if battery_soc is not None else 0.0,
            "mode": mode,
            "mode_name": mode_name,
            "solar_kwh": round(solar_kwh, 3),
            "consumption_kwh": round(consumption_kwh, 3),
            "grid_import": round(grid_import_kwh, 3),
            "grid_export": round(grid_export_kwh, 3),
            "spot_price": round(spot_price, 2),
            "export_price": round(export_price, 2),
            "net_cost": round(net_cost, 2),
        }

        if log_rl:
            log_rl(
                "fetch_interval_sample",
                "debug",
                "[fetch_interval_from_history] sample %s -> soc=%s kwh=%.2f cons=%.3f net=%.2f",
                start_time.strftime(LOG_DATETIME_FMT),
                battery_soc,
                battery_kwh,
                result["consumption_kwh"],
                result["net_cost"],
                cooldown_s=900.0,
            )

        return result

    except Exception as err:
        _LOGGER.warning("Failed to fetch history for %s: %s", start_time, err)
        return None


async def update_actual_from_history(sensor: Any) -> None:
    """Load actual values from HA history for today."""
    now = dt_util.now()
    today_str = now.strftime(DATE_FMT)

    plan_storage = await sensor._load_plan_from_storage(
        today_str
    )  # pylint: disable=protected-access
    if not plan_storage:
        _LOGGER.debug("No plan in Storage for %s, skipping history update", today_str)
        return

    plan_data = {
        "date": today_str,
        "plan": plan_storage.get("intervals", []),
        "actual": [],
    }

    if (
        sensor._daily_plan_state and sensor._daily_plan_state.get("date") == today_str
    ):  # pylint: disable=protected-access
        existing_actual = copy.deepcopy(
            sensor._daily_plan_state.get("actual", [])
        )  # pylint: disable=protected-access
        plan_data["actual"] = existing_actual
    else:
        existing_actual = plan_data.get("actual", [])

    _LOGGER.info("📊 Updating actual values from history for %s...", today_str)

    existing_actual = await _patch_existing_actual(sensor, existing_actual)
    plan_data["actual"] = existing_actual

    existing_times = {interval.get("time") for interval in existing_actual}

    _LOGGER.debug("Found %s existing actual intervals", len(existing_actual))

    start_time = dt_util.start_of_local_day(now)
    new_intervals = await _build_new_actual_intervals(
        sensor, start_time, now, existing_times
    )

    if new_intervals:
        plan_data["actual"] = existing_actual + new_intervals
        _LOGGER.info(
            "✅ Added %s new actual intervals (total: %s)",
            len(new_intervals),
            len(plan_data["actual"]),
        )
    else:
        _LOGGER.debug("No new actual intervals to add")

    if new_intervals:
        sensor._daily_plan_state = plan_data  # pylint: disable=protected-access
    else:
        _LOGGER.debug("No changes, skipping storage update")


async def fetch_mode_history_from_recorder(
    sensor: Any, start_time: datetime, end_time: datetime
) -> List[Dict[str, Any]]:
    """Load historical modes from HA Recorder."""
    if not sensor._hass:  # pylint: disable=protected-access
        _LOGGER.warning("HASS not available, cannot fetch mode history")
        return []

    sensor_id = (
        f"sensor.oig_{sensor._box_id}_box_prms_mode"  # pylint: disable=protected-access
    )

    try:
        from homeassistant.components.recorder import history

        history_data = await sensor._hass.async_add_executor_job(  # pylint: disable=protected-access
            history.state_changes_during_period,
            sensor._hass,
            start_time,
            end_time,
            sensor_id,
        )

        if not history_data or sensor_id not in history_data:
            _LOGGER.debug(
                "No mode history found for %s between %s - %s",
                sensor_id,
                start_time,
                end_time,
            )
            return []

        states = history_data[sensor_id]
        if not states:
            return []

        mode_intervals = []
        for state in states:
            mode_name = state.state
            if mode_name in ["unavailable", "unknown", None]:
                continue

            mode_id = map_mode_name_to_id(mode_name)

            mode_intervals.append(
                {
                    "time": state.last_changed.isoformat(),
                    "mode_name": mode_name,
                    "mode": mode_id,
                }
            )

        _LOGGER.debug(
            "📊 Fetched %s mode changes from Recorder for %s (%s - %s)",
            len(mode_intervals),
            sensor_id,
            start_time.strftime(LOG_DATETIME_FMT),
            end_time.strftime(LOG_DATETIME_FMT),
        )

        return mode_intervals

    except ImportError:
        _LOGGER.error("Recorder component not available")
        return []
    except Exception as err:
        _LOGGER.error("Error fetching mode history from Recorder: %s", err)
        return []


def map_mode_name_to_id(mode_name: str) -> int:
    """Map mode name (from sensor state) to mode ID."""
    mode_mapping = {
        SERVICE_MODE_HOME_1: CBB_MODE_HOME_I,
        SERVICE_MODE_HOME_2: CBB_MODE_HOME_II,
        SERVICE_MODE_HOME_3: CBB_MODE_HOME_III,
        SERVICE_MODE_HOME_UPS: CBB_MODE_HOME_UPS,
        "Home 5": CBB_MODE_HOME_I,
        "Home 6": CBB_MODE_HOME_I,
    }

    normalized = str(mode_name or "").strip()
    if not normalized:
        return CBB_MODE_HOME_I
    if normalized.lower() in {"unknown", "neznámý", "neznamy"}:
        return CBB_MODE_HOME_I

    mode_id = mode_mapping.get(normalized)
    if mode_id is None:
        _LOGGER.warning(
            "Unknown mode name '%s', using fallback mode ID 0 (HOME I)", mode_name
        )
        return CBB_MODE_HOME_I

    return mode_id


async def build_historical_modes_lookup(
    sensor: Any,
    *,
    day_start: datetime,
    fetch_end: datetime,
    date_str: str,
    source: str,
) -> Dict[str, Dict[str, Any]]:
    """Load historical mode changes from Recorder and expand to 15-min intervals."""
    if not sensor._hass:  # pylint: disable=protected-access
        return {}

    mode_history = await fetch_mode_history_from_recorder(sensor, day_start, fetch_end)
    mode_changes = _normalize_mode_history(mode_history)
    historical_modes_lookup = _expand_modes_to_intervals(
        mode_changes, day_start, fetch_end
    )

    _LOGGER.debug(
        "📊 Loaded %s historical mode intervals from Recorder for %s (%s) "
        "(expanded from %s changes)",
        len(historical_modes_lookup),
        date_str,
        source,
        len(mode_changes),
    )
    return historical_modes_lookup
