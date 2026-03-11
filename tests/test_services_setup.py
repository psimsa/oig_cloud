from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest


class DummySpan:
    def __enter__(self):
        return self

    def __exit__(self, *_args, **_kwargs):
        return False


class DummyTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return DummySpan()


sys.modules.setdefault(
    "opentelemetry",
    SimpleNamespace(trace=SimpleNamespace(get_tracer=lambda *_a, **_k: DummyTracer())),
)

from custom_components.oig_cloud import services as services_module
from custom_components.oig_cloud.const import DOMAIN


class DummyStore:
    saved = None
    data = None

    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key

    async def async_save(self, data):
        DummyStore.saved = data

    async def async_load(self):
        return DummyStore.data


class DummyServices:
    def __init__(self):
        self.registered = {}

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler, schema=None, supports_response=False):
        self.registered[(domain, service)] = handler


class DummyHass:
    def __init__(self):
        self.services = DummyServices()
        self.data = {}
        self.config_entries = SimpleNamespace(async_get_entry=lambda _eid: None)


class DummyServiceCall:
    def __init__(self, data=None, context=None):
        self.data = data or {}
        self.context = context


class DummySolarForecast:
    def __init__(self):
        self.updated = False

    async def async_update(self):
        self.updated = True


class DummyApi:
    def __init__(self):
        self.calls = []

    async def set_box_mode(self, mode):
        self.calls.append(("set_box_mode", mode))

    async def set_grid_delivery(self, mode):
        self.calls.append(("set_grid_delivery", mode))

    async def set_grid_delivery_limit(self, limit):
        self.calls.append(("set_grid_delivery_limit", limit))
        return True

    async def set_boiler_mode(self, mode):
        self.calls.append(("set_boiler_mode", mode))

    async def set_formating_mode(self, mode):
        self.calls.append(("set_formating_mode", mode))


class DummyCoordinator:
    def __init__(self, api, entry=None):
        self.api = api
        self.config_entry = entry


class DummyEntry(SimpleNamespace):
    pass


class DummyShield:
    def __init__(self):
        self.calls = []

    async def intercept_service_call(
        self, domain, service_name, data, original_call, blocking, context
    ):
        self.calls.append((domain, service_name, data, blocking, context))
        await original_call(domain, service_name, data["params"], blocking, context)


@pytest.mark.asyncio
async def test_async_setup_services_dashboard_tiles(monkeypatch):
    hass = DummyHass()
    hass.data[DOMAIN] = {
        "entry1": {"coordinator": SimpleNamespace(solar_forecast=DummySolarForecast())}
    }

    monkeypatch.setattr(
        "homeassistant.helpers.storage.Store", DummyStore
    )

    await services_module.async_setup_services(hass)

    save_handler = hass.services.registered[(DOMAIN, "save_dashboard_tiles")]
    get_handler = hass.services.registered[(DOMAIN, "get_dashboard_tiles")]

    config = {"tiles_left": [], "tiles_right": [], "version": 1}
    await save_handler(DummyServiceCall({"config": json.dumps(config)}))

    DummyStore.data = DummyStore.saved
    response = await get_handler(DummyServiceCall())

    assert response["config"]["version"] == 1


@pytest.mark.asyncio
async def test_async_setup_services_update_solar(monkeypatch):
    hass = DummyHass()
    forecast = DummySolarForecast()
    hass.data[DOMAIN] = {"entry1": {"coordinator": SimpleNamespace(solar_forecast=forecast)}}

    await services_module.async_setup_services(hass)

    update_handler = hass.services.registered[(DOMAIN, "update_solar_forecast")]
    await update_handler(DummyServiceCall())

    assert forecast.updated is True


@pytest.mark.asyncio
async def test_async_setup_services_check_balancing_no_entries():
    hass = DummyHass()
    hass.data[DOMAIN] = {}

    await services_module.async_setup_services(hass)

    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]
    response = await check_handler(DummyServiceCall())

    assert response["processed_entries"] == 0
    assert response["results"] == []


@pytest.mark.asyncio
async def test_async_setup_services_save_tiles_invalid_json(monkeypatch):
    hass = DummyHass()
    hass.data[DOMAIN] = {}

    monkeypatch.setattr(
        "homeassistant.helpers.storage.Store", DummyStore
    )
    DummyStore.saved = None

    await services_module.async_setup_services(hass)

    save_handler = hass.services.registered[(DOMAIN, "save_dashboard_tiles")]
    await save_handler(DummyServiceCall({"config": "{invalid"}))

    assert DummyStore.saved is None


@pytest.mark.asyncio
async def test_async_setup_services_save_tiles_missing_keys(monkeypatch):
    hass = DummyHass()
    hass.data[DOMAIN] = {}

    monkeypatch.setattr("homeassistant.helpers.storage.Store", DummyStore)
    DummyStore.saved = None

    await services_module.async_setup_services(hass)

    save_handler = hass.services.registered[(DOMAIN, "save_dashboard_tiles")]
    await save_handler(DummyServiceCall({"config": json.dumps({"version": 1})}))

    assert DummyStore.saved is None


@pytest.mark.asyncio
async def test_async_setup_services_get_tiles_none(monkeypatch):
    hass = DummyHass()
    hass.data[DOMAIN] = {}

    monkeypatch.setattr("homeassistant.helpers.storage.Store", DummyStore)
    DummyStore.data = None

    await services_module.async_setup_services(hass)

    get_handler = hass.services.registered[(DOMAIN, "get_dashboard_tiles")]
    response = await get_handler(DummyServiceCall())

    assert response["config"] is None


@pytest.mark.asyncio
async def test_async_setup_services_check_balancing_success_and_error():
    hass = DummyHass()

    class DummyEnum:
        def __init__(self, value):
            self.value = value

    plan = SimpleNamespace(
        mode=DummyEnum("holding"),
        reason="forced",
        holding_start=None,
        holding_end=None,
        priority=DummyEnum("high"),
    )

    class DummyManager:
        def __init__(self, box_id, result):
            self.box_id = box_id
            self._result = result

        async def check_balancing(self, force=False):
            if isinstance(self._result, Exception):
                raise self._result
            return self._result

    hass.data[DOMAIN] = {
        "entry_ok": {"balancing_manager": DummyManager("123", plan)},
        "entry_err": {"balancing_manager": DummyManager("999", RuntimeError("fail"))},
    }

    await services_module.async_setup_services(hass)
    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]
    response = await check_handler(DummyServiceCall({"force": True}))

    assert response["processed_entries"] == 2
    assert response["results"][0]["plan_mode"] == "holding"
    assert response["results"][1]["error"] == "fail"


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback_calls_api():
    hass = DummyHass()
    api = DummyApi()
    entry = DummyEntry(
        entry_id="entry1",
        options={"box_id": "123"},
        data={},
        title="OIG 123",
    )
    coordinator = DummyCoordinator(api, entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    await services_module.async_setup_entry_services_fallback(hass, entry)

    set_grid = hass.services.registered[(DOMAIN, "set_grid_delivery")]
    await set_grid(DummyServiceCall({"limit": 2500, "acknowledgement": True, "warning": True}))

    set_format = hass.services.registered[(DOMAIN, "set_formating_mode")]
    await set_format(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": False}))

    assert ("set_grid_delivery_limit", 2500) in api.calls
    assert not any(call[0] == "set_formating_mode" for call in api.calls)


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_calls_intercept():
    hass = DummyHass()
    api = DummyApi()
    entry = DummyEntry(
        entry_id="entry1",
        options={"box_id": "123"},
        data={},
        title="OIG 123",
    )
    coordinator = DummyCoordinator(api, entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}
    shield = DummyShield()

    await services_module.async_setup_entry_services_with_shield(hass, entry, shield)

    set_box_mode = hass.services.registered[(DOMAIN, "set_box_mode")]
    await set_box_mode(
        DummyServiceCall({"mode": "Home 2", "acknowledgement": True})
    )

    assert shield.calls
    assert ("set_box_mode", "1") in api.calls
