from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.shield import validation as module


class DummyStates:
    def __init__(self, entities):
        self._entities = entities
        self._map = {e.entity_id: e for e in entities}

    def async_all(self):
        return self._entities

    def get(self, entity_id):
        return self._map.get(entity_id)


class DummyHass:
    def __init__(self, entities):
        self.states = DummyStates(entities)
        self.data = {}


class DummyEntry:
    def __init__(self, options=None, data=None):
        self.options = options or {}
        self.data = data or {}


class DummyEntity:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state


class DummyShield:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.last_checked_entity_id = None


def test_extract_api_info_grid_delivery():
    info = module.extract_api_info("oig_cloud.set_grid_delivery", {"limit": 50})
    assert info["api_table"] == "invertor_prm1"
    info = module.extract_api_info("oig_cloud.set_grid_delivery", {"mode": "off"})
    assert info["api_table"] == "invertor_prms"


def test_extract_expected_entities_box_mode_resolve(monkeypatch):
    entity = DummyEntity("sensor.oig_123_box_prms_mode", "Home 1")
    hass = DummyHass([entity])
    entry = DummyEntry(options={}, data={})
    shield = DummyShield(hass, entry)
    hass.data = {"oig_cloud": {"entry1": {"service_shield": shield, "coordinator": object()}}}

    monkeypatch.setattr(
        "custom_components.oig_cloud.entities.base_sensor.resolve_box_id",
        lambda _coord: "123",
        raising=False,
    )

    expected = module.extract_expected_entities(
        shield, module.SERVICE_SET_BOX_MODE, {"mode": "Home 2"}
    )
    assert expected == {"sensor.oig_123_box_prms_mode": "Home 2"}


def test_extract_expected_entities_formating_mode():
    hass = DummyHass([])
    shield = DummyShield(hass, DummyEntry())
    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_formating_mode", {}
    )
    assert list(expected.values()) == ["completed_after_timeout"]
