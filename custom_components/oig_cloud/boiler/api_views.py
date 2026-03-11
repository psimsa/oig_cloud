"""API views pro bojlerový modul."""

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BoilerProfileView(HomeAssistantView):
    """API endpoint pro data profilu."""

    url = "/api/oig_cloud/{entry_id}/boiler_profile"
    name = "api:oig_cloud:boiler_profile"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Vrátí profilová data ve formátu pro heatmapu."""
        try:
            # Získat boiler coordinator
            entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if not entry_data:
                return web.json_response({"error": "Entry not found"}, status=404)

            boiler_coordinator = entry_data.get("boiler_coordinator")
            if not boiler_coordinator:
                return web.json_response(
                    {"error": "Boiler module not enabled"}, status=404
                )

            # Získat všechny profily
            profiles = boiler_coordinator.profiler.get_all_profiles()

            # Formátovat data pro frontend
            response_data = {
                "profiles": {},
                "current_category": None,
            }

            # Aktuální profil
            if boiler_coordinator._current_profile:
                response_data["current_category"] = (
                    boiler_coordinator._current_profile.category
                )

            # Všechny profily
            for category, profile in profiles.items():
                # Heatmap data: 7 dní × 24 hodin
                heatmap_data = []
                for day in range(7):
                    day_data = []
                    for hour in range(24):
                        consumption, confidence = profile.get_consumption(hour)
                        day_data.append(
                            {
                                "hour": hour,
                                "consumption": round(consumption, 3),
                                "confidence": round(confidence, 2),
                            }
                        )
                    heatmap_data.append(day_data)

                response_data["profiles"][category] = {
                    "category": category,
                    "heatmap": heatmap_data,
                    "hourly_avg": {
                        str(h): round(v, 3) for h, v in profile.hourly_avg.items()
                    },
                    "confidence": {
                        str(h): round(v, 2) for h, v in profile.confidence.items()
                    },
                    "sample_count": {
                        str(h): c for h, c in profile.sample_count.items()
                    },
                    "last_updated": (
                        profile.last_updated.isoformat()
                        if profile.last_updated
                        else None
                    ),
                }

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error("Error in boiler profile API: %s", e, exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


class BoilerPlanView(HomeAssistantView):
    """API endpoint pro plán ohřevu."""

    url = "/api/oig_cloud/{entry_id}/boiler_plan"
    name = "api:oig_cloud:boiler_plan"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Vrátí plán ohřevu."""
        try:
            # Získat boiler coordinator
            entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if not entry_data:
                return web.json_response({"error": "Entry not found"}, status=404)

            boiler_coordinator = entry_data.get("boiler_coordinator")
            if not boiler_coordinator:
                return web.json_response(
                    {"error": "Boiler module not enabled"}, status=404
                )

            # Získat plán
            plan = boiler_coordinator._current_plan
            if not plan:
                return web.json_response({"error": "No plan available yet"}, status=404)

            # Formátovat sloty
            slots_data = []
            for slot in plan.slots:
                slots_data.append(
                    {
                        "start": slot.start.isoformat(),
                        "end": slot.end.isoformat(),
                        "consumption_kwh": round(slot.avg_consumption_kwh, 3),
                        "confidence": round(slot.confidence, 2),
                        "recommended_source": slot.recommended_source.value,
                        "spot_price": slot.spot_price_kwh,
                        "alt_price": slot.alt_price_kwh,
                        "overflow_available": slot.overflow_available,
                    }
                )

            response_data = {
                "created_at": plan.created_at.isoformat(),
                "valid_until": plan.valid_until.isoformat(),
                "total_consumption_kwh": round(plan.total_consumption_kwh, 2),
                "estimated_cost_czk": round(plan.estimated_cost_czk, 2),
                "fve_kwh": round(plan.fve_kwh, 2),
                "grid_kwh": round(plan.grid_kwh, 2),
                "alt_kwh": round(plan.alt_kwh, 2),
                "slots": slots_data,
            }

            return web.json_response(response_data)

        except Exception as e:
            _LOGGER.error("Error in boiler plan API: %s", e, exc_info=True)
            return web.json_response({"error": str(e)}, status=500)


def register_boiler_api_views(hass: HomeAssistant) -> None:
    """Registruje API views pro bojlerový modul."""
    hass.http.register_view(BoilerProfileView(hass))
    hass.http.register_view(BoilerPlanView(hass))
    _LOGGER.info("Boiler API views registered")
