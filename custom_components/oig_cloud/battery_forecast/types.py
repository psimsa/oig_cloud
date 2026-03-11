"""Type definitions and constants for battery forecast module.

This module contains:
- CBB Mode constants and mappings
- TypedDicts for type safety
- Physical and operational constants
- Transition costs and constraints

All types are designed for static type checking with mypy/pyright.
"""

from enum import IntEnum
from typing import Any, Dict, List, Optional, TypedDict

# =============================================================================
# CBB Mode Constants
# =============================================================================


class CBBMode(IntEnum):
    """CBB 3F Home Plus Premium operating modes.

    These correspond to the inverter's actual mode values from
    sensor.oig_{box_id}_box_prms_mode
    """

    HOME_I = 0  # Grid priority - cheap mode, minimal battery usage
    HOME_II = 1  # Battery priority - preserve battery, grid covers deficit
    HOME_III = 2  # Solar priority - default, FVE → consumption → battery
    HOME_UPS = 3  # UPS mode - AC charging enabled from grid


# Legacy constants for backward compatibility
CBB_MODE_HOME_I: int = CBBMode.HOME_I.value  # 0
CBB_MODE_HOME_II: int = CBBMode.HOME_II.value  # 1
CBB_MODE_HOME_III: int = CBBMode.HOME_III.value  # 2
CBB_MODE_HOME_UPS: int = CBBMode.HOME_UPS.value  # 3

# Mode display names
CBB_MODE_NAMES: Dict[int, str] = {
    CBB_MODE_HOME_I: "HOME I",
    CBB_MODE_HOME_II: "HOME II",
    CBB_MODE_HOME_III: "HOME III",
    CBB_MODE_HOME_UPS: "HOME UPS",
}

MODE_LABEL_HOME_I = "Home I"
MODE_LABEL_HOME_II = "Home II"
MODE_LABEL_HOME_III = "Home III"
MODE_LABEL_HOME_UPS = "Home UPS"

SERVICE_MODE_HOME_1 = "Home 1"
SERVICE_MODE_HOME_2 = "Home 2"
SERVICE_MODE_HOME_3 = "Home 3"
SERVICE_MODE_HOME_UPS = "Home UPS"
SERVICE_MODE_HOME_5 = "Home 5"
SERVICE_MODE_HOME_6 = "Home 6"

# Mapping to Home Assistant service names
CBB_MODE_SERVICE_MAP: Dict[int, str] = {
    CBB_MODE_HOME_I: SERVICE_MODE_HOME_1,
    CBB_MODE_HOME_II: SERVICE_MODE_HOME_2,
    CBB_MODE_HOME_III: SERVICE_MODE_HOME_3,
    CBB_MODE_HOME_UPS: SERVICE_MODE_HOME_UPS,
}

# Modes where AC charging is DISABLED (only solar DC/DC charging allowed)
AC_CHARGING_DISABLED_MODES: List[int] = [
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
]


# =============================================================================
# Physical Constants
# =============================================================================

# Time interval for planning (15 minutes)
INTERVAL_MINUTES: int = 15
INTERVALS_PER_HOUR: int = 4
INTERVALS_PER_DAY: int = 96

# Default battery efficiency if sensor unavailable
# Based on CBB 3F Home Plus Premium specs: DC/AC 88.2%, AC/DC 95%, DC/DC 95%
DEFAULT_EFFICIENCY: float = 0.882

# Default AC charging rate if not configured
# CBB 3F: ~2.8 kW max → 0.7 kWh per 15min interval
DEFAULT_CHARGE_RATE_KW: float = 2.8
DEFAULT_CHARGE_RATE_PER_INTERVAL: float = DEFAULT_CHARGE_RATE_KW * (
    INTERVAL_MINUTES / 60
)

# Battery capacity bounds (CBB 3F Home Plus Premium)
# Physical minimum: 20% SOC (inverter protection)
# User minimum: configurable (typically 33% for emergency reserve)
PHYSICAL_SOC_MIN: float = 0.20
DEFAULT_USER_SOC_MIN: float = 0.33
DEFAULT_TARGET_SOC: float = 0.80


# =============================================================================
# Transition Costs
# =============================================================================

# Mode transition costs (energy loss + time delay)
# Key: (from_mode, to_mode) tuple with service names
TRANSITION_COSTS: Dict[tuple, Dict[str, Any]] = {
    (MODE_LABEL_HOME_I, MODE_LABEL_HOME_UPS): {
        "energy_loss_kwh": 0.05,  # Energy loss when switching to UPS
        "time_delay_intervals": 1,  # Delay in 15-min intervals
    },
    (MODE_LABEL_HOME_UPS, MODE_LABEL_HOME_I): {
        "energy_loss_kwh": 0.02,  # Energy loss when switching from UPS
        "time_delay_intervals": 0,
    },
    (MODE_LABEL_HOME_I, MODE_LABEL_HOME_II): {
        "energy_loss_kwh": 0.0,  # No loss between Home modes
        "time_delay_intervals": 0,
    },
    (MODE_LABEL_HOME_II, MODE_LABEL_HOME_I): {
        "energy_loss_kwh": 0.0,
        "time_delay_intervals": 0,
    },
    # All other transitions default to zero cost
}

# Minimum mode duration (in 15-min intervals)
MIN_MODE_DURATION: Dict[str, int] = {
    MODE_LABEL_HOME_UPS: 2,  # UPS must run at least 30 minutes (2×15min)
    MODE_LABEL_HOME_I: 1,
    MODE_LABEL_HOME_II: 1,
    MODE_LABEL_HOME_III: 1,
}


# =============================================================================
# TypedDicts for Type Safety
# =============================================================================


class SpotPrice(TypedDict, total=False):
    """Spot price data for a single interval.

    Attributes:
        time: ISO timestamp of interval start
        price: Price in CZK/kWh (buy price)
        export_price: Export/sell price in CZK/kWh
        level: Price level category (low/medium/high)
    """

    time: str
    price: float
    export_price: float
    level: str


class SolarForecast(TypedDict, total=False):
    """Solar forecast data.

    Attributes:
        today: Dict mapping ISO timestamp to kWh production
        tomorrow: Dict mapping ISO timestamp to kWh production
        total_today: Total expected production today (kWh)
        total_tomorrow: Total expected production tomorrow (kWh)
    """

    today: Dict[str, float]
    tomorrow: Dict[str, float]
    total_today: float
    total_tomorrow: float


class TimelineInterval(TypedDict, total=False):
    """Single interval in the battery timeline.

    Attributes:
        timestamp: ISO timestamp of interval start
        battery_kwh: Battery state of charge at interval START (kWh)
        battery_pct: Battery state of charge as percentage (0-100)
        mode: Recommended mode (0=HOME I, 1=HOME II, 2=HOME III, 3=HOME UPS)
        mode_name: Human-readable mode name
        solar_kwh: Expected solar production this interval (kWh)
        consumption_kwh: Expected consumption this interval (kWh)
        grid_import_kwh: Expected grid import this interval (kWh)
        grid_export_kwh: Expected grid export this interval (kWh)
        spot_price: Spot price this interval (CZK/kWh)
        cost_czk: Cost of this interval (CZK)
        reason: Reason for mode selection
        is_mode_change: True if mode changed from previous interval
        is_charging: True if battery is charging (from grid or solar)
        is_balancing: True if this interval is part of balancing plan
        is_holding: True if in holding period (maintain 100%)
    """

    timestamp: str
    battery_kwh: float
    battery_pct: float
    mode: int
    mode_name: str
    solar_kwh: float
    consumption_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    spot_price: float
    cost_czk: float
    reason: str
    is_mode_change: bool
    is_charging: bool
    is_balancing: bool
    is_holding: bool


class ChargingInterval(TypedDict, total=False):
    """Charging interval from balancing plan.

    Attributes:
        timestamp: ISO timestamp when to charge
        price: Spot price at this interval
        expected_kwh: Expected charging amount
    """

    timestamp: str
    price: float
    expected_kwh: float


class BalancingPlan(TypedDict, total=False):
    """Balancing plan from BalancingManager.

    Attributes:
        reason: Why balancing is needed (opportunistic/interval/emergency)
        mode: Balancing mode type
        holding_start: ISO timestamp when holding period starts (deadline)
        holding_end: ISO timestamp when holding period ends
        charging_intervals: List of preferred charging intervals
        target_soc_percent: Target SOC (always 100 for balancing)
        total_cost_czk: Estimated total cost
        deadline: Same as holding_start (when battery must be at 100%)
    """

    reason: str
    mode: str
    holding_start: str
    holding_end: str
    charging_intervals: List[ChargingInterval]
    target_soc_percent: float
    total_cost_czk: float
    deadline: str


class ModeRecommendation(TypedDict, total=False):
    """Mode recommendation for a time block.

    Used for dashboard display - groups consecutive intervals with same mode.

    Attributes:
        mode: Mode number (0-3)
        mode_name: Human-readable mode name
        start: ISO timestamp of block start
        end: ISO timestamp of block end
        duration_hours: Block duration in hours
        avg_battery_pct: Average battery percentage during block
        cost_czk: Total cost of this block
        savings_vs_home_i: Savings compared to pure HOME I strategy
        rationale: Human-readable explanation why this mode
    """

    mode: int
    mode_name: str
    start: str
    end: str
    duration_hours: float
    avg_battery_pct: float
    cost_czk: float
    savings_vs_home_i: float
    rationale: str


class OptimizationResult(TypedDict, total=False):
    """Result of HYBRID optimization algorithm.

    Attributes:
        modes: List of mode values for each interval (0-3)
        modes_distribution: Count of each mode type
        total_cost_czk: Total estimated cost
        baseline_cost_czk: Cost without optimization (HOME I only)
        total_grid_import_kwh: Total expected grid import
        total_grid_export_kwh: Total expected grid export
        total_solar_kwh: Total expected solar production
        ups_intervals_count: Number of HOME UPS intervals
        charging_kwh: Total expected charging amount
        final_battery_kwh: Expected battery at end of timeline
        is_balancing_mode: True if optimizing for balancing
        balancing_deadline: ISO timestamp of balancing deadline (if applicable)
        balancing_holding_start: ISO timestamp of holding start
        balancing_holding_end: ISO timestamp of holding end
        calculation_time_ms: Time taken for optimization
        negative_price_detected: True if negative prices were detected
        negative_price_start_idx: Index of first negative price interval
        negative_price_end_idx: Index of last negative price interval
        negative_price_excess_solar_kwh: Solar excess during negative prices
        negative_price_curtailment_kwh: Expected curtailment during negative prices
        negative_price_actions: List of recommended actions for negative prices
    """

    modes: List[int]
    modes_distribution: Dict[str, int]
    total_cost_czk: float
    baseline_cost_czk: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_solar_kwh: float
    ups_intervals_count: int
    charging_kwh: float
    final_battery_kwh: float
    is_balancing_mode: bool
    balancing_deadline: Optional[str]
    balancing_holding_start: Optional[str]
    balancing_holding_end: Optional[str]
    calculation_time_ms: float
    # Negative price strategy fields
    negative_price_detected: bool
    negative_price_start_idx: int
    negative_price_end_idx: int
    negative_price_excess_solar_kwh: float
    negative_price_curtailment_kwh: float
    negative_price_actions: List[str]


class BatteryConfig(TypedDict, total=False):
    """Battery configuration parameters.

    Attributes:
        max_capacity_kwh: Maximum battery capacity (kWh)
        min_capacity_kwh: Minimum usable capacity / user reserve (kWh)
        physical_min_kwh: Physical minimum (20% SOC protection)
        target_capacity_kwh: Target SOC for optimization
        charge_rate_kw: AC charging rate (kW)
        efficiency: Round-trip efficiency (0-1)
        box_id: Device identifier
    """

    max_capacity_kwh: float
    min_capacity_kwh: float
    physical_min_kwh: float
    target_capacity_kwh: float
    charge_rate_kw: float
    efficiency: float
    box_id: str


# =============================================================================
# Helper Functions
# =============================================================================


def get_mode_name(mode: int) -> str:
    """Get human-readable mode name from mode number."""
    return CBB_MODE_NAMES.get(mode, f"UNKNOWN ({mode})")


def get_service_name(mode: int) -> str:
    """Get HA service name from mode number."""
    return CBB_MODE_SERVICE_MAP.get(mode, "Home 3")  # Default to HOME III


def is_charging_mode(mode: int) -> bool:
    """Check if mode allows AC charging from grid."""
    return mode == CBB_MODE_HOME_UPS


def mode_from_name(name: str) -> int:
    """Get mode number from name (case insensitive)."""
    name_upper = name.upper().replace(" ", "_").replace("_", " ")
    for mode_num, mode_name in CBB_MODE_NAMES.items():
        if mode_name.upper() == name_upper or mode_name.upper().replace(
            " ", ""
        ) == name_upper.replace(" ", ""):
            return mode_num
    # Legacy aliases (older UI / logs)
    legacy = {
        "HOME I": CBB_MODE_HOME_I,
        "HOME 1": CBB_MODE_HOME_I,
        "HOME II": CBB_MODE_HOME_II,
        "HOME 2": CBB_MODE_HOME_II,
        "HOME III": CBB_MODE_HOME_III,
        "HOME 3": CBB_MODE_HOME_III,
        "HOME UPS": CBB_MODE_HOME_UPS,
    }
    if name_upper in legacy:
        return legacy[name_upper]
    return CBB_MODE_HOME_III  # Default


def safe_nested_get(obj: Optional[Dict[str, Any]], *keys: str, default: Any = 0) -> Any:
    """Safely get nested dict values, handling None at any level.

    Args:
        obj: Dict or None
        keys: Sequence of keys to traverse (e.g., "planned", "net_cost")
        default: Default value if any key is missing or value is None

    Returns:
        Value if found, default otherwise

    Example:
        safe_nested_get(interval, "planned", "net_cost", default=0)
        # Same as: interval.get("planned", {}).get("net_cost", 0)
        # But handles: interval.get("planned") = None ✓
    """
    current = obj
    for key in keys:
        if current is None or not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default
