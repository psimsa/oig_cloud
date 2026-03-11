"""Lifecycle helpers for battery forecast sensor."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import timedelta

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..planning import auto_switch as auto_switch_module

_LOGGER = logging.getLogger(__name__)
DATE_FMT = "%Y-%m-%d"


async def async_added_to_hass(sensor):  # noqa: C901
    """Pri pridani do HA - restore persistent data."""

    # Phase 3.0: Retry Storage Helper initialization if failed in __init__
    if not sensor._plans_store and sensor._hass:
        sensor._plans_store = Store(
            sensor._hass,
            version=1,
            key=f"oig_cloud.battery_plans_{sensor._box_id}",
        )
        _LOGGER.info(
            f" Retry: Initialized Storage Helper: oig_cloud.battery_plans_{sensor._box_id}"
        )

    # Phase 3.5: Retry Precomputed Data Storage initialization if failed in __init__
    if not sensor._precomputed_store and sensor._hass:
        sensor._precomputed_store = Store(
            sensor._hass,
            version=1,
            key=f"oig_cloud.precomputed_data_{sensor._box_id}",
        )
        _LOGGER.info(
            f" Retry: Initialized Precomputed Data Storage: oig_cloud.precomputed_data_{sensor._box_id}"
        )

    if auto_switch_module.auto_mode_switch_enabled(sensor):
        auto_switch_module.start_auto_switch_watchdog(sensor)
        # Keep scheduled set_box_mode calls aligned with the currently loaded timeline.
        if sensor._side_effects_enabled:
            sensor._create_task_threadsafe(
                auto_switch_module.update_auto_switch_schedule, sensor
            )

    # Restore last successful forecast output (so dashboard doesn't show 0 after restart)
    # Source of truth is the precomputed storage which also includes timeline snapshot.
    if sensor._precomputed_store:
        try:
            precomputed = await sensor._precomputed_store.async_load() or {}
            timeline = precomputed.get("timeline_hybrid")
            last_update = precomputed.get("last_update")
            if isinstance(timeline, list) and timeline:
                sensor._timeline_data = timeline
                # Keep a copy as hybrid timeline if other code references it.
                setattr(sensor, "_hybrid_timeline", copy.deepcopy(timeline))
                if isinstance(last_update, str) and last_update:
                    try:
                        sensor._last_update = dt_util.parse_datetime(
                            last_update
                        ) or dt_util.dt.datetime.fromisoformat(last_update)
                    except Exception:
                        sensor._last_update = dt_util.now()
                sensor._data_hash = sensor._calculate_data_hash(sensor._timeline_data)
                sensor.async_write_ha_state()
                _LOGGER.debug(
                    "[BatteryForecast] Restored timeline from storage (%d points)",
                    len(sensor._timeline_data),
                )
        except Exception as err:
            _LOGGER.debug(
                "[BatteryForecast] Failed to restore precomputed data: %s", err
            )

    # Restore data z predchozi instance
    if last_state := await sensor.async_get_last_state():
        if last_state.attributes:
            # Restore active plan z attributes (pokud existoval)
            if "active_plan_data" in last_state.attributes:
                try:
                    plan_json = last_state.attributes.get("active_plan_data")
                    if plan_json:
                        sensor._active_charging_plan = json.loads(plan_json)
                        sensor._plan_status = last_state.attributes.get(
                            "plan_status", "pending"
                        )
                        if sensor._active_charging_plan:
                            _LOGGER.info(
                                f" Restored charging plan: "
                                f"requester={sensor._active_charging_plan.get('requester', 'unknown')}, "
                                f"status={sensor._plan_status}"
                            )
                except (json.decoder.JSONDecodeError, TypeError) as e:
                    _LOGGER.warning(f"Failed to restore charging plan: {e}")

    # PHASE 3.0: Storage Helper Integration
    # Storage plan se nacita on-demand v build_timeline_extended() (kdyz API endpoint vola)
    # NEPOTREBUJEME nacitat pri startu - to jen zpomaluje startup
    _LOGGER.debug("Sensor initialized - storage plans will load on-demand via API")

    # PHASE 3.1: Load daily plans archive from storage (vcera data pro Unified Cost Tile)
    if sensor._plans_store:
        try:
            storage_data = await sensor._plans_store.async_load() or {}
            if "daily_archive" in storage_data:
                sensor._daily_plans_archive = storage_data["daily_archive"]
                _LOGGER.info(
                    f" Restored daily plans archive from storage: {len(sensor._daily_plans_archive)} days"
                )
            else:
                _LOGGER.info("No daily archive in storage - will backfill from history")
        except Exception as e:
            _LOGGER.warning(f"Failed to load daily plans archive from storage: {e}")

    # PHASE 3.1: Backfill missing days from storage detailed plans
    if sensor._plans_store and len(sensor._daily_plans_archive) < 3:
        try:
            _LOGGER.info(" Backfilling daily plans archive from storage...")
            await sensor._backfill_daily_archive_from_storage()
        except Exception as e:
            _LOGGER.warning(f"Failed to backfill daily archive: {e}")

    # FALLBACK: Restore z attributes (stary zpusob - bude deprecated)
    if last_state and last_state.attributes:
        # Restore daily plan state with actual intervals (Phase 2.9)
        if "daily_plan_state" in last_state.attributes:
            try:
                daily_plan_json = last_state.attributes.get("daily_plan_state")
                if daily_plan_json:
                    sensor._daily_plan_state = json.loads(daily_plan_json)
                    actual_count = len(sensor._daily_plan_state.get("actual", []))
                    _LOGGER.info(
                        f" Restored daily plan state: "
                        f"date={sensor._daily_plan_state.get('date')}, "
                        f"actual={actual_count}"
                    )
            except (json.decoder.JSONDecodeError, TypeError) as e:
                _LOGGER.warning(f"Failed to restore daily plan state: {e}")

    # PHASE 3.0: DISABLED - Historical data loading moved to on-demand (API only)
    # Old Phase 2.9 loaded history every 15 min - POMALE a ZBYTECNE!
    # Nove: build_timeline_extended() nacita z Recorderu on-demand pri API volani
    _LOGGER.debug("Historical data will load on-demand via API (not at startup)")

    # Import helper pro time tracking
    from homeassistant.helpers.event import async_track_time_change

    # ========================================================================
    # SCHEDULER: Forecast refresh kazdych 15 minut (asynchronni, neblokuje)
    # ========================================================================
    async def _forecast_refresh_job(now):
        """Run forecast refresh every 15 minutes (aligned with spot price intervals)."""
        _LOGGER.info(f" Forecast refresh triggered at {now.strftime('%H:%M')}")
        try:
            await sensor.async_update()
        except Exception as e:
            _LOGGER.error(f"Forecast refresh failed: {e}", exc_info=True)

    # Schedule every 15 minutes (at :00, :15, :30, :45)
    for minute in [0, 15, 30, 45]:
        async_track_time_change(
            sensor.hass,
            _forecast_refresh_job,
            minute=minute,
            second=30,  # 30s offset to ensure spot prices are updated
        )
    _LOGGER.info(" Scheduled forecast refresh every 15 minutes")

    # ========================================================================
    # LISTEN for AdaptiveLoadProfiles updates (dispatcher pattern)
    # ========================================================================
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    async def _on_profiles_updated():
        """Called when AdaptiveLoadProfiles completes update."""
        # Do not recompute immediately; keep forecast cadence at 1 / 15 minutes.
        # Mark inputs dirty and let the next scheduled 15-min tick pick it up.
        sensor._profiles_dirty = True
        sensor._log_rate_limited(
            "profiles_updated_deferred",
            "info",
            " profiles_updated received - deferring forecast refresh to next 15-min tick",
            cooldown_s=300.0,
        )

    # Subscribe to profiles updates
    signal_name = f"oig_cloud_{sensor._box_id}_profiles_updated"
    _LOGGER.debug(f" Subscribing to signal: {signal_name}")
    async_dispatcher_connect(sensor.hass, signal_name, _on_profiles_updated)

    # ========================================================================
    # INITIAL REFRESH: Wait for profiles, then calculate (non-blocking)
    # ========================================================================
    async def _delayed_initial_refresh():
        """Initial forecast calculation - wait for profiles (non-blocking)."""
        # Wait max 60s for first profiles update
        _LOGGER.info(" Waiting for AdaptiveLoadProfiles to complete (max 60s)...")

        profiles_ready = False

        async def _mark_ready():
            nonlocal profiles_ready
            profiles_ready = True

        # Temporary listener for initial profiles
        temp_unsub = async_dispatcher_connect(
            sensor.hass, f"oig_cloud_{sensor._box_id}_profiles_updated", _mark_ready
        )

        try:
            # Wait max 60s for profiles
            for _ in range(60):
                if profiles_ready:
                    _LOGGER.info(" Profiles ready - starting initial forecast")
                    break
                await asyncio.sleep(1)
            else:
                _LOGGER.info("Profiles not ready after 60s - starting forecast anyway")

            # Now run forecast
            await sensor.async_update()
            _LOGGER.info(" Initial forecast completed")

        except Exception as e:
            _LOGGER.error(f"Initial forecast failed: {e}", exc_info=True)
        finally:
            # Cleanup temporary listener
            temp_unsub()

    # Spustit jako background task (neblokuje async_added_to_hass)
    sensor.hass.async_create_task(_delayed_initial_refresh())

    # ========================================================================
    # SCHEDULER: Daily and weekly aggregations
    # ========================================================================
    # Daily aggregation at 00:05 (aggregate yesterday's data)
    async def _daily_aggregation_job(now):
        """Run daily aggregation at 00:05."""
        yesterday = (now.date() - timedelta(days=1)).strftime(DATE_FMT)
        _LOGGER.info(f" Daily aggregation job triggered for {yesterday}")
        await sensor._aggregate_daily(yesterday)

    async_track_time_change(
        sensor.hass,
        _daily_aggregation_job,
        hour=0,
        minute=5,
        second=0,
    )
    _LOGGER.debug(" Scheduled daily aggregation at 00:05")

    # Weekly aggregation every Sunday at 23:55
    async def _weekly_aggregation_job(now):
        """Run weekly aggregation on Sunday at 23:55."""
        # Only run on Sunday (weekday() == 6)
        if now.weekday() != 6:
            return

        # Calculate week info
        year, week_num, _ = now.isocalendar()
        week_str = f"{year}-W{week_num:02d}"

        # Week end is today (Sunday)
        end_date = now.date().strftime(DATE_FMT)
        # Week start is 6 days ago (Monday)
        start_date = (now.date() - timedelta(days=6)).strftime(DATE_FMT)

        _LOGGER.info(f" Weekly aggregation job triggered for {week_str}")
        await sensor._aggregate_weekly(week_str, start_date, end_date)

    async_track_time_change(
        sensor.hass,
        _weekly_aggregation_job,
        hour=23,
        minute=55,
        second=0,
    )
    _LOGGER.debug(" Scheduled weekly aggregation at Sunday 23:55")
