from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.entities import sensor_runtime as runtime_module


class DummyCoordinator:
    def __init__(self, data, last_update_success=True):
        self.data = data
        self.last_update_success = last_update_success


class DummyHass:
    def __init__(self, language="en"):
        self.config = SimpleNamespace(language=language)


class DummySensor(runtime_module.OigCloudSensorRuntimeMixin):
    def __init__(self, coordinator, hass, sensor_type, box_id="123"):
        self.coordinator = coordinator
        self.hass = hass
        self._sensor_type = sensor_type
        self._box_id = box_id
        self._node_id = None
        self._node_key = None
        self.entity_id = f"sensor.oig_{box_id}_{sensor_type}"


def test_available_with_missing_node():
    coordinator = DummyCoordinator({"123": {"box_prms": {}}}, last_update_success=True)
    sensor = DummySensor(coordinator, DummyHass(), "test_sensor")
    sensor._node_id = "missing_node"
    sensor._node_key = "mode"

    assert sensor.available is False


def test_available_when_data_present():
    coordinator = DummyCoordinator({"123": {"box_prms": {"mode": 1}}})
    sensor = DummySensor(coordinator, DummyHass(), "test_sensor")
    sensor._node_id = "box_prms"
    sensor._node_key = "mode"

    assert sensor.available is True


def test_available_false_variants():
    coordinator = DummyCoordinator({"123": {"box_prms": {"mode": 1}}})
    sensor = DummySensor(coordinator, DummyHass(), "test_sensor")
    sensor._node_id = "box_prms"
    sensor._node_key = "mode"

    sensor.coordinator.last_update_success = False
    assert sensor.available is False

    sensor.coordinator.last_update_success = True
    sensor.coordinator.data = None
    assert sensor.available is False

    sensor.coordinator.data = {"123": {"box_prms": {"mode": 1}}}
    sensor._box_id = "unknown"
    assert sensor.available is False

    sensor._box_id = "123"
    sensor.coordinator.data = {"123": {"other": {}}}
    assert sensor.available is False


def test_device_info_categories(monkeypatch):
    def _fake_def(sensor_type):
        if sensor_type == "shield_sensor":
            return {"sensor_type_category": "shield", "name": "Shield"}
        if sensor_type == "pricing_sensor":
            return {"sensor_type_category": "pricing", "name": "Pricing"}
        return {"sensor_type_category": "main", "name": "Main"}

    monkeypatch.setattr(runtime_module, "get_sensor_definition", _fake_def)

    data = {"123": {"box_prms": {"sw": "1.2.3"}, "queen": False}}
    coordinator = DummyCoordinator(data)

    shield_sensor = DummySensor(coordinator, DummyHass(), "shield_sensor")
    pricing_sensor = DummySensor(coordinator, DummyHass(), "pricing_sensor")
    main_sensor = DummySensor(coordinator, DummyHass(), "main_sensor")

    assert any(
        "shield" in ident[1] for ident in shield_sensor.device_info["identifiers"]
    )
    assert any(
        "analytics" in ident[1] for ident in pricing_sensor.device_info["identifiers"]
    )
    assert "Battery Box" in main_sensor.device_info["model"]


def test_device_info_queen_and_non_dict_data(monkeypatch):
    monkeypatch.setattr(
        runtime_module,
        "get_sensor_definition",
        lambda _t: {"sensor_type_category": "main", "name": "Main"},
    )
    coordinator = DummyCoordinator("not-a-dict")
    sensor = DummySensor(coordinator, DummyHass(), "main_sensor")
    info = sensor.device_info
    assert "Home" in info["model"]

    coordinator = DummyCoordinator({"123": {"queen": True, "box_prms": {"sw": "2.0"}}})
    sensor = DummySensor(coordinator, DummyHass(), "main_sensor")
    info = sensor.device_info
    assert "Queen" in info["model"]
    assert info["sw_version"] == "2.0"


def test_name_uses_language(monkeypatch):
    monkeypatch.setattr(
        runtime_module,
        "get_sensor_definition",
        lambda _t: {"name": "Voltage", "name_cs": "Napeti"},
    )
    coordinator = DummyCoordinator({"123": {}})
    sensor = DummySensor(coordinator, DummyHass(language="cs"), "grid_voltage")
    assert sensor.name == "Napeti"
    sensor.hass = DummyHass(language="en")
    assert sensor.name == "Voltage"


def test_name_fallback_and_metadata(monkeypatch):
    monkeypatch.setattr(
        runtime_module,
        "get_sensor_definition",
        lambda _t: {
            "name": "Voltage",
            "options": ["a", "b"],
            "icon": "mdi:flash",
            "device_class": "voltage",
            "state_class": "measurement",
        },
    )
    sensor = DummySensor(DummyCoordinator({"123": {}}), DummyHass(language="cs"), "v")
    assert sensor.name == "Voltage"
    assert sensor.options == ["a", "b"]
    assert sensor.icon == "mdi:flash"
    assert sensor.device_class == "voltage"
    assert sensor.state_class == "measurement"


def test_get_node_value_variants():
    coordinator = DummyCoordinator({"123": {"box_prms": {"mode": 2}}})
    sensor = DummySensor(coordinator, DummyHass(), "test_sensor")
    sensor._node_id = "box_prms"
    sensor._node_key = "mode"
    assert sensor.get_node_value() == 2

    sensor._box_id = "unknown"
    assert sensor.get_node_value() is None

    sensor._box_id = "123"
    sensor.coordinator.data = {"123": {"box_prms": {}}}
    assert sensor.get_node_value() is None

    sensor.coordinator.data = {"123": {"box_prms": "bad"}}
    assert sensor.get_node_value() is None
