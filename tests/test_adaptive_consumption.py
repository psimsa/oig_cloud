from datetime import datetime

import pytest

from custom_components.oig_cloud.battery_forecast.data.adaptive_consumption import (
    NO_PROFILE_LABEL,
    UNKNOWN_PROFILE_LABEL,
    AdaptiveConsumptionHelper,
)


def test_format_profile_description_strips_similarity() -> None:
    profile = {
        "ui": {
            "name": "Weekend (7 podobnych dnu, shoda 0.82)",
            "sample_count": 7,
            "similarity_score": 0.82,
        },
        "characteristics": {"season": "winter"},
    }

    assert (
        AdaptiveConsumptionHelper.format_profile_description(profile)
        == "Weekend (zimn\u00ed, 7 dn\u016f, shoda 0.82)"
    )


def test_format_profile_description_empty() -> None:
    assert (
        AdaptiveConsumptionHelper.format_profile_description(None) == NO_PROFILE_LABEL
    )


def test_calculate_consumption_summary_list_and_dict() -> None:
    helper = AdaptiveConsumptionHelper(None, "123")
    current_hour = datetime.now().hour

    today_profile = {"hourly_consumption": list(range(24)), "start_hour": 0}
    tomorrow_profile = {
        "hourly_consumption": {h: 1.0 for h in range(24)},
        "start_hour": 0,
    }

    summary = helper.calculate_consumption_summary(
        {"today_profile": today_profile, "tomorrow_profile": tomorrow_profile}
    )

    expected_today = sum(range(current_hour, 24))
    expected_tomorrow = 24.0

    assert summary["planned_consumption_today"] == round(expected_today, 1)
    assert summary["planned_consumption_tomorrow"] == round(expected_tomorrow, 1)
    assert summary["profile_today"] == UNKNOWN_PROFILE_LABEL
    assert summary["profile_tomorrow"] == UNKNOWN_PROFILE_LABEL


def test_process_adaptive_consumption_for_dashboard() -> None:
    helper = AdaptiveConsumptionHelper(None, "123")
    now = datetime.now()

    today_profile = {
        "hourly_consumption": [1.0] * 24,
        "start_hour": 0,
        "season": "summer",
        "day_count": 5,
    }

    adaptive_profiles = {
        "today_profile": today_profile,
        "profile_name": "Test profile",
        "match_score": 80,
    }

    timeline = [
        {
            "timestamp": now.isoformat() + "Z",
            "charging_kwh": 2.0,
            "spot_price_czk_per_kwh": 5.0,
        }
    ]

    result = helper.process_adaptive_consumption_for_dashboard(
        adaptive_profiles, timeline
    )

    expected_remaining = 24 - now.hour
    assert result["remaining_kwh"] == round(expected_remaining, 1)
    assert result["profile_name"] == "Test profile"
    assert (
        result["profile_details"]
        == "letn\u00ed, 5 podobn\u00fdch dn\u016f \u2022 80% shoda"
    )
    assert result["charging_cost_today"] == 10


def test_select_tomorrow_profile_transition() -> None:
    profiles = {
        "friday_to_saturday_winter_1": {"id": "transition"},
        "weekend_winter_typical": {"id": "weekend"},
    }
    current_time = datetime(2025, 1, 3, 12, 0)

    selected = AdaptiveConsumptionHelper.select_tomorrow_profile(profiles, current_time)
    assert selected == profiles["friday_to_saturday_winter_1"]


def test_select_tomorrow_profile_standard() -> None:
    profiles = {
        "weekday_summer_typical": {"id": "weekday"},
        "weekend_summer_typical": {"id": "weekend"},
    }
    current_time = datetime(2025, 7, 1, 12, 0)

    selected = AdaptiveConsumptionHelper.select_tomorrow_profile(profiles, current_time)
    assert selected == profiles["weekday_summer_typical"]
