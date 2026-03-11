"""Battery state helpers extracted from the forecast sensor."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    CBB_MODE_NAMES,
    MODE_LABEL_HOME_I,
    MODE_LABEL_HOME_II,
    MODE_LABEL_HOME_III,
    MODE_LABEL_HOME_UPS,
    SERVICE_MODE_HOME_1,
    SERVICE_MODE_HOME_2,
    SERVICE_MODE_HOME_3,
    SERVICE_MODE_HOME_5,
    SERVICE_MODE_HOME_6,
)

_LOGGER = logging.getLogger(__name__)

INVALID_STATES = {"unknown", "unavailable", None, ""}


def _read_state_float(
    sensor: Any, entity_id: str, *, scale: float = 1.0
) -> Optional[float]:
    if not sensor._hass:
        return None
    state = sensor._hass.states.get(entity_id)
    if not state or state.state in INVALID_STATES:
        return None
    try:
        return float(state.state) / scale
    except (ValueError, TypeError):
        return None


def _get_capacity_from_pv_data(sensor: Any) -> Optional[float]:
    pv_data_sensor = f"sensor.oig_{sensor._box_id}_pv_data"
    state = sensor._hass.states.get(pv_data_sensor) if sensor._hass else None
    if not state or not hasattr(state, "attributes"):
        return None
    try:
        pv_data = state.attributes.get("data", {})
        if isinstance(pv_data, dict):
            p_bat_wp = pv_data.get("box_prms", {}).get("p_bat")
            if p_bat_wp:
                total_kwh = float(p_bat_wp) / 1000.0
                _LOGGER.debug(
                    "Total battery capacity from API: %s Wp = %.2f kWh",
                    p_bat_wp,
                    total_kwh,
                )
                return total_kwh
    except (KeyError, ValueError, TypeError) as err:
        _LOGGER.debug("Error reading p_bat from pv_data: %s", err)
    return None


def _get_capacity_from_usable(sensor: Any) -> Optional[float]:
    usable_sensor = f"sensor.oig_{sensor._box_id}_usable_battery_capacity"
    usable_kwh = _read_state_float(sensor, usable_sensor, scale=1.0)
    if usable_kwh is None:
        return None
    total_kwh = usable_kwh / 0.8
    _LOGGER.debug(
        "Total battery capacity from usable: %.2f kWh -> %.2f kWh",
        usable_kwh,
        total_kwh,
    )
    return total_kwh


def get_total_battery_capacity(sensor: Any) -> Optional[float]:
    """Return total battery capacity in kWh."""
    if not sensor._hass:
        return None

    installed_sensor = f"sensor.oig_{sensor._box_id}_installed_battery_capacity_kwh"
    total_kwh = _read_state_float(sensor, installed_sensor, scale=1000.0)
    if total_kwh and total_kwh > 0:
        return total_kwh

    total_kwh = _get_capacity_from_pv_data(sensor)
    if total_kwh is not None:
        return total_kwh

    total_kwh = _get_capacity_from_usable(sensor)
    if total_kwh is not None:
        return total_kwh

    sensor._log_rate_limited(
        "battery_capacity_missing",
        "debug",
        "Battery total capacity not available yet; waiting for sensors",
        cooldown_s=600.0,
    )
    return None


def get_current_battery_soc_percent(sensor: Any) -> Optional[float]:
    """Return current battery SOC percentage."""
    if not sensor._hass:
        return None

    soc_sensor = f"sensor.oig_{sensor._box_id}_batt_bat_c"
    soc_percent = _read_state_float(sensor, soc_sensor, scale=1.0)
    if soc_percent is not None:
        _LOGGER.debug("Battery SOC from API: %.1f%%", soc_percent)
        return soc_percent

    sensor._log_rate_limited(
        "battery_soc_missing",
        "debug",
        "Battery SOC percent not available yet; waiting for sensors",
        cooldown_s=600.0,
    )
    return None


def get_current_battery_capacity(sensor: Any) -> Optional[float]:
    """Return current battery capacity in kWh (total * SOC%)."""
    total = get_total_battery_capacity(sensor)
    soc_percent = get_current_battery_soc_percent(sensor)
    if total is None or soc_percent is None:
        return None
    current_kwh = total * soc_percent / 100.0
    _LOGGER.debug(
        "Current battery capacity: %.2f kWh x %.1f%% = %.2f kWh",
        total,
        soc_percent,
        current_kwh,
    )
    return current_kwh


def get_max_battery_capacity(sensor: Any) -> Optional[float]:
    """Return max battery capacity (same as total)."""
    return get_total_battery_capacity(sensor)


def get_min_battery_capacity(sensor: Any) -> Optional[float]:
    """Return configured minimum capacity in kWh."""
    total = get_total_battery_capacity(sensor)
    if total is None:
        return None

    if sensor._config_entry:
        min_percent = (
            sensor._config_entry.options.get("min_capacity_percent")
            if sensor._config_entry.options
            else sensor._config_entry.data.get("min_capacity_percent", 33.0)
        )
        if min_percent is None:
            min_percent = 33.0
        min_kwh = total * float(min_percent) / 100.0
        _LOGGER.debug(
            "Min battery capacity: %.0f%% x %.2f kWh = %.2f kWh",
            min_percent,
            total,
            min_kwh,
        )
        return min_kwh

    return total * 0.33


def get_target_battery_capacity(sensor: Any) -> Optional[float]:
    """Return configured target capacity in kWh."""
    total = get_total_battery_capacity(sensor)
    if total is None:
        return None

    if sensor._config_entry:
        target_percent = (
            sensor._config_entry.options.get("target_capacity_percent")
            if sensor._config_entry.options
            else sensor._config_entry.data.get("target_capacity_percent", 80.0)
        )
        if target_percent is None:
            target_percent = 80.0
        target_kwh = total * float(target_percent) / 100.0
        _LOGGER.debug(
            "Target battery capacity: %.0f%% x %.2f kWh = %.2f kWh",
            target_percent,
            total,
            target_kwh,
        )
        return target_kwh

    return total * 0.80


def get_battery_efficiency(sensor: Any) -> float:
    """Return battery efficiency as a fraction."""
    if not sensor._hass:
        _LOGGER.debug("HASS not available, using fallback efficiency 0.882")
        return 0.882

    sensor_id = f"sensor.oig_{sensor._box_id}_battery_efficiency"
    state = sensor._hass.states.get(sensor_id)

    if not state or state.state in ["unknown", "unavailable"]:
        return 0.882

    try:
        efficiency_pct = float(state.state)
        efficiency = efficiency_pct / 100.0
        if efficiency < 0.70 or efficiency > 1.0:
            _LOGGER.warning(
                "Unrealistic efficiency %.3f (%.1f%%), using fallback 0.882",
                efficiency,
                efficiency_pct,
            )
            return 0.882
        return efficiency
    except (ValueError, TypeError) as err:
        _LOGGER.error("Error parsing battery efficiency: %s", err)
        return 0.882


def get_ac_charging_limit_kwh_15min(sensor: Any) -> float:
    """Return AC charging limit per 15 min interval in kWh."""
    config = sensor._config_entry.options if sensor._config_entry else {}
    charging_power_kw = config.get("home_charge_rate", 2.8)
    return charging_power_kw / 4.0


def get_current_mode(sensor: Any) -> int:
    """Return current CBB mode (0-3) based on sensor state."""
    if not sensor._hass:
        _LOGGER.debug("HASS not available, using fallback mode HOME III")
        return CBB_MODE_HOME_III

    sensor_id = f"sensor.oig_{sensor._box_id}_box_prms_mode"
    state = sensor._hass.states.get(sensor_id)

    if not state or state.state in ["unknown", "unavailable"]:
        _LOGGER.debug(
            "Mode sensor %s not available, using fallback HOME III", sensor_id
        )
        return CBB_MODE_HOME_III

    try:
        mode_value = state.state
        if isinstance(mode_value, str):
            mode_map = {
                MODE_LABEL_HOME_I: CBB_MODE_HOME_I,
                MODE_LABEL_HOME_II: CBB_MODE_HOME_II,
                MODE_LABEL_HOME_III: CBB_MODE_HOME_III,
                MODE_LABEL_HOME_UPS: CBB_MODE_HOME_UPS,
                SERVICE_MODE_HOME_1: CBB_MODE_HOME_I,
                SERVICE_MODE_HOME_2: CBB_MODE_HOME_II,
                SERVICE_MODE_HOME_3: CBB_MODE_HOME_III,
                SERVICE_MODE_HOME_5: CBB_MODE_HOME_I,
                SERVICE_MODE_HOME_6: CBB_MODE_HOME_I,
            }
            if mode_value in mode_map:
                mode = mode_map[mode_value]
            else:
                mode = int(mode_value)
        else:
            mode = int(mode_value)

        if mode in (4, 5):
            return CBB_MODE_HOME_I
        if mode not in (
            CBB_MODE_HOME_I,
            CBB_MODE_HOME_II,
            CBB_MODE_HOME_III,
            CBB_MODE_HOME_UPS,
        ):
            _LOGGER.warning("Invalid mode %s, using fallback HOME III", mode)
            return CBB_MODE_HOME_III

        mode_name = CBB_MODE_NAMES.get(mode, f"UNKNOWN_{mode}")
        _LOGGER.debug("Current CBB mode: %s (%s)", mode_name, mode)
        return mode

    except (ValueError, TypeError) as err:
        _LOGGER.error("Error parsing CBB mode from '%s': %s", state.state, err)
        return CBB_MODE_HOME_III


def get_boiler_available_capacity(sensor: Any) -> float:
    """Return boiler capacity per 15 min interval in kWh."""
    if not sensor._hass:
        return 0.0

    boiler_use_sensor = f"sensor.oig_{sensor._box_id}_boiler_is_use"
    state = sensor._hass.states.get(boiler_use_sensor)

    if not state or state.state not in ["on", "1", "true"]:
        return 0.0

    boiler_power_sensor = f"sensor.oig_{sensor._box_id}_boiler_install_power"
    power_state = sensor._hass.states.get(boiler_power_sensor)

    if not power_state:
        _LOGGER.warning(
            "Boiler is enabled but %s not found, using default 2.8 kW",
            boiler_power_sensor,
        )
        return 0.7

    try:
        power_kw = float(power_state.state)
        capacity_kwh_15min = power_kw / 4.0
        _LOGGER.debug(
            "Boiler available: %.2f kW -> %.2f kWh/15min",
            power_kw,
            capacity_kwh_15min,
        )
        return capacity_kwh_15min

    except (ValueError, TypeError) as err:
        _LOGGER.warning("Error parsing boiler power: %s, using default 0.7 kWh", err)
        return 0.7
