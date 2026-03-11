from __future__ import annotations

from types import SimpleNamespace
import sys
import types

import pytest

from custom_components.oig_cloud.api import planning_api
from homeassistant.helpers.http import KEY_HASS


class DummyPlan:
    def __init__(self, plan_id="plan-1"):
        self.plan_id = plan_id

    def to_dict(self):
        return {"id": self.plan_id}


class DummyPlanManager:
    def __init__(self):
        self._active_plan = None
        self._plans = {}

    def get_active_plan(self):
        return self._active_plan

    def list_plans(self, plan_type=None, status=None, limit=100):
        _ = plan_type
        _ = status
        return list(self._plans.values())[:limit]

    def get_plan(self, plan_id):
        return self._plans.get(plan_id)

    def create_manual_plan(self, **_kwargs):
        return DummyPlan(plan_id="manual")

    def activate_plan(self, plan_id):
        return DummyPlan(plan_id=plan_id)

    def deactivate_plan(self, plan_id):
        return DummyPlan(plan_id=plan_id)


class DummyPlanningSystem:
    def __init__(self):
        self.plan_manager = DummyPlanManager()


class DummyRequest:
    def __init__(self, hass, query=None, json_data=None):
        self.app = {KEY_HASS: hass}
        self.query = query or {}
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_active_plan_missing_system():
    view = planning_api.OIGCloudActivePlanView()
    request = DummyRequest(hass=SimpleNamespace(data={}))
    response = await view.get(request, "box")
    assert response.status == 503


@pytest.mark.asyncio
async def test_active_plan_none():
    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudActivePlanView().get(request, "box")
    assert response.body == b"null"


@pytest.mark.asyncio
async def test_active_plan_success():
    system = DummyPlanningSystem()
    system.plan_manager._active_plan = DummyPlan(plan_id="active")
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudActivePlanView().get(request, "box")
    assert response.status == 200
    assert b"active" in response.body


@pytest.mark.asyncio
async def test_active_plan_error():
    system = DummyPlanningSystem()

    def _boom():
        raise RuntimeError("fail")

    system.plan_manager.get_active_plan = _boom
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudActivePlanView().get(request, "box")
    assert response.status == 500


@pytest.mark.asyncio
async def test_plan_list_success():
    module = types.SimpleNamespace(
        PlanType=lambda value: value,
        PlanStatus=lambda value: value,
    )
    sys.modules["custom_components.oig_cloud.planning.plan_manager"] = module

    system = DummyPlanningSystem()
    system.plan_manager._plans = {
        "a": DummyPlan(plan_id="a"),
        "b": DummyPlan(plan_id="b"),
    }
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass, query={"limit": "1", "status": "active"})
    response = await planning_api.OIGCloudPlanListView().get(request, "box")
    assert response.status == 200
    assert b"plans" in response.body


@pytest.mark.asyncio
async def test_plan_list_invalid_filter():
    def _raise(_value):
        raise ValueError("bad")

    module = types.SimpleNamespace(PlanType=_raise, PlanStatus=_raise)
    sys.modules["custom_components.oig_cloud.planning.plan_manager"] = module

    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass, query={"type": "bad"})
    response = await planning_api.OIGCloudPlanListView().get(request, "box")
    assert response.status == 500


@pytest.mark.asyncio
async def test_plan_list_missing_system():
    request = DummyRequest(hass=SimpleNamespace(data={}))
    response = await planning_api.OIGCloudPlanListView().get(request, "box")
    assert response.status == 503


@pytest.mark.asyncio
async def test_plan_detail_not_found():
    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudPlanDetailView().get(request, "box", "x")
    assert response.status == 404


@pytest.mark.asyncio
async def test_plan_detail_missing_system():
    request = DummyRequest(hass=SimpleNamespace(data={}))
    response = await planning_api.OIGCloudPlanDetailView().get(request, "box", "x")
    assert response.status == 503


@pytest.mark.asyncio
async def test_plan_detail_error():
    system = DummyPlanningSystem()

    def _boom(_plan_id):
        raise RuntimeError("fail")

    system.plan_manager.get_plan = _boom
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudPlanDetailView().get(request, "box", "x")
    assert response.status == 500


@pytest.mark.asyncio
async def test_plan_detail_success():
    system = DummyPlanningSystem()
    system.plan_manager._plans["x"] = DummyPlan(plan_id="x")
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudPlanDetailView().get(request, "box", "x")
    assert response.status == 200


@pytest.mark.asyncio
async def test_create_manual_plan_missing_fields():
    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass, json_data={"target_soc_percent": 80})
    response = await planning_api.OIGCloudCreateManualPlanView().post(request, "box")
    assert response.status == 400


@pytest.mark.asyncio
async def test_create_manual_plan_missing_system():
    request = DummyRequest(
        hass=SimpleNamespace(data={}),
        json_data={"target_soc_percent": 80, "target_time": "2025-01-01T12:00:00"},
    )
    response = await planning_api.OIGCloudCreateManualPlanView().post(request, "box")
    assert response.status == 503


@pytest.mark.asyncio
async def test_create_manual_plan_success():
    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(
        hass=hass,
        json_data={
            "target_soc_percent": 80,
            "target_time": "2025-01-01T12:00:00",
            "holding_hours": 1,
            "holding_mode": 2,
        },
    )
    response = await planning_api.OIGCloudCreateManualPlanView().post(request, "box")
    assert response.status == 200
    assert b"manual" in response.body


@pytest.mark.asyncio
async def test_create_manual_plan_error():
    system = DummyPlanningSystem()

    def _boom(**_kwargs):
        raise RuntimeError("fail")

    system.plan_manager.create_manual_plan = _boom
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(
        hass=hass,
        json_data={"target_soc_percent": 80, "target_time": "2025-01-01T12:00:00"},
    )
    response = await planning_api.OIGCloudCreateManualPlanView().post(request, "box")
    assert response.status == 500


@pytest.mark.asyncio
async def test_activate_plan_missing_system():
    request = DummyRequest(hass=SimpleNamespace(data={}))
    response = await planning_api.OIGCloudActivatePlanView().post(request, "box", "p1")
    assert response.status == 503


@pytest.mark.asyncio
async def test_deactivate_plan_missing_system():
    request = DummyRequest(hass=SimpleNamespace(data={}))
    response = await planning_api.OIGCloudDeactivatePlanView().post(
        request, "box", "p1"
    )
    assert response.status == 503


@pytest.mark.asyncio
async def test_activate_deactivate_plan():
    system = DummyPlanningSystem()
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudActivatePlanView().post(request, "box", "p1")
    assert response.status == 200
    response = await planning_api.OIGCloudDeactivatePlanView().post(request, "box", "p1")
    assert response.status == 200


@pytest.mark.asyncio
async def test_activate_deactivate_plan_error():
    system = DummyPlanningSystem()

    def _boom(_plan_id):
        raise RuntimeError("fail")

    system.plan_manager.activate_plan = _boom
    system.plan_manager.deactivate_plan = _boom
    hass = SimpleNamespace(data={"oig_cloud": {"planning_system": system}})
    request = DummyRequest(hass=hass)
    response = await planning_api.OIGCloudActivatePlanView().post(request, "box", "p1")
    assert response.status == 500
    response = await planning_api.OIGCloudDeactivatePlanView().post(request, "box", "p1")
    assert response.status == 500


def test_setup_planning_api_views():
    class DummyHTTP:
        def __init__(self):
            self.views = []

        def register_view(self, view):
            self.views.append(view)

    hass = SimpleNamespace(http=DummyHTTP())
    planning_api.setup_planning_api_views(hass)
    assert len(hass.http.views) == 6
