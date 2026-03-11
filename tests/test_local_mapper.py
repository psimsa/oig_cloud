from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.core import local_mapper


def test_coerce_and_normalize_box_mode():
    assert local_mapper._coerce_number("10") == 10
    assert local_mapper._coerce_number("1.5") == 1.5
    assert local_mapper._coerce_number("unknown") is None

    assert local_mapper._normalize_box_mode(2) == 2
    assert local_mapper._normalize_box_mode("HOME 2") == 1
    assert local_mapper._normalize_box_mode("Home UPS") == 3
    assert local_mapper._normalize_box_mode("unknown") is None


def test_normalize_domains_and_value_map():
    assert local_mapper._normalize_domains("sensor") == ("sensor",)
    assert local_mapper._normalize_domains(["binary_sensor", "sensor"]) == (
        "binary_sensor",
        "sensor",
    )

    value_map = local_mapper._normalize_value_map({"On": 1, "Off": 0})
    assert value_map["on"] == 1
    assert local_mapper._apply_value_map("On", value_map) == 1
    assert local_mapper._apply_value_map("10", None) == 10


def test_as_utc():
    naive = datetime(2025, 1, 1, 12, 0, 0)
    aware = dt_util.as_local(naive)

    assert local_mapper._as_utc(naive).tzinfo is not None
    assert local_mapper._as_utc(aware).tzinfo is not None
