from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.oig_cloud.battery_forecast.data import history as history_module
from custom_components.oig_cloud.battery_forecast.sensors.efficiency_sensor import (
    OigCloudBatteryEfficiencySensor,
)
from custom_components.oig_cloud.battery_forecast.types import CBB_MODE_HOME_II
from custom_components.oig_cloud.entities.computed_sensor import OigCloudComputedSensor


@pytest.mark.e2e
async def test_any_entity_change_updates_real_data_timestamp(e2e_setup, freezer):
    hass, entry = e2e_setup
    box_id = entry.options["box_id"]

    sensor = OigCloudComputedSensor(
        hass.data["oig_cloud"][entry.entry_id]["coordinator"], "real_data_update"
    )
    sensor.hass = hass

    freezer.move_to("2026-01-01 00:00:00+00:00")
    hass.states.async_set(f"sensor.oig_{box_id}_box_prms_mode", "Home 1")
    hass.states.async_set(
        f"sensor.oig_{box_id}_invertor_prms_to_grid", "Zapnuto / On"
    )
    hass.states.async_set(
        f"sensor.oig_{box_id}_invertor_prm1_p_max_feed_grid", "2000"
    )
    hass.states.async_set(f"sensor.oig_{box_id}_boiler_manual_mode", "Auto")
    hass.states.async_set(
        f"sensor.oig_{box_id}_device_lastcall", "2026-01-01T00:00:00+00:00"
    )
    first = sensor._state_real_data_update()
    assert first is not None

    freezer.move_to("2026-01-01 00:05:00+00:00")
    hass.states.async_set(f"sensor.oig_{box_id}_box_prms_mode", "Home 3")
    second = sensor._state_real_data_update()
    assert second is not None

    first_dt = dt_util.parse_datetime(first)
    second_dt = dt_util.parse_datetime(second)
    assert first_dt is not None
    assert second_dt is not None
    assert second_dt > first_dt


@pytest.mark.e2e
async def test_fetch_interval_from_history_mocked(e2e_setup, monkeypatch):
    hass, entry = e2e_setup
    box_id = entry.options["box_id"]

    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)

    def _state(value: float, ts: datetime) -> SimpleNamespace:
        return SimpleNamespace(state=str(value), last_updated=ts)

    history_states = {
        f"sensor.oig_{box_id}_ac_out_en_day": [
            _state(1000, start),
            _state(1500, end),
        ],
        f"sensor.oig_{box_id}_ac_in_ac_ad": [
            _state(200, start),
            _state(400, end),
        ],
        f"sensor.oig_{box_id}_ac_in_ac_pd": [
            _state(50, start),
            _state(150, end),
        ],
        f"sensor.oig_{box_id}_dc_in_fv_ad": [
            _state(300, start),
            _state(900, end),
        ],
        f"sensor.oig_{box_id}_batt_bat_c": [_state(60, end)],
        f"sensor.oig_{box_id}_box_prms_mode": [_state("Home 2", end)],
        f"sensor.oig_{box_id}_spot_price_current_15min": [_state(5.0, end)],
        f"sensor.oig_{box_id}_export_price_current_15min": [_state(2.0, end)],
    }

    def fake_get_significant_states(
        _hass, _start, _end, entity_ids, *_args, **_kwargs
    ):
        return {eid: history_states.get(eid, []) for eid in entity_ids}

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )

    # Mock get_instance to return a recorder that can execute jobs
    class MockRecorderInstance:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda hass: MockRecorderInstance(),
    )

    sensor = SimpleNamespace(
        _hass=hass,
        _box_id=box_id,
        _get_total_battery_capacity=lambda: 10.0,
    )

    result = await history_module.fetch_interval_from_history(sensor, start, end)
    assert result is not None
    assert result["consumption_kwh"] == pytest.approx(0.5)
    assert result["grid_import"] == pytest.approx(0.2)
    assert result["grid_export"] == pytest.approx(0.1)
    assert result["solar_kwh"] == pytest.approx(0.6)
    assert result["battery_kwh"] == pytest.approx(6.0)
    assert result["spot_price"] == pytest.approx(5.0)
    assert result["export_price"] == pytest.approx(2.0)
    assert result["net_cost"] == pytest.approx(0.8)
    assert result["mode"] == CBB_MODE_HOME_II


@pytest.mark.e2e
async def test_efficiency_history_load_mocked(e2e_setup, monkeypatch, freezer):
    hass, entry = e2e_setup
    box_id = entry.options["box_id"]

    freezer.move_to("2026-02-15 00:00:00")

    charge_sensor = f"sensor.oig_{box_id}_computed_batt_charge_energy_month"
    discharge_sensor = f"sensor.oig_{box_id}_computed_batt_discharge_energy_month"
    battery_sensor = f"sensor.oig_{box_id}_remaining_usable_capacity"

    def _state(value: float, ts: datetime) -> SimpleNamespace:
        return SimpleNamespace(state=str(value), last_updated=ts)

    def fake_get_significant_states(_hass, start, end, entity_ids, *_args, **_kwargs):
        history = {}
        if entity_ids == [battery_sensor]:
            history[battery_sensor] = [_state(10.0, start)]
            return history

        history[charge_sensor] = [_state(20000.0, end)]
        history[discharge_sensor] = [_state(15000.0, end)]
        history[battery_sensor] = [_state(12.0, end)]
        return history

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        fake_get_significant_states,
    )

    sensor = OigCloudBatteryEfficiencySensor(
        hass.data["oig_cloud"][entry.entry_id]["coordinator"],
        "battery_efficiency",
        entry,
        {"identifiers": {(f"oig_cloud", f"{box_id}_analytics")}},
        hass=hass,
    )
    sensor.hass = hass
    sensor.async_write_ha_state = Mock()

    now_local = dt_util.as_local(datetime(2026, 2, 15, tzinfo=timezone.utc))
    await sensor._finalize_last_month(now_local, force=True)

    assert sensor._last_month_metrics is not None
    assert sensor._last_month_metrics["efficiency_pct"] == pytest.approx(65.0)
    assert sensor._last_month_metrics["charge_kwh"] == pytest.approx(20.0)
    assert sensor._last_month_metrics["discharge_kwh"] == pytest.approx(15.0)
