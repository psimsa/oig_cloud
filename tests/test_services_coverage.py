"""Extended tests for services.py to reach >= 90% coverage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol

from custom_components.oig_cloud import services as module
from custom_components.oig_cloud.const import DOMAIN


class DummyServices:
    def __init__(self, existing: set[str] | None = None, fail: bool = False):
        self.existing = existing or set()
        self.fail = fail
        self.registered: dict[tuple[str, str], Any] = {}
        self.removed: list[tuple[str, str]] = []

    def has_service(self, _domain: str, name: str) -> bool:
        return name in self.existing

    def async_register(self, domain, name, handler, schema=None, supports_response=False):
        if self.fail:
            raise RuntimeError("register failed")
        self.registered[(domain, name)] = (handler, schema, supports_response)
        self.existing.add(name)

    def async_remove(self, domain, name):
        self.removed.append((domain, name))
        self.existing.discard(name)


class DummyApi:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []

    async def set_box_mode(self, value):
        self.calls.append(("set_box_mode", value))

    async def set_grid_delivery(self, value):
        self.calls.append(("set_grid_delivery", value))

    async def set_grid_delivery_limit(self, value):
        self.calls.append(("set_grid_delivery_limit", value))
        return True

    async def set_boiler_mode(self, value):
        self.calls.append(("set_boiler_mode", value))

    async def set_formating_mode(self, value):
        self.calls.append(("set_formating_mode", value))

    async def set_box_prm2_app(self, value):
        self.calls.append(("set_box_prm2_app", value))


def _make_hass(entry_id: str = "entry"):
    api = DummyApi()
    coordinator = SimpleNamespace(api=api, config_entry=None, data={"123": {}})
    hass = SimpleNamespace(
        data={DOMAIN: {entry_id: {"coordinator": coordinator}}},
        services=DummyServices(),
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None),
    )
    entry = SimpleNamespace(entry_id=entry_id)
    return hass, entry, api


def test_noop_setup_boiler_services():
    assert module._noop_setup_boiler_services("a", b=1) is None


def test_validate_box_mode_legacy_aliases():
    for alias in ("home_5", "home_6", "Home 5", "Home 6", "home5", "home6"):
        with pytest.raises(vol.Invalid, match="Home 5/6"):
            module._validate_box_mode(alias)


def test_validate_set_box_mode_schema_no_mode_no_toggles():
    with pytest.raises(vol.Invalid, match="At least one"):
        module._validate_set_box_mode_schema({"acknowledgement": True})


def test_box_id_from_entry_options():
    entry = SimpleNamespace(options={"box_id": "98765"}, data={})
    coordinator = SimpleNamespace(config_entry=entry)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None)
    )
    assert module._box_id_from_entry(hass, coordinator, "x") == "98765"


def test_box_id_from_entry_data_box_id():
    entry = SimpleNamespace(options={}, data={"box_id": "54321"})
    coordinator = SimpleNamespace(config_entry=entry)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None)
    )
    assert module._box_id_from_entry(hass, coordinator, "x") == "54321"


def test_box_id_from_entry_inverter_sn():
    entry = SimpleNamespace(options={}, data={"inverter_sn": "11111"})
    coordinator = SimpleNamespace(config_entry=entry)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None)
    )
    assert module._box_id_from_entry(hass, coordinator, "x") == "11111"


def test_box_id_from_entry_non_digit():
    entry = SimpleNamespace(options={}, data={"box_id": "abc"})
    coordinator = SimpleNamespace(config_entry=entry)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None)
    )
    assert module._box_id_from_entry(hass, coordinator, "x") is None


def test_box_id_from_entry_no_entry():
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None)
    )
    assert module._box_id_from_entry(hass, coordinator=None, entry_id="x") is None


def test_box_id_from_coordinator_exception():
    class BadCoord:
        @property
        def data(self):
            raise RuntimeError("boom")

    assert module._box_id_from_coordinator(BadCoord()) is None


def test_box_id_from_coordinator_empty_dict():
    coordinator = SimpleNamespace(data={})
    assert module._box_id_from_coordinator(coordinator) is None


def test_extract_box_id_from_device_found():
    device = SimpleNamespace(identifiers={(DOMAIN, "12345_shield")})
    assert module._extract_box_id_from_device(device, "dev") == "12345"


def test_extract_box_id_from_device_other_domain():
    device = SimpleNamespace(identifiers={("other", "12345")})
    assert module._extract_box_id_from_device(device, "dev") is None


def test_extract_box_id_from_device_non_digit():
    device = SimpleNamespace(identifiers={(DOMAIN, "abc")})
    assert module._extract_box_id_from_device(device, "dev") is None


def test_get_box_id_from_device_no_device_id_entry():
    entry = SimpleNamespace(options={"box_id": "999"}, data={})
    coordinator = SimpleNamespace(config_entry=entry, data={})
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry),
    )
    assert module.get_box_id_from_device(hass, None, "ent") == "999"


def test_get_box_id_from_device_no_device_id_coordinator():
    coordinator = SimpleNamespace(config_entry=None, data={"888": {}})
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None),
    )
    assert module.get_box_id_from_device(hass, None, "ent") == "888"


def test_get_box_id_from_device_no_device_id_none():
    coordinator = SimpleNamespace(config_entry=None, data={})
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None),
    )
    assert module.get_box_id_from_device(hass, None, "ent") is None


def test_get_box_id_from_device_not_found_fallback():
    entry = SimpleNamespace(options={}, data={"box_id": "777"})
    coordinator = SimpleNamespace(config_entry=entry, data={})
    registry = SimpleNamespace(async_get=lambda _did: None)
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry),
    )
    import custom_components.oig_cloud.services as svc_mod

    orig = svc_mod.dr.async_get
    svc_mod.dr.async_get = lambda _hass: registry
    try:
        assert module.get_box_id_from_device(hass, "missing_dev", "ent") == "777"
    finally:
        svc_mod.dr.async_get = orig


def test_get_box_id_from_device_found():
    device = SimpleNamespace(identifiers={(DOMAIN, "5555")})
    registry = SimpleNamespace(async_get=lambda _did: device)
    coordinator = SimpleNamespace(config_entry=None, data={})
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None),
    )
    import custom_components.oig_cloud.services as svc_mod

    orig = svc_mod.dr.async_get
    svc_mod.dr.async_get = lambda _hass: registry
    try:
        assert module.get_box_id_from_device(hass, "dev_123", "ent") == "5555"
    finally:
        svc_mod.dr.async_get = orig


def test_get_box_id_from_device_no_identifier_fallback():
    device = SimpleNamespace(identifiers={("other_domain", "abc")})
    registry = SimpleNamespace(async_get=lambda _did: device)
    entry = SimpleNamespace(options={}, data={"box_id": "444"})
    coordinator = SimpleNamespace(config_entry=entry, data={})
    hass = SimpleNamespace(
        data={DOMAIN: {"ent": {"coordinator": coordinator}}},
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: entry),
    )
    import custom_components.oig_cloud.services as svc_mod

    orig = svc_mod.dr.async_get
    svc_mod.dr.async_get = lambda _hass: registry
    try:
        assert module.get_box_id_from_device(hass, "dev_123", "ent") == "444"
    finally:
        svc_mod.dr.async_get = orig


def test_resolve_box_id_from_service_none(monkeypatch):
    hass, entry, _ = _make_hass()
    monkeypatch.setattr(module, "get_box_id_from_device", lambda _h, _d, _e: None)
    result = module._resolve_box_id_from_service(
        hass, entry, {}, "test_service"
    )
    assert result is None


def test_validate_grid_delivery_inputs_both_none():
    with pytest.raises(vol.Invalid):
        module._validate_grid_delivery_inputs(None, None)


def test_validate_grid_delivery_inputs_both_set():
    with pytest.raises(vol.Invalid):
        module._validate_grid_delivery_inputs("on", 100)


def test_validate_grid_delivery_inputs_limit_out_of_range():
    with pytest.raises(vol.Invalid, match="Limit"):
        module._validate_grid_delivery_inputs(None, 10000)
    with pytest.raises(vol.Invalid, match="Limit"):
        module._validate_grid_delivery_inputs(None, 0)


def test_acknowledged_true():
    assert module._acknowledged({"acknowledgement": True}, "svc") is True


def test_acknowledged_false():
    assert module._acknowledged({"acknowledgement": False}, "svc") is False


@pytest.mark.asyncio
async def test_action_set_box_mode_toggles_current_raw(monkeypatch):
    hass, entry, api = _make_hass()
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.data = {"box_prm2": {"app": 1}}
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"home_grid_v": True, "home_grid_vi": False}, ""
    )
    assert any(c[0] == "set_box_prm2_app" for c in api.calls)


@pytest.mark.asyncio
async def test_action_set_box_mode_toggles_fallback_values(monkeypatch):
    hass, entry, api = _make_hass()
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.data = {"outer": {"box_prm2": {"app": 2}}}
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"home_grid_v": False, "home_grid_vi": True}, ""
    )
    assert any(c[0] == "set_box_prm2_app" for c in api.calls)


@pytest.mark.asyncio
async def test_action_set_box_mode_flexibilita_error(monkeypatch):
    hass, entry, _api = _make_hass()
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.data = {"box_prm2": {"app": 4}}
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    with pytest.raises(vol.Invalid, match="Flexibilita"):
        await module._action_set_box_mode(
            hass, entry, {"home_grid_v": True}, ""
        )


@pytest.mark.asyncio
async def test_action_set_box_mode_unknown_current_raw(monkeypatch):
    hass, entry, _api = _make_hass()
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.data = {}
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    with pytest.raises(vol.Invalid, match="unknown"):
        await module._action_set_box_mode(
            hass, entry, {"home_grid_v": True}, ""
        )


@pytest.mark.asyncio
async def test_action_set_boiler_mode_invalid_mode(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")
    with pytest.raises(vol.Invalid, match="Neplatný režim bojleru"):
        await module._action_set_boiler_mode(hass, entry, {"mode": "invalid"}, "")


@pytest.mark.asyncio
async def test_action_set_grid_delivery_limit_success(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")
    await module._action_set_grid_delivery(
        hass, entry, {"mode": None, "limit": 500}, "", False
    )
    assert ("set_grid_delivery_limit", 500) in api.calls


@pytest.mark.asyncio
async def test_action_set_grid_delivery_limit_enforce_error(monkeypatch):
    hass, entry, api = _make_hass()

    async def _fail(_v):
        return False

    api.set_grid_delivery_limit = _fail  # type: ignore[method-assign]
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")
    with pytest.raises(vol.Invalid, match="Limit"):
        await module._action_set_grid_delivery(
            hass, entry, {"mode": None, "limit": 500}, "", True
        )


@pytest.mark.asyncio
async def test_action_set_formating_mode_limit_branch(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")
    await module._action_set_formating_mode(
        hass, entry, {"mode": "charge", "acknowledgement": True, "limit": 42}, ""
    )
    assert ("set_formating_mode", "42") in api.calls


@pytest.mark.asyncio
async def test_shield_set_box_mode(monkeypatch):
    called = False

    async def _action(h, e, d, lp):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_box_mode", _action)
    hass, entry, _ = _make_hass()
    await module._shield_set_box_mode(hass, entry, {"mode": "home_1"})
    assert called


@pytest.mark.asyncio
async def test_shield_set_grid_delivery(monkeypatch):
    called = False

    async def _action(h, e, d, lp, enforce):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_grid_delivery", _action)
    hass, entry, _ = _make_hass()
    await module._shield_set_grid_delivery(hass, entry, {"mode": "on"})
    assert called


@pytest.mark.asyncio
async def test_shield_set_boiler_mode(monkeypatch):
    called = False

    async def _action(h, e, d, lp):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_boiler_mode", _action)
    hass, entry, _ = _make_hass()
    await module._shield_set_boiler_mode(hass, entry, {"mode": "cbb"})
    assert called


@pytest.mark.asyncio
async def test_shield_set_formating_mode(monkeypatch):
    called = False

    async def _action(h, e, d, lp):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_formating_mode", _action)
    hass, entry, _ = _make_hass()
    await module._shield_set_formating_mode(hass, entry, {"mode": "charge"})
    assert called


@pytest.mark.asyncio
async def test_fallback_set_grid_delivery(monkeypatch):
    called = False

    async def _action(h, e, d, lp, enforce):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_grid_delivery", _action)
    hass, entry, _ = _make_hass()
    await module._fallback_set_grid_delivery(hass, entry, {"mode": "on"})
    assert called


@pytest.mark.asyncio
async def test_fallback_set_formating_mode(monkeypatch):
    called = False

    async def _action(h, e, d, lp):
        nonlocal called
        called = True

    monkeypatch.setattr(module, "_action_set_formating_mode", _action)
    hass, entry, _ = _make_hass()
    await module._fallback_set_formating_mode(hass, entry, {"mode": "charge"})
    assert called


def test_make_shield_action():
    called = {}

    async def action(h, e, d):
        called["data"] = d

    hass, entry, _ = _make_hass()
    handler = module._make_shield_action(hass, entry, action)
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        handler(DOMAIN, "set_box_mode", {"x": 1}, False, None)
    )
    assert called["data"] == {"x": 1}


@pytest.mark.asyncio
async def test_wrap_with_shield():
    intercepted = {}

    class FakeShield:
        async def intercept_service_call(self, domain, service, payload, handler, blocking, context):
            intercepted["payload"] = payload
            intercepted["domain"] = domain
            intercepted["service"] = service

    async def action(h, e, d):
        pass

    hass, entry, _ = _make_hass()
    shield = FakeShield()
    wrapper = module._wrap_with_shield(hass, entry, shield, "set_box_mode", action)
    call = SimpleNamespace(data={"mode": "home_1"}, context=None)
    await wrapper(call)
    assert intercepted["domain"] == DOMAIN
    assert intercepted["service"] == "set_box_mode"
    assert intercepted["payload"]["params"]["mode"] == "home_1"


@pytest.mark.asyncio
async def test_make_fallback_handler():
    called = {}

    async def action(h, e, d):
        called["data"] = d

    hass, entry, _ = _make_hass()
    handler = module._make_fallback_handler(hass, entry, action)
    call = SimpleNamespace(data={"mode": "home_1"})
    await handler(call)
    assert called["data"] == {"mode": "home_1"}


def test_register_service_definitions():
    hass = SimpleNamespace(services=DummyServices())

    async def handler(call):
        return None

    module._register_service_definitions(
        hass,
        [
            ("svc1", handler, vol.Schema({}), module.SupportsResponse.NONE, "msg1"),
            ("svc2", handler, vol.Schema({}), module.SupportsResponse.OPTIONAL, "msg2"),
        ],
    )
    assert hass.services.has_service(DOMAIN, "svc1")
    assert hass.services.has_service(DOMAIN, "svc2")


def test_log_prefix():
    assert module._log_prefix("[SHIELD]") == "[SHIELD] "
    assert module._log_prefix("") == ""


@pytest.mark.asyncio
async def test_async_setup_services_update_solar_forecast(monkeypatch):
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        services=DummyServices(),
    )
    monkeypatch.setattr(module, "_update_solar_forecast_for_entry", lambda _eid, _ed, _ent: {"status": "updated"})
    await module.async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, "update_solar_forecast")][0]
    call = SimpleNamespace(data={})
    result = await handler(call)
    assert result["updated"] == []


@pytest.mark.asyncio
async def test_async_setup_services_save_dashboard_tiles(monkeypatch):
    saved = {}

    async def _save(h, cfg):
        saved["cfg"] = cfg

    monkeypatch.setattr(module, "_save_dashboard_tiles_config", _save)
    hass = SimpleNamespace(data={DOMAIN: {}}, services=DummyServices())
    await module.async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, "save_dashboard_tiles")][0]
    call = SimpleNamespace(data={"config": '{"tiles_left": [], "tiles_right": [], "version": 1}'})
    await handler(call)
    assert saved["cfg"] == '{"tiles_left": [], "tiles_right": [], "version": 1}'


@pytest.mark.asyncio
async def test_async_setup_services_get_dashboard_tiles(monkeypatch):
    async def _load(_h):
        return {"config": {"x": 1}}

    monkeypatch.setattr(module, "_load_dashboard_tiles_config", _load)
    hass = SimpleNamespace(data={DOMAIN: {}}, services=DummyServices())
    await module.async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, "get_dashboard_tiles")][0]
    call = SimpleNamespace(data={})
    result = await handler(call)
    assert result == {"config": {"x": 1}}


@pytest.mark.asyncio
async def test_async_setup_services_check_balancing(monkeypatch):
    async def _run(_h, _c):
        return {"results": []}

    monkeypatch.setattr(module, "_run_manual_balancing_checks", _run)
    hass = SimpleNamespace(data={DOMAIN: {}}, services=DummyServices())
    await module.async_setup_services(hass)
    handler = hass.services.registered[(DOMAIN, "check_balancing")][0]
    call = SimpleNamespace(data={})
    result = await handler(call)
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_normal():
    hass, entry, _ = _make_hass()
    shield = SimpleNamespace(
        intercept_service_call=lambda *a, **k: None
    )
    await module.async_setup_entry_services_with_shield(hass, entry, shield)
    assert hass.services.has_service(DOMAIN, "set_box_mode")
    assert hass.services.has_service(DOMAIN, "set_grid_delivery")
    assert hass.services.has_service(DOMAIN, "set_boiler_mode")
    assert hass.services.has_service(DOMAIN, "set_formating_mode")


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback_normal():
    hass, entry, _ = _make_hass()
    await module.async_setup_entry_services_fallback(hass, entry)
    assert hass.services.has_service(DOMAIN, "set_box_mode")
    assert hass.services.has_service(DOMAIN, "set_grid_delivery")
    assert hass.services.has_service(DOMAIN, "set_boiler_mode")
    assert hass.services.has_service(DOMAIN, "set_formating_mode")


def test_entry_service_actions_shielded():
    actions = module._entry_service_actions(shielded=True)
    names = [a[0] for a in actions]
    assert "set_box_mode" in names
    assert "set_grid_delivery" in names


def test_entry_service_actions_fallback():
    actions = module._entry_service_actions(shielded=False)
    names = [a[0] for a in actions]
    assert "set_box_mode" in names
    assert "set_boiler_mode" in names


def test_register_entry_services_exception():
    hass = SimpleNamespace(services=DummyServices(fail=True))
    entry = SimpleNamespace(entry_id="e")

    async def action(h, e, d):
        pass

    module._register_entry_services(
        hass,
        entry,
        [("svc1", action, vol.Schema({}))],
        lambda _name, _action: (lambda _call: None),
    )


@pytest.mark.asyncio
async def test_save_dashboard_tiles_success(monkeypatch):
    saved = {}

    class GoodStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_save(self, data):
            saved["data"] = data

    monkeypatch.setattr("homeassistant.helpers.storage.Store", GoodStore)
    hass = SimpleNamespace()
    await module._save_dashboard_tiles_config(
        hass, '{"tiles_left": [1], "tiles_right": [2], "version": 1}'
    )
    assert saved["data"]["tiles_left"] == [1]


@pytest.mark.asyncio
async def test_save_dashboard_tiles_json_decode_error(monkeypatch):
    class GoodStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_save(self, _data):
            pass

    monkeypatch.setattr("homeassistant.helpers.storage.Store", GoodStore)
    hass = SimpleNamespace()
    await module._save_dashboard_tiles_config(hass, "not json")


@pytest.mark.asyncio
async def test_save_dashboard_tiles_validation_error(monkeypatch):
    class GoodStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_save(self, _data):
            pass

    monkeypatch.setattr("homeassistant.helpers.storage.Store", GoodStore)
    hass = SimpleNamespace()
    await module._save_dashboard_tiles_config(hass, '{"missing": "keys"}')


@pytest.mark.asyncio
async def test_load_dashboard_tiles_success(monkeypatch):
    class GoodStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_load(self):
            return {"tiles_left": [1]}

    monkeypatch.setattr("homeassistant.helpers.storage.Store", GoodStore)
    hass = SimpleNamespace()
    result = await module._load_dashboard_tiles_config(hass)
    assert result["config"] == {"tiles_left": [1]}


@pytest.mark.asyncio
async def test_load_dashboard_tiles_no_data(monkeypatch):
    class GoodStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_load(self):
            return None

    monkeypatch.setattr("homeassistant.helpers.storage.Store", GoodStore)
    hass = SimpleNamespace()
    result = await module._load_dashboard_tiles_config(hass)
    assert result["config"] is None


def test_validate_dashboard_tiles_config_missing_key():
    with pytest.raises(ValueError, match="Missing required key"):
        module._validate_dashboard_tiles_config({"tiles_left": [], "version": 1})


def test_serialize_dt_none():
    assert module._serialize_dt(None) is None


def test_serialize_dt_str():
    assert module._serialize_dt("already") == "already"


def test_iter_balancing_managers_no_requested_box():
    mgr = SimpleNamespace(box_id="1")
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "shield": {"x": 1},
                "entry": {"balancing_manager": mgr},
            }
        }
    )
    rows = module._iter_balancing_managers(hass, requested_box=None)
    assert len(rows) == 1


def test_iter_balancing_managers_no_manager():
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "entry": {},
            }
        }
    )
    rows = module._iter_balancing_managers(hass, requested_box=None)
    assert rows == []


def test_build_balancing_plan_result():
    plan = SimpleNamespace(
        mode=SimpleNamespace(value="hold"),
        reason="test",
        holding_start=None,
        holding_end=None,
        priority=SimpleNamespace(value=1),
    )
    result = module._build_balancing_plan_result("e1", "123", plan)
    assert result["plan_mode"] == "hold"
    assert result["reason"] == "test"


def test_build_no_plan_result():
    result = module._build_no_plan_result("e1", "123")
    assert result["reason"] == "no_plan_needed"


def test_build_error_result():
    result = module._build_error_result("e1", "123", RuntimeError("oops"))
    assert result["error"] == "oops"


class FakePlan:
    mode = SimpleNamespace(value="hold")
    reason = "test_reason"
    holding_start = None
    holding_end = None
    priority = SimpleNamespace(value=1)


@pytest.mark.asyncio
async def test_run_manual_balancing_checks_plan_branch():
    class Manager:
        box_id = "1"

        async def check_balancing(self, force=False):
            return FakePlan()

    hass = SimpleNamespace(data={DOMAIN: {"entry": {"balancing_manager": Manager()}}})
    call = SimpleNamespace(data={})
    result = await module._run_manual_balancing_checks(hass, call)
    assert result["processed_entries"] == 1
    assert result["results"][0]["plan_mode"] == "hold"


@pytest.mark.asyncio
async def test_run_manual_balancing_checks_exception():
    class Manager:
        box_id = "1"

        async def check_balancing(self, force=False):
            raise RuntimeError("fail")

    hass = SimpleNamespace(data={DOMAIN: {"entry": {"balancing_manager": Manager()}}})
    call = SimpleNamespace(data={})
    result = await module._run_manual_balancing_checks(hass, call)
    assert result["processed_entries"] == 1
    assert "fail" in result["results"][0]["error"]


@pytest.mark.asyncio
async def test_run_manual_balancing_checks_no_results():
    hass = SimpleNamespace(data={DOMAIN: {}})
    call = SimpleNamespace(data={})
    result = await module._run_manual_balancing_checks(hass, call)
    assert result["processed_entries"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_async_setup_entry_services_shield(monkeypatch):
    called = {"shield": 0, "fallback": 0}

    async def _shield(*_args, **_kwargs):
        called["shield"] += 1

    async def _fallback(*_args, **_kwargs):
        called["fallback"] += 1

    monkeypatch.setattr(module, "async_setup_entry_services_with_shield", _shield)
    monkeypatch.setattr(module, "async_setup_entry_services_fallback", _fallback)

    entry = SimpleNamespace(entry_id="entry")
    hass = SimpleNamespace(data={DOMAIN: {"shield": object()}})
    await module.async_setup_entry_services(hass, entry)
    assert called["shield"] == 1


@pytest.mark.asyncio
async def test_async_setup_entry_services_no_shield(monkeypatch):
    called = {"shield": 0, "fallback": 0}

    async def _shield(*_args, **_kwargs):
        called["shield"] += 1

    async def _fallback(*_args, **_kwargs):
        called["fallback"] += 1

    monkeypatch.setattr(module, "async_setup_entry_services_with_shield", _shield)
    monkeypatch.setattr(module, "async_setup_entry_services_fallback", _fallback)

    entry = SimpleNamespace(entry_id="entry")
    hass = SimpleNamespace(data={DOMAIN: {"shield": None}})
    await module.async_setup_entry_services(hass, entry)
    assert called["fallback"] == 1
