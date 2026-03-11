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


def test_values_match_numeric_and_exception():
    assert module.values_match("1.5", "1.5") is True
    assert module.values_match("bad", "1") is False


def test_get_entity_state_missing():
    hass = DummyHass([])
    assert module.get_entity_state(hass, "sensor.nope") is None


def test_extract_api_info_variants():
    info = module.extract_api_info("oig_cloud.set_boiler_mode", {"mode": "manual"})
    assert info["api_table"] == "boiler_prms"
    info = module.extract_api_info(module.SERVICE_SET_BOX_MODE, {"mode": 2})
    assert info["api_table"] == "box_prms"


def test_extract_expected_entities_no_box_id():
    hass = DummyHass([])
    shield = DummyShield(hass, DummyEntry())
    expected = module.extract_expected_entities(
        shield, module.SERVICE_SET_BOX_MODE, {"mode": "Home 2"}
    )
    assert expected == {}


def test_extract_expected_entities_unknown_boiler_mode():
    entity = DummyEntity("sensor.oig_123_boiler_manual_mode", "CBB")
    hass = DummyHass([entity])
    entry = DummyEntry(options={"box_id": "123"})
    shield = DummyShield(hass, entry)
    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_boiler_mode", {"mode": "invalid"}
    )
    assert expected == {}


def test_extract_expected_entities_grid_delivery_limit_same():
    entity = DummyEntity("sensor.oig_123_invertor_prm1_p_max_feed_grid", "50")
    hass = DummyHass([entity])
    entry = DummyEntry(options={"box_id": "123"})
    shield = DummyShield(hass, entry)
    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_grid_delivery", {"limit": 50}
    )
    assert expected == {}


def test_extract_expected_entities_grid_delivery_mode_same():
    entity = DummyEntity("sensor.oig_123_invertor_prms_to_grid", "Vypnuto")
    hass = DummyHass([entity])
    entry = DummyEntry(options={"box_id": "123"})
    shield = DummyShield(hass, entry)
    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_grid_delivery", {"mode": "off"}
    )
    assert expected == {}


def test_extract_expected_entities_grid_delivery_bad_inputs():
    entity = DummyEntity("sensor.oig_123_invertor_prm1_p_max_feed_grid", "x")
    hass = DummyHass([entity])
    entry = DummyEntry(options={"box_id": "123"})
    shield = DummyShield(hass, entry)
    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_grid_delivery", {"limit": "bad"}
    )
    assert expected == {}

    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_grid_delivery", {"mode": "unknown"}
    )
    assert expected == {}

    expected = module.extract_expected_entities(
        shield, "oig_cloud.set_grid_delivery", {"mode": "on", "limit": 10}
    )
    assert expected == {}


def test_check_entity_state_change_variants():
    entities = [
        DummyEntity("sensor.oig_123_box_prms_mode", "Home UPS"),
        DummyEntity("binary_sensor.oig_123_invertor_prms_to_grid", "Omezeno"),
        DummyEntity("sensor.oig_123_invertor_prms_to_grid", "Zapnuto"),
        DummyEntity("sensor.oig_123_invertor_prm1_p_max_feed_grid", "50"),
        DummyEntity("sensor.oig_123_other", "2"),
    ]
    hass = DummyHass(entities)
    shield = SimpleNamespace(hass=hass)

    assert module.check_entity_state_change(
        shield, "sensor.oig_123_box_prms_mode", "Home UPS"
    )
    assert module.check_entity_state_change(
        shield, "sensor.oig_123_box_prms_mode", "3"
    )
    assert module.check_entity_state_change(
        shield, "binary_sensor.oig_123_invertor_prms_to_grid", "omezeno"
    )
    assert module.check_entity_state_change(
        shield, "sensor.oig_123_invertor_prms_to_grid", 1
    )
    assert module.check_entity_state_change(
        shield, "sensor.oig_123_invertor_prm1_p_max_feed_grid", "50"
    )
    assert module.check_entity_state_change(shield, "sensor.oig_123_other", 2)

    assert module.check_entity_state_change(
        shield, "sensor.oig_123_missing", 1
    ) is False
