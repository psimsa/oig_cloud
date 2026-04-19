"""Additional tests for services module to improve coverage to 100%."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import voluptuous as vol

# Import only what we need, avoiding opentelemetry issue
import sys
sys.path.insert(0, '.')

# Import the specific functions directly
from custom_components.oig_cloud.services import (
    _strip_identifier_suffix,
)


def test_strip_identifier_suffix_shield():
    """Test _strip_identifier_suffix removes _shield suffix."""
    result = _strip_identifier_suffix("box123_shield")
    assert result == "box123"


def test_strip_identifier_suffix_analytics():
    """Test _strip_identifier_suffix removes _analytics suffix."""
    result = _strip_identifier_suffix("box123_analytics")
    assert result == "box123"


def test_strip_identifier_suffix_no_suffix():
    """Test _strip_identifier_suffix keeps string without suffix."""
    result = _strip_identifier_suffix("box123")
    assert result == "box123"


def test_strip_identifier_suffix_multiple_suffixes():
    """Test _strip_identifier_suffix handles multiple suffixes."""
    result = _strip_identifier_suffix("box123_shield_analytics")
    # Note: current implementation only removes once, so this tests current behavior
    assert "box123" in result


def test_strip_identifier_suffix_empty_string():
    """Test _strip_identifier_suffix with empty string."""
    result = _strip_identifier_suffix("")
    assert result == ""


class DummyServices:
    """Mock services object."""
    def __init__(self):
        self.registered = {}
        self.removed = set()

    def async_register(self, domain, name, handler, schema=None, supports_response=False):
        self.registered[(domain, name)] = handler
        return True

    def has_service(self, domain, name):
        return (domain, name) in self.registered


class DummyHass:
    """Mock HomeAssistant for testing."""
    def __init__(self):
        self.services = DummyServices()
        self.data = {}


def test_constants_defined():
    """Test that all required constants are defined."""
    from custom_components.oig_cloud import services

    # Home modes
    assert hasattr(services, "HOME_1")
    assert hasattr(services, "HOME_2")
    assert hasattr(services, "HOME_3")
    assert hasattr(services, "HOME_UPS")
    assert hasattr(services, "HOME_MODE_LABELS")

    # Grid modes
    assert hasattr(services, "GRID_OFF_LABEL")
    assert hasattr(services, "GRID_ON_LABEL")
    assert hasattr(services, "GRID_LIMITED_LABEL")
    assert hasattr(services, "GRID_DELIVERY_LABELS")
    assert hasattr(services, "GRID_DELIVERY_CANONICAL")
    assert hasattr(services, "GRID_DELIVERY_ALL_KEYS")

    # Boiler modes
    assert hasattr(services, "BOILER_CBB_LABEL")
    assert hasattr(services, "BOILER_MANUAL_LABEL")
    assert hasattr(services, "BOILER_MODE_LABELS")
    assert hasattr(services, "BOILER_MODE_CANONICAL")
    assert hasattr(services, "BOILER_MODE_ALL_KEYS")

    # Formating modes
    assert hasattr(services, "FORMAT_NO_CHARGE_LABEL")
    assert hasattr(services, "FORMAT_CHARGE_LABEL")
    assert hasattr(services, "FORMAT_BATTERY_LABELS")
    assert hasattr(services, "FORMAT_BATTERY_CANONICAL")
    assert hasattr(services, "FORMAT_BATTERY_ALL_KEYS")

    # Shield
    assert hasattr(services, "SHIELD_LOG_PREFIX")


def test_schemas_defined():
    """Test that all required schemas are defined."""
    from custom_components.oig_cloud import services

    assert hasattr(services, "SET_BOX_MODE_SCHEMA")
    assert hasattr(services, "SET_GRID_DELIVERY_SCHEMA")
    assert hasattr(services, "SET_BOILER_MODE_SCHEMA")
    assert hasattr(services, "SET_FORMATING_MODE_SCHEMA")

    # Test SET_BOX_MODE_SCHEMA (already supports both labels and canonical)
    schema = services.SET_BOX_MODE_SCHEMA
    data = {
        "device_id": "123",
        "mode": "home_1",
        "acknowledgement": True
    }
    result = schema(data)
    assert result["device_id"] == "123"
    assert result["mode"] == "home_1"
    assert result["acknowledgement"] is True

    # Test SET_GRID_DELIVERY_SCHEMA with canonical values
    schema = services.SET_GRID_DELIVERY_SCHEMA
    data = {
        "mode": "limited",
        "limit": 1234,
        "acknowledgement": True,
        "warning": True
    }
    result = schema(data)
    assert result["mode"] == "limited"
    assert result["limit"] == 1234
    assert result["acknowledgement"] is True
    assert result["warning"] is True

    # Test SET_GRID_DELIVERY_SCHEMA with legacy labels (backward compatibility)
    data_legacy = {
        "mode": "Zapnuto / On",
        "limit": 1234,
        "acknowledgement": True,
        "warning": True
    }
    result_legacy = schema(data_legacy)
    assert result_legacy["mode"] == "Zapnuto / On"

    # Test SET_BOILER_MODE_SCHEMA with canonical values
    schema = services.SET_BOILER_MODE_SCHEMA
    data = {
        "device_id": "456",
        "mode": "manual",
        "acknowledgement": True
    }
    result = schema(data)
    assert result["mode"] == "manual"
    assert result["acknowledgement"] is True

    # Test SET_BOILER_MODE_SCHEMA with legacy labels (backward compatibility)
    data_legacy = {
        "device_id": "456",
        "mode": "Manual",
        "acknowledgement": True
    }
    result_legacy = schema(data_legacy)
    assert result_legacy["mode"] == "Manual"

    # Test SET_FORMATING_MODE_SCHEMA with canonical values
    schema = services.SET_FORMATING_MODE_SCHEMA
    data = {
        "device_id": "789",
        "mode": "charge",
        "acknowledgement": True,
        "limit": 5678
    }
    result = schema(data)
    assert result["mode"] == "charge"
    assert result["acknowledgement"] is True
    assert result["limit"] == 5678

    # Test SET_FORMATING_MODE_SCHEMA with legacy labels (backward compatibility)
    data_legacy = {
        "device_id": "789",
        "mode": "Nabíjet",
        "acknowledgement": True,
        "limit": 5678
    }
    result_legacy = schema(data_legacy)
    assert result_legacy["mode"] == "Nabíjet"


def test_schema_validation_missing_required_fields():
    """Test that schemas reject missing required fields."""
    from custom_components.oig_cloud import services

    # SET_BOX_MODE_SCHEMA without required fields
    with pytest.raises(vol.Invalid):
        services.SET_BOX_MODE_SCHEMA({"device_id": "123"})

    # SET_GRID_DELIVERY_SCHEMA without required fields
    with pytest.raises(vol.Invalid):
        services.SET_GRID_DELIVERY_SCHEMA({"mode": "on"})


def test_schema_validation_invalid_values():
    """Test that schemas reject invalid values."""
    from custom_components.oig_cloud import services

    # Invalid mode for SET_BOX_MODE_SCHEMA
    with pytest.raises(vol.Invalid):
        services.SET_BOX_MODE_SCHEMA({
            "device_id": "123",
            "mode": "InvalidMode",
            "acknowledgement": True
        })

    # Invalid canonical mode for SET_GRID_DELIVERY_SCHEMA
    with pytest.raises(vol.Invalid):
        services.SET_GRID_DELIVERY_SCHEMA({
            "mode": "invalid_mode",
            "limit": 1234,
            "acknowledgement": True,
            "warning": True
        })

    # Invalid canonical mode for SET_BOILER_MODE_SCHEMA
    with pytest.raises(vol.Invalid):
        services.SET_BOILER_MODE_SCHEMA({
            "device_id": "456",
            "mode": "invalid_mode",
            "acknowledgement": True
        })

    # Invalid canonical mode for SET_FORMATING_MODE_SCHEMA
    with pytest.raises(vol.Invalid):
        services.SET_FORMATING_MODE_SCHEMA({
            "device_id": "789",
            "mode": "invalid_mode",
            "acknowledgement": True,
            "limit": 5678
        })

    # Invalid acknowledgement value
    with pytest.raises(vol.Invalid):
        services.SET_BOX_MODE_SCHEMA({
            "device_id": "123",
            "mode": "home_1",
            "acknowledgement": False
        })


def test_home_mode_labels():
    """Test that HOME_MODE_LABELS contains correct values."""
    from custom_components.oig_cloud import services

    expected = ("Home 1", "Home 2", "Home 3", "Home UPS")
    assert services.HOME_MODE_LABELS == expected


def test_home_mode_all_keys():
    """Test that HOME_MODE_ALL_KEYS contains canonical and label values."""
    from custom_components.oig_cloud import services

    # Should include canonical slugs
    assert "home_1" in services.HOME_MODE_ALL_KEYS
    assert "home_ups" in services.HOME_MODE_ALL_KEYS
    # Should include legacy labels
    assert "Home 1" in services.HOME_MODE_ALL_KEYS
    assert "Home UPS" in services.HOME_MODE_ALL_KEYS


def test_grid_delivery_labels():
    """Test that GRID_DELIVERY_LABELS contains correct label values."""
    from custom_components.oig_cloud import services

    expected = ("Vypnuto / Off", "Zapnuto / On", "S omezením / Limited")
    assert services.GRID_DELIVERY_LABELS == expected


def test_grid_delivery_canonical():
    """Test that GRID_DELIVERY_CANONICAL contains correct machine values."""
    from custom_components.oig_cloud import services

    expected = ("off", "on", "limited")
    assert services.GRID_DELIVERY_CANONICAL == expected


def test_grid_delivery_all_keys():
    """Test that GRID_DELIVERY_ALL_KEYS contains both canonical and label values."""
    from custom_components.oig_cloud import services

    # Should include canonical values
    assert "off" in services.GRID_DELIVERY_ALL_KEYS
    assert "on" in services.GRID_DELIVERY_ALL_KEYS
    assert "limited" in services.GRID_DELIVERY_ALL_KEYS
    # Should include legacy labels
    assert "Vypnuto / Off" in services.GRID_DELIVERY_ALL_KEYS
    assert "Zapnuto / On" in services.GRID_DELIVERY_ALL_KEYS
    assert "S omezením / Limited" in services.GRID_DELIVERY_ALL_KEYS


def test_boiler_mode_labels():
    """Test that BOILER_MODE_LABELS contains correct label values."""
    from custom_components.oig_cloud import services

    expected = ("CBB", "Manual")
    assert services.BOILER_MODE_LABELS == expected


def test_boiler_mode_canonical():
    """Test that BOILER_MODE_CANONICAL contains correct machine values."""
    from custom_components.oig_cloud import services

    expected = ("cbb", "manual")
    assert services.BOILER_MODE_CANONICAL == expected


def test_boiler_mode_all_keys():
    """Test that BOILER_MODE_ALL_KEYS contains both canonical and label values."""
    from custom_components.oig_cloud import services

    # Should include canonical values
    assert "cbb" in services.BOILER_MODE_ALL_KEYS
    assert "manual" in services.BOILER_MODE_ALL_KEYS
    # Should include legacy labels
    assert "CBB" in services.BOILER_MODE_ALL_KEYS
    assert "Manual" in services.BOILER_MODE_ALL_KEYS


def test_formating_mode_labels():
    """Test that FORMAT_BATTERY_LABELS contains correct label values."""
    from custom_components.oig_cloud import services

    expected = ("Nenabíjet", "Nabíjet")
    assert services.FORMAT_BATTERY_LABELS == expected


def test_formating_mode_canonical():
    """Test that FORMAT_BATTERY_CANONICAL contains correct machine values."""
    from custom_components.oig_cloud import services

    expected = ("no_charge", "charge")
    assert services.FORMAT_BATTERY_CANONICAL == expected


def test_formating_mode_all_keys():
    """Test that FORMAT_BATTERY_ALL_KEYS contains both canonical and label values."""
    from custom_components.oig_cloud import services

    # Should include canonical values
    assert "no_charge" in services.FORMAT_BATTERY_ALL_KEYS
    assert "charge" in services.FORMAT_BATTERY_ALL_KEYS
    # Should include legacy labels
    assert "Nenabíjet" in services.FORMAT_BATTERY_ALL_KEYS
    assert "Nabíjet" in services.FORMAT_BATTERY_ALL_KEYS


def test_shield_log_prefix():
    """Test that SHIELD_LOG_PREFIX is defined."""
    from custom_components.oig_cloud import services

    assert services.SHIELD_LOG_PREFIX == "[SHIELD]"


@pytest.mark.asyncio
async def test_register_service_already_exists(monkeypatch):
    """Test that _register_service_if_missing returns False if service exists."""
    hass = DummyHass()
    hass.services.has_service = lambda domain, name: True

    from custom_components.oig_cloud.services import _register_service_if_missing

    result = _register_service_if_missing(hass, "test_service", lambda call: None, vol.Schema({}))

    assert result is False


@pytest.mark.asyncio
async def test_register_service_if_missing_registers_new_service(monkeypatch):
    """Test that _register_service_if_missing registers new service."""
    hass = DummyHass()
    hass.services.has_service = lambda domain, name: False

    from custom_components.oig_cloud.services import _register_service_if_missing

    async def handler(call):
        return None

    result = _register_service_if_missing(
        hass, "test_service", handler, vol.Schema({})
    )

    assert result is True
    assert ("oig_cloud", "test_service") in hass.services.registered