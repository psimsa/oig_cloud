"""
OIG Cloud - Planning System REST API Endpoints.

Provides API endpoints for accessing battery planning system data.

Endpoints:
- /api/oig_cloud/plans/<box_id>/active - Get active plan
- /api/oig_cloud/plans/<box_id>/list - List all plans
- /api/oig_cloud/plans/<box_id>/<plan_id> - Get specific plan
- /api/oig_cloud/plans/<box_id>/create/manual - Create manual plan
- /api/oig_cloud/plans/<box_id>/<plan_id>/activate - Activate plan
- /api/oig_cloud/plans/<box_id>/<plan_id>/deactivate - Deactivate plan

Author: OIG Cloud Integration
Date: 2025-11-02
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

_LOGGER = logging.getLogger(__name__)

PLANNING_SYSTEM_NOT_INITIALIZED = "Planning system not initialized"

# API routes base
API_BASE = "/api/oig_cloud"


class OIGCloudActivePlanView(HomeAssistantView):
    """API endpoint for active plan data."""

    url = f"{API_BASE}/plans/{{box_id}}/active"
    name = "api:oig_cloud:active_plan"
    requires_auth = True

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        Get currently active plan.

        Returns:
            JSON with plan data or null if no active plan
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Get planning system from hass.data
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # Get active plan
            plan_manager = planning_system.plan_manager
            active_plan = plan_manager.get_active_plan()

            if not active_plan:
                return web.json_response(None)

            return web.json_response(active_plan.to_dict())

        except Exception as e:
            _LOGGER.error(f"Error getting active plan: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudPlanListView(HomeAssistantView):
    """API endpoint for listing plans."""

    url = f"{API_BASE}/plans/{{box_id}}/list"
    name = "api:oig_cloud:plan_list"
    requires_auth = True

    async def get(self, request: web.Request, box_id: str) -> web.Response:
        """
        List plans with optional filters.

        Query params:
            ?type=automatic|manual|balancing|weather - Filter by type
            ?status=simulated|active|deactivated - Filter by status
            ?limit=N - Limit number of results (default: 100)

        Returns:
            JSON array of plan objects
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Get query params
            plan_type = request.query.get("type")
            status = request.query.get("status")
            limit = int(request.query.get("limit", 100))

            # Get planning system
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # List plans
            from ..planning.plan_manager import PlanStatus, PlanType

            plan_type_enum = None
            if plan_type:
                plan_type_enum = PlanType(plan_type)

            status_enum = None
            if status:
                status_enum = PlanStatus(status)

            plans = planning_system.plan_manager.list_plans(
                plan_type=plan_type_enum,
                status=status_enum,
                limit=limit,
            )

            # Convert to dicts
            plans_data = [plan.to_dict() for plan in plans]

            return web.json_response(
                {
                    "plans": plans_data,
                    "count": len(plans_data),
                    "filters": {
                        "type": plan_type,
                        "status": status,
                        "limit": limit,
                    },
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error listing plans: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudPlanDetailView(HomeAssistantView):
    """API endpoint for specific plan details."""

    url = f"{API_BASE}/plans/{{box_id}}/{{plan_id}}"
    name = "api:oig_cloud:plan_detail"
    requires_auth = True

    async def get(
        self, request: web.Request, box_id: str, plan_id: str
    ) -> web.Response:
        """
        Get specific plan by ID.

        Returns:
            JSON with plan data or 404 if not found
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Get planning system
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # Get plan
            plan = planning_system.plan_manager.get_plan(plan_id)
            if not plan:
                return web.json_response(
                    {"error": f"Plan {plan_id} not found"}, status=404
                )

            return web.json_response(plan.to_dict())

        except Exception as e:
            _LOGGER.error(f"Error getting plan {plan_id}: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudCreateManualPlanView(HomeAssistantView):
    """API endpoint for creating manual plan."""

    url = f"{API_BASE}/plans/{{box_id}}/create/manual"
    name = "api:oig_cloud:create_manual_plan"
    requires_auth = True

    async def post(self, request: web.Request, box_id: str) -> web.Response:
        """
        Create manual plan.

        POST body:
        {
            "target_soc_percent": 100.0,
            "target_time": "2024-11-02T18:00:00",
            "holding_hours": 6,  // optional
            "holding_mode": 2     // optional (HOME_III)
        }

        Returns:
            JSON with created plan
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Parse request body
            data = await request.json()

            # Validate required fields
            if "target_soc_percent" not in data or "target_time" not in data:
                return web.json_response(
                    {"error": "target_soc_percent and target_time required"}, status=400
                )

            # Get planning system
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # Parse parameters
            target_soc = float(data["target_soc_percent"])
            target_time = datetime.fromisoformat(data["target_time"])
            holding_hours = data.get("holding_hours")
            holding_mode = data.get("holding_mode")

            # Create plan
            plan = planning_system.plan_manager.create_manual_plan(
                target_soc_percent=target_soc,
                target_time=target_time,
                holding_hours=holding_hours,
                holding_mode=holding_mode,
            )

            return web.json_response(
                {
                    "success": True,
                    "plan": plan.to_dict(),
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error creating manual plan: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudActivatePlanView(HomeAssistantView):
    """API endpoint for activating plan."""

    url = f"{API_BASE}/plans/{{box_id}}/{{plan_id}}/activate"
    name = "api:oig_cloud:activate_plan"
    requires_auth = True

    async def post(
        self, request: web.Request, box_id: str, plan_id: str
    ) -> web.Response:
        """
        Activate plan.

        Returns:
            JSON with activated plan
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Get planning system
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # Activate plan
            plan = planning_system.plan_manager.activate_plan(plan_id)

            return web.json_response(
                {
                    "success": True,
                    "plan": plan.to_dict(),
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error activating plan {plan_id}: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class OIGCloudDeactivatePlanView(HomeAssistantView):
    """API endpoint for deactivating plan."""

    url = f"{API_BASE}/plans/{{box_id}}/{{plan_id}}/deactivate"
    name = "api:oig_cloud:deactivate_plan"
    requires_auth = True

    async def post(
        self, request: web.Request, box_id: str, plan_id: str
    ) -> web.Response:
        """
        Deactivate plan.

        Returns:
            JSON with deactivated plan
        """
        hass: HomeAssistant = request.app[KEY_HASS]

        try:
            # Get planning system
            planning_system = hass.data.get("oig_cloud", {}).get("planning_system")
            if not planning_system:
                return web.json_response(
                    {"error": PLANNING_SYSTEM_NOT_INITIALIZED}, status=503
                )

            # Deactivate plan
            plan = planning_system.plan_manager.deactivate_plan(plan_id)

            return web.json_response(
                {
                    "success": True,
                    "plan": plan.to_dict(),
                }
            )

        except Exception as e:
            _LOGGER.error(f"Error deactivating plan {plan_id}: {e}", exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


def setup_planning_api_views(hass: HomeAssistant) -> None:
    """Register all planning API views.

    Call this from __init__.py during setup.
    """
    hass.http.register_view(OIGCloudActivePlanView())
    hass.http.register_view(OIGCloudPlanListView())
    hass.http.register_view(OIGCloudPlanDetailView())
    hass.http.register_view(OIGCloudCreateManualPlanView())
    hass.http.register_view(OIGCloudActivatePlanView())
    hass.http.register_view(OIGCloudDeactivatePlanView())

    _LOGGER.info("Planning API endpoints registered")
