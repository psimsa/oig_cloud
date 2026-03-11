from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.oig_cloud import sensor as sensor_module
from custom_components.oig_cloud.const import DOMAIN


class DummyEntityRegistry:
    def __init__(self) -> None:
        self.removed = []

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)


def test_get_expected_sensor_types(monkeypatch):
    fake_types = {
        "base": {"sensor_type_category": "data"},
        "stats": {"sensor_type_category": "statistics"},
        "battery": {"sensor_type_category": "battery_prediction"},
        "pricing": {"sensor_type_category": "pricing"},
        "other": {"sensor_type_category": "chmu_warnings"},
    }
    monkeypatch.setattr(sensor_module, "SENSOR_TYPES", fake_types)

    entry = SimpleNamespace(
        entry_id="entry",
        options={
            "enable_battery_prediction": True,
            "enable_pricing": True,
            "enable_chmu_warnings": False,
        },
    )
    hass = SimpleNamespace(data={DOMAIN: {"entry": {"statistics_enabled": True}}})

    expected = sensor_module._get_expected_sensor_types(hass, entry)

    assert expected == {"base", "stats", "battery", "pricing"}


@pytest.mark.asyncio
async def test_cleanup_renamed_sensors(monkeypatch):
    entry = SimpleNamespace(entry_id="entry")
    expected = {"live_sensor"}
    registry = DummyEntityRegistry()

    entries = [
        SimpleNamespace(entity_id="sensor.oig_123_battery_prediction_test"),
        SimpleNamespace(entity_id="sensor.oig_123_live_sensor"),
        SimpleNamespace(entity_id="sensor.oig_123_old_stuff"),
        SimpleNamespace(entity_id="sensor.oig_bojler_mode"),
        SimpleNamespace(entity_id="switch.oig_123_other"),
    ]

    def _entries_for_config_entry(_entity_reg, _entry_id):
        return entries

    monkeypatch.setattr(
        "homeassistant.helpers.entity_registry.async_entries_for_config_entry",
        _entries_for_config_entry,
    )

    removed = await sensor_module._cleanup_renamed_sensors(
        registry, entry, expected
    )

    assert removed == 2
    assert "sensor.oig_123_battery_prediction_test" in registry.removed
    assert "sensor.oig_123_old_stuff" in registry.removed
