"""Utility funkce pro bojlerový modul."""

import logging
from typing import Optional

from .const import (
    BOILER_HEIGHT_DEFAULT,
    JOULES_TO_KWH,
    SENSOR_POSITION_MAP,
    TEMP_GRADIENT_PER_10CM,
    WATER_SPECIFIC_HEAT,
)

_LOGGER = logging.getLogger(__name__)


def calculate_stratified_temp(
    measured_temp: float,
    sensor_position: str,
    mode: str = "two_zone",
    split_ratio: float = 0.5,
    boiler_height_m: float = BOILER_HEIGHT_DEFAULT,
) -> tuple[float, float]:
    """
    Vypočítá (horní_zóna_temp, dolní_zóna_temp) z jednoho teploměru.

    Args:
        measured_temp: Naměřená teplota [°C]
        sensor_position: "top", "upper_quarter", "middle", "lower_quarter"
        mode: "two_zone" nebo "simple_avg"
        split_ratio: Poměr horní zóny (0.5 = polovina)
        boiler_height_m: Výška bojleru [m]

    Returns:
        (T_horní, T_dolní) v °C
    """
    if mode == "simple_avg":
        # Jednoduchý režim - obě zóny = měřená hodnota
        return (measured_temp, measured_temp)

    # Pozice senzoru (0.0 = spodek, 1.0 = vršek)
    sensor_height_ratio = SENSOR_POSITION_MAP.get(sensor_position, 1.0)

    # Gradient: °C/m
    gradient_per_meter = TEMP_GRADIENT_PER_10CM * 10.0

    # Střed horní zóny
    upper_zone_center = 1.0 - (1.0 - split_ratio) / 2.0
    # Střed dolní zóny
    lower_zone_center = split_ratio / 2.0

    # Výpočet teplot zón
    height_diff_upper = (upper_zone_center - sensor_height_ratio) * boiler_height_m
    temp_upper = measured_temp + (gradient_per_meter * height_diff_upper)

    height_diff_lower = (lower_zone_center - sensor_height_ratio) * boiler_height_m
    temp_lower = measured_temp + (gradient_per_meter * height_diff_lower)

    return (temp_upper, temp_lower)


def calculate_energy_to_heat(
    volume_liters: float,
    temp_current: float,
    temp_target: float,
) -> float:
    """
    Vypočítá energii potřebnou k ohřevu vody.

    Args:
        volume_liters: Objem vody [l]
        temp_current: Současná teplota [°C]
        temp_target: Cílová teplota [°C]

    Returns:
        Energie [kWh]
    """
    if temp_target <= temp_current:
        return 0.0

    mass_kg = volume_liters  # 1l vody = 1kg
    temp_delta = temp_target - temp_current

    # Q = m × c × ΔT
    energy_joules = mass_kg * WATER_SPECIFIC_HEAT * temp_delta
    energy_kwh = energy_joules * JOULES_TO_KWH

    return energy_kwh


def estimate_residual_energy(
    total_consumption_kwh: float,
    fve_contribution_kwh: float,
    grid_contribution_kwh: float,
) -> float:
    """
    Vypočítá residuální energii (alternativní zdroj) jako rozdíl.

    Args:
        total_consumption_kwh: Celková spotřeba bojleru
        fve_contribution_kwh: Energie z FVE
        grid_contribution_kwh: Energie ze sítě

    Returns:
        Residuální energie [kWh] (≥ 0)
    """
    residual = total_consumption_kwh - fve_contribution_kwh - grid_contribution_kwh
    return max(0.0, residual)


def validate_temperature_sensor(
    state: Optional[object],
    sensor_name: str,
) -> Optional[float]:
    """
    Validuje a vrací teplotu ze senzoru.

    Args:
        state: Stav entity z Home Assistant
        sensor_name: Název senzoru (pro logging)

    Returns:
        Teplota v °C nebo None pokud neplatná
    """
    if state is None:
        _LOGGER.debug("Senzor %s není dostupný", sensor_name)
        return None

    try:
        temp = float(state.state)  # type: ignore[attr-defined]
        if not (-50 <= temp <= 150):
            _LOGGER.warning(
                "Senzor %s má neplatnou teplotu: %s°C (rozsah -50 až 150°C)",
                sensor_name,
                temp,
            )
            return None
        return temp
    except (ValueError, AttributeError) as err:
        _LOGGER.warning("Nelze přečíst teplotu ze senzoru %s: %s", sensor_name, err)
        return None
