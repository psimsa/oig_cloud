"""Sdílený kód pro OIG Cloud komponentu."""

import logging
from enum import Enum

_LOGGER = logging.getLogger(__name__)


class GridMode(Enum):
    """Enum pro různé režimy provozu FVE."""

    OFF = "Vypnuto"
    ON = "Do sítě"
    LIMITED = "Omezeno"
    CHANGING = "Probíhá změna"


# Přidané konstanty pro handlování OpenTelemetry bez blokujícího importu
SERVICE_NAME = "oig_cloud"
TELEMETRY_ENABLED = False


def setup_non_blocking_telemetry(enabled: bool = False) -> None:
    """Nastaví telemetrii bez blokujících importů."""
    global TELEMETRY_ENABLED
    TELEMETRY_ENABLED = enabled
    _LOGGER.debug(f"Telemetry {'enabled' if enabled else 'disabled'}")
