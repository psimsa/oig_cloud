"""Tests for computed_sensor and shield_sensor coverage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from custom_components.oig_cloud.sensor_types import SENSOR_TYPES

_EXTRA_SENSOR_TYPES = {
    "time_to_full": {
        "name": "Time to Full",
        "name_cs": "Čas do nabití",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": None,
    },
    "time_to_empty": {
        "name": "Time to Empty",
        "name_cs": "Čas do vybití",
        "device_class": None,
        "unit_of_measurement": None,
        "state_class": None,
    },
    "usable_battery_capacity": {
        "name": "Usable Battery Capacity",
        "name_cs": "Použitelná kapacita baterie",
        "device_class": None,
        "unit_of_measurement": "kWh",
        "state_class": None,
    },
    "missing_battery_kwh": {
        "name": "Missing Battery kWh",
        "name_cs": "Chybějící energie baterie",
        "device_class": None,
        "unit_of_measurement": "kWh",
        "state_class": None,
    },
    "remaining_usable_capacity": {
        "name": "Remaining Usable Capacity",
        "name_cs": "Zbývající použitelná kapacita",
        "device_class": None,
        "unit_of_measurement": "kWh",
        "state_class": None,
    },
    "computed_batt_charge_energy_today": {
        "name": "Battery Charge Energy Today",
        "name_cs": "Nabíjení baterie dnes",
        "device_class": None,
        "unit_of_measurement": "Wh",
        "state_class": None,
    },
    "computed_batt_discharge_energy_today": {
        "name": "Battery Discharge Energy Today",
        "name_cs": "Vybíjení baterie dnes",
        "device_class": None,
        "unit_of_measurement": "Wh",
        "state_class": None,
    },
    "computed_batt_charge_energy_month": {
        "name": "Battery Charge Energy Month",
        "name_cs": "Nabíjení baterie měsíc",
        "device_class": None,
        "unit_of_measurement": "Wh",
        "state_class": None,
    },
    "computed_batt_charge_energy_year": {
        "name": "Battery Charge Energy Year",
        "name_cs": "Nabíjení baterie rok",
        "device_class": None,
        "unit_of_measurement": "Wh",
        "state_class": None,
    },
    "ac_in_aci_wtotal": {
        "name": "AC In Total",
        "name_cs": "AC In Celkem",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
    "actual_aci_wtotal": {
        "name": "Actual ACI Total",
        "name_cs": "Aktuální ACI celkem",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
    "dc_in_fv_total": {
        "name": "DC In FV Total",
        "name_cs": "DC In FV celkem",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
    "actual_fv_total": {
        "name": "Actual FV Total",
        "name_cs": "Aktuální FV celkem",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
    "batt_batt_comp_p_charge": {
        "name": "Battery Charge Power",
        "name_cs": "Výkon nabíjení baterie",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
    "batt_batt_comp_p_discharge": {
        "name": "Battery Discharge Power",
        "name_cs": "Výkon vybíjení baterie",
        "device_class": None,
        "unit_of_measurement": "W",
        "state_class": None,
    },
}
SENSOR_TYPES.update(_EXTRA_SENSOR_TYPES)

from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor
from custom_components.oig_cloud.entities.shield_sensor import (
    OigCloudShieldSensor,
    _build_changes,
    _build_description,
    _build_queue_items,
    _build_running_requests,
    _build_shield_attrs,
    _build_targets,
    _compute_mode_reaction_time,
    _compute_shield_activity,
    _extract_param_type,
    _format_entity_display,
    _get_shield_state,
    _resolve_queue_meta,
    translate_shield_state,
)


class DummyCoordinator:
    def __init__(self, box_id: str = "1234567890"):
        self.forced_box_id = box_id
        self.hass = None
        self.data = {box_id: {"some": "data"}}
        self.config_entry = SimpleNamespace(
            entry_id="test_entry",
            options={"box_id": box_id},
            data={},
            title=f"OIG Cloud {box_id}",
        )

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


class DummyState:
    def __init__(self, state, last_updated=None, last_changed=None):
        self.state = state
        self.last_updated = last_updated or datetime.now(timezone.utc)
        self.last_changed = last_changed or self.last_updated


class DummyStates:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def get(self, entity_id):
        return self._mapping.get(entity_id)

    def async_all(self, domain):
        prefix = f"{domain}."
        states = []
        for eid, st in self._mapping.items():
            if eid.startswith(prefix):
                st.entity_id = eid
                states.append(st)
        return states


class DummyHass:
    def __init__(self, mapping=None):
        self.states = DummyStates(mapping)
        self.data = {"oig_cloud": {}}
        self.config = MagicMock()

    def async_create_task(self, coro):
        return MagicMock() if coro else None


def _make_computed_sensor(sensor_type: str, box_id: str = "1234567890"):
    coordinator = DummyCoordinator(box_id)
    return OigCloudComputedSensor(coordinator, sensor_type)


def _make_shield_sensor(sensor_type: str, box_id: str = "1234567890"):
    coordinator = DummyCoordinator(box_id)
    return OigCloudShieldSensor(coordinator, sensor_type)


# ---------------------------------------------------------------------------
# computed_sensor: _sum_three_phase / _sum_two_phase
# ---------------------------------------------------------------------------


def test_sum_three_phase_all_present():
    sensor = _make_computed_sensor("ac_in_aci_wtotal")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_ac_in_aci_wr": DummyState("100.0"),
            "sensor.oig_1234567890_ac_in_aci_ws": DummyState("200.0"),
            "sensor.oig_1234567890_ac_in_aci_wt": DummyState("300.0"),
        }
    )
    assert sensor._sum_three_phase("ac_in_aci") == 600.0


def test_sum_three_phase_missing_one():
    sensor = _make_computed_sensor("ac_in_aci_wtotal")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_ac_in_aci_wr": DummyState("100.0"),
            "sensor.oig_1234567890_ac_in_aci_wt": DummyState("300.0"),
        }
    )
    assert sensor._sum_three_phase("ac_in_aci") is None


def test_sum_two_phase_all_present():
    sensor = _make_computed_sensor("dc_in_fv_total")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_dc_in_fv_p1": DummyState("500.0"),
            "sensor.oig_1234567890_dc_in_fv_p2": DummyState("600.0"),
        }
    )
    assert sensor._sum_two_phase("dc_in_fv") == 1100.0


def test_sum_two_phase_missing_one():
    sensor = _make_computed_sensor("dc_in_fv_total")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_dc_in_fv_p1": DummyState("500.0"),
        }
    )
    assert sensor._sum_two_phase("dc_in_fv") is None


# ---------------------------------------------------------------------------
# computed_sensor: _format_time
# ---------------------------------------------------------------------------


def test_format_time_zero():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._format_time(0) == "N/A"


def test_format_time_negative():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._format_time(-1) == "N/A"


def test_format_time_minutes_only():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._format_time(0.5)  # 30 minutes
    assert result == "30 minut"
    assert sensor._attr_extra_state_attributes["minutes"] == 30


def test_format_time_hours_and_minutes():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._format_time(2.5)  # 2h 30m
    assert result == "2 hodin 30 minut"
    assert sensor._attr_extra_state_attributes["hours"] == 2


def test_format_time_one_day():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._format_time(25.0)  # 1d 1h
    assert "1 den" in result


def test_format_time_two_to_four_days():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._format_time(50.0)  # 2d 2h
    assert "2 dny" in result


def test_format_time_many_days():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._format_time(120.0)  # 5d
    assert "5 dnů" in result


# ---------------------------------------------------------------------------
# computed_sensor: boiler consumption
# ---------------------------------------------------------------------------


def test_get_boiler_consumption_from_entities_manual_mode():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_fv_p1": DummyState("1000"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("500"),
            "sensor.oig_1234567890_actual_aco_p": DummyState("2000"),
            "sensor.oig_1234567890_actual_aci_wr": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("0"),
            "sensor.oig_1234567890_boiler_install_power": DummyState("3000"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("on"),
        }
    )
    result = sensor._get_boiler_consumption_from_entities()
    assert result == 3000.0


def test_get_boiler_consumption_from_entities_auto_mode():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_fv_p1": DummyState("1000"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("500"),
            "sensor.oig_1234567890_actual_aco_p": DummyState("2000"),
            "sensor.oig_1234567890_actual_aci_wr": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("0"),
            "sensor.oig_1234567890_boiler_install_power": DummyState("3000"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._get_boiler_consumption_from_entities()
    # available = fv - load - export = 1500 - 2000 - 0 = -500, clamped to 0
    assert result == 0.0


def test_get_boiler_consumption_from_entities_with_export():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_fv_p1": DummyState("3000"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("2000"),
            "sensor.oig_1234567890_actual_aco_p": DummyState("2000"),
            "sensor.oig_1234567890_actual_aci_wr": DummyState("100"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("200"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("300"),
            "sensor.oig_1234567890_boiler_install_power": DummyState("3000"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._get_boiler_consumption_from_entities()
    # available = 5000 - 2000 - 600 = 2400, clamped to boiler_p_set=3000
    assert result == 2400.0


def test_get_boiler_consumption_wrong_sensor_type():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._get_boiler_consumption_from_entities()
    assert result is None


def test_get_boiler_consumption_legacy_wrapper():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_fv_p1": DummyState("0"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("0"),
            "sensor.oig_1234567890_actual_aco_p": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wr": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("0"),
            "sensor.oig_1234567890_boiler_install_power": DummyState("0"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._get_boiler_consumption({})
    assert result == 0.0


# ---------------------------------------------------------------------------
# computed_sensor: _state_box_mode_extended
# ---------------------------------------------------------------------------


def test_state_box_mode_extended_raw_0():
    sensor = _make_computed_sensor("box_mode_extended")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_box_prm2_app": DummyState("0")}
    )
    assert sensor._state_box_mode_extended() == "none"


def test_state_box_mode_extended_unavailable():
    sensor = _make_computed_sensor("box_mode_extended")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_box_prm2_app": DummyState("unavailable")}
    )
    assert sensor._state_box_mode_extended() == "unknown"


# ---------------------------------------------------------------------------
# computed_sensor: battery metrics helpers
# ---------------------------------------------------------------------------


def test_missing_capacity():
    sensor = _make_computed_sensor("usable_battery_capacity")
    assert sensor._missing_capacity(10000, 50) == 5000.0


def test_remaining_capacity():
    sensor = _make_computed_sensor("usable_battery_capacity")
    result = sensor._remaining_capacity(10000, 0.8, 50)
    # usable = 8000, missing = 5000, remaining = 3000
    assert result == 3000.0


def test_time_to_full_charging():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._time_to_full(5000, 1000) == "5 hodin 0 minut"


def test_time_to_full_already_full():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._time_to_full(0, 1000) == "N/A"


def test_time_to_full_discharging():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._time_to_full(5000, -100) == "Vybíjí se"


def test_time_to_empty_full_battery():
    sensor = _make_computed_sensor("time_to_empty")
    assert sensor._time_to_empty(1000, 100, -500) == "Nabito"


def test_time_to_empty_discharging():
    sensor = _make_computed_sensor("time_to_empty")
    assert sensor._time_to_empty(5000, 50, -1000) == "5 hodin 0 minut"


def test_time_to_empty_empty():
    sensor = _make_computed_sensor("time_to_empty")
    assert sensor._time_to_empty(0, 50, 100) == "Vybito"


def test_time_to_empty_charging():
    sensor = _make_computed_sensor("time_to_empty")
    assert sensor._time_to_empty(5000, 50, 100) == "Nabíjí se"


# ---------------------------------------------------------------------------
# computed_sensor: _state_battery_metrics
# ---------------------------------------------------------------------------


def test_state_battery_metrics_usable_capacity():
    sensor = _make_computed_sensor("usable_battery_capacity")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_installed_battery_capacity_kwh": DummyState("10"),
            "sensor.oig_1234567890_batt_bat_min": DummyState("20"),
            "sensor.oig_1234567890_batt_bat_c": DummyState("50"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
        }
    )
    result = sensor._state_battery_metrics()
    # (10 * 0.8) / 1000 = 0.008 -> round 2 = 0.01
    assert result == 0.01


def test_state_battery_metrics_missing_kwh():
    sensor = _make_computed_sensor("missing_battery_kwh")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_installed_battery_capacity_kwh": DummyState("10000"),
            "sensor.oig_1234567890_batt_bat_min": DummyState("20"),
            "sensor.oig_1234567890_batt_bat_c": DummyState("50"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
        }
    )
    result = sensor._state_battery_metrics()
    # missing = 10000 * (1 - 0.5) = 5000 -> /1000 = 5
    assert result == 5.0


def test_state_battery_metrics_remaining_usable():
    sensor = _make_computed_sensor("remaining_usable_capacity")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_installed_battery_capacity_kwh": DummyState("10000"),
            "sensor.oig_1234567890_batt_bat_min": DummyState("20"),
            "sensor.oig_1234567890_batt_bat_c": DummyState("50"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
        }
    )
    result = sensor._state_battery_metrics()
    # usable = 8000, missing = 5000, remaining = 3000 -> /1000 = 3
    assert result == 3.0


def test_state_battery_metrics_time_to_full():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_installed_battery_capacity_kwh": DummyState("10000"),
            "sensor.oig_1234567890_batt_bat_min": DummyState("20"),
            "sensor.oig_1234567890_batt_bat_c": DummyState("50"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
        }
    )
    result = sensor._state_battery_metrics()
    assert result == "5 hodin 0 minut"


def test_state_battery_metrics_time_to_empty():
    sensor = _make_computed_sensor("time_to_empty")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_installed_battery_capacity_kwh": DummyState("10000"),
            "sensor.oig_1234567890_batt_bat_min": DummyState("20"),
            "sensor.oig_1234567890_batt_bat_c": DummyState("50"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("-1000"),
        }
    )
    result = sensor._state_battery_metrics()
    assert result == "3 hodin 0 minut"


def test_state_battery_metrics_no_params():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass({})
    result = sensor._state_battery_metrics()
    assert result == "Nabito"


# ---------------------------------------------------------------------------
# computed_sensor: _state_batt_comp_charge / _state_batt_comp_discharge
# ---------------------------------------------------------------------------


def test_state_batt_comp_charge_positive():
    sensor = _make_computed_sensor("batt_batt_comp_p_charge")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": DummyState("1500")}
    )
    assert sensor._state_batt_comp_charge() == 1500.0


def test_state_batt_comp_charge_negative():
    sensor = _make_computed_sensor("batt_batt_comp_p_charge")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": DummyState("-1500")}
    )
    assert sensor._state_batt_comp_charge() == 0.0


def test_state_batt_comp_charge_none():
    sensor = _make_computed_sensor("batt_batt_comp_p_charge")
    sensor.hass = DummyHass({})
    assert sensor._state_batt_comp_charge() is None


def test_state_batt_comp_discharge_positive():
    sensor = _make_computed_sensor("batt_batt_comp_p_discharge")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": DummyState("1500")}
    )
    assert sensor._state_batt_comp_discharge() == 0.0


def test_state_batt_comp_discharge_negative():
    sensor = _make_computed_sensor("batt_batt_comp_p_discharge")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": DummyState("-1500")}
    )
    assert sensor._state_batt_comp_discharge() == 1500.0


def test_state_batt_comp_discharge_none():
    sensor = _make_computed_sensor("batt_batt_comp_p_discharge")
    sensor.hass = DummyHass({})
    assert sensor._state_batt_comp_discharge() is None


# ---------------------------------------------------------------------------
# computed_sensor: entity number / timestamp helpers
# ---------------------------------------------------------------------------


def test_get_entity_number_valid():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass({"sensor.test": DummyState("42.5")})
    assert sensor._get_entity_number("sensor.test") == 42.5


def test_get_entity_number_unavailable():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass({"sensor.test": DummyState("unavailable")})
    assert sensor._get_entity_number("sensor.test") is None


def test_get_entity_number_invalid():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass({"sensor.test": DummyState("not_a_number")})
    assert sensor._get_entity_number("sensor.test") is None


def test_get_entity_number_no_hass():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._get_entity_number("sensor.test") is None


def test_get_oig_number():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": DummyState("100")}
    )
    assert sensor._get_oig_number("batt_batt_comp_p") == 100.0


def test_get_oig_number_invalid_box():
    sensor = _make_computed_sensor("time_to_full", box_id="abc")
    assert sensor._get_oig_number("batt_batt_comp_p") is None


def test_normalize_timestamp():
    sensor = _make_computed_sensor("time_to_full")
    dt = datetime(2024, 1, 1, 12, 0, 0)
    result = sensor._normalize_timestamp(dt)
    assert result.tzinfo is not None


def test_parse_state_timestamp():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._parse_state_timestamp("2024-01-01T12:00:00+00:00")
    assert result is not None


def test_parse_state_timestamp_invalid():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._parse_state_timestamp("not-a-date")
    assert result is None


def test_get_entity_timestamp_from_state():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass(
        {"sensor.test": DummyState("2024-01-01T12:00:00+00:00")}
    )
    result = sensor._get_entity_timestamp("sensor.test")
    assert result is not None


def test_get_entity_timestamp_from_last_changed():
    sensor = _make_computed_sensor("time_to_full")
    sensor.hass = DummyHass({"sensor.test": DummyState("invalid-date")})
    result = sensor._get_entity_timestamp("sensor.test")
    assert result is not None


def test_get_entity_timestamp_no_hass():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._get_entity_timestamp("sensor.test") is None


# ---------------------------------------------------------------------------
# computed_sensor: _has_numeric_box
# ---------------------------------------------------------------------------


def test_has_numeric_box_true():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._has_numeric_box() is True


def test_has_numeric_box_false():
    sensor = _make_computed_sensor("time_to_full", box_id="unknown")
    assert sensor._has_numeric_box() is False


# ---------------------------------------------------------------------------
# computed_sensor: _get_box_prm2_app
# ---------------------------------------------------------------------------


def test_get_box_prm2_app_valid():
    sensor = _make_computed_sensor("box_mode_extended")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_box_prm2_app": DummyState("2")}
    )
    assert sensor._get_box_prm2_app() == 2.0


def test_get_box_prm2_app_empty():
    sensor = _make_computed_sensor("box_mode_extended")
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_box_prm2_app": DummyState("")}
    )
    assert sensor._get_box_prm2_app() is None


def test_get_box_prm2_app_invalid_box():
    sensor = _make_computed_sensor("box_mode_extended", box_id="abc")
    assert sensor._get_box_prm2_app() is None


# ---------------------------------------------------------------------------
# computed_sensor: _state_from_mapping
# ---------------------------------------------------------------------------


def test_state_from_mapping_real_data_update():
    sensor = _make_computed_sensor("real_data_update")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState(
                "100", last_changed=datetime.now(timezone.utc)
            ),
        }
    )
    result = sensor._state_from_mapping()
    assert result is not None


def test_state_from_mapping_computed_batt():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
            "sensor.oig_1234567890_actual_fv_p1": DummyState("500"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("500"),
        }
    )
    result = sensor._state_from_mapping()
    # First call initializes last_update, returns 0
    assert result is not None


# ---------------------------------------------------------------------------
# computed_sensor: energy accumulation
# ---------------------------------------------------------------------------


def test_get_energy_value_key():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    assert sensor._get_energy_value_key() == "charge_today"


def test_get_energy_value_key_unknown():
    sensor = _make_computed_sensor("time_to_full")
    assert sensor._get_energy_value_key() is None


def test_update_shared_energy_cache():
    from custom_components.oig_cloud.entities.computed_sensor import _energy_data_cache
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._update_shared_energy_cache()
    assert sensor._box_id in _energy_data_cache


def test_apply_charge_delta():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._apply_charge_delta(100.0, 3600.0, 1000.0, 2000.0)
    assert sensor._energy["charge_today"] == 100.0
    assert sensor._energy["charge_fve_today"] == 1000.0
    assert sensor._energy["charge_grid_today"] == 0.0


def test_apply_charge_delta_low_fv():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._apply_charge_delta(100.0, 3600.0, 1000.0, 10.0)
    assert sensor._energy["charge_fve_today"] == 0.0
    assert sensor._energy["charge_grid_today"] == 1000.0


def test_apply_discharge_delta():
    sensor = _make_computed_sensor("computed_batt_discharge_energy_today")
    sensor._apply_discharge_delta(50.0)
    assert sensor._energy["discharge_today"] == 50.0


def test_reset_energy_by_suffix():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._energy["charge_today"] = 100.0
    sensor._energy["charge_month"] = 200.0
    sensor._reset_energy_by_suffix("today")
    assert sensor._energy["charge_today"] == 0.0
    assert sensor._energy["charge_month"] == 200.0


# ---------------------------------------------------------------------------
# computed_sensor: _get_power_values
# ---------------------------------------------------------------------------


def test_get_power_values():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("1000"),
            "sensor.oig_1234567890_actual_fv_p1": DummyState("500"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("600"),
        }
    )
    result = sensor._get_power_values()
    assert result == (1000.0, 1100.0)


def test_get_power_values_no_batt():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor.hass = DummyHass({})
    assert sensor._get_power_values() is None


# ---------------------------------------------------------------------------
# computed_sensor: _iter_oig_states / _get_latest_oig_entity_update
# ---------------------------------------------------------------------------


def test_iter_oig_states():
    sensor = _make_computed_sensor("real_data_update")
    st1 = DummyState("100")
    st1.entity_id = "sensor.oig_1234567890_batt_batt_comp_p"
    st2 = DummyState("200")
    st2.entity_id = "sensor.oig_1234567890_actual_fv_p1"
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_batt_batt_comp_p": st1,
            "sensor.oig_1234567890_actual_fv_p1": st2,
        }
    )
    states = list(sensor._iter_oig_states("sensor", "1234567890"))
    assert len(states) == 2


def test_get_latest_oig_entity_update():
    sensor = _make_computed_sensor("real_data_update")
    now = datetime.now(timezone.utc)
    st1 = DummyState("100", last_changed=now - timedelta(minutes=5))
    st1.entity_id = "sensor.oig_1234567890_batt_batt_comp_p"
    st2 = DummyState("200", last_changed=now)
    st2.entity_id = "sensor.oig_1234567890_actual_fv_p1"
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_batt_batt_comp_p": st1,
            "sensor.oig_1234567890_actual_fv_p1": st2,
        }
    )
    result = sensor._get_latest_oig_entity_update()
    assert result is not None


# ---------------------------------------------------------------------------
# computed_sensor: _get_oig_last_updated
# ---------------------------------------------------------------------------


def test_get_oig_last_updated():
    sensor = _make_computed_sensor("real_data_update")
    now = datetime.now(timezone.utc)
    st = DummyState("100", last_changed=now)
    sensor.hass = DummyHass(
        {"sensor.oig_1234567890_batt_batt_comp_p": st}
    )
    result = sensor._get_oig_last_updated("batt_batt_comp_p")
    assert result is not None


def test_get_oig_last_updated_no_state():
    sensor = _make_computed_sensor("real_data_update")
    sensor.hass = DummyHass({})
    assert sensor._get_oig_last_updated("batt_batt_comp_p") is None


# ---------------------------------------------------------------------------
# computed_sensor: _is_boiler_manual
# ---------------------------------------------------------------------------


def test_is_boiler_manual_true():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("on"),
        }
    )
    assert sensor._is_boiler_manual() is True


def test_is_boiler_manual_manual_text():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("manual"),
        }
    )
    assert sensor._is_boiler_manual() is True


def test_is_boiler_manual_false():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    assert sensor._is_boiler_manual() is False


def test_is_boiler_manual_no_hass():
    sensor = _make_computed_sensor("boiler_current_w")
    assert sensor._is_boiler_manual() is False


# ---------------------------------------------------------------------------
# computed_sensor: _grid_export_power
# ---------------------------------------------------------------------------


def test_grid_export_power():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_aci_wr": DummyState("100"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("200"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("300"),
        }
    )
    assert sensor._grid_export_power() == 600.0


# ---------------------------------------------------------------------------
# computed_sensor: _compute_boiler_power
# ---------------------------------------------------------------------------


def test_compute_boiler_power_manual():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("on"),
        }
    )
    result = sensor._compute_boiler_power(
        boiler_p_set=3000, fv_power=5000, load_power=2000, export_power=0, bat_power=0
    )
    assert result == 3000


def test_compute_boiler_power_auto_no_bat():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._compute_boiler_power(
        boiler_p_set=3000, fv_power=5000, load_power=2000, export_power=0, bat_power=0
    )
    assert result == 3000


def test_compute_boiler_power_auto_with_bat():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._compute_boiler_power(
        boiler_p_set=3000, fv_power=5000, load_power=2000, export_power=0, bat_power=1000
    )
    assert result == 0.0


def test_compute_boiler_power_auto_negative_available():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor._compute_boiler_power(
        boiler_p_set=3000, fv_power=1000, load_power=2000, export_power=0, bat_power=0
    )
    assert result == 0.0


# ---------------------------------------------------------------------------
# computed_sensor: extra_state_attributes property
# ---------------------------------------------------------------------------


def test_extra_state_attributes():
    sensor = _make_computed_sensor("time_to_full")
    sensor._attr_extra_state_attributes = {"days": 0, "hours": 1, "minutes": 30}
    assert sensor.extra_state_attributes == {"days": 0, "hours": 1, "minutes": 30}


# ---------------------------------------------------------------------------
# computed_sensor: _get_energy_store
# ---------------------------------------------------------------------------


def test_get_energy_store():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor.hass = DummyHass({})
    store = sensor._get_energy_store()
    # Returns a Store object since hass is present
    assert store is not None


# ---------------------------------------------------------------------------
# computed_sensor: _get_batt_power_charge / _get_batt_power_discharge
# ---------------------------------------------------------------------------


def test_get_batt_power_charge():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._get_batt_power_charge({"actual": {"bat_p": "1500"}})
    assert result == 1500.0


def test_get_batt_power_charge_no_actual():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._get_batt_power_charge({})
    assert result == 0.0


def test_get_batt_power_discharge():
    sensor = _make_computed_sensor("time_to_full")
    result = sensor._get_batt_power_discharge({"actual": {"bat_p": "-1500"}})
    assert result == 1500.0


# ---------------------------------------------------------------------------
# computed_sensor: _check_for_real_data_changes / _extract_real_data_values
# ---------------------------------------------------------------------------


def test_check_for_real_data_changes():
    sensor = _make_computed_sensor("real_data_update")
    sensor._key_sensors = ["bat_p", "fv_p1"]
    sensor._monitored_sensors = {}
    result = sensor._check_for_real_data_changes(
        {"actual": {"bat_p": 100, "fv_p1": 200}}
    )
    assert result is True


def test_extract_real_data_values_no_actual():
    sensor = _make_computed_sensor("real_data_update")
    sensor._key_sensors = ["bat_p"]
    result = sensor._extract_real_data_values({})
    assert result is None


def test_detect_real_data_changes():
    sensor = _make_computed_sensor("real_data_update")
    sensor._monitored_sensors = {"bat_p": 100}
    result = sensor._detect_real_data_changes({"bat_p": 105})
    assert result is True


def test_detect_real_data_changes_no_change():
    sensor = _make_computed_sensor("real_data_update")
    sensor._monitored_sensors = {"bat_p": 100}
    result = sensor._detect_real_data_changes({"bat_p": 100.05})
    assert result is False


# ---------------------------------------------------------------------------
# computed_sensor: state property edge cases
# ---------------------------------------------------------------------------


def test_state_property_no_numeric_box():
    sensor = _make_computed_sensor("time_to_full", box_id="unknown")
    assert sensor.state is None


def test_state_property_boiler():
    sensor = _make_computed_sensor("boiler_current_w")
    sensor.hass = DummyHass(
        {
            "sensor.oig_1234567890_actual_fv_p1": DummyState("0"),
            "sensor.oig_1234567890_actual_fv_p2": DummyState("0"),
            "sensor.oig_1234567890_actual_aco_p": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wr": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_ws": DummyState("0"),
            "sensor.oig_1234567890_actual_aci_wt": DummyState("0"),
            "sensor.oig_1234567890_boiler_install_power": DummyState("0"),
            "sensor.oig_1234567890_batt_batt_comp_p": DummyState("0"),
            "sensor.oig_1234567890_boiler_manual_mode": DummyState("off"),
        }
    )
    result = sensor.state
    assert result is not None


# ---------------------------------------------------------------------------
# shield_sensor: _extract_param_type
# ---------------------------------------------------------------------------


def test_extract_param_type_limit():
    assert _extract_param_type("sensor.oig_123_p_max_feed_grid") == "limit"


def test_extract_param_type_mode_prms():
    assert _extract_param_type("sensor.oig_123_prms_to_grid") == "mode"


def test_extract_param_type_mode_box():
    assert _extract_param_type("sensor.oig_123_box_prms_mode") == "mode"


def test_extract_param_type_app():
    assert _extract_param_type("sensor.oig_123_box_prm2_app") == "app"


def test_extract_param_type_boiler():
    assert _extract_param_type("sensor.oig_123_boiler_manual_mode") == "mode"


def test_extract_param_type_formating():
    assert _extract_param_type("sensor.oig_123_formating_mode") == "level"


def test_extract_param_type_fallback():
    assert _extract_param_type("sensor.oig_123_unknown_sensor") == "value"


# ---------------------------------------------------------------------------
# shield_sensor: translate_shield_state
# ---------------------------------------------------------------------------


def test_translate_shield_state_known():
    assert translate_shield_state("active") == "aktivní"
    assert translate_shield_state("idle") == "nečinný"
    assert translate_shield_state("unknown") == "neznámý"


def test_translate_shield_state_unknown():
    assert translate_shield_state("nonexistent") == "nonexistent"


# ---------------------------------------------------------------------------
# shield_sensor: _get_shield_state
# ---------------------------------------------------------------------------


def test_get_shield_state_status():
    shield = MagicMock()
    assert _get_shield_state("service_shield_status", shield) == "aktivní"


def test_get_shield_state_queue():
    shield = MagicMock()
    shield.queue = [1, 2, 3]
    shield.pending = {"a": 1, "b": 2}
    assert _get_shield_state("service_shield_queue", shield) == 5


def test_get_shield_state_reaction_time():
    shield = MagicMock()
    shield.mode_tracker = MagicMock()
    shield.mode_tracker.get_statistics.return_value = {
        "s1": {"median_seconds": 10.0, "samples": 5},
        "s2": {"median_seconds": 20.0, "samples": 3},
    }
    result = _get_shield_state("mode_reaction_time", shield)
    assert result == 15.0


def test_get_shield_state_activity():
    shield = MagicMock()
    shield.running = "oig_cloud.set_box_mode"
    shield.pending = {}
    result = _get_shield_state("service_shield_activity", shield)
    assert result == "set_box_mode"


def test_get_shield_state_unknown():
    shield = MagicMock()
    assert _get_shield_state("unknown_sensor", shield) == "neznámý"


# ---------------------------------------------------------------------------
# shield_sensor: _compute_mode_reaction_time
# ---------------------------------------------------------------------------


def test_compute_mode_reaction_time_no_tracker():
    shield = MagicMock()
    shield.mode_tracker = None
    assert _compute_mode_reaction_time(shield) is None


def test_compute_mode_reaction_time_no_stats():
    shield = MagicMock()
    shield.mode_tracker.get_statistics.return_value = {}
    assert _compute_mode_reaction_time(shield) is None


def test_compute_mode_reaction_time_no_medians():
    shield = MagicMock()
    shield.mode_tracker.get_statistics.return_value = {"s1": {"samples": 5}}
    assert _compute_mode_reaction_time(shield) is None


# ---------------------------------------------------------------------------
# shield_sensor: _compute_shield_activity
# ---------------------------------------------------------------------------


def test_compute_shield_activity_idle():
    shield = MagicMock()
    shield.running = None
    assert _compute_shield_activity(shield) == "nečinný"


def test_compute_shield_activity_with_target():
    shield = MagicMock()
    shield.running = "oig_cloud.set_box_mode"
    shield.pending = {
        "oig_cloud.set_box_mode": {
            "entities": {"sensor.oig_123_box_prm2_app": "3"}
        }
    }
    result = _compute_shield_activity(shield)
    assert result == "set_box_mode: 3"


def test_compute_shield_activity_without_target():
    shield = MagicMock()
    shield.running = "oig_cloud.set_grid_delivery"
    shield.pending = {"oig_cloud.set_grid_delivery": {"entities": {}}}
    result = _compute_shield_activity(shield)
    assert result == "set_grid_delivery"


# ---------------------------------------------------------------------------
# shield_sensor: _build_shield_attrs
# ---------------------------------------------------------------------------


def test_build_shield_attrs_basic():
    shield = MagicMock()
    shield.queue = []
    shield.pending = {}
    shield.running = None
    shield.queue_metadata = {}
    hass = DummyHass({})
    result = _build_shield_attrs(hass, shield, sensor_type="service_shield_status")
    assert result["total_requests"] == 0
    assert result["queue_length"] == 0
    assert result["running_count"] == 0


def test_build_shield_attrs_with_reaction_time():
    shield = MagicMock()
    shield.queue = []
    shield.pending = {}
    shield.running = None
    shield.queue_metadata = {}
    shield.mode_tracker = MagicMock()
    shield.mode_tracker.get_statistics.return_value = {
        "s1": {"median_seconds": 10.0, "samples": 5}
    }
    hass = DummyHass({})
    result = _build_shield_attrs(hass, shield, sensor_type="mode_reaction_time")
    assert result["scenarios"] == {"s1": {"median_seconds": 10.0, "samples": 5}}
    assert result["total_samples"] == 5
    assert result["tracked_scenarios"] == 1


# ---------------------------------------------------------------------------
# shield_sensor: _build_running_requests
# ---------------------------------------------------------------------------


def test_build_running_requests():
    now = datetime.now()
    pending = {
        "oig_cloud.set_box_mode": {
            "entities": {"sensor.oig_123_box_prm2_app": "3"},
            "original_states": {"sensor.oig_123_box_prm2_app": "0"},
            "called_at": now,
            "params": {"_box_mode_step": "step1"},
        }
    }
    hass = DummyHass(
        {"sensor.oig_123_box_prm2_app": DummyState("2")}
    )
    result = _build_running_requests(hass, pending, "oig_cloud.set_box_mode")
    assert len(result) == 1
    assert result[0]["service"] == "set_box_mode"
    assert result[0]["is_primary"] is True
    assert result[0]["box_mode_step"] == "step1"


# ---------------------------------------------------------------------------
# shield_sensor: _build_queue_items
# ---------------------------------------------------------------------------


def test_build_queue_items():
    now = datetime.now()
    queue = [
        (
            "oig_cloud.set_box_mode",
            {"_box_mode_step": "step1"},
            {"sensor.oig_123_box_prm2_app": "3"},
        )
    ]
    queue_metadata = {
        ("oig_cloud.set_box_mode", str({"_box_mode_step": "step1"})): {
            "queued_at": now,
            "trace_id": "trace-123",
        }
    }
    hass = DummyHass(
        {"sensor.oig_123_box_prm2_app": DummyState("2")}
    )
    result = _build_queue_items(hass, queue, queue_metadata)
    assert len(result) == 1
    assert result[0]["position"] == 1
    assert result[0]["service"] == "set_box_mode"
    assert result[0]["trace_id"] == "trace-123"
    assert result[0]["box_mode_step"] == "step1"


# ---------------------------------------------------------------------------
# shield_sensor: _build_targets
# ---------------------------------------------------------------------------


def test_build_targets():
    hass = DummyHass(
        {"sensor.oig_123_box_prm2_app": DummyState("2")}
    )
    entities = {"sensor.oig_123_box_prm2_app": "3"}
    original_states = {"sensor.oig_123_box_prm2_app": "0"}
    result = _build_targets(hass, entities, original_states=original_states)
    assert len(result) == 1
    assert result[0]["param"] == "app"
    assert result[0]["value"] == "3"
    assert result[0]["from"] == "0"
    assert result[0]["to"] == "3"
    assert result[0]["current"] == "2"


def test_build_targets_no_original():
    hass = DummyHass(
        {"sensor.oig_123_box_prm2_app": DummyState("2")}
    )
    entities = {"sensor.oig_123_box_prm2_app": "3"}
    result = _build_targets(hass, entities, original_states=None)
    assert result[0]["from"] == "2"
    assert result[0]["current"] == "2"


# ---------------------------------------------------------------------------
# shield_sensor: _build_changes
# ---------------------------------------------------------------------------


def test_build_changes_with_current():
    targets = [
        {
            "entity_id": "sensor.oig_123_box_prm2_app",
            "from": "0",
            "to": "3",
            "current": "2",
        }
    ]
    result = _build_changes(targets, include_current=True)
    assert len(result) == 1
    assert "nyní" in result[0]


def test_build_changes_without_current():
    targets = [
        {
            "entity_id": "sensor.oig_123_box_prm2_app",
            "from": "0",
            "to": "3",
            "current": "2",
        }
    ]
    result = _build_changes(targets, include_current=False)
    assert len(result) == 1
    assert "nyní" not in result[0]


# ---------------------------------------------------------------------------
# shield_sensor: _format_entity_display
# ---------------------------------------------------------------------------


def test_format_entity_display_p_max():
    assert _format_entity_display("sensor.oig_123_p_max_feed_grid") == "123_p_max_feed_grid"


def test_format_entity_display_generic():
    assert _format_entity_display("sensor.oig_123_box_prm2_app") == "prm2_app"


def test_format_entity_display_no_underscore():
    assert _format_entity_display("sensor") == "sensor"


# ---------------------------------------------------------------------------
# shield_sensor: _build_description
# ---------------------------------------------------------------------------


def test_build_description_with_value():
    targets = [{"value": "3"}]
    result = _build_description("set_box_mode", targets, {})
    assert result == "set_box_mode: 3"


def test_build_description_with_grid_step():
    targets = [{"value": "3"}]
    result = _build_description("set_grid_delivery", targets, {"_grid_delivery_step": "step2"})
    assert result == "set_grid_delivery: 3 (step: step2)"


def test_build_description_with_box_mode_step():
    targets = [{"value": "3"}]
    result = _build_description("set_box_mode", targets, {"_box_mode_step": "step1"})
    assert result == "set_box_mode: 3 (step: step1)"


def test_build_description_no_targets():
    result = _build_description("set_box_mode", [], {})
    assert "Změna" in result


# ---------------------------------------------------------------------------
# shield_sensor: _resolve_queue_meta
# ---------------------------------------------------------------------------


def test_resolve_queue_meta_dict():
    now = datetime.now()
    queue_metadata = {
        ("svc", "params"): {"queued_at": now, "trace_id": "t1"}
    }
    result_dt, result_trace = _resolve_queue_meta(queue_metadata, "svc", "params")
    assert result_dt == now
    assert result_trace == "t1"


def test_resolve_queue_meta_string():
    queue_metadata = {("svc", "params"): "trace-123"}
    result_dt, result_trace = _resolve_queue_meta(queue_metadata, "svc", "params")
    assert result_dt is None
    assert result_trace == "trace-123"


def test_resolve_queue_meta_missing():
    result_dt, result_trace = _resolve_queue_meta({}, "svc", "params")
    assert result_dt is None
    assert result_trace is None


# ---------------------------------------------------------------------------
# shield_sensor: OigCloudShieldSensor class
# ---------------------------------------------------------------------------


def test_shield_sensor_init():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor._sensor_type == "service_shield_status"
    assert sensor._box_id == "1234567890"
    assert sensor.entity_id == "sensor.oig_1234567890_service_shield_status"


def test_shield_sensor_should_poll():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor.should_poll is False


def test_shield_sensor_name():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor.name == "Stav Service Shield"


def test_shield_sensor_icon():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor.icon == "mdi:shield"


def test_shield_sensor_unit_of_measurement():
    sensor = _make_shield_sensor("mode_reaction_time")
    assert sensor.unit_of_measurement == "s"


def test_shield_sensor_device_class():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor.device_class is None


def test_shield_sensor_unique_id():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor.unique_id == "oig_cloud_shield_1234567890_service_shield_status_v2"


def test_shield_sensor_device_info():
    sensor = _make_shield_sensor("service_shield_status")
    info = sensor.device_info
    assert info["name"] == "ServiceShield 1234567890"
    assert info["manufacturer"] == "OIG"


def test_shield_sensor_resolve_box_id():
    sensor = _make_shield_sensor("service_shield_status")
    assert sensor._resolve_box_id() == "1234567890"


def test_shield_sensor_available():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {"shield": MagicMock()}}
    assert sensor.available is True


def test_shield_sensor_not_available():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {}}
    assert sensor.available is False


def test_shield_sensor_state():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {"shield": MagicMock()}}
    result = sensor.state
    assert result == "aktivní"


def test_shield_sensor_state_unavailable():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    result = sensor.state
    assert result == "nedostupný"


def test_shield_sensor_extra_state_attributes():
    sensor = _make_shield_sensor("service_shield_status")
    shield = MagicMock()
    shield.queue = []
    shield.pending = {}
    shield.running = None
    shield.queue_metadata = {}
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {"shield": shield}}
    attrs = sensor.extra_state_attributes
    assert attrs["total_requests"] == 0


def test_shield_sensor_extra_state_attributes_no_shield():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {}}
    attrs = sensor.extra_state_attributes
    assert attrs == {}


# ---------------------------------------------------------------------------
# shield_sensor: async_added_to_hass / async_will_remove_from_hass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shield_sensor_async_added_to_hass():
    sensor = _make_shield_sensor("service_shield_status")
    shield = MagicMock()
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {"shield": shield}}
    await sensor.async_added_to_hass()
    assert sensor._shield_callback_registered is True
    shield.register_state_change_callback.assert_called_once()


@pytest.mark.asyncio
async def test_shield_sensor_async_will_remove_from_hass():
    sensor = _make_shield_sensor("service_shield_status")
    shield = MagicMock()
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {"shield": shield}}
    sensor._shield_callback_registered = True
    await sensor.async_will_remove_from_hass()
    assert sensor._shield_callback_registered is False
    shield.unregister_state_change_callback.assert_called_once()


@pytest.mark.asyncio
async def test_shield_sensor_async_added_no_shield():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.hass.data = {"oig_cloud": {}}
    await sensor.async_added_to_hass()
    assert sensor._shield_callback_registered is False


# ---------------------------------------------------------------------------
# shield_sensor: _on_shield_state_changed
# ---------------------------------------------------------------------------


def test_shield_sensor_on_state_changed():
    sensor = _make_shield_sensor("service_shield_status")
    sensor.hass = DummyHass({})
    sensor.schedule_update_ha_state = MagicMock()
    sensor._on_shield_state_changed()
    sensor.schedule_update_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# computed_sensor: _get_extended_fve_current
# ---------------------------------------------------------------------------


def test_get_extended_fve_current_1():
    sensor = _make_computed_sensor("time_to_full")
    coordinator = DummyCoordinator()
    coordinator.data = {
        "extended_fve_power_1": 1000,
        "extended_fve_voltage_1": 50,
    }
    result = sensor._get_extended_fve_current_1(coordinator)
    assert result == 20.0


def test_get_extended_fve_current_1_zero_voltage():
    sensor = _make_computed_sensor("time_to_full")
    coordinator = DummyCoordinator()
    coordinator.data = {
        "extended_fve_power_1": 1000,
        "extended_fve_voltage_1": 0,
    }
    result = sensor._get_extended_fve_current_1(coordinator)
    assert result == 0.0


def test_get_extended_fve_current_1_missing_key():
    sensor = _make_computed_sensor("time_to_full")
    coordinator = DummyCoordinator()
    coordinator.data = {}
    result = sensor._get_extended_fve_current_1(coordinator)
    assert result is None


def test_get_extended_fve_current_2():
    sensor = _make_computed_sensor("time_to_full")
    coordinator = DummyCoordinator()
    coordinator.data = {
        "extended_fve_power_2": 500,
        "extended_fve_voltage_2": 25,
    }
    result = sensor._get_extended_fve_current_2(coordinator)
    assert result == 20.0


# ---------------------------------------------------------------------------
# computed_sensor: _cancel_reset
# ---------------------------------------------------------------------------


def test_cancel_reset():
    sensor = _make_computed_sensor("time_to_full")
    unsub = MagicMock()
    sensor._daily_reset_unsub = unsub
    sensor._cancel_reset()
    assert sensor._daily_reset_unsub is None
    unsub.assert_called_once()


def test_cancel_reset_no_unsub():
    sensor = _make_computed_sensor("time_to_full")
    sensor._daily_reset_unsub = None
    sensor._cancel_reset()
    assert sensor._daily_reset_unsub is None


# ---------------------------------------------------------------------------
# computed_sensor: _max_energy_attribute / _restore_from_entity_state
# ---------------------------------------------------------------------------


def test_max_energy_attribute():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    attrs = {"charge_today": 100.0, "discharge_today": 50.0}
    assert sensor._max_energy_attribute(attrs) == 100.0


def test_max_energy_attribute_invalid():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    attrs = {"charge_today": "invalid", "discharge_today": 50.0}
    assert sensor._max_energy_attribute(attrs) == 50.0


def test_restore_from_entity_state():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    old_state = MagicMock()
    old_state.state = "42.5"
    assert sensor._restore_from_entity_state(old_state) == 42.5
    assert sensor._energy["charge_today"] == 42.5


def test_restore_from_entity_state_invalid():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    old_state = MagicMock()
    old_state.state = "invalid"
    assert sensor._restore_from_entity_state(old_state) == 0.0


# ---------------------------------------------------------------------------
# computed_sensor: _get_energy_value
# ---------------------------------------------------------------------------


def test_get_energy_value():
    from custom_components.oig_cloud.entities.computed_sensor import _energy_data_cache
    _energy_data_cache.pop("1234567890", None)
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._energy["charge_today"] = 123.456
    result = sensor._get_energy_value()
    assert result == 123.456


# ---------------------------------------------------------------------------
# computed_sensor: _maybe_schedule_energy_save
# ---------------------------------------------------------------------------


def test_maybe_schedule_energy_save_no_hass():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    sensor._maybe_schedule_energy_save()
    # Should not raise


# ---------------------------------------------------------------------------
# computed_sensor: _apply_energy_accumulation
# ---------------------------------------------------------------------------


def test_apply_energy_accumulation_charge():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    now = datetime.now(timezone.utc)
    last = now - timedelta(hours=1)
    sensor._apply_energy_accumulation(now, last, 1000.0, 2000.0)
    assert sensor._energy["charge_today"] > 0


def test_apply_energy_accumulation_discharge():
    sensor = _make_computed_sensor("computed_batt_discharge_energy_today")
    now = datetime.now(timezone.utc)
    last = now - timedelta(hours=1)
    sensor._apply_energy_accumulation(now, last, -1000.0, 0.0)
    assert sensor._energy["discharge_today"] > 0


# ---------------------------------------------------------------------------
# computed_sensor: _get_last_energy_update / _set_last_energy_update
# ---------------------------------------------------------------------------


def test_get_set_last_energy_update():
    sensor = _make_computed_sensor("computed_batt_charge_energy_today")
    now = datetime.now(timezone.utc)
    sensor._set_last_energy_update(now)
    assert sensor._get_last_energy_update() == now
