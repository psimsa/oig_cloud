"""Balancing Manager - Pure Planning Layer (NO PHYSICS).

TODO 5: Implement Natural/Opportunistic/Forced balancing as mode planner.

This module is ONLY responsible for:
1. Detecting when balancing is needed (7-day cycle)
2. Finding suitable charging windows
3. Creating BalancingPlan with mode overrides

It does NOT:
- Simulate battery physics (that's in forecast._simulate_interval)
- Calculate costs (that's in HYBRID)
- Apply modes (that's in HYBRID reading this plan)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ...const import HOME_UPS
from .plan import (
    BalancingInterval,
    BalancingPlan,
    create_forced_plan,
    create_natural_plan,
    create_opportunistic_plan,
)

_LOGGER = logging.getLogger(__name__)

# Constants per refactoring requirements
# These are now loaded from config_entry.options, keeping defaults here for reference:
# - balancing_holding_time: 3 hours (how long to hold at 100%)
# - balancing_cycle_days: 7 days (max days between forced balancing)
# - balancing_cooldown_hours: 24 hours (min time between opportunistic attempts)
# - balancing_soc_threshold: 80% (min SoC for opportunistic balancing)

MIN_MODE_DURATION = 4  # Minimum 4 intervals (1 hour) per mode


class BalancingManager:
    """Balancing manager - pure planning layer.

    Implements TODO 5: Natural/Opportunistic/Forced balancing logic.

    This is NOT a simulation engine - it only creates plans (mode schedules).
    Forecast applies these plans during HYBRID calculation.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        box_id: str,
        storage_path: str,
        config_entry: Any,
    ):
        """Initialize balancing manager.

        Args:
            hass: Home Assistant instance
            box_id: Box ID for sensor access
            storage_path: Path for storing balancing state
            config_entry: Config entry for accessing balancing options
        """
        self.hass = hass
        self.box_id = box_id
        self._config_entry = config_entry
        self._logger = _LOGGER

        # Storage for balancing state
        self._store = Store(
            hass,
            version=1,
            key=f"oig_cloud_balancing_{box_id}",
            private=True,
        )

        # Current state
        self._last_balancing_ts: Optional[datetime] = None
        self._active_plan: Optional[BalancingPlan] = None
        self._forecast_sensor = None  # Reference to forecast sensor for timeline access
        self._coordinator = None  # Reference to coordinator for refresh triggers

        # Cost tracking for frontend display
        self._last_immediate_cost: Optional[float] = None
        self._last_selected_cost: Optional[float] = None
        self._last_cost_savings: Optional[float] = None

    # Configuration parameter helpers
    def _get_holding_time_hours(self) -> int:
        """Get balancing holding time from config (default 3 hours)."""
        opts = self._config_entry.options
        # Wizard/options key used in config_flow.py
        if "balancing_hold_hours" in opts:
            return int(opts.get("balancing_hold_hours") or 3)
        # Legacy/internal key
        return int(opts.get("balancing_holding_time") or 3)

    def _get_cycle_days(self) -> int:
        """Get balancing cycle days from config (default 7 days)."""
        opts = self._config_entry.options
        if "balancing_interval_days" in opts:
            return int(opts.get("balancing_interval_days") or 7)
        return int(opts.get("balancing_cycle_days") or 7)

    def _get_cooldown_hours(self) -> int:
        """Get balancing cooldown hours from config (default ~70% of cycle, min 24h)."""
        configured = self._config_entry.options.get("balancing_cooldown_hours")
        if configured is not None:
            try:
                configured_val = float(configured)
            except (TypeError, ValueError):
                configured_val = None
            if configured_val and configured_val > 0:
                return int(configured_val)

        cycle_days = float(self._get_cycle_days())
        cooldown_hours = int(math.ceil(cycle_days * 24 * 0.7))
        return max(24, cooldown_hours)

    def _get_soc_threshold(self) -> int:
        """Get SoC threshold for opportunistic balancing from config (default 80%)."""
        return self._config_entry.options.get("balancing_soc_threshold", 80)

    def _get_cheap_window_percentile(self) -> int:
        """Percentile threshold for 'cheap' windows (default 30%).

        Reuses the general cheap-window option so balancing aligns with planner behavior.
        """
        try:
            return int(self._config_entry.options.get("cheap_window_percentile", 30))
        except Exception:
            return 30

    async def async_setup(self) -> None:
        """Load balancing state from storage - MUST be fast and safe."""
        _LOGGER.info("BalancingManager: async_setup() start")
        try:
            # 1) Load state from storage (already async)
            await self._load_state_safe()

            # 2) No periodic task registration here - done in __init__.py
            # 3) No initial check here - done in __init__.py via async_call_later

            _LOGGER.info("BalancingManager: async_setup() done")
        except Exception as err:
            _LOGGER.error(
                "BalancingManager: async_setup() failed: %s", err, exc_info=True
            )
            raise

    async def _load_state_safe(self) -> None:
        """Safely load state from storage."""
        try:
            data = await self._store.async_load()
            if data:
                if data.get("last_balancing_ts"):
                    self._last_balancing_ts = datetime.fromisoformat(
                        data["last_balancing_ts"]
                    )
                if data.get("active_plan"):
                    self._active_plan = BalancingPlan.from_dict(data["active_plan"])

            _LOGGER.info(
                f"BalancingManager: State loaded. Last balancing: {self._last_balancing_ts}"
            )
        except Exception as err:
            _LOGGER.warning(
                "BalancingManager: Failed to load state: %s (starting fresh)", err
            )
            # Start with clean state if load fails
            self._last_balancing_ts = None
            self._active_plan = None

    async def _save_state(self) -> None:
        """Save balancing state to storage."""
        data = {
            "last_balancing_ts": (
                self._last_balancing_ts.isoformat() if self._last_balancing_ts else None
            ),
            "active_plan": self._active_plan.to_dict() if self._active_plan else None,
        }
        await self._store.async_save(data)

        # CRITICAL: Trigger coordinator refresh to recalculate timeline with new plan
        # This ensures UI (detail tabs) shows updated HOME_UPS blocks for balancing
        # Use coordinator instead of direct call to avoid blocking/deadlock
        if self._coordinator:
            _LOGGER.info(
                "🔄 Requesting coordinator refresh after balancing state change"
            )
            try:
                # Schedule async refresh - non-blocking
                await self._coordinator.async_request_refresh()
                _LOGGER.info("✅ Coordinator refresh scheduled successfully")
            except Exception as e:
                _LOGGER.error(f"Failed to request coordinator refresh: {e}")
                _LOGGER.info(
                    "✅ Forecast sensor and storage updated with balancing plan"
                )

    def set_forecast_sensor(self, forecast_sensor: Any) -> None:
        """Set reference to forecast sensor for timeline access.

        Args:
            forecast_sensor: OigCloudBatteryForecastSensor instance
        """
        self._forecast_sensor = forecast_sensor

    def set_coordinator(self, coordinator: Any) -> None:
        """Set reference to coordinator for refresh triggers.

        Args:
            coordinator: DataUpdateCoordinator instance
        """
        self._coordinator = coordinator

    async def check_balancing(self, force: bool = False) -> Optional[BalancingPlan]:
        """Check if balancing is needed and create plan.

        Called periodically (e.g., every 30 minutes) by coordinator.

        Args:
            force: If True, forces creation of balancing plan regardless of cooldown/cycle

        Returns:
            BalancingPlan if created, None otherwise
        """
        _LOGGER.debug(f"BalancingManager: check_balancing() CALLED (force={force})")

        if not self._forecast_sensor:
            _LOGGER.warning("Forecast sensor not set, cannot check balancing")
            return None

        # 0. Check if balancing just completed
        balancing_occurred, completion_time = await self._check_if_balancing_occurred()
        if balancing_occurred:
            _LOGGER.info(
                f"✅ Balancing completed at {completion_time.strftime('%Y-%m-%d %H:%M')}! "
                f"Battery held at ≥99% for {self._get_holding_time_hours()}h"
            )
            self._last_balancing_ts = completion_time
            self._active_plan = None  # Clear active plan
            await self._save_state()
            return None

        # 0.5 CRITICAL FIX: If we already have an ACTIVE plan, DO NOT create a new one!
        # This prevents deadline from shifting every 30 minutes
        # EXCEPTION: If deadline (holding_start) is in the past, we missed it -> create new plan
        # BUT: If we're DURING holding period, keep the plan active!
        if self._active_plan is not None:
            now = dt_util.now()

            # Ensure holding_start is datetime (might be string from old storage)
            holding_start = self._active_plan.holding_start
            if isinstance(holding_start, str):
                holding_start = datetime.fromisoformat(holding_start)

            # Ensure holding_end is datetime too
            holding_end = self._active_plan.holding_end
            if isinstance(holding_end, str):
                holding_end = datetime.fromisoformat(holding_end)

            # Ensure timezone aware for comparison
            if holding_start.tzinfo is None:
                holding_start = dt_util.as_local(holding_start)
            if holding_end.tzinfo is None:
                holding_end = dt_util.as_local(holding_end)

            # Check if we're DURING holding period
            if holding_start <= now <= holding_end:
                _LOGGER.info(
                    f"🔋 Currently IN holding period ({holding_start.strftime('%H:%M')}-"
                    f"{holding_end.strftime('%H:%M')}). Keeping active plan."
                )
                return self._active_plan

            # Check if holding period completely passed
            if holding_end < now:
                _LOGGER.warning(
                    f"⏰ Holding period ended at {holding_end.strftime('%H:%M')}. "
                    f"Clearing expired plan."
                )
                self._active_plan = None
                await self._save_state()
            else:
                # Deadline still in future - keep existing plan
                _LOGGER.debug(
                    f"🔒 Active plan already exists ({self._active_plan.mode.name}), "
                    f"deadline at {holding_start.strftime('%H:%M')}. "
                    "Skipping new plan creation."
                )
                return self._active_plan

        # FORCE MODE: Skip all checks and create forced plan immediately
        if force:
            _LOGGER.warning("🔴 FORCE MODE enabled - creating forced balancing plan!")
            forced_plan = await self._create_forced_plan()
            if forced_plan:
                _LOGGER.warning("🔴 FORCED balancing plan created (manual trigger)!")
                self._active_plan = forced_plan
                await self._save_state()
                return forced_plan
            else:
                _LOGGER.error("Failed to create forced balancing plan!")
                return None

        # Calculate days since last balancing
        days_since_last = self._get_days_since_last_balancing()
        cycle_days = self._get_cycle_days()
        cooldown_hours = self._get_cooldown_hours()

        _LOGGER.info(f"📊 Balancing check: {days_since_last:.1f} days since last")

        # Check in order: Natural → Opportunistic → Forced

        # 1. Natural: Check if HYBRID already reaches 100% naturally
        _LOGGER.debug("Checking Natural balancing...")
        natural_plan = await self._check_natural_balancing()
        if natural_plan:
            _LOGGER.info("✓ Natural balancing detected in HYBRID forecast")
            self._active_plan = natural_plan
            self._last_balancing_ts = datetime.fromisoformat(natural_plan.holding_end)
            await self._save_state()
            return natural_plan

        # 2. Forced: cycle_days passed, charge ASAP regardless of cost
        if days_since_last >= cycle_days:
            forced_plan = await self._create_forced_plan()
            if forced_plan:
                _LOGGER.warning(
                    f"🔴 FORCED balancing after {days_since_last:.1f} days! "
                    "Health priority over cost."
                )
                self._active_plan = forced_plan
                await self._save_state()
                return forced_plan

        # 3. Opportunistic: SoC ≥ threshold AND cooldown passed
        hours_since_last = self._get_hours_since_last_balancing()
        if hours_since_last >= cooldown_hours:
            _LOGGER.debug(
                f"Checking Opportunistic balancing (hours={hours_since_last:.1f})..."
            )
            opportunistic_plan = await self._create_opportunistic_plan()
            if opportunistic_plan:
                _LOGGER.info(
                    f"⚡ Opportunistic balancing planned after {hours_since_last:.1f} hours"
                )
                self._active_plan = opportunistic_plan
                await self._save_state()
                return opportunistic_plan

        _LOGGER.info(f"No balancing needed yet ({days_since_last:.1f} days)")
        return None

    def _get_days_since_last_balancing(self) -> int:
        """Calculate days since last balancing."""
        if self._last_balancing_ts is None:
            return 99  # Unknown

        delta = dt_util.now() - self._last_balancing_ts
        return delta.days

    def _get_hours_since_last_balancing(self) -> float:
        """Calculate hours since last successful balancing.

        Returns:
            Hours as float (e.g., 25.5 hours)
        """
        if not self._last_balancing_ts:
            # Never balanced - assume cooldown passed
            return float(self._get_cooldown_hours())

        delta = dt_util.now() - self._last_balancing_ts
        return delta.total_seconds() / 3600.0

    async def _check_if_balancing_occurred(self) -> Tuple[bool, Optional[datetime]]:
        """Check if battery balancing just completed.

        Scans battery SoC sensor history to detect continuous period at ≥99%
        lasting for holding_time hours.

        Returns:
            (balancing_occurred, completion_time)
            - balancing_occurred: True if balancing detected
            - completion_time: End of holding period (when to update last_balancing)
        """
        holding_time_hours = self._get_holding_time_hours()

        # Get battery SoC sensor
        battery_sensor_id = f"sensor.oig_{self.box_id}_batt_bat_c"

        # Determine how far back to scan
        from homeassistant.util import dt as dt_util

        end_time = dt_util.now()

        if self._last_balancing_ts is None:
            # No previous balancing recorded - scan last 30 days to find it
            history_hours = 30 * 24
            _LOGGER.info(
                "No last balancing timestamp - scanning last 30 days for completion"
            )
        else:
            # Have previous balancing - only check recent history for new completion
            history_hours = holding_time_hours + 1

        start_time = end_time - timedelta(hours=history_hours)

        # Query HA statistics (longer retention than state history)
        try:
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            # Use hourly statistics for battery SoC
            stats = await self.hass.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start_time,
                end_time,
                {battery_sensor_id},
                "hour",
                None,
                {"mean", "max"},
            )

            if not stats or battery_sensor_id not in stats:
                _LOGGER.debug(
                    "No battery SoC statistics available for balancing detection"
                )
                return (False, None)

            hourly_stats = stats[battery_sensor_id]

            # Scan for ALL continuous periods with SoC ≥99% and find the latest one
            holding_start = None
            latest_completion = None
            latest_completion_time = None

            for stat in hourly_stats:
                # Use 'max' if available, otherwise 'mean'
                soc = stat.get("max") or stat.get("mean")

                # stat["start"] can be datetime, float (timestamp), or string
                stat_start = stat.get("start")
                if stat_start is None:
                    continue

                if isinstance(stat_start, datetime):
                    stat_time = stat_start
                elif isinstance(stat_start, (int, float)):
                    stat_time = datetime.fromtimestamp(stat_start, tz=dt_util.UTC)
                elif isinstance(stat_start, str):
                    stat_time = dt_util.parse_datetime(stat_start)
                    if stat_time is None:
                        continue
                else:
                    continue

                if soc and soc >= 99.0:
                    # Battery at high SoC during this hour
                    if holding_start is None:
                        holding_start = stat_time
                else:
                    # Battery dropped below threshold
                    if holding_start is not None:
                        # Check if previous high-SoC period was long enough
                        holding_duration = stat_time - holding_start
                        if holding_duration >= timedelta(hours=holding_time_hours):
                            # Found a balancing completion - keep track of latest
                            if (
                                latest_completion_time is None
                                or stat_time > latest_completion_time
                            ):
                                latest_completion = (
                                    holding_start,
                                    stat_time,
                                    holding_duration,
                                )
                                latest_completion_time = stat_time
                    holding_start = None

            # Check if still holding (last stat was ≥99%)
            if holding_start is not None and hourly_stats:
                now = dt_util.now()
                holding_duration = now - holding_start
                if holding_duration >= timedelta(hours=holding_time_hours):
                    # Balancing completed and still holding!
                    # This is the most recent, use it
                    _LOGGER.info(
                        f"Detected ongoing balancing completion: "
                        f"SoC ≥99% since {holding_start.strftime('%Y-%m-%d %H:%M')} "
                        f"({holding_duration.total_seconds() / 3600:.1f}h)"
                    )
                    return (True, now)

            # Return the latest completed balancing found
            if latest_completion is not None:
                holding_start, completion_time, holding_duration = latest_completion
                _LOGGER.info(
                    f"Detected last balancing completion: "
                    f"SoC ≥99% from {holding_start.strftime('%Y-%m-%d %H:%M')} "
                    f"to {completion_time.strftime('%Y-%m-%d %H:%M')} "
                    f"({holding_duration.total_seconds() / 3600:.1f}h)"
                )
                return (True, completion_time)

        except RuntimeError as e:
            # Recorder DB nemusí být hned po startu připravená
            if "database connection has not been established" in str(e).lower():
                _LOGGER.warning(
                    "Error checking balancing completion: Recorder not ready yet; skipping"
                )
                return (False, None)
            _LOGGER.error(f"Error checking balancing completion: {e}", exc_info=True)
        except Exception as e:
            _LOGGER.error(f"Error checking balancing completion: {e}", exc_info=True)

        return (False, None)

    async def _check_natural_balancing(self) -> Optional[BalancingPlan]:
        """Check if HYBRID forecast naturally reaches 100% for 3h.

        TODO 5.1: Natural balancing detection.

        Scans HYBRID timeline to find 3-hour window at 100% SoC.
        If found, creates natural plan (no mode overrides needed).

        Returns:
            Natural BalancingPlan if 100% window found, None otherwise
        """
        _LOGGER.debug("_check_natural_balancing: Getting HYBRID timeline...")
        timeline = self._get_hybrid_timeline()
        if not timeline:
            _LOGGER.warning("No HYBRID timeline available for natural balancing check")
            return None

        _LOGGER.debug(f"Timeline has {len(timeline)} intervals")

        # Look for 12 consecutive intervals (3 hours) at >= 99% SoC
        battery_capacity_kwh = self._get_battery_capacity_kwh()
        if not battery_capacity_kwh:
            return None

        threshold_kwh = battery_capacity_kwh * 0.99  # 99% = close enough to 100%

        window_start = None
        window_count = 0

        for interval in timeline:
            soc_kwh = interval.get("battery_soc_kwh", 0)

            if soc_kwh >= threshold_kwh:
                if window_start is None:
                    window_start = interval.get("timestamp")
                window_count += 1

                # Found 3-hour window?
                if window_count >= 12:  # 12 intervals = 3 hours
                    window_end_ts = interval.get("timestamp")
                    window_end = datetime.fromisoformat(window_end_ts)

                    return create_natural_plan(
                        holding_start=datetime.fromisoformat(window_start),
                        holding_end=window_end,
                        last_balancing_ts=window_end,
                    )
            else:
                # Reset window
                window_start = None
                window_count = 0

        return None

    async def _create_opportunistic_plan(self) -> Optional[BalancingPlan]:
        """Create opportunistic balancing plan.

        TODO 5.2: Opportunistic balancing.

        Checks if current SoC ≥ threshold, then calculates total cost for:
        1. Immediate balancing (charge NOW to 100%)
        2. Delayed balancing (wait for cheap window + charge then)

        Selects option with minimum total cost.

        Returns:
            Opportunistic BalancingPlan or None if SoC below threshold
        """
        # Check if SoC meets threshold
        current_soc_percent = await self._get_current_soc_percent()
        if current_soc_percent is None:
            _LOGGER.warning("Cannot get current SoC for opportunistic balancing")
            return None

        soc_threshold = self._get_soc_threshold()
        if current_soc_percent < soc_threshold:
            _LOGGER.debug(
                f"SoC {current_soc_percent:.1f}% below threshold {soc_threshold}%, "
                "no opportunistic balancing"
            )
            return None

        # Cost optimization: evaluate immediate vs. all delayed windows
        _LOGGER.info(
            f"Evaluating balancing costs (SoC={current_soc_percent:.1f}%, "
            f"threshold={soc_threshold}%)"
        )

        # 1. Calculate immediate balancing cost
        immediate_cost = await self._calculate_immediate_balancing_cost(
            current_soc_percent
        )
        _LOGGER.info(f"Immediate balancing cost: {immediate_cost:.2f} CZK")

        # 2. Find all possible holding windows in next 48h
        prices = await self._get_spot_prices_48h()
        if not prices:
            _LOGGER.warning("No spot prices available for cost optimization")
            # Fall back to immediate
            holding_start = datetime.now() + timedelta(hours=1)
            holding_end = holding_start + timedelta(
                hours=self._get_holding_time_hours()
            )
        else:
            # Evaluate each possible window
            timestamps = sorted(prices.keys())
            holding_time_hours = self._get_holding_time_hours()
            intervals_needed = holding_time_hours * 4  # 15min intervals

            # Restrict balancing to "cheap" windows. This prevents opportunistic balancing
            # from selecting expensive evening windows just because waiting has a modeled cost.
            # Users expect balancing to happen primarily in the cheapest part of the day (night).
            all_price_values = [float(p) for p in prices.values()]
            all_price_values.sort()
            cheap_pct = self._get_cheap_window_percentile()
            cheap_idx = int(len(all_price_values) * cheap_pct / 100)
            cheap_price_threshold = (
                all_price_values[cheap_idx] if all_price_values else float("inf")
            )

            min_cost = immediate_cost
            best_window_start = None  # None means immediate is best

            for i in range(len(timestamps) - intervals_needed + 1):
                window_start = timestamps[i]

                # Skip if window starts in past
                if window_start <= datetime.now():
                    continue

                # Skip windows that are not in the cheap price band.
                window_prices = [
                    float(prices[timestamps[j]]) for j in range(i, i + intervals_needed)
                ]
                window_avg_price = sum(window_prices) / len(window_prices)
                if window_avg_price > cheap_price_threshold:
                    continue

                # Calculate total cost for this window
                delayed_cost = await self._calculate_total_balancing_cost(
                    window_start, current_soc_percent
                )

                if delayed_cost < min_cost:
                    min_cost = delayed_cost
                    best_window_start = window_start

            # Log decision
            if best_window_start is None:
                # Immediate is cheapest
                _LOGGER.info(
                    f"✅ Immediate balancing selected: {immediate_cost:.2f} CZK "
                    f"(cheapest option)"
                )
                holding_start = datetime.now() + timedelta(hours=1)
                holding_end = holding_start + timedelta(hours=holding_time_hours)

                # Store costs for sensor
                self._last_immediate_cost = immediate_cost
                self._last_selected_cost = immediate_cost
                self._last_cost_savings = 0.0
            else:
                # Delayed window is cheaper
                holding_start = best_window_start
                holding_end = holding_start + timedelta(hours=holding_time_hours)
                savings = immediate_cost - min_cost
                _LOGGER.info(
                    f"⏰ Delayed balancing selected: {min_cost:.2f} CZK at "
                    f"{holding_start.strftime('%H:%M')} "
                    f"(vs immediate {immediate_cost:.2f} CZK, saving {savings:.2f} CZK)"
                )

                # Store costs for sensor
                self._last_immediate_cost = immediate_cost
                self._last_selected_cost = min_cost
                self._last_cost_savings = savings

        # Plan UPS intervals before holding window
        charging_intervals = self._plan_ups_charging(
            target_time=holding_start,
            current_soc_percent=current_soc_percent,
            target_soc_percent=100.0,
        )

        # Add holding intervals (HOME_UPS during holding window to maintain 100%)
        holding_intervals = self._create_holding_intervals(
            holding_start, holding_end, mode=HOME_UPS
        )

        all_intervals = charging_intervals + holding_intervals

        return create_opportunistic_plan(
            holding_start=holding_start,
            holding_end=holding_end,
            charging_intervals=all_intervals,
            days_since_last=int(self._get_days_since_last_balancing()),
        )

    async def _create_forced_plan(self) -> Optional[BalancingPlan]:
        """Create forced balancing plan.

        TODO 5.3: Forced balancing.

        Emergency balancing after cycle_days. Charges ASAP regardless of cost.
        Still calculates and logs costs for monitoring purposes.

        Returns:
            Forced BalancingPlan (locked, critical priority)
        """
        # Get current SoC
        current_soc_percent = await self._get_current_soc_percent()
        if current_soc_percent is None:
            current_soc_percent = 50.0  # Assume worst case

        # Calculate costs for monitoring (even though we ignore them)
        immediate_cost = await self._calculate_immediate_balancing_cost(
            current_soc_percent
        )

        _LOGGER.warning(
            f"🔴 FORCED balancing: Health priority! "
            f"Cost={immediate_cost:.2f} CZK (not optimized)"
        )

        # Store costs for sensor
        self._last_immediate_cost = immediate_cost
        self._last_selected_cost = immediate_cost
        self._last_cost_savings = 0.0  # No optimization in forced mode

        # Find next available holding window (ASAP)
        now = datetime.now()
        holding_time_hours = self._get_holding_time_hours()

        # Calculate required charging time based on current SoC
        # Conservative estimate: 5% per 15min interval, round up
        soc_needed = 100.0 - current_soc_percent
        intervals_needed = max(1, int(soc_needed / 5.0) + 1)  # +1 for safety margin
        charging_hours = intervals_needed * 0.25  # 15min = 0.25h

        # Start holding when charging completes
        # Round to next 15-min interval
        minutes_from_now = int(charging_hours * 60)
        minutes_rounded = (
            (minutes_from_now + 14) // 15
        ) * 15  # Round up to nearest 15min
        holding_start = now + timedelta(minutes=minutes_rounded)
        holding_end = holding_start + timedelta(hours=holding_time_hours)

        _LOGGER.info(
            f"⚡ Forced balancing schedule: SoC {current_soc_percent:.1f}% → 100%, "
            f"charging ~{charging_hours:.1f}h ({intervals_needed} intervals), "
            f"holding {holding_start.strftime('%H:%M')}-{holding_end.strftime('%H:%M')}"
        )

        # Plan aggressive UPS charging NOW
        charging_intervals = self._plan_ups_charging(
            target_time=holding_start,
            current_soc_percent=current_soc_percent,
            target_soc_percent=100.0,
        )

        # Add holding intervals
        holding_intervals = self._create_holding_intervals(
            holding_start, holding_end, mode=HOME_UPS
        )

        all_intervals = charging_intervals + holding_intervals

        return create_forced_plan(
            holding_start=holding_start,
            holding_end=holding_end,
            charging_intervals=all_intervals,
        )

    def _plan_ups_charging(
        self,
        target_time: datetime,
        current_soc_percent: float,
        target_soc_percent: float,
    ) -> List[BalancingInterval]:
        """Plan UPS charging intervals to reach target SoC.

        Simple heuristic: Assume ~3kW charging power (HOME_UPS limit).
        Battery capacity ~15 kWh, so 5% ≈ 0.75 kWh, takes 15 min.

        Args:
            target_time: When to reach target SoC
            current_soc_percent: Current battery SoC (%)
            target_soc_percent: Target SoC (typically 100%)

        Returns:
            List of BalancingInterval with HOME_UPS mode
        """
        soc_needed = target_soc_percent - current_soc_percent
        if soc_needed <= 0:
            return []  # Already at target

        # Conservative estimate: 5% per 15min interval
        intervals_needed = max(1, int(soc_needed / 5.0))

        # Respect MIN_MODE_DURATION
        intervals_needed = max(intervals_needed, MIN_MODE_DURATION)

        # Start charging before target time
        charging_start = target_time - timedelta(minutes=15 * intervals_needed)

        # Create UPS intervals
        intervals = []
        current_ts = charging_start
        for _ in range(intervals_needed):
            intervals.append(
                BalancingInterval(
                    ts=current_ts.isoformat(),
                    mode=HOME_UPS,
                )
            )
            current_ts += timedelta(minutes=15)

        _LOGGER.debug(
            f"Planned {intervals_needed} UPS intervals "
            f"from {charging_start.strftime('%H:%M')} to {target_time.strftime('%H:%M')}"
        )

        return intervals

    def _create_holding_intervals(
        self, start: datetime, end: datetime, mode: int = HOME_UPS
    ) -> List[BalancingInterval]:
        """Create intervals for holding window.

        Args:
            start: Window start
            end: Window end
            mode: CBB mode to use (default HOME_UPS)

        Returns:
            List of BalancingInterval
        """
        intervals = []
        current_ts = start

        while current_ts < end:
            intervals.append(
                BalancingInterval(
                    ts=current_ts.isoformat(),
                    mode=mode,
                )
            )
            current_ts += timedelta(minutes=15)

        return intervals

    async def _calculate_immediate_balancing_cost(
        self, current_soc_percent: float
    ) -> float:
        """Calculate cost to balance immediately.

        Args:
            current_soc_percent: Current battery SoC %

        Returns:
            Cost in CZK to charge from current SoC to 100%
        """
        # Get current spot price
        prices = await self._get_spot_prices_48h()
        if not prices:
            _LOGGER.warning("No spot prices available for immediate cost calculation")
            return 999.0  # High cost to prevent selection

        now = datetime.now()
        # Find closest timestamp
        current_price = None
        min_delta = timedelta(hours=1)
        for ts, price in prices.items():
            delta = abs(ts - now)
            if delta < min_delta:
                min_delta = delta
                current_price = price

        if current_price is None:
            _LOGGER.warning("Could not find current spot price")
            return 999.0

        # Calculate charge needed
        battery_capacity_kwh = self._get_battery_capacity_kwh()
        if not battery_capacity_kwh:
            return 999.0

        charge_needed_kwh = (100 - current_soc_percent) / 100 * battery_capacity_kwh

        # Price is already in CZK/kWh (includes all fees)
        immediate_cost = charge_needed_kwh * current_price

        _LOGGER.debug(
            f"Immediate cost: {charge_needed_kwh:.2f} kWh * {current_price:.4f} CZK/kWh "
            f"= {immediate_cost:.2f} CZK"
        )

        return immediate_cost

    async def _calculate_total_balancing_cost(
        self, window_start: datetime, current_soc_percent: float
    ) -> float:
        """Calculate total cost for delayed balancing.

        Total cost = waiting_cost + charging_cost

        Waiting cost includes:
        - Battery discharge during wait (self-discharge rate ~0.05 kWh/h)
        - Grid consumption during wait (from forecast timeline)

        Charging cost:
        - Energy needed to reach 100% at window start
        - Multiplied by average spot price during charging window

        Args:
            window_start: When to start holding window
            current_soc_percent: Current battery SoC %

        Returns:
            Total cost in CZK (waiting + charging)
        """
        now = datetime.now()
        wait_duration = (window_start - now).total_seconds() / 3600.0  # hours

        if wait_duration <= 0:
            # Window is now or in past, no waiting cost
            return await self._calculate_immediate_balancing_cost(current_soc_percent)

        battery_capacity_kwh = self._get_battery_capacity_kwh()
        if not battery_capacity_kwh:
            return 999.0

        # 1. Calculate battery discharge during wait
        # Self-discharge rate ~0.05 kWh/hour (from battery specs)
        DISCHARGE_RATE_KWH_PER_HOUR = 0.05
        battery_loss_kwh = wait_duration * DISCHARGE_RATE_KWH_PER_HOUR

        # 2. Get grid consumption during wait from forecast timeline
        grid_consumption_kwh = 0.0
        if self._forecast_sensor and hasattr(self._forecast_sensor, "_timeline_data"):
            timeline = self._forecast_sensor._timeline_data
            if timeline:
                for interval in timeline:
                    # OPRAVA: Timeline data jsou slovníky, ne objekty
                    ts_str = (
                        interval.get("timestamp")
                        if isinstance(interval, dict)
                        else getattr(interval, "ts", None)
                    )
                    if not ts_str:
                        continue
                    try:
                        interval_time = datetime.fromisoformat(ts_str)
                        if now <= interval_time < window_start:
                            # Grid consumption in this 15-min interval
                            if isinstance(interval, dict):
                                grid_kwh = float(
                                    interval.get(
                                        "grid_consumption_kwh",
                                        interval.get(
                                            "grid_import", interval.get("grid_net", 0.0)
                                        ),
                                    )
                                    or 0.0
                                )
                            else:
                                grid_kwh = float(
                                    getattr(
                                        interval,
                                        "grid_consumption_kwh",
                                        getattr(
                                            interval,
                                            "grid_import",
                                            getattr(interval, "grid_net", 0.0),
                                        ),
                                    )
                                    or 0.0
                                )
                            grid_consumption_kwh += grid_kwh
                    except (ValueError, TypeError):
                        continue

        # 3. Calculate average spot price during wait
        prices = await self._get_spot_prices_48h()
        wait_prices = [
            price for ts, price in prices.items() if now <= ts < window_start
        ]
        avg_wait_price = sum(wait_prices) / len(wait_prices) if wait_prices else 5.0

        # 4. Calculate waiting cost
        total_wait_energy = battery_loss_kwh + grid_consumption_kwh
        # Price is already in CZK/kWh (includes all fees)
        waiting_cost = total_wait_energy * avg_wait_price

        # 5. Calculate SoC at window start
        soc_loss_percent = (battery_loss_kwh / battery_capacity_kwh) * 100
        soc_at_window = max(0, current_soc_percent - soc_loss_percent)

        # 6. Calculate charging cost
        charge_needed_kwh = (100 - soc_at_window) / 100 * battery_capacity_kwh

        # Average spot price during charging/holding window
        holding_time_hours = self._get_holding_time_hours()
        window_end = window_start + timedelta(hours=holding_time_hours)
        charging_prices = [
            price for ts, price in prices.items() if window_start <= ts < window_end
        ]
        avg_charging_price = (
            sum(charging_prices) / len(charging_prices) if charging_prices else 5.0
        )

        # Price is already in CZK/kWh (includes all fees)
        charging_cost = charge_needed_kwh * avg_charging_price

        # 7. Total cost
        total_cost = waiting_cost + charging_cost

        _LOGGER.debug(
            f"Delayed cost for window {window_start.strftime('%H:%M')}: "
            f"waiting={waiting_cost:.2f} CZK ({battery_loss_kwh:.2f} + {grid_consumption_kwh:.2f} kWh @ {avg_wait_price:.4f}), "
            f"charging={charging_cost:.2f} CZK ({charge_needed_kwh:.2f} kWh @ {avg_charging_price:.4f}), "
            f"total={total_cost:.2f} CZK"
        )

        return total_cost

    async def _find_cheap_holding_window(
        self,
    ) -> Optional[Tuple[datetime, datetime]]:
        """Find cheapest 3-hour window in next 48 hours.

        Returns:
            (holding_start, holding_end) or None
        """
        # Get spot prices for next 48h
        prices = await self._get_spot_prices_48h()
        if not prices:
            return None

        # Find 3-hour window with lowest average price
        # Use 12 consecutive 15min intervals
        min_avg_price = float("inf")
        best_start = None

        timestamps = sorted(prices.keys())
        holding_time_hours = self._get_holding_time_hours()
        intervals_needed = holding_time_hours * 4  # 4 intervals per hour (15min each)

        for i in range(len(timestamps) - intervals_needed + 1):
            window_prices = [
                prices[timestamps[j]] for j in range(i, i + intervals_needed)
            ]
            avg_price = sum(window_prices) / len(window_prices)

            if avg_price < min_avg_price:
                min_avg_price = avg_price
                best_start = timestamps[i]

        if best_start:
            best_end = best_start + timedelta(hours=holding_time_hours)
            _LOGGER.debug(
                f"Found cheap window: {best_start.strftime('%H:%M')} - "
                f"{best_end.strftime('%H:%M')}, avg price {min_avg_price:.2f} CZK/kWh"
            )
            return best_start, best_end

        return None

    def _get_hybrid_timeline(self) -> Optional[List[Dict[str, Any]]]:
        """Get HYBRID timeline from forecast sensor.

        Returns:
            Timeline list or None
        """
        if not self._forecast_sensor:
            return None

        # Access forecast sensor's HYBRID timeline
        # This is the source of truth for what will actually happen
        timeline = getattr(self._forecast_sensor, "_hybrid_timeline", None)
        return timeline

    async def _get_current_soc_percent(self) -> Optional[float]:
        """Get current battery SoC percentage.

        Returns:
            SoC as percentage (0-100) or None
        """
        sensor_id = f"sensor.oig_{self.box_id}_batt_bat_c"
        state = self.hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_battery_capacity_kwh(self) -> Optional[float]:
        """Get battery capacity in kWh.

        Returns:
            Capacity in kWh or None
        """
        sensor_id = f"sensor.oig_{self.box_id}_installed_battery_capacity_kwh"
        state = self.hass.states.get(sensor_id)

        if not state or state.state in ["unknown", "unavailable"]:
            _LOGGER.warning(
                f"Battery capacity sensor {sensor_id} not available or unknown"
            )
            return None

        try:
            capacity_raw = float(state.state)
            unit = (state.attributes or {}).get("unit_of_measurement")
            capacity = capacity_raw

            # Some installations expose this sensor in Wh, not kWh.
            if unit and unit.lower() == "wh":
                capacity = capacity_raw / 1000.0
            elif capacity_raw > 1000:
                # Safety net: treat large values as Wh.
                capacity = capacity_raw / 1000.0

            _LOGGER.debug(
                f"Battery capacity: {capacity:.2f} kWh from {sensor_id} (raw={capacity_raw}, unit={unit})"
            )
            return capacity
        except (ValueError, TypeError):
            return None

    async def _get_spot_prices_48h(self) -> Dict[datetime, float]:
        """Get spot prices for next 48 hours from forecast sensor.

        Returns:
            Dict mapping datetime to price (CZK/kWh)
        """
        if not self._forecast_sensor:
            _LOGGER.warning("Forecast sensor not set, cannot get spot prices")
            return {}

        # Get active timeline from forecast sensor (_timeline_data attribute)
        timeline = getattr(self._forecast_sensor, "_timeline_data", None)
        if not timeline:
            _LOGGER.warning("No active timeline available for spot prices")
            return {}

        prices = {}
        for interval in timeline:
            timestamp_str = interval.get("timestamp") or interval.get("time")
            if not timestamp_str:
                continue

            try:
                ts = datetime.fromisoformat(timestamp_str)
                spot_price = interval.get("spot_price_czk") or interval.get(
                    "spot_price"
                )
                if spot_price is not None:
                    prices[ts] = float(spot_price)
            except (ValueError, TypeError) as e:
                _LOGGER.debug(f"Failed to parse interval timestamp/price: {e}")
                continue

        _LOGGER.debug(f"Loaded {len(prices)} spot price intervals from forecast")
        return prices

    def get_active_plan(self) -> Optional[BalancingPlan]:
        """Get currently active balancing plan.

        Returns:
            Active BalancingPlan or None
        """
        return self._active_plan

    def get_sensor_state(self) -> str:
        """Get sensor state string for HA balancing sensor.

        Returns:
            State: idle | natural | opportunistic | forced | overdue | error
        """
        if not self._active_plan:
            days_since = self._get_days_since_last_balancing()
            cycle_days = self._get_cycle_days()
            if days_since >= cycle_days:
                return "overdue"
            return "idle"

        return self._active_plan.mode.value

    def get_sensor_attributes(self) -> Dict[str, Any]:
        """Get sensor attributes for HA balancing sensor.

        Returns:
            Attributes dict
        """
        days_since = self._get_days_since_last_balancing()

        attrs = {
            "last_balancing_ts": (
                self._last_balancing_ts.isoformat() if self._last_balancing_ts else None
            ),
            "days_since_last": round(days_since, 1),
            "active_plan": None,
            "holding_start": None,
            "holding_end": None,
            "reason": None,
            "priority": None,
            "locked": False,
            # Cost information
            "immediate_cost_czk": self._last_immediate_cost,
            "selected_cost_czk": self._last_selected_cost,
            "cost_savings_czk": self._last_cost_savings,
        }

        if self._active_plan:
            attrs.update(
                {
                    "active_plan": self._active_plan.mode.value,
                    "holding_start": self._active_plan.holding_start,
                    "holding_end": self._active_plan.holding_end,
                    "reason": self._active_plan.reason,
                    "priority": self._active_plan.priority.value,
                    "locked": self._active_plan.locked,
                }
            )

        return attrs
