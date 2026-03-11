from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.oig_cloud import services as services_module
from custom_components.oig_cloud.const import DOMAIN


class DummyServices:
    def __init__(self) -> None:
        self.registered = {}
        self.removed = []
        self.fail_on = set()

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler, schema=None, supports_response=False):
        if service in self.fail_on:
            raise RuntimeError("register failed")
        self.registered[(domain, service)] = handler

    def async_remove(self, domain, service):
        self.removed.append((domain, service))


class DummyConfigEntries:
    def __init__(self, entry=None):
        self._entry = entry

    def async_get_entry(self, _eid):
        return self._entry


class DummyHass:
    def __init__(self, entry=None) -> None:
        self.services = DummyServices()
        self.data = {}
        self.config_entries = DummyConfigEntries(entry)


class DummyDeviceRegistry:
    def __init__(self, device=None):
        self._device = device

    def async_get(self, _device_id):
        return self._device


class DummyApi:
    def __init__(self):
        self.calls = []
        self.limit_ok = True

    async def set_box_mode(self, mode):
        self.calls.append(("set_box_mode", mode))

    async def set_grid_delivery(self, mode):
        self.calls.append(("set_grid_delivery", mode))

    async def set_grid_delivery_limit(self, limit):
        self.calls.append(("set_grid_delivery_limit", limit))
        return self.limit_ok

    async def set_boiler_mode(self, mode):
        self.calls.append(("set_boiler_mode", mode))

    async def set_formating_mode(self, mode):
        self.calls.append(("set_formating_mode", mode))


class DummyServiceCall:
    def __init__(self, data=None, context=None):
        self.data = data or {}
        self.context = context


def test_get_box_id_from_device_entry_and_coordinator(monkeypatch):
    entry = SimpleNamespace(options={"box_id": "123"}, data={})
    coordinator = SimpleNamespace(config_entry=entry, data={"999": {}})
    hass = DummyHass(entry)
    hass.data[DOMAIN] = {"entry": {"coordinator": coordinator}}

    assert services_module.get_box_id_from_device(hass, None, "entry") == "123"

    entry.options = {}
    assert services_module.get_box_id_from_device(hass, None, "entry") == "999"


def test_get_box_id_from_device_exceptions(monkeypatch):
    class _BadCoordinator:
        def __getattr__(self, name):
            if name == "config_entry":
                raise RuntimeError("boom")
            raise AttributeError

        @property
        def data(self):
            raise RuntimeError("boom")

    coordinator = _BadCoordinator()
    hass = DummyHass()
    hass.data[DOMAIN] = {"entry": {"coordinator": coordinator}}

    assert services_module.get_box_id_from_device(hass, None, "entry") is None


def test_get_box_id_from_device_registry(monkeypatch):
    entry = SimpleNamespace(options={}, data={"box_id": "456"})
    coordinator = SimpleNamespace(config_entry=entry, data={})
    hass = DummyHass(entry)
    hass.data[DOMAIN] = {"entry": {"coordinator": coordinator}}

    device = SimpleNamespace(identifiers={(DOMAIN, "789_shield")})
    device_registry = DummyDeviceRegistry(device)

    monkeypatch.setattr(services_module.dr, "async_get", lambda _hass: device_registry)
    assert services_module.get_box_id_from_device(hass, "dev1", "entry") == "789"

    device_registry = DummyDeviceRegistry(None)
    monkeypatch.setattr(services_module.dr, "async_get", lambda _hass: device_registry)
    assert services_module.get_box_id_from_device(hass, "dev1", "entry") == "456"

    device = SimpleNamespace(identifiers={("other", "nope")})
    device_registry = DummyDeviceRegistry(device)
    monkeypatch.setattr(services_module.dr, "async_get", lambda _hass: device_registry)
    assert services_module.get_box_id_from_device(hass, "dev1", "entry") == "456"


@pytest.mark.asyncio
async def test_async_setup_services_extra_paths(monkeypatch):
    class DummyStore:
        def __init__(self, _hass, _version, _key):
            pass

        async def async_save(self, _data):
            raise RuntimeError("boom")

        async def async_load(self):
            raise RuntimeError("boom")

    class DummyForecast:
        async def async_update(self):
            raise RuntimeError("boom")

    hass = DummyHass()
    hass.data[DOMAIN] = {
        "entry1": {"coordinator": SimpleNamespace(solar_forecast=DummyForecast())},
        "entry2": {"coordinator": SimpleNamespace()},
    }

    monkeypatch.setattr("homeassistant.helpers.storage.Store", DummyStore)

    await services_module.async_setup_services(hass)

    update_handler = hass.services.registered[(DOMAIN, "update_solar_forecast")]
    save_handler = hass.services.registered[(DOMAIN, "save_dashboard_tiles")]
    get_handler = hass.services.registered[(DOMAIN, "get_dashboard_tiles")]
    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]

    await update_handler(DummyServiceCall())
    await save_handler(DummyServiceCall({}))
    await save_handler(DummyServiceCall({"config": json.dumps([])}))
    await save_handler(DummyServiceCall({"config": json.dumps({"tiles_left": []})}))
    await save_handler(
        DummyServiceCall(
            {
                "config": json.dumps(
                    {"tiles_left": [], "tiles_right": [], "version": 1}
                )
            }
        )
    )
    await get_handler(DummyServiceCall())

    response = await check_handler(DummyServiceCall({"box_id": "999"}))
    assert response["processed_entries"] == 0


@pytest.mark.asyncio
async def test_check_balancing_paths():
    class DummyMode:
        value = "forced"

    class DummyPriority:
        value = "high"

    class DummyPlan:
        mode = DummyMode()
        reason = "test"
        holding_start = SimpleNamespace()
        holding_end = "end"
        priority = DummyPriority()

    class DummyPlanIso:
        mode = DummyMode()
        reason = "iso"
        holding_start = datetime.now(timezone.utc)
        holding_end = "end"
        priority = DummyPriority()

    async def _check(**_kwargs):
        return DummyPlan()

    async def _check_iso(**_kwargs):
        return DummyPlanIso()

    async def _none(**_kwargs):
        return None

    async def _boom(**_kwargs):
        raise RuntimeError("boom")

    hass = DummyHass()
    hass.data[DOMAIN] = {
        "shield": "ignore",
        "entry1": {"balancing_manager": SimpleNamespace(check_balancing=_check, box_id="1")},
        "entry2": {"balancing_manager": SimpleNamespace(check_balancing=_none, box_id="2")},
        "entry3": {"balancing_manager": SimpleNamespace(check_balancing=_boom, box_id="3")},
        "entry4": {"balancing_manager": SimpleNamespace(check_balancing=_check_iso, box_id="4")},
    }

    await services_module.async_setup_services(hass)
    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]

    response = await check_handler(DummyServiceCall())
    assert response["processed_entries"] == 4

    response = await check_handler(DummyServiceCall({"box_id": "999"}))
    assert response["processed_entries"] == 0


@pytest.mark.asyncio
async def test_check_balancing_requested_box_skip():
    async def _check(**_kwargs):
        return None

    hass = DummyHass()
    hass.data[DOMAIN] = {
        "entry1": {"balancing_manager": SimpleNamespace(check_balancing=_check, box_id="1")},
    }

    await services_module.async_setup_services(hass)
    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]
    response = await check_handler(DummyServiceCall({"box_id": "2"}))
    assert response["processed_entries"] == 0


@pytest.mark.asyncio
async def test_check_balancing_no_plan():
    async def _none(**_kwargs):
        return None

    hass = DummyHass()
    hass.data[DOMAIN] = {
        "entry1": {"balancing_manager": SimpleNamespace(check_balancing=_none, box_id="1")},
    }

    await services_module.async_setup_services(hass)
    check_handler = hass.services.registered[(DOMAIN, "check_balancing")]
    response = await check_handler(DummyServiceCall())
    assert response["results"][0]["reason"] == "no_plan_needed"


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry")
    api = DummyApi()
    coordinator = SimpleNamespace(api=api)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator, "boiler_coordinator": object()}}

    class DummyShield:
        def __init__(self):
            self.calls = []

        async def intercept_service_call(self, domain, service_name, data, original_call, blocking, context):
            self.calls.append((domain, service_name, data))
            await original_call(domain, service_name, data["params"], blocking, context)

    shield = DummyShield()

    def _box_id(_hass, _device_id, _entry_id):
        return "123"

    monkeypatch.setattr(services_module, "get_box_id_from_device", _box_id)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.oig_cloud.services.boiler",
        SimpleNamespace(setup_boiler_services=lambda *_a, **_k: None),
    )

    await services_module.async_setup_entry_services_with_shield(hass, entry, shield)
    await services_module.async_setup_entry_services_with_shield(hass, entry, shield)

    set_box = hass.services.registered[(DOMAIN, "set_box_mode")]
    await set_box(DummyServiceCall({"mode": "Home 1", "acknowledgement": True}))

    set_grid = hass.services.registered[(DOMAIN, "set_grid_delivery")]
    await set_grid(DummyServiceCall({"mode": "Zapnuto / On", "acknowledgement": True, "warning": True}))
    await set_grid(DummyServiceCall({"limit": 10, "acknowledgement": True, "warning": True}))

    set_boiler = hass.services.registered[(DOMAIN, "set_boiler_mode")]
    await set_boiler(DummyServiceCall({"mode": "Manual", "acknowledgement": True}))

    set_form = hass.services.registered[(DOMAIN, "set_formating_mode")]
    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": True}))
    await set_form(DummyServiceCall({"limit": 50, "acknowledgement": True}))


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_none(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry")
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": SimpleNamespace(api=DummyApi())}}

    called = {"fallback": False}

    async def _fallback(_hass, _entry):
        called["fallback"] = True

    monkeypatch.setattr(services_module, "async_setup_entry_services_fallback", _fallback)
    await services_module.async_setup_entry_services_with_shield(hass, entry, None)
    assert called["fallback"] is True


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_errors(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry")
    api = DummyApi()
    coordinator = SimpleNamespace(api=api)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    class DummyShield:
        async def intercept_service_call(self, domain, service_name, data, original_call, blocking, context):
            await original_call(domain, service_name, data["params"], blocking, context)

    shield = DummyShield()
    await services_module.async_setup_entry_services_with_shield(hass, entry, shield)

    def _no_box(_hass, _device_id, _entry_id):
        return None

    monkeypatch.setattr(services_module, "get_box_id_from_device", _no_box)

    set_box = hass.services.registered[(DOMAIN, "set_box_mode")]
    await set_box(DummyServiceCall({"mode": "Home 1", "acknowledgement": True}))

    set_grid = hass.services.registered[(DOMAIN, "set_grid_delivery")]
    await set_grid(DummyServiceCall({"mode": None, "limit": None, "acknowledgement": True, "warning": True}))

    set_boiler = hass.services.registered[(DOMAIN, "set_boiler_mode")]
    await set_boiler(DummyServiceCall({"mode": "Manual", "acknowledgement": True}))

    set_form = hass.services.registered[(DOMAIN, "set_formating_mode")]
    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": True}))

    def _box(_hass, _device_id, _entry_id):
        return "123"

    monkeypatch.setattr(services_module, "get_box_id_from_device", _box)
    api.limit_ok = False

    with pytest.raises(vol.Invalid):
        await set_grid(DummyServiceCall({"acknowledgement": True, "warning": True}))
    with pytest.raises(vol.Invalid):
        await set_grid(DummyServiceCall({"mode": "Zapnuto / On", "limit": 1, "acknowledgement": True, "warning": True}))
    with pytest.raises(vol.Invalid):
        await set_grid(DummyServiceCall({"limit": 10000, "acknowledgement": True, "warning": True}))
    with pytest.raises(vol.Invalid):
        await set_grid(DummyServiceCall({"limit": 10, "acknowledgement": True, "warning": True}))

    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": False}))
    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": False}))


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_boiler_error(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry")
    api = DummyApi()
    coordinator = SimpleNamespace(api=api)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator, "boiler_coordinator": object()}}

    monkeypatch.setitem(
        sys.modules,
        "custom_components.oig_cloud.services.boiler",
        SimpleNamespace(setup_boiler_services=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    await services_module.async_setup_entry_services_with_shield(hass, entry, SimpleNamespace(intercept_service_call=lambda *_a, **_k: None))


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback(monkeypatch):
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry", options={"box_id": "123"}, data={})
    api = DummyApi()
    coordinator = SimpleNamespace(api=api, data={"123": {}})
    hass = DummyHass(entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    await services_module.async_setup_entry_services_fallback(hass, entry)

    set_box = hass.services.registered[(DOMAIN, "set_box_mode")]
    await set_box(DummyServiceCall({"mode": "Home 1", "acknowledgement": True}))

    set_boiler = hass.services.registered[(DOMAIN, "set_boiler_mode")]
    await set_boiler(DummyServiceCall({"mode": "CBB", "acknowledgement": True}))

    set_grid = hass.services.registered[(DOMAIN, "set_grid_delivery")]
    await set_grid(DummyServiceCall({"mode": "Vypnuto / Off", "acknowledgement": True, "warning": True}))
    await set_grid(DummyServiceCall({"limit": 5, "acknowledgement": True, "warning": True}))

    set_form = hass.services.registered[(DOMAIN, "set_formating_mode")]
    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": True}))
    await set_form(DummyServiceCall({"limit": 10, "acknowledgement": True}))

    hass.services.registered[(DOMAIN, "set_box_mode")] = set_box
    await services_module.async_setup_entry_services_fallback(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback_registration_error():
    entry = SimpleNamespace(entry_id="entry", options={"box_id": "123"}, data={})
    api = DummyApi()
    coordinator = SimpleNamespace(api=api, data={"123": {}})
    hass = DummyHass(entry)
    hass.services.fail_on.add("set_box_mode")
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    await services_module.async_setup_entry_services_fallback(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback_missing_box_id():
    entry = SimpleNamespace(entry_id="entry", options={}, data={})
    api = DummyApi()
    coordinator = SimpleNamespace(api=api, data={})
    hass = DummyHass(entry)
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coordinator}}

    await services_module.async_setup_entry_services_fallback(hass, entry)

    set_box = hass.services.registered[(DOMAIN, "set_box_mode")]
    await set_box(DummyServiceCall({"mode": "Home 1", "acknowledgement": True}))

    set_boiler = hass.services.registered[(DOMAIN, "set_boiler_mode")]
    await set_boiler(DummyServiceCall({"mode": "Manual", "acknowledgement": True}))

    set_grid = hass.services.registered[(DOMAIN, "set_grid_delivery")]
    await set_grid(DummyServiceCall({"mode": "Zapnuto / On", "acknowledgement": True, "warning": True}))

    set_form = hass.services.registered[(DOMAIN, "set_formating_mode")]
    await set_form(DummyServiceCall({"mode": "Nabíjet", "acknowledgement": True}))


@pytest.mark.asyncio
async def test_async_setup_entry_services_switch_paths():
    hass = DummyHass()
    entry = SimpleNamespace(entry_id="entry")
    hass.data[DOMAIN] = {"shield": object()}
    await services_module.async_setup_entry_services(hass, entry)

    hass.data[DOMAIN] = {}
    await services_module.async_setup_entry_services(hass, entry)


@pytest.mark.asyncio
async def test_async_unload_services():
    hass = DummyHass()
    hass.services.registered[(DOMAIN, "update_solar_forecast")] = lambda *_a, **_k: None
    hass.services.registered[(DOMAIN, "save_dashboard_tiles")] = lambda *_a, **_k: None
    await services_module.async_unload_services(hass)
    assert (DOMAIN, "update_solar_forecast") in hass.services.removed
