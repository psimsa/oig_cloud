"""
OIG Cloud - Home Assistant REST API Endpoints.

This module provides REST API endpoints for accessing large sensor data
that would otherwise bloat sensor attributes and cause memory issues.

Architecture:
- Sensors store ONLY summary data in attributes (< 2 KB)
- Full data stored in internal variables or via event profiling
- API endpoints expose full data on-demand via HTTP GET
- Dashboard/frontend fetches via /api/oig_cloud/<endpoint>

Endpoints:
- /api/oig_cloud/battery_forecast/<box_id>/timeline - Full timeline data (280 KB)
- /api/oig_cloud/battery_forecast/<box_id>/baseline - Baseline timeline (280 KB)
- /api/oig_cloud/spot_prices/<box_id>/intervals - 15min price intervals (155 KB)
- /api/oig_cloud/analytics/<box_id>/hourly - Hourly analytics (6.5 KB)
- /api/oig_cloud/consumption_profiles/<box_id> - 72h consumption prediction (~2 KB)
- /api/oig_cloud/balancing_decisions/<box_id> - 7d balancing pattern prediction (~15 KB)

Total API payload: ~739 KB
Total sensor attributes: ~17 KB (97% reduction!)

Author: OIG Cloud Integration
Date: 2025-10-28
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from ..const import CONF_AUTO_MODE_SWITCH, DOMAIN

_LOGGER = logging.getLogger(__name__)

# API routes base
API_BASE = "/api/oig_cloud"
SENSOR_COMPONENT_NOT_FOUND = "Sensor component not found"


def _transform_timeline_for_api(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Transform timeline from internal format to API format.

    Internal format uses long descriptive keys:
    - solar_production_kwh → solar_kwh
    - consumption_kwh → load_kwh
    - grid_charge_kwh → stays same

    API format uses short keys expected by frontend.
    """
    transformed = []
    for point in timeline:
        new_point = point.copy()

        # Rename long keys to short keys
        if "solar_production_kwh" in new_point:
            new_point["solar_kwh"] = new_point.pop("solar_production_kwh")
        if "consumption_kwh" in new_point:
            new_point["load_kwh"] = new_point.pop("consumption_kwh")

        transformed.append(new_point)

    return transformed


def _find_entry_for_box(hass: HomeAssistant, box_id: str) -> Optional[ConfigEntry]:
    """Locate config entry that owns a given box_id."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None

    domain_data = hass.data.get(DOMAIN, {})
    for entry in entries:
        entry_data = domain_data.get(entry.entry_id, {})
        coordinator = entry_data.get("coordinator")
        if not coordinator or not hasattr(coordinator, "data"):
            continue
        box_map = getattr(coordinator, "data", {})
        if isinstance(box_map, dict) and box_id in box_map:
            return entry

    return None


class OIGCloudBatteryTimelineView(HomeAssistantView):
    """API endpoint for battery forecast timeline data."""

    url = f"{API_BASE}/battery_forecast/{{box_id}}/timeline"
    name = "api:oig_cloud:battery_timeline"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get full battery forecast timeline data.

        Args:
            box_id: OIG box ID (e.g., "2206237016")

        Query params:
            ?type=active - Active timeline (with applied charging plan)
            ?type=baseline - Baseline timeline (no charging plan)
            ?type=both - Both timelines (default)

        Returns:
            JSON with timeline data:
            {
                "active": [...],  # 192 timeline points
                "baseline": [...],  # 192 timeline points
                "metadata": {
                    "box_id": "2206237016",
                    "last_update": "2025-10-28T12:00:00+01:00",
                    "points_count": 192,
                    "size_kb": 280
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]
        request.query.get("mode", "hybrid").lower()
        timeline_type = request.query.get("type", "both")
        _ = request.query.get("plan", "hybrid").lower()  # legacy (single-planner)

        try:
            # STORAGE-FIRST: Serve from precomputed storage if available (fast path)
            from homeassistant.helpers.storage import Store

            store: Store = Store(hass, 1, f"oig_cloud.precomputed_data_{box_id}")
            precomputed_data: Optional[Dict[str, Any]] = None
            try:
                loaded: Optional[Dict[str, Any]] = await store.async_load()
                if isinstance(loaded, dict):
                    precomputed_data = loaded
            except Exception as storage_error:
                _LOGGER.warning(
                    f"Failed to read precomputed timeline data (fast path): {storage_error}"
                )

            if precomputed_data:
                last_update: Optional[str] = (precomputed_data or {}).get("last_update")

                stored_hybrid: Optional[list[Any]] = (precomputed_data or {}).get("timeline")  # type: ignore[assignment]
                if not stored_hybrid:
                    stored_hybrid = (precomputed_data or {}).get("timeline_hybrid")  # type: ignore[assignment]
                if stored_hybrid:
                    metadata = {
                        "box_id": box_id,
                        "last_update": last_update,
                        "points_count": len(stored_hybrid),
                        "size_kb": round(sys.getsizeof(str(stored_hybrid)) / 1024, 1),
                    }
                    # Return in the same shape as the live path so the dashboard
                    # can always consume `active` (and keep `timeline` for backward compatibility).
                    response_data = {
                        "plan": "hybrid",
                        "active": stored_hybrid,
                        "timeline": stored_hybrid,
                        "metadata": metadata,
                    }
                    if timeline_type in ("baseline", "both"):
                        response_data["baseline"] = []  # baseline removed
                    return web.json_response(response_data)

            # FALLBACK: Find sensor entity and attempt to serve from its data
            sensor_id = f"sensor.oig_{box_id}_battery_forecast"
            component: EntityComponent = hass.data.get("sensor")  # type: ignore

            if not component:
                return web.json_response(
                    {"error": "Sensor component not found and no precomputed data"},
                    status=503,
                )

            # Find entity by entity_id
            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Sensor {sensor_id} not found and no precomputed data"},
                    status=503,
                )

            # Attempt reading precomputed from entity (secondary path)
            precomputed_data = None
            if hasattr(entity_obj, "_precomputed_store") and getattr(
                entity_obj, "_precomputed_store"
            ):
                try:
                    precomputed_data = (
                        await entity_obj._precomputed_store.async_load() or {}
                    )
                except Exception as storage_error:
                    _LOGGER.warning(
                        f"Failed to read precomputed timeline data: {storage_error}"
                    )

            # Get timeline data from storage or sensor's internal variables
            stored_active = None
            if precomputed_data:
                stored_active = precomputed_data.get(
                    "timeline"
                ) or precomputed_data.get("timeline_hybrid")
                if stored_active:
                    _LOGGER.debug(
                        "API: Serving hybrid timeline from precomputed storage for %s",
                        box_id,
                    )

            active_timeline = stored_active or getattr(entity_obj, "_timeline_data", [])
            last_update = getattr(entity_obj, "_last_update", None)
            if stored_active and precomputed_data:
                last_update = precomputed_data.get("last_update", last_update)

            # Build response based on requested type
            response_data: Dict[str, Any] = {}

            if timeline_type in ("active", "both"):
                response_data["active"] = active_timeline

            if timeline_type in ("baseline", "both"):
                response_data["baseline"] = []  # baseline removed

            # Add metadata
            response_data["metadata"] = {
                "box_id": box_id,
                "last_update": str(last_update) if last_update else None,
                "points_count": len(active_timeline),
                "size_kb": round(sys.getsizeof(str(response_data)) / 1024, 1),
            }

            _LOGGER.debug(
                f"API: Serving battery timeline for {box_id}, "
                f"type={timeline_type}, points={len(active_timeline)}"
            )

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error(f"Error serving battery timeline API: {e}")
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudSpotPricesView(HomeAssistantView):
    """API endpoint for spot price intervals (Phase 1.5)."""

    url = f"{API_BASE}/spot_prices/{{box_id}}/intervals"
    name = "api:oig_cloud:spot_prices"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get 15-minute spot price intervals.

        Args:
            box_id: OIG box ID (e.g., "2206237016")

        Query params:
            ?type=export - Export prices (without VAT/distribution)
            ?type=spot - Spot prices (with VAT/distribution)
            ?currency=czk - CZK prices only (default)
            ?currency=eur - EUR prices only
            ?currency=both - Both currencies

        Returns:
            JSON with price intervals:
            {
                "intervals": [
                    {"time": "2025-10-28T00:00:00", "price": 1.234},
                    ...
                ],
                "metadata": {
                    "box_id": "2206237016",
                    "type": "export",
                    "intervals_count": 192,
                    "last_update": "2025-10-28T12:00:00+01:00",
                    "currency": "czk",
                    "size_kb": 12
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]
        price_type = request.query.get("type", "export")  # export or spot
        currency = request.query.get("currency", "czk")

        try:
            # Determine sensor ID based on type
            if price_type == "export":
                sensor_id = f"sensor.oig_{box_id}_export_price_current_15min"
            elif price_type == "spot":
                sensor_id = f"sensor.oig_{box_id}_spot_price_current_15min"
            else:
                return web.json_response(
                    {"error": f"Invalid type: {price_type}. Use 'export' or 'spot'."},
                    status=400,
                )

            component: EntityComponent = hass.data.get("sensor")  # type: ignore

            if not component:
                return web.json_response(
                    {"error": SENSOR_COMPONENT_NOT_FOUND}, status=500
                )

            # Find entity
            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Sensor {sensor_id} not found"}, status=404
                )

            # Get spot data from sensor's internal variables
            spot_data = getattr(entity_obj, "_spot_data_15min", {})
            last_update = getattr(entity_obj, "_last_update", None)

            # Extract intervals
            prices_15m = spot_data.get("prices15m_czk_kwh", {})
            intervals = [
                {"time": time_key, "price": price}
                for time_key, price in sorted(prices_15m.items())
            ]

            # Build response
            response_data = {
                "intervals": intervals,
                "metadata": {
                    "box_id": box_id,
                    "type": price_type,
                    "intervals_count": len(intervals),
                    "last_update": last_update.isoformat() if last_update else None,
                    "currency": currency,
                },
            }

            # Add size info
            import sys

            response_data["metadata"]["size_kb"] = round(
                sys.getsizeof(str(response_data)) / 1024, 1
            )

            _LOGGER.debug(
                f"API: Serving {price_type} prices for {box_id}, "
                f"currency={currency}, intervals={len(intervals)}"
            )

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error(f"Error serving spot prices API: {e}")
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudAnalyticsView(HomeAssistantView):
    """API endpoint for hourly analytics data."""

    url = f"{API_BASE}/analytics/{{box_id}}/hourly"
    name = "api:oig_cloud:analytics"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get hourly analytics data.

        Args:
            box_id: OIG box ID (e.g., "2206237016")

        Returns:
            JSON with hourly analytics:
            {
                "hourly_prices": [...],  # 48 hours of data
                "metadata": {
                    "box_id": "2206237016",
                    "hours_count": 48,
                    "last_update": "2025-10-28T12:00:00+01:00",
                    "size_kb": 6.5
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]

        try:
            # Find analytics sensor
            sensor_id = f"sensor.oig_{box_id}_hourly_analytics"
            component: EntityComponent = hass.data.get("sensor")  # type: ignore

            if not component:
                return web.json_response(
                    {"error": SENSOR_COMPONENT_NOT_FOUND}, status=500
                )

            # Find entity
            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Sensor {sensor_id} not found"}, status=404
                )

            # Get hourly data
            hourly_prices = getattr(entity_obj, "_hourly_prices", [])
            last_update = getattr(entity_obj, "_last_update", None)

            # Build response
            import sys

            response_data = {
                "hourly_prices": hourly_prices,
                "metadata": {
                    "box_id": box_id,
                    "hours_count": len(hourly_prices),
                    "last_update": str(last_update) if last_update else None,
                    "size_kb": round(sys.getsizeof(str(hourly_prices)) / 1024, 1),
                },
            }

            _LOGGER.debug(
                f"API: Serving analytics for {box_id}, " f"hours={len(hourly_prices)}"
            )

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error(f"Error serving analytics API: {e}")
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudConsumptionProfilesView(HomeAssistantView):
    """API endpoint for 72h consumption profiles data."""

    url = f"{API_BASE}/consumption_profiles/{{box_id}}"
    name = "api:oig_cloud:consumption_profiles"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get current 72h consumption profile and prediction.

        Args:
            box_id: OIG box ID (e.g., "2206237016")

        Returns:
            JSON with profile data:
            {
                "current_prediction": {
                    "matched_profile_created": "2025-10-20T00:30:00+01:00",
                    "similarity_score": 0.856,
                    "predicted_consumption_24h": [...],  # 24 hourly values
                    "predicted_total_kwh": 28.45,
                    "predicted_avg_kwh": 1.185
                },
                "metadata": {
                    "box_id": "2206237016",
                    "last_profile_created": "2025-10-28T00:30:00+01:00",
                    "profiling_status": "ok",
                    "data_hash": "a3f2b1c4"
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]

        try:
            # Find sensor entity
            sensor_id = f"sensor.oig_{box_id}_adaptive_load_profiles"
            component: EntityComponent = hass.data.get("sensor")  # type: ignore

            if not component:
                return web.json_response(
                    {"error": SENSOR_COMPONENT_NOT_FOUND}, status=500
                )

            # Find entity by entity_id
            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Sensor {sensor_id} not found"}, status=404
                )

            # Get prediction from sensor
            current_prediction = entity_obj.get_current_prediction()

            response_data = {
                "current_prediction": current_prediction,
                "metadata": {
                    "box_id": box_id,
                    "last_profile_created": getattr(
                        entity_obj, "_last_profile_created", None
                    ),
                    "profiling_status": getattr(
                        entity_obj, "_profiling_status", "unknown"
                    ),
                    "data_hash": getattr(entity_obj, "_data_hash", None),
                },
            }

            _LOGGER.debug(f"API: Serving consumption profiles for {box_id}")

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error(f"Error serving consumption profiles API: {e}")
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudBalancingDecisionsView(HomeAssistantView):
    """API endpoint for balancing decision pattern data."""

    url = f"{API_BASE}/balancing_decisions/{{box_id}}"
    name = "api:oig_cloud:balancing_decisions"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        GET /api/oig_cloud/balancing_decisions/{box_id}

        Returns balancing decision pattern prediction based on 7d profiling.

        Response structure:
        {
            "current_prediction": {
                "matched_profile_created": "2025-10-27T00:30:00",
                "similarity_score": 0.87,
                "predicted_120h_data": [...],  # 120 hours of predicted data
                "predicted_balancing_hours": 18,
                "predicted_balancing_percentage": 15.0,
                "predicted_avg_spot_price": 2.35,
                "matched_profile_balancing_hours": 22
            },
            "metadata": {
                "box_id": "CBB00000123",
                "last_profile_created": "2025-10-28T00:30:00",
                "profiling_status": "ok",
                "data_source": "7d_balancing_profiling"
            }
        }
        """
        try:
            # Find battery_balancing sensor entity
            entity_id = f"sensor.oig_{box_id}_battery_balancing"
            entity_component: EntityComponent = self.hass.data.get("entity_components", {}).get("sensor")  # type: ignore

            if not entity_component:
                return web.json_response(
                    {"error": SENSOR_COMPONENT_NOT_FOUND}, status=404
                )

            # Get entity object
            entity_obj = None
            for entity in entity_component.entities:
                if entity.entity_id == entity_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Battery balancing sensor {entity_id} not found"},
                    status=404,
                )

            # Get current prediction from sensor
            current_prediction = None
            if hasattr(entity_obj, "_find_best_matching_balancing_pattern"):
                try:
                    current_prediction = await entity_obj._find_best_matching_balancing_pattern()  # type: ignore
                except Exception as e:
                    _LOGGER.warning(f"Failed to get balancing pattern: {e}")

            # Prepare response
            metadata = {
                "box_id": box_id,
                "last_profile_created": (
                    entity_obj._last_balancing_profile_created.isoformat()  # type: ignore
                    if hasattr(entity_obj, "_last_balancing_profile_created")
                    and entity_obj._last_balancing_profile_created  # type: ignore
                    else None
                ),
                "profiling_status": (
                    entity_obj._balancing_profiling_status  # type: ignore
                    if hasattr(entity_obj, "_balancing_profiling_status")
                    else "unknown"
                ),
                "data_source": "7d_balancing_profiling",
            }

            response_data = {
                "current_prediction": current_prediction,
                "metadata": metadata,
            }

            _LOGGER.debug(f"API: Serving balancing decisions for {box_id}")

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error(f"Error serving balancing decisions API: {e}")
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudUnifiedCostTileView(HomeAssistantView):
    """
    API endpoint for Unified Cost Tile data.

    Phase V2: PLAN_VS_ACTUAL_UX_REDESIGN_V2.md - Fáze 1
    Consolidates 2 cost tiles into one with today/yesterday/tomorrow context.
    """

    url = f"{API_BASE}/battery_forecast/{{box_id}}/unified_cost_tile"
    name = "api:oig_cloud:unified_cost_tile"
    requires_auth = False

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get unified cost tile data.

        Returns:
            JSON with today/yesterday/tomorrow cost data:
            {
                "today": {
                    "plan_total_cost": 45.50,
                    "actual_total_cost": 42.30,
                    "delta": -3.20,
                    "performance": "better",
                    "completed_intervals": 32,
                    "total_intervals": 96,
                    "progress_pct": 33,
                    "eod_prediction": {
                        "predicted_total": 128.50,
                        "vs_plan": -4.50,
                        "confidence": "medium"
                    }
                },
                "yesterday": {
                    "plan_total_cost": 125.00,
                    "actual_total_cost": 118.50,
                    "delta": -6.50,
                    "performance": "better"
                },
                "tomorrow": {
                    "plan_total_cost": 135.00
                }
            }
        """
        hass: HomeAssistant = request.app["hass"]
        _ = request.query.get("plan") or request.query.get("mode") or "hybrid"  # legacy
        mode = "hybrid"

        try:
            # PERFORMANCE FIX: Try precomputed storage FIRST before looking for entity
            # This avoids entity lookup issues and is much faster
            from homeassistant.helpers.storage import Store

            store = Store(hass, 1, f"oig_cloud.precomputed_data_{box_id}")

            try:
                precomputed_data = await store.async_load()
            except Exception:
                precomputed_data = None

            # Single-planner: serve unified cost tile.
            tile_key = "unified_cost_tile"
            if precomputed_data and not precomputed_data.get(tile_key):
                tile_key = "unified_cost_tile_hybrid"  # legacy alias

            # If we have precomputed data, serve it directly (fastest path)
            if precomputed_data and precomputed_data.get(tile_key):
                response_payload = dict(precomputed_data.get(tile_key))
                comparison_summary = precomputed_data.get("cost_comparison")
                if comparison_summary and isinstance(response_payload, dict):
                    response_payload["comparison"] = comparison_summary
                _LOGGER.debug(
                    "API: Serving %s unified cost tile from precomputed storage",
                    mode,
                )
                return web.json_response(response_payload)

            # Fallback: If no precomputed data, try to build on-demand (slow)
            # Find sensor entity
            sensor_id = f"sensor.oig_{box_id}_battery_forecast"
            component: EntityComponent = hass.data.get("sensor")  # type: ignore

            if not component:
                return web.json_response(
                    {
                        "error": "Sensor component not found, and no precomputed data available"
                    },
                    status=503,
                )

            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {
                        "error": f"Sensor {sensor_id} not found, and no precomputed data available"
                    },
                    status=503,
                )

            # If we get here, entity exists but no precomputed data - build on demand
            # (This is the slow fallback path - should rarely happen in production)
            tile_data = None
            comparison_summary = (
                precomputed_data.get("cost_comparison") if precomputed_data else None
            )

            if hasattr(entity_obj, "build_unified_cost_tile"):
                try:
                    _LOGGER.info("API: Building unified cost tile for %s...", box_id)
                    tile_data = await entity_obj.build_unified_cost_tile()
                    _LOGGER.info(
                        "API: Unified cost tile built successfully: %s",
                        (
                            list(tile_data.keys())
                            if isinstance(tile_data, dict)
                            else type(tile_data)
                        ),
                    )
                except Exception as build_error:
                    _LOGGER.error(
                        "API: Error in build_unified_cost_tile() for %s: %s",
                        box_id,
                        build_error,
                        exc_info=True,
                    )
                    return web.json_response(
                        {"error": f"Failed to build tile: {str(build_error)}"},
                        status=500,
                    )
            else:
                return web.json_response(
                    {"error": "build_unified_cost_tile method not found"},
                    status=500,
                )

            if comparison_summary and isinstance(tile_data, dict):
                tile_data = dict(tile_data)
                tile_data["comparison"] = comparison_summary

            _LOGGER.debug(
                f"API: Serving unified cost tile for {box_id}, "
                f"today_delta={tile_data.get('today', {}).get('delta', 0):.2f} Kč"
            )

            return web.json_response(tile_data)

        except Exception as e:
            _LOGGER.error(f"Error serving unified cost tile API: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudDetailTabsView(HomeAssistantView):
    """
    API endpoint for Detail Tabs - mode-aggregated battery forecast data.

    Phase 3.0: Detail Tabs API
    Provides aggregated data by CBB modes instead of 15min intervals.
    """

    url = f"{API_BASE}/battery_forecast/{{box_id}}/detail_tabs"
    name = "api:oig_cloud:detail_tabs"
    requires_auth = False  # NOTE: Re-enable once auth method is implemented

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get Detail Tabs data - aggregated by CBB modes.

        Args:
            box_id: OIG box ID (e.g., "2206237016")

        Query params:
            ?tab=yesterday|today|tomorrow - Filter specific tab (optional)

        Returns:
            JSON with mode-aggregated data:
            {
                "yesterday": {
                    "date": "2025-11-05",
                    "mode_blocks": [
                        {
                            "mode_historical": "HOME I",
                            "mode_planned": "HOME I",
                            "mode_match": true,
                            "status": "completed",
                            "start_time": "00:00",
                            "end_time": "02:30",
                            "interval_count": 10,
                            "duration_hours": 2.5,
                            "cost_historical": 12.50,
                            "cost_planned": 12.00,
                            "cost_delta": 0.50,
                            "battery_soc_start": 50.0,
                            "battery_soc_end": 45.2,
                            "solar_total_kwh": 0.0,
                            "consumption_total_kwh": 1.8,
                            "grid_import_total_kwh": 1.8,
                            "grid_export_total_kwh": 0.0,
                            "adherence_pct": 100
                        }
                    ],
                    "summary": {
                        "total_cost": 28.50,
                        "overall_adherence": 65,
                        "mode_switches": 8
                    }
                },
                "today": {...},
                "tomorrow": {...}
            }
        """
        hass: HomeAssistant = request.app["hass"]
        tab = request.query.get("tab", None)
        # Always use hybrid plan (autonomy removed)
        plan_key = "hybrid"

        try:
            # STORAGE-FIRST: Serve from precomputed storage if available (fast path)
            from homeassistant.helpers.storage import Store

            store: Store = Store(hass, 1, f"oig_cloud.precomputed_data_{box_id}")
            precomputed_data: Optional[Dict[str, Any]] = None
            try:
                loaded: Optional[Dict[str, Any]] = await store.async_load()
                if isinstance(loaded, dict):
                    precomputed_data = loaded
            except Exception as storage_error:
                _LOGGER.warning(
                    "Failed to read precomputed detail tabs data (fast path): %s",
                    storage_error,
                )

            if precomputed_data:
                detail_tabs = precomputed_data.get(
                    "detail_tabs"
                ) or precomputed_data.get("detail_tabs_hybrid")
                if detail_tabs:
                    if tab and tab in ["yesterday", "today", "tomorrow"]:
                        return web.json_response({tab: detail_tabs.get(tab, {})})
                    return web.json_response(
                        {
                            "yesterday": detail_tabs.get("yesterday", {}),
                            "today": detail_tabs.get("today", {}),
                            "tomorrow": detail_tabs.get("tomorrow", {}),
                        }
                    )

            # FALLBACK: Find sensor entity
            sensor_id = f"sensor.oig_{box_id}_battery_forecast"
            component: Optional[EntityComponent] = (
                hass.data.get("entity_components", {}).get("sensor")  # type: ignore[assignment]
                if isinstance(hass.data.get("entity_components"), dict)
                else None
            )
            if component is None:
                component = hass.data.get("sensor")  # type: ignore[assignment]

            if not component:
                return web.json_response(
                    {"error": SENSOR_COMPONENT_NOT_FOUND}, status=503
                )

            # Find entity by entity_id
            entity_obj = None
            for entity in component.entities:
                if entity.entity_id == sensor_id:
                    entity_obj = entity
                    break

            if not entity_obj:
                return web.json_response(
                    {"error": f"Sensor {sensor_id} not found"}, status=404
                )

            # PHASE 3.5: Read from precomputed storage for instant response
            if (
                hasattr(entity_obj, "_precomputed_store")
                and entity_obj._precomputed_store
            ):
                try:
                    precomputed_data = await entity_obj._precomputed_store.async_load()
                    if precomputed_data:
                        detail_tabs = precomputed_data.get(
                            "detail_tabs"
                        ) or precomputed_data.get("detail_tabs_hybrid")
                        if not detail_tabs:
                            _LOGGER.debug(
                                "API: detail_tabs missing in precomputed store",
                            )
                            detail_tabs = None

                        if detail_tabs:
                            # Filter by tab if requested
                            if tab and tab in ["yesterday", "today", "tomorrow"]:
                                result = {tab: detail_tabs.get(tab, {})}
                            else:
                                # Return all tabs
                                result = {
                                    "yesterday": detail_tabs.get("yesterday", {}),
                                    "today": detail_tabs.get("today", {}),
                                    "tomorrow": detail_tabs.get("tomorrow", {}),
                                }

                            _LOGGER.debug(
                                f"API: Serving detail tabs ({plan_key}) from precomputed storage for {box_id}, "
                                f"tab_filter={tab}, "
                                f"age={(dt_util.now() - dt_util.parse_datetime(precomputed_data.get('last_update', ''))).total_seconds():.0f}s"
                                if precomputed_data.get("last_update")
                                else "unknown age"
                            )

                            return web.json_response(result)

                    _LOGGER.debug(
                        "No precomputed detail_tabs (%s) data found for %s, falling back to live build",
                        plan_key,
                        box_id,
                    )
                except Exception as storage_error:
                    _LOGGER.warning(
                        f"Failed to read precomputed data ({plan_key}): {storage_error}, falling back to live build"
                    )

            # Fallback: Build detail tabs on-demand (old behavior)
            if hasattr(entity_obj, "build_detail_tabs"):
                try:
                    detail_tabs = await entity_obj.build_detail_tabs(
                        tab=tab, plan=plan_key
                    )
                except Exception as build_error:
                    _LOGGER.error(
                        f"API: Error in build_detail_tabs() for {box_id}: {build_error}",
                        exc_info=True,
                    )
                    return web.json_response(
                        {"error": f"Failed to build detail tabs: {build_error}"},
                        status=500,
                    )
            else:
                return web.json_response(
                    {"error": "build_detail_tabs method not found"}, status=500
                )

            _LOGGER.debug(
                f"API: Serving detail tabs for {box_id}, "
                f"tab_filter={tab}, "
                f"tabs_count={len(detail_tabs)}"
            )

            return web.json_response(detail_tabs)

        except Exception as e:
            _LOGGER.error(f"Error serving detail tabs API: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudPlannerSettingsView(HomeAssistantView):
    """API endpoint to read/update planner settings."""

    url = f"{API_BASE}/battery_forecast/{{box_id}}/planner_settings"
    name = "api:oig_cloud:planner_settings"
    requires_auth = True

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = _find_entry_for_box(hass, box_id)
        if not entry:
            return web.json_response({"error": "Box not found"}, status=404)

        value = entry.options.get(CONF_AUTO_MODE_SWITCH, False)
        # Always use hybrid plan (autonomy removed)
        return web.json_response(
            {
                "auto_mode_switch_enabled": value,
                "planner_mode": "hybrid",
            }
        )

    async def post(self, request: web.Request, box_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = _find_entry_for_box(hass, box_id)
        if not entry:
            return web.json_response({"error": "Box not found"}, status=404)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON payload"}, status=400)

        if not isinstance(payload, dict):
            return web.json_response({"error": "Invalid payload"}, status=400)

        current_enabled = entry.options.get(CONF_AUTO_MODE_SWITCH, False)

        desired_enabled = current_enabled

        if "auto_mode_switch_enabled" in payload:
            desired_enabled = bool(payload.get("auto_mode_switch_enabled"))

        # Always use hybrid plan (autonomy removed)
        if desired_enabled == current_enabled:
            return web.json_response(
                {
                    "auto_mode_switch_enabled": current_enabled,
                    "planner_mode": "hybrid",
                    "updated": False,
                }
            )

        new_options = dict(entry.options)
        new_options[CONF_AUTO_MODE_SWITCH] = desired_enabled
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info(
            "Planner settings updated for %s: auto_mode_switch_enabled=%s",
            box_id,
            desired_enabled,
        )

        return web.json_response(
            {
                "auto_mode_switch_enabled": desired_enabled,
                "planner_mode": "hybrid",
                "updated": True,
            }
        )


class OIGCloudDashboardModulesView(HomeAssistantView):
    """API endpoint to read enabled dashboard modules for an entry."""

    url = f"{API_BASE}/{{entry_id}}/modules"
    name = "api:oig_cloud:dashboard_modules"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != DOMAIN:
            return web.json_response({"error": "Entry not found"}, status=404)

        opts = entry.options or {}
        return web.json_response(
            {
                "enable_boiler": bool(opts.get("enable_boiler", False)),
                "enable_auto": bool(opts.get("enable_auto", False)),
            }
        )


@callback
def setup_api_endpoints(hass: HomeAssistant) -> None:
    """
    Register all REST API endpoints for OIG Cloud integration.

    Args:
        hass: Home Assistant instance
    """
    _LOGGER.info("🚀 Registering OIG Cloud REST API endpoints")

    # Register views
    hass.http.register_view(OIGCloudBatteryTimelineView())
    hass.http.register_view(OIGCloudUnifiedCostTileView())
    hass.http.register_view(OIGCloudDetailTabsView())
    hass.http.register_view(OIGCloudPlannerSettingsView())
    hass.http.register_view(OIGCloudDashboardModulesView())
    hass.http.register_view(OIGCloudSpotPricesView())
    hass.http.register_view(OIGCloudAnalyticsView())
    hass.http.register_view(OIGCloudConsumptionProfilesView())
    hass.http.register_view(OIGCloudBalancingDecisionsView())

    _LOGGER.info(
        "✅ OIG Cloud REST API endpoints registered:\n"
        f"  - {API_BASE}/battery_forecast/<box_id>/timeline\n"
        f"  - {API_BASE}/battery_forecast/<box_id>/unified_cost_tile\n"
        f"  - {API_BASE}/battery_forecast/<box_id>/detail_tabs\n"
        f"  - {API_BASE}/battery_forecast/<box_id>/planner_settings\n"
        f"  - {API_BASE}/<entry_id>/modules\n"
        f"  - {API_BASE}/spot_prices/<box_id>/intervals\n"
        f"  - {API_BASE}/analytics/<box_id>/hourly\n"
        f"  - {API_BASE}/consumption_profiles/<box_id>\n"
        f"  - {API_BASE}/balancing_decisions/<box_id>"
    )
