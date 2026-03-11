"""Konstanty pro bojlerový modul."""

from typing import Final

# Fyzikální konstanty
WATER_SPECIFIC_HEAT: Final[float] = 4186.0  # J/(kg·K)
WATER_DENSITY: Final[float] = 1000.0  # kg/m³
JOULES_TO_KWH: Final[float] = 1 / 3_600_000  # 1 kWh = 3.6 MJ

# Stratifikace
TEMP_GRADIENT_PER_10CM: Final[float] = 0.8  # °C/10cm výška
BOILER_HEIGHT_DEFAULT: Final[float] = 1.5  # m

# Pozice senzoru (% výšky od spodu)
SENSOR_POSITION_MAP: Final[dict[str, float]] = {
    "top": 1.0,  # 100%
    "upper_quarter": 0.75,  # 75%
    "middle": 0.5,  # 50%
    "lower_quarter": 0.25,  # 25%
}

# Profiling - adaptivní kategorie
PROFILE_CATEGORIES: Final[list[str]] = [
    "workday_spring",
    "workday_summer",
    "workday_autumn",
    "workday_winter",
    "weekend_spring",
    "weekend_summer",
    "weekend_autumn",
    "weekend_winter",
]

# Sezóny (měsíc → sezóna)
SEASON_MAP: Final[dict[int, str]] = {
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
    1: "winter",
    2: "winter",
}

# Minimální confidence pro použití profilu
MIN_CONFIDENCE: Final[float] = 0.3

# FVE overflow detekce
BATTERY_SOC_OVERFLOW_THRESHOLD: Final[float] = 100.0  # %

# Planning
DEFAULT_HYSTERESIS_TEMP: Final[float] = 5.0  # °C
MIN_SLOT_DURATION: Final[int] = 15  # minut
