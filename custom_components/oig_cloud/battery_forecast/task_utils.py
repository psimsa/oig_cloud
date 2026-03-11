"""Async task helpers for battery forecast."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)


def schedule_forecast_retry(sensor, delay_seconds: float) -> None:
    """Schedule a forecast retry with throttling."""
    if not sensor._hass or delay_seconds <= 0:
        return
    if sensor._forecast_retry_unsub:
        return

    def _retry(now: datetime) -> None:
        sensor._forecast_retry_unsub = None
        create_task_threadsafe(sensor, sensor.async_update)

    sensor._forecast_retry_unsub = async_call_later(sensor._hass, delay_seconds, _retry)


def create_task_threadsafe(sensor, coro_func, *args) -> None:
    """Create an HA task safely from any thread."""
    hass = getattr(sensor, "_hass", None) or getattr(sensor, "hass", None)
    if not hass:
        return

    def _runner() -> None:
        try:
            hass.async_create_task(coro_func(*args))
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.debug(
                "Failed to schedule task %s: %s",
                getattr(coro_func, "__name__", str(coro_func)),
                err,
            )

    try:
        loop = hass.loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _runner()
        else:
            loop.call_soon_threadsafe(_runner)
    except Exception:  # pragma: no cover - defensive
        _runner()
