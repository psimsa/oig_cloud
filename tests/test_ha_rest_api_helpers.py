from __future__ import annotations

from types import SimpleNamespace

from custom_components.oig_cloud.api import ha_rest_api as api_module
from custom_components.oig_cloud.const import DOMAIN


class DummyConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, _domain):
        return self._entries


class DummyCoordinator:
    def __init__(self, data):
        self.data = data


class DummyHass:
    def __init__(self, entries, data):
        self.config_entries = DummyConfigEntries(entries)
        self.data = {DOMAIN: data}


def test_transform_timeline_for_api():
    timeline = [
        {"solar_production_kwh": 1.2, "consumption_kwh": 0.5, "grid_charge_kwh": 0.1},
        {"solar_kwh": 2.0, "load_kwh": 1.0},
    ]

    transformed = api_module._transform_timeline_for_api(timeline)

    assert transformed[0]["solar_kwh"] == 1.2
    assert transformed[0]["load_kwh"] == 0.5
    assert "solar_production_kwh" not in transformed[0]
    assert "consumption_kwh" not in transformed[0]

    assert transformed[1]["solar_kwh"] == 2.0
    assert transformed[1]["load_kwh"] == 1.0


def test_find_entry_for_box():
    entry1 = SimpleNamespace(entry_id="entry1")
    entry2 = SimpleNamespace(entry_id="entry2")

    data = {
        entry1.entry_id: {"coordinator": DummyCoordinator({"111": {}})},
        entry2.entry_id: {"coordinator": DummyCoordinator({"222": {}})},
    }

    hass = DummyHass([entry1, entry2], data)

    assert api_module._find_entry_for_box(hass, "222") == entry2
    assert api_module._find_entry_for_box(hass, "999") is None
