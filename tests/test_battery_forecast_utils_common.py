from __future__ import annotations

from datetime import datetime

from custom_components.oig_cloud.battery_forecast import utils_common


def test_safe_nested_get_handles_none_and_non_dict():
    assert utils_common.safe_nested_get(None, "a", default="x") == "x"
    assert utils_common.safe_nested_get({"a": None}, "a", default=5) == 5
    assert utils_common.safe_nested_get({"a": "b"}, "a", "b", default=3) == 3


def test_parse_timeline_timestamp_invalid_and_naive():
    assert utils_common.parse_timeline_timestamp(None) is None
    assert utils_common.parse_timeline_timestamp("bad") is None

    parsed = utils_common.parse_timeline_timestamp("2025-01-01T12:00:00")
    assert parsed is not None


def test_format_time_label_variants():
    assert utils_common.format_time_label(None) == "--:--"

    label = utils_common.format_time_label("2025-01-01T12:00:00Z")
    assert ":" in label

    assert utils_common.format_time_label("not-a-date") == "not-a-date"


def test_parse_tariff_times_invalid():
    assert utils_common.parse_tariff_times("") == []
    assert utils_common.parse_tariff_times("x,1") == []


def test_get_tariff_for_datetime_variants():
    now = datetime(2025, 1, 1, 10, 0, 0)
    assert utils_common.get_tariff_for_datetime(now, {"dual_tariff_enabled": False}) == "VT"

    config = {
        "dual_tariff_enabled": True,
        "tariff_nt_start_weekday": "22",
        "tariff_vt_start_weekday": "6",
    }
    assert utils_common.get_tariff_for_datetime(now, config) == "VT"

    weekend = datetime(2025, 1, 4, 10, 0, 0)
    assert utils_common.get_tariff_for_datetime(weekend, config) == "NT"
