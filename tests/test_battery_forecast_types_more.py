from __future__ import annotations

from custom_components.oig_cloud.battery_forecast import types as types_module


def test_get_service_name_default():
    assert types_module.get_service_name(999) == "Home 3"


def test_mode_from_name_variants_and_default():
    assert types_module.mode_from_name("home ups") == types_module.CBB_MODE_HOME_UPS
    assert types_module.mode_from_name("HOMEIII") == types_module.CBB_MODE_HOME_III
    assert types_module.mode_from_name("HOME 1") == types_module.CBB_MODE_HOME_I
    assert types_module.mode_from_name("unknown") == types_module.CBB_MODE_HOME_III


def test_safe_nested_get_from_types():
    data = {"planned": {"net_cost": 1.2}}
    assert types_module.safe_nested_get(data, "planned", "net_cost", default=0) == 1.2
    assert types_module.safe_nested_get(data, "planned", "missing", default=5) == 5
    assert types_module.safe_nested_get(None, "planned", default=7) == 7
