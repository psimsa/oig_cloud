"""Shared helpers for spot price sensors."""

from __future__ import annotations

from typing import Any

from ..const import OTE_SPOT_PRICE_CACHE_FILE


def _ote_cache_path(hass) -> str:
    return hass.config.path(".storage", OTE_SPOT_PRICE_CACHE_FILE)


def _resolve_box_id_from_coordinator(coordinator: Any) -> str:
    """Resolve numeric box_id (never use helper keys like 'spot_prices')."""
    try:
        from ..entities.base_sensor import resolve_box_id

        return resolve_box_id(coordinator)
    except Exception:
        return "unknown"


# Retry plán: 5, 10, 15, 30 minut a pak každou hodinu
RETRY_DELAYS_SECONDS = [300, 600, 900, 1800]
HOURLY_RETRY_SECONDS = 3600
# Denní stahování ve 13:00
DAILY_FETCH_HOUR = 13
DAILY_FETCH_MINUTE = 0
