from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.oig_cloud.boiler import coordinator as module
from custom_components.oig_cloud.boiler.models import BoilerProfile, EnergySource


class DummyState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class DummyStates:
    def __init__(self, data):
        self._data = data

    def get(self, entity_id):
        return self._data.get(entity_id)


class DummyHass:
    def __init__(self, states=None):
        self.states = DummyStates(states or {})
        self.data = {}


class DummyProfiler:
    def __init__(self, *args, **kwargs):
        self._profiles = []

    async def async_update_profiles(self):
        return self._profiles

    def get_profile_for_datetime(self, _dt):
        return BoilerProfile(category="test")


class DummyPlanner:
    def __init__(self, *args, **kwargs):
        self._overflow = []

    async def async_create_plan(self, **_kwargs):
        return SimpleNamespace(
            get_current_slot=lambda _now: SimpleNamespace(
                recommended_source=SimpleNamespace(value=EnergySource.GRID.value)
            )
        )

    async def async_get_overflow_windows(self, _data):
        return self._overflow


@pytest.mark.asyncio
async def test_async_update_data_success(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)
    monkeypatch.setattr(module, "validate_temperature_sensor", lambda *_a: 55.0)
    monkeypatch.setattr(
        module, "calculate_stratified_temp", lambda **_k: (55.0, 45.0)
    )
    monkeypatch.setattr(module, "calculate_energy_to_heat", lambda **_k: 1.23)

    hass = DummyHass(
        {
            "sensor.top": DummyState("55"),
            "sensor.bottom": DummyState("45"),
        }
    )
    config = {
        module.CONF_BOILER_TEMP_SENSOR_TOP: "sensor.top",
        module.CONF_BOILER_TEMP_SENSOR_BOTTOM: "sensor.bottom",
    }
    coordinator = module.BoilerCoordinator(hass, config)

    data = await coordinator._async_update_data()
    assert data["energy_state"]["energy_needed_kwh"] == 1.23
    assert data["charging_recommended"] is True


@pytest.mark.asyncio
async def test_async_update_data_error(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)

    hass = DummyHass()
    coordinator = module.BoilerCoordinator(hass, {})

    async def _boom():
        raise RuntimeError("fail")

    monkeypatch.setattr(coordinator, "_read_temperatures", _boom)

    with pytest.raises(module.UpdateFailed):
        await coordinator._async_update_data()


def test_should_update_profile():
    coordinator = module.BoilerCoordinator(DummyHass(), {})
    now = datetime(2025, 1, 1, 12, 0, 0)
    assert coordinator._should_update_profile(now) is True
    coordinator._last_profile_update = now
    assert coordinator._should_update_profile(now + timedelta(hours=1)) is False
    assert coordinator._should_update_profile(
        now + module.PROFILE_UPDATE_INTERVAL
    ) is True


@pytest.mark.asyncio
async def test_update_profile_error(monkeypatch):
    class BadProfiler(DummyProfiler):
        async def async_update_profiles(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(module, "BoilerProfiler", BadProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)

    coordinator = module.BoilerCoordinator(DummyHass(), {})
    await coordinator._update_profile()
    assert coordinator._current_profile is None


@pytest.mark.asyncio
async def test_read_temperatures_paths(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)
    monkeypatch.setattr(module, "validate_temperature_sensor", lambda *_a: 50.0)
    monkeypatch.setattr(
        module, "calculate_stratified_temp", lambda **_k: (52.0, 48.0)
    )

    hass = DummyHass({"sensor.top": DummyState("50")})
    config = {module.CONF_BOILER_TEMP_SENSOR_TOP: "sensor.top"}
    coordinator = module.BoilerCoordinator(hass, config)
    temps = await coordinator._read_temperatures()
    assert temps["upper_zone"] == 52.0


def test_calculate_energy_state(monkeypatch):
    monkeypatch.setattr(module, "calculate_energy_to_heat", lambda **_k: 2.0)
    coordinator = module.BoilerCoordinator(DummyHass(), {})
    temps = {"upper_zone": 60.0, "lower_zone": 40.0}
    energy = coordinator._calculate_energy_state(temps)
    assert energy["energy_needed_kwh"] == 2.0
    temps = {"upper_zone": None, "lower_zone": None}
    energy = coordinator._calculate_energy_state(temps)
    assert energy["avg_temp"] == 0.0


@pytest.mark.asyncio
async def test_track_energy_sources_variants(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)
    monkeypatch.setattr(module, "estimate_residual_energy", lambda *_a: 3.0)

    hass = DummyHass(
        {
            "sensor.oig_2206237016_boiler_manual_mode": DummyState("Zapnuto"),
            "sensor.oig_2206237016_boiler_current_cbb_w": DummyState("5"),
            "sensor.oig_2206237016_boiler_day_w": DummyState("1000"),
            "sensor.alt": DummyState("2000", {"unit_of_measurement": "Wh"}),
        }
    )
    config = {module.CONF_BOILER_ALT_ENERGY_SENSOR: "sensor.alt"}
    coordinator = module.BoilerCoordinator(hass, config)
    data = await coordinator._track_energy_sources()
    assert data["current_source"] == EnergySource.FVE.value
    assert data["total_kwh"] == 1.0
    assert data["alt_kwh"] == 2.0

    hass = DummyHass(
        {
            "sensor.oig_2206237016_boiler_current_cbb_w": DummyState("bad"),
            "sensor.oig_2206237016_boiler_day_w": DummyState("bad"),
        }
    )
    coordinator = module.BoilerCoordinator(hass, {})
    data = await coordinator._track_energy_sources()
    assert data["alt_kwh"] == 3.0


@pytest.mark.asyncio
async def test_update_plan_and_spot_prices(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)

    hass = DummyHass(
        {
            "sensor.spot": DummyState(
                "ok",
                {
                    "prices": [
                        {"datetime": "2025-01-01T00:00:00", "price": 2.0},
                        {"datetime": None, "price": 3.0},
                    ]
                },
            )
        }
    )
    config = {module.CONF_BOILER_SPOT_PRICE_SENSOR: "sensor.spot"}
    coordinator = module.BoilerCoordinator(hass, config)
    coordinator._current_profile = BoilerProfile(category="test")

    await coordinator._update_plan()
    assert coordinator._current_plan is not None

    prices = await coordinator._get_spot_prices()
    assert len(prices) == 1


@pytest.mark.asyncio
async def test_overflow_windows_missing_and_present(monkeypatch):
    monkeypatch.setattr(module, "BoilerProfiler", DummyProfiler)
    monkeypatch.setattr(module, "BoilerPlanner", DummyPlanner)

    coordinator = module.BoilerCoordinator(DummyHass(), {})
    assert await coordinator._get_overflow_windows() == []

    coordinator.hass.data = {
        "oig_cloud": {"battery_forecast_coordinator": SimpleNamespace(data={"x": 1})}
    }
    coordinator.planner._overflow = [(datetime(2025, 1, 1), datetime(2025, 1, 2))]
    windows = await coordinator._get_overflow_windows()
    assert windows
