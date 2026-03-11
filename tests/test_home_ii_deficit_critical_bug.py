"""
HOME II mode behavior - critical bug validation.

BUG: HOME II při deficitu (solar < load) NESMÍ vybíjet baterii,
     deficit musí jít ZE SÍTĚ.
"""

import pytest

from tests.simulate_interval_standalone import (CBB_MODE_HOME_I,
                                                CBB_MODE_HOME_II,
                                                simulate_interval)


@pytest.fixture
def common_params():
    return {
        "capacity_kwh": 12.29,
        "hw_min_capacity_kwh": 2.458,  # 20%
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
        "home_charge_rate_kwh_15min": 0.7,  # 2.8kW
        "spot_price_czk": 4.0,
        "export_price_czk": 2.0,
    }


class TestHOMEIIDeficitBehavior:
    def test_home_ii_surplus_charges_battery(self, common_params):
        result = simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=3.0,
            load_kwh=1.5,
            battery_soc_kwh=5.0,
            **common_params,
        )

        assert result["battery_charge_kwh"] == pytest.approx(1.5, abs=0.01)
        assert result["grid_import_kwh"] == 0
        assert result["battery_discharge_kwh"] == 0

    def test_home_ii_deficit_uses_grid_NOT_battery(self, common_params):
        initial_soc = 5.0
        result = simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=1.0,
            load_kwh=2.5,
            battery_soc_kwh=initial_soc,
            **common_params,
        )

        assert result["battery_discharge_kwh"] == 0
        assert result["grid_import_kwh"] == pytest.approx(1.5, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(initial_soc, abs=0.01)
        assert result["battery_charge_kwh"] == 0
        assert result["grid_cost_czk"] == pytest.approx(1.5 * 4.0, abs=0.01)

    def test_home_ii_night_discharges_normally(self, common_params):
        params = dict(common_params)
        params["export_price_czk"] = 0.0
        result = simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.0,
            load_kwh=1.2,
            battery_soc_kwh=5.0,
            **params,
        )

        assert result["battery_discharge_kwh"] > 0

        available_battery = max(0.0, 5.0 - common_params["hw_min_capacity_kwh"])
        usable_from_battery = available_battery * common_params["discharge_efficiency"]
        expected_out = min(1.2, usable_from_battery)
        expected_discharge = expected_out / common_params["discharge_efficiency"]
        assert result["battery_discharge_kwh"] == pytest.approx(expected_discharge, abs=0.01)

    def test_home_ii_vs_home_i_deficit_difference(self, common_params):
        scenario = {
            "solar_kwh": 1.0,
            "load_kwh": 2.5,
            "battery_soc_kwh": 5.0,
        }

        result_home_i = simulate_interval(
            mode=CBB_MODE_HOME_I, **scenario, **common_params
        )
        result_home_ii = simulate_interval(
            mode=CBB_MODE_HOME_II, **scenario, **common_params
        )

        assert result_home_i["battery_discharge_kwh"] > 0
        assert result_home_ii["battery_discharge_kwh"] == 0
        assert result_home_ii["grid_import_kwh"] > result_home_i["grid_import_kwh"]
        assert result_home_ii["grid_cost_czk"] > result_home_i["grid_cost_czk"]
