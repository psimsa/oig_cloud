from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.oig_cloud.config.steps import WizardMixin


def _schema_keys(schema: vol.Schema) -> set[str]:
    return {getattr(key, "schema", key) for key in schema.schema}


class DummyWizard(WizardMixin):
    def __init__(self) -> None:
        super().__init__()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    async def async_step_wizard_summary(self, user_input=None):
        return {"type": "summary", "data": dict(self._wizard_data)}

    async def async_step_wizard_welcome(self, user_input=None):
        return {"type": "welcome"}

    async def async_step_wizard_battery(self, user_input=None):
        return {"type": "battery"}

    def _get_next_step(self, _current_step: str) -> str:
        return "wizard_summary"


def _install_boiler_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("custom_components.oig_cloud.config.const")
    values = {
        "CONF_BOILER_ALT_COST_KWH": "boiler_alt_cost_kwh",
        "CONF_BOILER_ALT_ENERGY_SENSOR": "boiler_alt_energy_sensor",
        "CONF_BOILER_ALT_HEATER_SWITCH_ENTITY": "boiler_alt_heater_switch_entity",
        "CONF_BOILER_COLD_INLET_TEMP_C": "boiler_cold_inlet_temp_c",
        "CONF_BOILER_DEADLINE_TIME": "boiler_deadline_time",
        "CONF_BOILER_HAS_ALTERNATIVE_HEATING": "boiler_has_alternative_heating",
        "CONF_BOILER_HEATER_POWER_KW_ENTITY": "boiler_heater_power_kw_entity",
        "CONF_BOILER_HEATER_SWITCH_ENTITY": "boiler_heater_switch_entity",
        "CONF_BOILER_PLAN_SLOT_MINUTES": "boiler_plan_slot_minutes",
        "CONF_BOILER_PLANNING_HORIZON_HOURS": "boiler_planning_horizon_hours",
        "CONF_BOILER_SPOT_PRICE_SENSOR": "boiler_spot_price_sensor",
        "CONF_BOILER_STRATIFICATION_MODE": "boiler_stratification_mode",
        "CONF_BOILER_TARGET_TEMP_C": "boiler_target_temp_c",
        "CONF_BOILER_TEMP_SENSOR_BOTTOM": "boiler_temp_sensor_bottom",
        "CONF_BOILER_TEMP_SENSOR_POSITION": "boiler_temp_sensor_position",
        "CONF_BOILER_TEMP_SENSOR_TOP": "boiler_temp_sensor_top",
        "CONF_BOILER_TWO_ZONE_SPLIT_RATIO": "boiler_two_zone_split_ratio",
        "CONF_BOILER_VOLUME_L": "boiler_volume_l",
        "DEFAULT_BOILER_COLD_INLET_TEMP_C": 10.0,
        "DEFAULT_BOILER_DEADLINE_TIME": "08:00:00",
        "DEFAULT_BOILER_HEATER_POWER_KW_ENTITY": "sensor.boiler_power",
        "DEFAULT_BOILER_PLAN_SLOT_MINUTES": 30,
        "DEFAULT_BOILER_PLANNING_HORIZON_HOURS": 24,
        "DEFAULT_BOILER_STRATIFICATION_MODE": "single_zone",
        "DEFAULT_BOILER_TARGET_TEMP_C": 55.0,
        "DEFAULT_BOILER_TEMP_SENSOR_POSITION": "top",
        "DEFAULT_BOILER_TWO_ZONE_SPLIT_RATIO": 0.6,
    }
    for key, value in values.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, "custom_components.oig_cloud.config.const", module)


def test_get_defaults_migrates_legacy_pricing():
    flow = DummyWizard()
    flow.config_entry = SimpleNamespace(
        options={
            "spot_pricing_model": "percentage",
            "spot_positive_fee_percent": 12.0,
            "spot_negative_fee_percent": 5.0,
            "dual_tariff_enabled": False,
        }
    )

    defaults = flow._get_defaults()
    assert defaults["import_pricing_scenario"] == "spot_percentage_1tariff"


def test_pricing_distribution_schema_defaults_weekend_same():
    flow = DummyWizard()
    schema = flow._get_pricing_distribution_schema({"tariff_count": "dual"})
    keys = _schema_keys(schema)

    assert "tariff_weekend_same_as_weekday" in keys
    assert "tariff_vt_start_weekend" not in keys
    assert "tariff_nt_start_weekend" not in keys


@pytest.mark.asyncio
async def test_wizard_boiler_back_button_uses_history(monkeypatch):
    _install_boiler_constants(monkeypatch)
    flow = DummyWizard()
    flow._step_history = ["wizard_battery", "wizard_boiler"]

    result = await flow.async_step_wizard_boiler({"go_back": True})
    assert result["type"] == "battery"


@pytest.mark.asyncio
async def test_wizard_boiler_form_and_submit(monkeypatch):
    _install_boiler_constants(monkeypatch)
    flow = DummyWizard()

    result = await flow.async_step_wizard_boiler()
    assert result["type"] == "form"
    assert result["step_id"] == "wizard_boiler"

    submit = await flow.async_step_wizard_boiler({"boiler_volume_l": 150})
    assert submit["type"] == "summary"
    assert flow._wizard_data["boiler_volume_l"] == 150


def test_migrate_old_pricing_data_percentage_dual():
    data = {
        "spot_pricing_model": "percentage",
        "spot_positive_fee_percent": 12.0,
        "spot_negative_fee_percent": 5.0,
        "export_pricing_model": "percentage",
        "export_fee_percent": 7.0,
        "dual_tariff_enabled": True,
        "vt_hours_start": "6:00",
        "vt_hours_end": "22:00",
        "tariff_vt_start_weekday": "6",
        "tariff_nt_start_weekday": "22,2",
    }
    migrated = WizardMixin._migrate_old_pricing_data(data)

    assert migrated["import_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["import_spot_positive_fee_percent_vt"] == 12.0
    assert migrated["import_spot_negative_fee_percent_nt"] == 5.0
    assert migrated["export_pricing_scenario"] == "spot_percentage_2tariff"
    assert migrated["export_spot_fee_percent_nt"] == 7.0
    assert migrated["tariff_weekend_same_as_weekday"] is True


def test_migrate_old_pricing_data_fixed_single():
    data = {
        "spot_pricing_model": "fixed",
        "spot_fixed_fee_mwh": 700.0,
        "export_pricing_model": "fixed",
        "export_fixed_fee_czk": 0.33,
        "dual_tariff_enabled": False,
    }
    migrated = WizardMixin._migrate_old_pricing_data(data)

    assert migrated["import_pricing_scenario"] == "spot_fixed_1tariff"
    assert migrated["import_spot_fixed_fee_mwh"] == 700.0
    assert migrated["export_pricing_scenario"] == "spot_fixed_1tariff"
    assert migrated["export_spot_fixed_fee_czk"] == 0.33


def test_migrate_old_pricing_data_fixed_prices_dual():
    data = {
        "spot_pricing_model": "fixed_prices",
        "fixed_commercial_price_vt": 4.8,
        "fixed_commercial_price_nt": 3.1,
        "dual_tariff_enabled": True,
    }
    migrated = WizardMixin._migrate_old_pricing_data(data)

    assert migrated["import_pricing_scenario"] == "fix_2tariff"
    assert migrated["import_fixed_price_vt"] == 4.8
    assert migrated["import_fixed_price_nt"] == 3.1


def test_migrate_old_pricing_data_noop_for_new():
    data = {"import_pricing_scenario": "spot_percentage"}
    migrated = WizardMixin._migrate_old_pricing_data(data)
    assert migrated is data


def test_map_pricing_to_backend_spot_fixed_and_percentage_export():
    wizard_data = {
        "import_pricing_scenario": "spot_fixed",
        "spot_fixed_fee_kwh": 0.7,
        "export_pricing_scenario": "spot_percentage",
        "export_fee_percent": 8.0,
    }

    mapped = WizardMixin._map_pricing_to_backend(wizard_data)
    assert mapped["spot_pricing_model"] == "fixed"
    assert mapped["spot_fixed_fee_mwh"] == 700.0
    assert mapped["export_pricing_model"] == "percentage"
    assert mapped["export_fee_percent"] == 8.0


def test_map_pricing_to_backend_fix_price_import_and_export():
    wizard_data = {
        "import_pricing_scenario": "fix_price",
        "fixed_price_vt_kwh": 4.6,
        "fixed_price_nt_kwh": 3.2,
        "export_pricing_scenario": "fix_price",
        "export_fixed_price_kwh": 2.7,
    }

    mapped = WizardMixin._map_pricing_to_backend(wizard_data)
    assert mapped["spot_pricing_model"] == "fixed_prices"
    assert mapped["fixed_commercial_price_vt"] == 4.6
    assert mapped["fixed_commercial_price_nt"] == 3.2
    assert mapped["export_pricing_model"] == "fixed_prices"
    assert mapped["export_fixed_price"] == 2.7
