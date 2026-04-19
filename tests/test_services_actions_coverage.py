from __future__ import annotations

from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.oig_cloud import services as module
from custom_components.oig_cloud.const import DOMAIN


class DummyServices:
    def __init__(self, existing: set[str] | None = None, fail: bool = False):
        self.existing = existing or set()
        self.fail = fail
        self.registered = {}
        self.removed = []

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
        self.calls = []

    async def set_box_mode(self, value):
        self.calls.append(("set_box_mode", value))

    async def set_grid_delivery(self, value):
        self.calls.append(("set_grid_delivery", value))

    async def set_grid_delivery_limit(self, value):
        self.calls.append(("set_grid_delivery_limit", value))
        return False

    async def set_boiler_mode(self, value):
        self.calls.append(("set_boiler_mode", value))

    async def set_formating_mode(self, value):
        self.calls.append(("set_formating_mode", value))


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


@pytest.mark.asyncio
async def test_action_set_grid_delivery_enforce_limit_error():
    hass, entry, _api = _make_hass()
    with pytest.raises(vol.Invalid):
        await module._action_set_grid_delivery(
            hass,
            entry,
            {"mode": None, "limit": 1000, "acknowledgement": True, "warning": True},
            "",
            True,
        )


@pytest.mark.asyncio
async def test_action_set_formating_mode_not_acknowledged():
    hass, entry, api = _make_hass()
    await module._action_set_formating_mode(
        hass,
        entry,
        {"mode": "charge", "acknowledgement": False},
        "",
    )
    assert api.calls == []


@pytest.mark.asyncio
async def test_async_setup_entry_services_with_shield_fallback(monkeypatch):
    hass, entry, _ = _make_hass()
    called = {"fallback": False}

    async def _fallback(_hass, _entry):
        called["fallback"] = True

    monkeypatch.setattr(module, "async_setup_entry_services_fallback", _fallback)
    await module.async_setup_entry_services_with_shield(hass, entry, shield=None)
    assert called["fallback"] is True


@pytest.mark.asyncio
async def test_async_setup_entry_services_fallback_already_registered():
    hass, entry, _ = _make_hass()
    hass.services = DummyServices(existing={"set_box_mode"})
    await module.async_setup_entry_services_fallback(hass, entry)
    assert hass.services.registered == {}


def test_register_entry_services_handles_exception():
    hass, entry, _ = _make_hass()
    hass.services = DummyServices(fail=True)

    module._register_entry_services(
        hass,
        entry,
        [("set_box_mode", module._fallback_set_box_mode, module.SET_BOX_MODE_SCHEMA)],
        lambda _name, _action: (lambda _call: None),
    )


def test_register_boiler_services_no_coordinator():
    hass = SimpleNamespace(data={DOMAIN: {"entry": {}}})
    entry = SimpleNamespace(entry_id="entry")
    module._register_boiler_services(hass, entry)


def test_register_boiler_services_exception(monkeypatch):
    hass = SimpleNamespace(data={DOMAIN: {"entry": {"boiler_coordinator": object()}}})
    entry = SimpleNamespace(entry_id="entry")

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("custom_components.oig_cloud.services.boiler.setup_boiler_services", _raise)
    module._register_boiler_services(hass, entry)


@pytest.mark.asyncio
async def test_save_dashboard_tiles_empty_config():
    hass = SimpleNamespace()
    await module._save_dashboard_tiles_config(hass, None)


@pytest.mark.asyncio
async def test_save_dashboard_tiles_store_exception(monkeypatch):
    class BadStore:
        def __init__(self, *_args, **_kwargs):
            pass

        async def async_save(self, _data):
            raise RuntimeError("save failed")

    monkeypatch.setattr("homeassistant.helpers.storage.Store", BadStore)
    hass = SimpleNamespace()
    valid = '{"tiles_left": [], "tiles_right": [], "version": 1}'
    await module._save_dashboard_tiles_config(hass, valid)


@pytest.mark.asyncio
async def test_load_dashboard_tiles_store_exception(monkeypatch):
    class BadStore:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("load failed")

    monkeypatch.setattr("homeassistant.helpers.storage.Store", BadStore)
    hass = SimpleNamespace()
    data = await module._load_dashboard_tiles_config(hass)
    assert data == {"config": None}


def test_validate_dashboard_tiles_config_non_dict():
    with pytest.raises(ValueError):
        module._validate_dashboard_tiles_config([])


@pytest.mark.asyncio
async def test_async_unload_services_removes_registered():
    services = DummyServices(
        existing={
            "update_solar_forecast",
            "save_dashboard_tiles",
            "set_box_mode",
            "set_grid_delivery",
            "set_boiler_mode",
            "set_formating_mode",
        }
    )
    hass = SimpleNamespace(services=services)
    await module.async_unload_services(hass)
    assert len(services.removed) == 6


def test_box_id_helpers_exception_branches():
    class BadConfigEntries:
        def async_get_entry(self, _entry_id):
            raise RuntimeError("boom")

    hass = SimpleNamespace(config_entries=BadConfigEntries())
    assert module._box_id_from_entry(hass, coordinator=None, entry_id="x") is None

    class BadCoordinator:
        @property
        def data(self):
            raise RuntimeError("boom")

    assert module._box_id_from_coordinator(BadCoordinator()) is None


def test_get_entry_solar_sensors_fallback_async_update():
    async def _update():
        return None

    fallback = SimpleNamespace(async_update=_update)
    sensors = module._get_entry_solar_sensors({"solar_forecast": fallback})
    assert sensors == [fallback]


@pytest.mark.asyncio
async def test_update_solar_forecast_no_primary_and_manual_failed(monkeypatch):
    # no_primary branch
    monkeypatch.setattr(module, "_get_primary_solar_sensor", lambda _entry_data: None)
    result = await module._update_solar_forecast_for_entry(
        "entry", {"solar_forecast_sensors": [SimpleNamespace(entity_id="sensor.x")]}
    )
    assert result["status"] == "no_primary"

    # manual_update_failed branch
    async def _manual_update():
        return False

    sensor = SimpleNamespace(entity_id="sensor.x", _sensor_type="solar_forecast", async_manual_update=_manual_update)
    monkeypatch.setattr(module, "_get_primary_solar_sensor", lambda _entry_data: sensor)
    result2 = await module._update_solar_forecast_for_entry(
        "entry", {"solar_forecast_sensors": [sensor]}
    )
    assert result2["status"] == "error"
    assert result2["error"] == "manual_update_failed"


@pytest.mark.asyncio
async def test_action_functions_return_when_no_box_id(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: None)

    await module._action_set_box_mode(hass, entry, {"mode": "home_1"}, "")
    await module._action_set_boiler_mode(hass, entry, {"mode": "cbb"}, "")
    await module._action_set_grid_delivery(
        hass,
        entry,
        {"mode": "on", "limit": None, "acknowledgement": True, "warning": True},
        "",
        False,
    )
    await module._action_set_formating_mode(
        hass,
        entry,
        {"mode": "charge", "acknowledgement": True},
        "",
    )
    assert api.calls == []


@pytest.mark.asyncio
async def test_action_grid_and_formating_calls(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_grid_delivery(
        hass,
        entry,
        {"mode": "on", "limit": None, "acknowledgement": True, "warning": True},
        "",
        False,
    )
    assert ("set_grid_delivery", 1) in api.calls

    await module._action_set_formating_mode(
        hass,
        entry,
        {"mode": "charge", "acknowledgement": True, "limit": None},
        "",
    )
    assert ("set_formating_mode", "1") in api.calls


@pytest.mark.asyncio
async def test_action_grid_and_formating_calls_legacy_labels(monkeypatch):
    """Test that legacy label values still work (backward compatibility)."""
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_grid_delivery(
        hass,
        entry,
        {"mode": module.GRID_ON_LABEL, "limit": None, "acknowledgement": True, "warning": True},
        "",
        False,
    )
    assert ("set_grid_delivery", 1) in api.calls

    await module._action_set_formating_mode(
        hass,
        entry,
        {"mode": module.FORMAT_CHARGE_LABEL, "acknowledgement": True, "limit": None},
        "",
    )
    assert ("set_formating_mode", "1") in api.calls


@pytest.mark.asyncio
async def test_fallback_wrappers_delegate(monkeypatch):
    called = {"box": False, "boiler": False}

    async def _box(*_args, **_kwargs):
        called["box"] = True

    async def _boiler(*_args, **_kwargs):
        called["boiler"] = True

    monkeypatch.setattr(module, "_action_set_box_mode", _box)
    monkeypatch.setattr(module, "_action_set_boiler_mode", _boiler)

    await module._fallback_set_box_mode(SimpleNamespace(), SimpleNamespace(), {})
    await module._fallback_set_boiler_mode(SimpleNamespace(), SimpleNamespace(), {})
    assert called["box"] is True
    assert called["boiler"] is True


@pytest.mark.asyncio
async def test_async_setup_entry_services_branches(monkeypatch):
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

    hass2 = SimpleNamespace(data={DOMAIN: {"shield": None}})
    await module.async_setup_entry_services(hass2, entry)

    assert called["shield"] == 1
    assert called["fallback"] == 1


def test_register_boiler_services_success(monkeypatch):
    called = {"ok": False}

    def _ok(*_args, **_kwargs):
        called["ok"] = True

    monkeypatch.setattr("custom_components.oig_cloud.services.boiler.setup_boiler_services", _ok)

    hass = SimpleNamespace(data={DOMAIN: {"entry": {"boiler_coordinator": object()}}})
    module._register_boiler_services(hass, SimpleNamespace(entry_id="entry"))
    assert called["ok"] is True


def test_serialize_dt_and_iter_balancing_manager_branches():
    dt_obj = SimpleNamespace(isoformat=lambda: "2025-01-01T00:00:00")
    assert module._serialize_dt(dt_obj) == "2025-01-01T00:00:00"

    manager = SimpleNamespace(box_id="1")
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "shield": {"x": 1},
                "entry_no_manager": {},
                "entry_other_box": {"balancing_manager": SimpleNamespace(box_id="2")},
                "entry_ok": {"balancing_manager": manager},
            }
        }
    )

    rows = module._iter_balancing_managers(hass, requested_box="1")
    assert rows == [("entry_ok", manager, "1")]


def test_serialize_dt_fallback_str_branch():
    class NoIso:
        def __str__(self):
            return "fallback-value"

    assert module._serialize_dt(NoIso()) == "fallback-value"


@pytest.mark.asyncio
async def test_run_manual_balancing_no_plan_branch():
    class Manager:
        box_id = "1"

        async def check_balancing(self, force=False):
            _ = force
            return None

    hass = SimpleNamespace(data={DOMAIN: {"entry": {"balancing_manager": Manager()}}})
    call = SimpleNamespace(data={})
    result = await module._run_manual_balancing_checks(hass, call)
    assert result["processed_entries"] == 1
    assert result["results"][0]["reason"] == "no_plan_needed"


class TestUpdateSolarForecastBranches:
    """Tests for _update_solar_forecast_for_entry branches."""

    def test_update_solar_forecast_no_sensors(self, monkeypatch):
        """Branch when no solar forecast sensors are available."""
        import asyncio
        monkeypatch.setattr(module, "_get_entry_solar_sensors", lambda _ed: [])
        result = asyncio.get_event_loop().run_until_complete(
            module._update_solar_forecast_for_entry(
                "entry_1", {"solar_forecast_sensors": []}
            )
        )
        assert result["status"] == "no_sensors"

    def test_update_solar_forecast_skipped(self, monkeypatch):
        """Branch when entity_ids don't match any sensors."""
        import asyncio
        sensor = SimpleNamespace(entity_id="sensor.solar")
        monkeypatch.setattr(module, "_get_entry_solar_sensors", lambda _ed: [sensor])
        result = asyncio.get_event_loop().run_until_complete(
            module._update_solar_forecast_for_entry(
                "entry_1", {"solar_forecast_sensors": [sensor]}, entity_ids=["sensor.other"]
            )
        )
        assert result["status"] == "skipped"

    def test_update_solar_forecast_no_primary(self, monkeypatch):
        """Branch when no primary solar sensor is found."""
        import asyncio
        monkeypatch.setattr(module, "_get_entry_solar_sensors", lambda _ed: [SimpleNamespace(entity_id="sensor.x")])
        monkeypatch.setattr(module, "_get_primary_solar_sensor", lambda _ed: None)
        result = asyncio.get_event_loop().run_until_complete(
            module._update_solar_forecast_for_entry(
                "entry_1", {"solar_forecast_sensors": [SimpleNamespace(entity_id="sensor.x")]}
            )
        )
        assert result["status"] == "no_primary"

    def test_update_solar_forecast_manual_update_failed(self, monkeypatch):
        """Branch when async_manual_update returns False."""
        import asyncio
        sensor = SimpleNamespace(entity_id="sensor.x", _sensor_type="solar_forecast")

        async def manual_update_false():
            return False

        sensor.async_manual_update = manual_update_false
        monkeypatch.setattr(module, "_get_primary_solar_sensor", lambda _ed: sensor)
        result = asyncio.get_event_loop().run_until_complete(
            module._update_solar_forecast_for_entry(
                "entry_1", {"solar_forecast_sensors": [sensor]}
            )
        )
        assert result["status"] == "error"
        assert result["error"] == "manual_update_failed"

    def test_update_solar_forecast_exception(self, monkeypatch):
        """Branch when exception is raised during update."""
        import asyncio

        async def raise_exc():
            raise RuntimeError("update failed")

        sensor = SimpleNamespace(entity_id="sensor.x", _sensor_type="solar_forecast", async_update=raise_exc)
        monkeypatch.setattr(module, "_get_primary_solar_sensor", lambda _ed: sensor)
        result = asyncio.get_event_loop().run_until_complete(
            module._update_solar_forecast_for_entry(
                "entry_1", {"solar_forecast_sensors": [sensor]}
            )
        )
        assert result["status"] == "error"
        assert "update failed" in result["error"]


class TestActionSetBoxModeBranches:
    """Tests for _action_set_box_mode branches."""

    def test_action_set_box_mode_home_5_legacy_invalid(self, monkeypatch):
        hass, entry, api = _make_hass()
        monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

        with pytest.raises(vol.Invalid, match="Neplatný režim boxu."):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                module._action_set_box_mode(hass, entry, {"mode": "home_5"}, "")
            )

    def test_action_set_box_mode_home_5_label_legacy_invalid(self, monkeypatch):
        hass, entry, api = _make_hass()
        monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

        with pytest.raises(vol.Invalid, match="Neplatný režim boxu."):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                module._action_set_box_mode(hass, entry, {"mode": "Home 5"}, "")
            )

    def test_action_set_box_mode_home_6_legacy_invalid(self, monkeypatch):
        hass, entry, api = _make_hass()
        monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

        with pytest.raises(vol.Invalid, match="Neplatný režim boxu."):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                module._action_set_box_mode(hass, entry, {"mode": "home_6"}, "")
            )

    def test_action_set_box_mode_non_500_error_passthrough(self, monkeypatch):
        """Non-500 errors should be re-raised."""
        hass, entry, api = _make_hass()

        async def raise_other(*args, **kwargs):
            raise Exception("403 Forbidden")

        api.set_box_mode = raise_other
        monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

        with pytest.raises(Exception, match="403 Forbidden"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                module._action_set_box_mode(hass, entry, {"mode": "home_1"}, "")
            )

    def test_action_set_box_mode_invalid_mode_raises(self, monkeypatch):
        """Invalid mode value raises vol.Invalid."""
        hass, entry, api = _make_hass()
        called = []

        async def track_call(*args, **kwargs):
            called.append(args)

        api.set_box_mode = track_call
        monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

        with pytest.raises(vol.Invalid, match="Neplatný režim boxu."):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                module._action_set_box_mode(hass, entry, {"mode": "invalid_mode"}, "")
            )
        assert len(called) == 0
