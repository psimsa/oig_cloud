from custom_components.oig_cloud.battery_forecast.data import battery_state
from types import SimpleNamespace
from custom_components.oig_cloud.battery_forecast.types import (
    CBB_MODE_HOME_I,
    CBB_MODE_HOME_III,
    CBB_MODE_HOME_UPS,
    MODE_LABEL_HOME_I,
    MODE_LABEL_HOME_III,
    MODE_LABEL_HOME_UPS,
    SERVICE_MODE_HOME_1,
)


class DummySensor:
    def __init__(self, hass, config_entry=None):
        self._hass = hass
        self._box_id = "123"
        self._config_entry = config_entry

    def _log_rate_limited(self, *args, **kwargs):
        return None


def test_get_total_battery_capacity_installed(hass):
    hass.states.async_set(
        "sensor.oig_123_installed_battery_capacity_kwh",
        "8000",
    )
    sensor = DummySensor(hass)
    assert battery_state.get_total_battery_capacity(sensor) == 8.0


def test_get_total_battery_capacity_pv_data(hass):
    hass.states.async_set(
        "sensor.oig_123_installed_battery_capacity_kwh",
        "unknown",
    )
    hass.states.async_set(
        "sensor.oig_123_pv_data",
        "ok",
        {"data": {"box_prms": {"p_bat": 9000}}},
    )
    sensor = DummySensor(hass)
    assert battery_state.get_total_battery_capacity(sensor) == 9.0


def test_get_current_battery_capacity(hass):
    hass.states.async_set(
        "sensor.oig_123_installed_battery_capacity_kwh",
        "8000",
    )
    hass.states.async_set("sensor.oig_123_batt_bat_c", "50")
    sensor = DummySensor(hass)
    assert battery_state.get_current_battery_capacity(sensor) == 4.0


def test_total_capacity_fallbacks(hass):
    hass.states.async_set(
        "sensor.oig_123_installed_battery_capacity_kwh",
        "unknown",
    )
    hass.states.async_set(
        "sensor.oig_123_usable_battery_capacity",
        "6.4",
    )
    sensor = DummySensor(hass)
    assert battery_state.get_total_battery_capacity(sensor) == 8.0

    hass.states.async_set(
        "sensor.oig_123_usable_battery_capacity",
        "unknown",
    )
    assert battery_state.get_total_battery_capacity(sensor) is None

    sensor = DummySensor(None)
    assert battery_state.get_total_battery_capacity(sensor) is None


def test_read_state_float_branches(hass):
    sensor = DummySensor(None)
    assert battery_state._read_state_float(sensor, "sensor.x") is None

    hass.states.async_set("sensor.x", "unknown")
    sensor = DummySensor(hass)
    assert battery_state._read_state_float(sensor, "sensor.x") is None

    hass.states.async_set("sensor.x", "bad")
    assert battery_state._read_state_float(sensor, "sensor.x") is None


def test_capacity_from_pv_data_error(hass):
    hass.states.async_set(
        "sensor.oig_123_pv_data",
        "ok",
        {"data": {"box_prms": {"p_bat": "bad"}}},
    )
    sensor = DummySensor(hass)
    assert battery_state._get_capacity_from_pv_data(sensor) is None


def test_current_soc_percent(hass):
    sensor = DummySensor(None)
    assert battery_state.get_current_battery_soc_percent(sensor) is None

    sensor = DummySensor(hass)
    assert battery_state.get_current_battery_soc_percent(sensor) is None

    hass.states.async_set("sensor.oig_123_batt_bat_c", "55")
    assert battery_state.get_current_battery_soc_percent(sensor) == 55.0


def test_min_target_capacity(hass):
    hass.states.async_set(
        "sensor.oig_123_installed_battery_capacity_kwh",
        "9000",
    )

    class ConfigEntry:
        def __init__(self, options=None, data=None):
            self.options = options
            self.data = data or {}

    sensor = DummySensor(hass, config_entry=ConfigEntry(options={"min_capacity_percent": 20}))
    assert battery_state.get_min_battery_capacity(sensor) == 1.8

    sensor = DummySensor(hass, config_entry=ConfigEntry(options={"min_capacity_percent": None}))
    assert battery_state.get_min_battery_capacity(sensor) == 2.97

    sensor = DummySensor(hass, config_entry=ConfigEntry(options={}))
    assert battery_state.get_min_battery_capacity(sensor) == 2.97

    sensor = DummySensor(hass, config_entry=ConfigEntry(options={"target_capacity_percent": None}))
    assert battery_state.get_target_battery_capacity(sensor) == 7.2

    sensor = DummySensor(hass, config_entry=None)
    assert battery_state.get_min_battery_capacity(sensor) == 2.97
    assert battery_state.get_target_battery_capacity(sensor) == 7.2

    hass.states.async_set("sensor.oig_123_installed_battery_capacity_kwh", "unknown")
    sensor = DummySensor(hass, config_entry=None)
    assert battery_state.get_min_battery_capacity(sensor) is None
    assert battery_state.get_target_battery_capacity(sensor) is None


def test_current_capacity_missing(hass):
    sensor = DummySensor(hass)
    hass.states.async_set("sensor.oig_123_installed_battery_capacity_kwh", "unknown")
    hass.states.async_set("sensor.oig_123_batt_bat_c", "unknown")
    assert battery_state.get_current_battery_capacity(sensor) is None


def test_get_max_capacity(hass):
    hass.states.async_set("sensor.oig_123_installed_battery_capacity_kwh", "8000")
    sensor = DummySensor(hass)
    assert battery_state.get_max_battery_capacity(sensor) == 8.0


def test_battery_efficiency(hass):
    sensor = DummySensor(None)
    assert battery_state.get_battery_efficiency(sensor) == 0.882

    sensor = DummySensor(hass)
    hass.states.async_set("sensor.oig_123_battery_efficiency", "unknown")
    assert battery_state.get_battery_efficiency(sensor) == 0.882

    hass.states.async_set("sensor.oig_123_battery_efficiency", "50")
    assert battery_state.get_battery_efficiency(sensor) == 0.882

    hass.states.async_set("sensor.oig_123_battery_efficiency", "bad")
    assert battery_state.get_battery_efficiency(sensor) == 0.882

    hass.states.async_set("sensor.oig_123_battery_efficiency", "90")
    assert battery_state.get_battery_efficiency(sensor) == 0.9


def test_ac_charging_limit(hass):
    class ConfigEntry:
        def __init__(self, options=None):
            self.options = options

    sensor = DummySensor(hass, config_entry=ConfigEntry(options={"home_charge_rate": 4.0}))
    assert battery_state.get_ac_charging_limit_kwh_15min(sensor) == 1.0

    sensor = DummySensor(hass, config_entry=None)
    assert battery_state.get_ac_charging_limit_kwh_15min(sensor) == 0.7


def test_get_current_mode(hass):
    sensor = DummySensor(None)
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_III

    sensor = DummySensor(hass)
    hass.states.async_set("sensor.oig_123_box_prms_mode", "unknown")
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_III

    hass.states.async_set("sensor.oig_123_box_prms_mode", MODE_LABEL_HOME_I)
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_I

    hass.states.async_set("sensor.oig_123_box_prms_mode", MODE_LABEL_HOME_UPS)
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_UPS

    hass.states.async_set("sensor.oig_123_box_prms_mode", SERVICE_MODE_HOME_1)
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_I

    hass.states.async_set("sensor.oig_123_box_prms_mode", MODE_LABEL_HOME_III)
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_III

    hass.states.async_set("sensor.oig_123_box_prms_mode", "4")
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_I

    hass.states.async_set("sensor.oig_123_box_prms_mode", "99")
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_III

    hass.states.async_set("sensor.oig_123_box_prms_mode", "bad")
    assert battery_state.get_current_mode(sensor) == CBB_MODE_HOME_III

    class DummyState:
        def __init__(self, value):
            self.state = value

    sensor = DummySensor(SimpleNamespace(states=SimpleNamespace(get=lambda _eid: DummyState(2))))
    assert battery_state.get_current_mode(sensor) == 2


def test_get_boiler_available_capacity(hass):
    sensor = DummySensor(None)
    assert battery_state.get_boiler_available_capacity(sensor) == 0.0

    sensor = DummySensor(hass)
    hass.states.async_set("sensor.oig_123_boiler_is_use", "off")
    assert battery_state.get_boiler_available_capacity(sensor) == 0.0

    hass.states.async_set("sensor.oig_123_boiler_is_use", "on")
    assert battery_state.get_boiler_available_capacity(sensor) == 0.7

    hass.states.async_set("sensor.oig_123_boiler_install_power", "2.0")
    assert battery_state.get_boiler_available_capacity(sensor) == 0.5

    hass.states.async_set("sensor.oig_123_boiler_install_power", "bad")
    assert battery_state.get_boiler_available_capacity(sensor) == 0.7
