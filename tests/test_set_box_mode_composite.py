"""TDD tests for set_box_mode composite contract."""

from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.oig_cloud import services as module
from custom_components.oig_cloud.const import DOMAIN


class DummyApi:
    def __init__(self):
        self.calls = []

    async def set_box_mode(self, value):
        self.calls.append(("set_box_mode", value))

    async def set_box_prm2_app(self, value):
        self.calls.append(("set_box_prm2_app", value))


def _make_hass(entry_id: str = "entry", box_prm2_app=None):
    api = DummyApi()
    data = {"123": {}}
    if box_prm2_app is not None:
        data["box_prm2"] = {"app": box_prm2_app}
    coordinator = SimpleNamespace(api=api, config_entry=None, data=data)
    hass = SimpleNamespace(
        data={DOMAIN: {entry_id: {"coordinator": coordinator}}},
        services=object(),
        config_entries=SimpleNamespace(async_get_entry=lambda _eid: None),
    )
    entry = SimpleNamespace(entry_id=entry_id)
    return hass, entry, api


def test_schema_mode_home_1_alone_valid():
    data = {"mode": "home_1", "acknowledgement": True}
    result = module.SET_BOX_MODE_SCHEMA(data)
    assert result["mode"] == "home_1"


def test_schema_mode_with_toggles_valid():
    data = {"mode": "home_1", "home_grid_v": True, "acknowledgement": True}
    result = module.SET_BOX_MODE_SCHEMA(data)
    assert result["mode"] == "home_1"
    assert result["home_grid_v"] is True


def test_schema_toggles_only_valid():
    data = {"home_grid_v": True, "acknowledgement": True}
    result = module.SET_BOX_MODE_SCHEMA(data)
    assert result["home_grid_v"] is True


def test_schema_empty_call_invalid():
    with pytest.raises(vol.Invalid):
        module.SET_BOX_MODE_SCHEMA({"acknowledgement": True})


@pytest.mark.parametrize(
    "legacy_mode",
    ["home_5", "home_6", "Home 5", "Home 6", "home5", "home6"],
)
def test_schema_rejects_legacy_aliases(legacy_mode):
    with pytest.raises(vol.Invalid, match="home_grid_v/home_grid_vi"):
        module.SET_BOX_MODE_SCHEMA({"mode": legacy_mode, "acknowledgement": True})


@pytest.mark.asyncio
async def test_action_mode_home_1_alone_calls_set_box_mode_only(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"mode": "home_1", "acknowledgement": True}, ""
    )

    assert ("set_box_mode", "0") in api.calls
    assert not any(c[0] == "set_box_prm2_app" for c in api.calls)


@pytest.mark.asyncio
async def test_action_mode_home_1_with_home_grid_v_calls_both(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=0)
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"mode": "home_1", "home_grid_v": True, "acknowledgement": True}, ""
    )

    assert api.calls == [("set_box_mode", "0"), ("set_box_prm2_app", 1)]


@pytest.mark.asyncio
async def test_action_home_grid_v_true_alone_rmw(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=0)
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"home_grid_v": True, "acknowledgement": True}, ""
    )

    assert api.calls == [("set_box_prm2_app", 1)]


@pytest.mark.asyncio
async def test_action_home_grid_v_true_and_home_grid_vi_true(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=0)
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass,
        entry,
        {"home_grid_v": True, "home_grid_vi": True, "acknowledgement": True},
        "",
    )

    assert api.calls == [("set_box_prm2_app", 3)]


@pytest.mark.asyncio
async def test_action_home_grid_v_false_preserves_vi_bit(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=3)
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    await module._action_set_box_mode(
        hass, entry, {"home_grid_v": False, "acknowledgement": True}, ""
    )

    assert api.calls == [("set_box_prm2_app", 2)]


@pytest.mark.asyncio
async def test_action_missing_box_prm2_app_raises(monkeypatch):
    hass, entry, api = _make_hass()
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    with pytest.raises(vol.Invalid, match="box_prm2.app state unknown"):
        await module._action_set_box_mode(
            hass, entry, {"home_grid_v": True, "acknowledgement": True}, ""
        )


@pytest.mark.asyncio
async def test_action_flexibilita_active_raises(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=4)
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    with pytest.raises(vol.Invalid, match="Flexibilita"):
        await module._action_set_box_mode(
            hass, entry, {"home_grid_v": True, "acknowledgement": True}, ""
        )


@pytest.mark.asyncio
async def test_action_set_box_prm2_app_500_propagated(monkeypatch):
    hass, entry, api = _make_hass(box_prm2_app=0)

    async def raise_500(*args, **kwargs):
        raise Exception("500 Internal Server Error")

    api.set_box_prm2_app = raise_500
    monkeypatch.setattr(module, "_resolve_box_id_from_service", lambda *_a, **_k: "123")

    with pytest.raises(Exception, match="500 Internal Server Error"):
        await module._action_set_box_mode(
            hass, entry, {"home_grid_v": True, "acknowledgement": True}, ""
        )


@pytest.mark.parametrize(
    "legacy_mode",
    ["home_5", "home_6", "Home 5", "Home 6", "home5", "home6"],
)
def test_action_legacy_alias_schema_rejection(legacy_mode):
    with pytest.raises(vol.Invalid, match="home_grid_v/home_grid_vi"):
        module.SET_BOX_MODE_SCHEMA({"mode": legacy_mode, "acknowledgement": True})
