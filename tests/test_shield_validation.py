from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.shield import validation as validation_module


class DummyState:
    def __init__(self, entity_id, state):
        self.entity_id = entity_id
        self.state = state


class DummyStates:
    def __init__(self, states):
        self._states = {state.entity_id: state for state in states}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_all(self, domain=None):
        if domain is None:
            return list(self._states.values())
        prefix = f"{domain}."
        return [state for entity_id, state in self._states.items() if entity_id.startswith(prefix)]


class DummyHass:
    def __init__(self, states):
        self.states = states
        self.data = {"oig_cloud": {}}


class DummyShield:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.last_checked_entity_id = None


def test_normalize_value_and_values_match():
    assert validation_module.normalize_value("Vypnuto / Off") == "vypnutooff"
    assert validation_module.normalize_value("S omezenim / Limited") == "omezeno"
    assert validation_module.normalize_value("Manual") == "manualni"
    assert validation_module.values_match("1.0", "1") is True
    assert validation_module.values_match("Home 1", "home1") is True


def test_extract_api_info():
    info = validation_module.extract_api_info("oig_cloud.set_boiler_mode", {"mode": "Manual"})
    assert info["api_table"] == "boiler_prms"
    assert info["api_value"] == 1

    info = validation_module.extract_api_info("oig_cloud.set_grid_delivery", {"limit": 500})
    assert info["api_column"] == "p_max_feed_grid"

    info = validation_module.extract_api_info("oig_cloud.set_grid_delivery", {"mode": 1})
    assert info["api_column"] == "to_grid"


def test_extract_expected_entities_box_mode():
    entity = DummyState("sensor.oig_123_box_prms_mode", "Home 1")
    hass = DummyHass(DummyStates([entity]))
    entry = SimpleNamespace(options={"box_id": "123"}, data={})
    shield = DummyShield(hass, entry)

    expected = validation_module.extract_expected_entities(
        shield, "oig_cloud.set_box_mode", {"mode": "Home UPS"}
    )

    assert expected == {"sensor.oig_123_box_prms_mode": "Home UPS"}
    assert shield.last_checked_entity_id == "sensor.oig_123_box_prms_mode"


def test_extract_expected_entities_formating():
    hass = DummyHass(DummyStates([]))
    entry = SimpleNamespace(options={"box_id": "123"}, data={})
    shield = DummyShield(hass, entry)

    expected = validation_module.extract_expected_entities(
        shield, "oig_cloud.set_formating_mode", {"mode": "on"}
    )

    assert len(expected) == 1
    key = next(iter(expected))
    assert key.startswith("fake_formating_mode_")
    assert expected[key] == "completed_after_timeout"
