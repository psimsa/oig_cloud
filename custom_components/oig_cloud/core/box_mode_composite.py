"""Box mode composite types for OIG Cloud integration."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MainMode(Enum):
    """Main operating mode of the battery box."""

    home_1 = "home_1"
    home_2 = "home_2"
    home_3 = "home_3"
    home_ups = "home_ups"


@dataclass(frozen=True)
class SupplementaryState:
    """Supplementary state bits for extended box mode.

    Attributes:
        home_grid_v: Grid V mode bit
        home_grid_vi: Grid VI mode bit
        flexibilita: Flexibility mode bit
        raw: Raw integer value from API
    """

    home_grid_v: bool
    home_grid_vi: bool
    flexibilita: bool
    raw: int


def parse_app_value(raw: Optional[int]) -> Optional[SupplementaryState]:
    """Parse raw integer value into SupplementaryState.

    Bitmask mapping:
        0 -> (False, False, False) - no supplementary bits set
        1 -> (True, False, False) - home_grid_v set
        2 -> (False, True, False) - home_grid_vi set
        3 -> (True, True, False) - both home_grid bits set
        4 -> (False, False, True) - flexibilita set
        None -> None
        other (5, negative, 999, etc.) -> unknown state

    Args:
        raw: Raw integer value from app/box communication

    Returns:
        SupplementaryState if raw is 0-4 or None, None if raw is None
    """
    if raw is None:
        return None

    if raw == 0:
        return SupplementaryState(home_grid_v=False, home_grid_vi=False, flexibilita=False, raw=0)
    elif raw == 1:
        return SupplementaryState(home_grid_v=True, home_grid_vi=False, flexibilita=False, raw=1)
    elif raw == 2:
        return SupplementaryState(home_grid_v=False, home_grid_vi=True, flexibilita=False, raw=2)
    elif raw == 3:
        return SupplementaryState(home_grid_v=True, home_grid_vi=True, flexibilita=False, raw=3)
    elif raw == 4:
        return SupplementaryState(home_grid_v=False, home_grid_vi=False, flexibilita=True, raw=4)
    else:
        return SupplementaryState(home_grid_v=False, home_grid_vi=False, flexibilita=False, raw=raw)


def build_app_value(
    home_grid_v: Optional[bool],
    home_grid_vi: Optional[bool],
    current_raw: Optional[int],
) -> int:
    """Build app value using read-modify-write semantics.

    Args:
        home_grid_v: New value for home_grid_v bit, or None to preserve
        home_grid_vi: New value for home_grid_vi bit, or None to preserve
        current_raw: Current raw value to modify

    Returns:
        New raw value with specified bits updated

    Raises:
        ValueError: If current_raw is None and any toggle is specified
    """
    has_any_toggle = home_grid_v is not None or home_grid_vi is not None

    if not has_any_toggle:
        raise ValueError("At least one of home_grid_v or home_grid_vi must be specified")

    if current_raw is None:
        raise ValueError("current_raw cannot be None when any toggle is specified")

    result = current_raw

    if home_grid_v is not None:
        if home_grid_v:
            result = result | 1
        else:
            result = result & ~1

    if home_grid_vi is not None:
        if home_grid_vi:
            result = result | 2
        else:
            result = result & ~2

    return result


def canonical_extended_state(state: Optional[SupplementaryState]) -> str:
    """Get canonical string representation of extended state.

    Args:
        state: SupplementaryState to convert, or None

    Returns:
        Canonical string:
            "none" - state is None or raw=0
            "home_5" - home_grid_v=True, home_grid_vi=False
            "home_6" - home_grid_v=False, home_grid_vi=True
            "home_5_home_6" - home_grid_v=True, home_grid_vi=True
            "flexibility" - flexibilita=True
            "unknown" - any other combination
    """
    if state is None:
        return "none"

    if state.raw == 0:
        return "none"

    if state.flexibilita:
        return "flexibility"

    if state.home_grid_v and not state.home_grid_vi:
        return "home_5"

    if not state.home_grid_v and state.home_grid_vi:
        return "home_6"

    if state.home_grid_v and state.home_grid_vi:
        return "home_5_home_6"

    return "unknown"
