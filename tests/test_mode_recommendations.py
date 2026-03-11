from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.oig_cloud.battery_forecast.planning import mode_recommendations
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_II,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
)


def _timeline_entry(time_str, mode, spot=2.0, solar=0.0, load=0.0):
    return {
        "time": time_str,
        "mode": mode,
        "mode_name": f"MODE_{mode}",
        "net_cost": 1.0,
        "solar_kwh": solar,
        "load_kwh": load,
        "spot_price": spot,
    }


def test_create_mode_recommendations_empty():
    assert (
        mode_recommendations.create_mode_recommendations(
            [],
            mode_home_i=CBB_MODE_HOME_I,
            mode_home_ii=CBB_MODE_HOME_II,
            mode_home_iii=CBB_MODE_HOME_III,
            mode_home_ups=CBB_MODE_HOME_UPS,
        )
        == []
    )


def test_create_mode_recommendations_invalid_time():
    now = datetime(2025, 1, 1, 10, 0, 0)
    timeline = [{"time": "bad", "mode": CBB_MODE_HOME_I, "mode_name": "Home 1"}]
    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs == []


def test_create_mode_recommendations_no_future_intervals():
    now = datetime(2025, 1, 2, 10, 0, 0)
    timeline = [
        _timeline_entry("2025-01-01T00:00:00", CBB_MODE_HOME_I),
    ]
    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs == []


def test_create_mode_recommendations_block_changes_and_split():
    now = datetime(2025, 1, 1, 23, 30, 0)
    timeline = [
        _timeline_entry("2025-01-01T23:45:00", CBB_MODE_HOME_I, solar=0.5, load=0.1),
        _timeline_entry("2025-01-02T00:00:00", CBB_MODE_HOME_II, spot=5.0),
    ]
    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs
    assert recs[0]["intervals_count"] >= 1


def test_create_mode_recommendations_bad_end_time(monkeypatch):
    now = datetime(2025, 1, 1, 10, 0, 0)
    timeline = [
        _timeline_entry("2025-01-01T10:00:00", CBB_MODE_HOME_I),
        _timeline_entry("2025-01-01T10:15:00", CBB_MODE_HOME_II),
    ]

    calls = {"count": 0}

    class DummyDateTime:
        max = datetime.max
        min = datetime.min

        @staticmethod
        def combine(date_val, time_val):
            return datetime.combine(date_val, time_val)

        @staticmethod
        def fromisoformat(value):
            if value == "2025-01-01T10:00:00":
                calls["count"] += 1
                if calls["count"] == 3:
                    raise ValueError("boom")
            return datetime.fromisoformat(value)

        @staticmethod
        def now():
            return datetime.now()

    monkeypatch.setattr(mode_recommendations, "datetime", DummyDateTime)

    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs


def test_create_mode_recommendations_final_block_parse_error(monkeypatch):
    now = datetime(2025, 1, 1, 10, 0, 0)
    timeline = [
        _timeline_entry("2025-01-01T10:00:00", CBB_MODE_HOME_I),
    ]

    calls = {"count": 0}

    class DummyDateTime:
        max = datetime.max
        min = datetime.min

        @staticmethod
        def combine(date_val, time_val):
            return datetime.combine(date_val, time_val)

        @staticmethod
        def fromisoformat(value):
            calls["count"] += 1
            if calls["count"] == 2:
                raise ValueError("boom")
            return datetime.fromisoformat(value)

        @staticmethod
        def now():
            return datetime.now()

    monkeypatch.setattr(mode_recommendations, "datetime", DummyDateTime)

    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs


def test_create_mode_recommendations_block_parse_error(monkeypatch):
    now = datetime(2025, 1, 1, 9, 0, 0)
    timeline = [
        _timeline_entry("2025-01-01T10:00:00", CBB_MODE_HOME_I),
        _timeline_entry("2025-01-01T10:15:00", CBB_MODE_HOME_II),
    ]

    calls = {"count": 0}

    class DummyDateTime:
        max = datetime.max
        min = datetime.min

        @staticmethod
        def combine(date_val, time_val):
            return datetime.combine(date_val, time_val)

        @staticmethod
        def fromisoformat(value):
            calls["count"] += 1
            if calls["count"] == 3:
                raise ValueError("boom")
            return datetime.fromisoformat(value)

        @staticmethod
        def now():
            return datetime.now()

    monkeypatch.setattr(mode_recommendations, "datetime", DummyDateTime)

    recs = mode_recommendations.create_mode_recommendations(
        timeline,
        now=now,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert recs


def test_add_block_details_modes():
    base = datetime(2025, 1, 1, 10, 0, 0)
    interval_time = base.isoformat()

    for mode, solar, load, price in [
        (CBB_MODE_HOME_I, 1.0, 0.1, 2.0),
        (CBB_MODE_HOME_II, 1.0, 0.1, 2.0),
        (CBB_MODE_HOME_III, 0.0, 0.5, 2.0),
        (CBB_MODE_HOME_UPS, 0.0, 0.0, 4.0),
        (99, 0.0, 0.0, 2.0),
    ]:
        block = {
            "mode": mode,
            "from_time": interval_time,
            "to_time": (base + timedelta(minutes=15)).isoformat(),
            "intervals_count": 1,
        }
        intervals = [_timeline_entry(interval_time, mode, spot=price, solar=solar, load=load)]
        mode_recommendations.add_block_details(
            block,
            intervals,
            mode_home_i=CBB_MODE_HOME_I,
            mode_home_ii=CBB_MODE_HOME_II,
            mode_home_iii=CBB_MODE_HOME_III,
            mode_home_ups=CBB_MODE_HOME_UPS,
        )
        assert "rationale" in block


def test_add_block_details_home_iii_solar():
    base = datetime(2025, 1, 1, 10, 0, 0)
    interval_time = base.isoformat()
    block = {
        "mode": CBB_MODE_HOME_III,
        "from_time": interval_time,
        "to_time": (base + timedelta(minutes=15)).isoformat(),
        "intervals_count": 1,
    }
    intervals = [
        _timeline_entry(interval_time, CBB_MODE_HOME_III, solar=0.3, load=0.0)
    ]
    mode_recommendations.add_block_details(
        block,
        intervals,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert "Maximální" in block["rationale"]


def test_add_block_details_ups_low_price():
    base = datetime(2025, 1, 1, 10, 0, 0)
    interval_time = base.isoformat()
    block = {
        "mode": CBB_MODE_HOME_UPS,
        "from_time": interval_time,
        "to_time": (base + timedelta(minutes=15)).isoformat(),
        "intervals_count": 1,
    }
    intervals = [
        _timeline_entry(interval_time, CBB_MODE_HOME_UPS, spot=2.5, solar=0.0, load=0.0)
    ]
    mode_recommendations.add_block_details(
        block,
        intervals,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert "velmi levný" in block["rationale"]


def test_add_block_details_fallbacks():
    block = {
        "mode": CBB_MODE_HOME_I,
        "from_time": "bad",
        "to_time": "bad",
        "intervals_count": 2,
    }
    mode_recommendations.add_block_details(
        block,
        [],
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert block["duration_hours"] == 0.5

    block = {
        "mode": CBB_MODE_HOME_I,
        "from_time": "2025-01-01T00:00:00",
        "to_time": "2025-01-01T00:15:00",
        "intervals_count": 1,
    }
    intervals = [_timeline_entry("2025-01-01T00:00:00", CBB_MODE_HOME_I, solar=0.0, load=0.0)]
    mode_recommendations.add_block_details(
        block,
        intervals,
        mode_home_i=CBB_MODE_HOME_I,
        mode_home_ii=CBB_MODE_HOME_II,
        mode_home_iii=CBB_MODE_HOME_III,
        mode_home_ups=CBB_MODE_HOME_UPS,
    )
    assert block["rationale"]
