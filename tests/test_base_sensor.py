from __future__ import annotations

import builtins
import sys

import pytest

from custom_components.oig_cloud.entities import base_sensor as module


class DummyCoordinator:
    def __init__(self):
        self.hass = None

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def test_base_sensor_import_error_uses_empty_config(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "custom_components.oig_cloud.sensor_types":
            raise ImportError("blocked")
        return original_import(name, *args, **kwargs)

    sys.modules.pop("custom_components.oig_cloud.sensor_types", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(module, "resolve_box_id", lambda _coord: "123")
    monkeypatch.setattr(module, "get_sensor_definition", lambda _sensor_type: {})

    sensor = module.OigCloudSensor(DummyCoordinator(), "dummy_sensor")

    assert sensor._sensor_config == {}


def test_base_sensor_service_shield_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(module, "resolve_box_id", lambda _coord: "123")
    monkeypatch.setattr(
        module, "get_sensor_definition", lambda _sensor_type: {"name": "Service"}
    )

    caplog.set_level("WARNING")
    module.OigCloudSensor(DummyCoordinator(), "service_shield_test")

    assert "ServiceShield" in caplog.text
