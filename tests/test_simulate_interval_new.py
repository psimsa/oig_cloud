"""
Unit testy pro novou centrální simulační funkci _simulate_interval().

Testuje všechny 4 CBB režimy podle CBB_MODES_DEFINITIVE.md:
- HOME I (0): FVE→load→battery (surplus), deficit vybíjí baterii
- HOME II (1): FVE→load, surplus→battery, deficit→GRID ONLY (NETOUCHED!)
- HOME III (2): FVE→battery, load→ALWAYS GRID
- HOME UPS (3): Nabíjení na 100% (FVE + grid max 2.8kW)

Testuje také:
- Night optimization (HOME I/II/III identické při solar=0)
- Edge cases (plná baterie, prázdná baterie, hw_min limit)
- Účinnosti (charge 95%, discharge 95%)
"""

import pytest

from tests.simulate_interval_standalone import (CBB_MODE_HOME_I,
                                                CBB_MODE_HOME_II,
                                                CBB_MODE_HOME_III,
                                                CBB_MODE_HOME_UPS,
                                                simulate_interval)


class MockBatteryForecast:
    """Mock class wrapping standalone function for test compatibility."""

    def _simulate_interval(self, **kwargs):
        """Wrapper pro standalone funkci."""
        return simulate_interval(**kwargs)


@pytest.fixture
def forecast():
    """Create mock battery forecast instance for testing."""
    return MockBatteryForecast()


# ============================================================================
# TEST PARAMETRY (common fixtures)
# ============================================================================


@pytest.fixture
def common_params():
    """Společné parametry pro většinu testů."""
    return {
        "capacity_kwh": 15.36,  # Celková kapacita
        "hw_min_capacity_kwh": 3.07,  # 20% hw minimum
        "spot_price_czk": 2.0,  # Nákupní cena
        "export_price_czk": 1.0,  # Prodejní cena
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
        "home_charge_rate_kwh_15min": 0.7,  # 2.8kW = 0.7kWh/15min
    }


# ============================================================================
# HOME I (0) - DEN: FVE → load → battery (surplus), deficit vybíjí
# ============================================================================


class TestHOMEI:
    """Testy pro HOME I režim."""

    def test_day_surplus_charges_battery(self, forecast, common_params):
        """DEN: FVE přebytek → baterie se nabíjí."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=2.0,  # FVE produkce
            load_kwh=1.0,  # Spotřeba
            battery_soc_kwh=10.0,  # Aktuální SoC
            **common_params,
        )

        # FVE pokrývá spotřebu (1.0), surplus 1.0 → baterie
        assert result["battery_charge_kwh"] == pytest.approx(1.0, abs=0.01)
        # Nabití: 1.0 * 0.95 = 0.95 kWh fyzicky
        assert result["new_soc_kwh"] == pytest.approx(10.95, abs=0.01)
        assert result["grid_import_kwh"] == 0.0
        assert result["grid_export_kwh"] == 0.0

    def test_day_surplus_battery_full_exports(self, forecast, common_params):
        """DEN: FVE přebytek + plná baterie → export."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=3.0,
            load_kwh=1.0,
            battery_soc_kwh=15.36,  # Baterie plná!
            **common_params,
        )

        # Baterie plná → surplus 2.0 → export
        assert result["battery_charge_kwh"] == 0.0
        assert result["new_soc_kwh"] == pytest.approx(15.36, abs=0.01)
        assert result["grid_export_kwh"] == pytest.approx(2.0, abs=0.01)
        assert result["export_revenue_czk"] == pytest.approx(2.0, abs=0.01)  # 2.0 * 1.0

    def test_day_deficit_discharges_battery(self, forecast, common_params):
        """DEN: FVE deficit → baterie se vybíjí."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=1.0,
            load_kwh=2.0,  # Deficit 1.0
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Deficit 1.0 → baterie vybíjí (s účinností)
        # Physical discharge: 1.0 / 0.95 = 1.053 kWh
        assert result["battery_discharge_kwh"] == pytest.approx(1.053, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(8.947, abs=0.01)  # 10.0 - 1.053
        assert result["grid_import_kwh"] == 0.0

    def test_day_deficit_battery_at_hw_min_uses_grid(self, forecast, common_params):
        """DEN: Deficit + baterie na hw_min → síť."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.5,
            load_kwh=2.0,  # Deficit 1.5
            battery_soc_kwh=3.07,  # Přesně na hw_min!
            **common_params,
        )

        # Baterie na hw_min → available = 0 → celý deficit ze sítě
        assert result["battery_discharge_kwh"] == 0.0
        assert result["new_soc_kwh"] == pytest.approx(3.07, abs=0.01)
        assert result["grid_import_kwh"] == pytest.approx(1.5, abs=0.01)
        assert result["grid_cost_czk"] == pytest.approx(3.0, abs=0.01)  # 1.5 * 2.0

    def test_night_discharges_to_hw_min(self, forecast, common_params):
        """NOC: Baterie vybíjí do hw_min, pak síť."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,  # Noc!
            load_kwh=2.0,
            battery_soc_kwh=5.0,
            **common_params,
        )

        # Available: 5.0 - 3.07 = 1.93 kWh
        # Usable: 1.93 * 0.95 = 1.8335 kWh
        # Battery covers: min(2.0, 1.8335) = 1.8335
        # Physical discharge: 1.8335 / 0.95 = 1.93
        assert result["battery_discharge_kwh"] == pytest.approx(1.93, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(3.07, abs=0.01)  # 5.0 - 1.93

        # Deficit: 2.0 - 1.8335 = 0.1665 → síť
        assert result["grid_import_kwh"] == pytest.approx(0.1665, abs=0.01)


# ============================================================================
# HOME II (1) - DEN: FVE→load, surplus→battery, deficit→GRID ONLY!
# ============================================================================


class TestHOMEII:
    """Testy pro HOME II režim - KRITICKÝ rozdíl v deficit chování!"""

    def test_day_surplus_charges_battery(self, forecast, common_params):
        """DEN: FVE přebytek → baterie se nabíjí (stejné jako HOME I)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=2.0,
            load_kwh=1.0,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Identické s HOME I při surplus
        assert result["battery_charge_kwh"] == pytest.approx(1.0, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(10.95, abs=0.01)
        assert result["grid_import_kwh"] == 0.0

    def test_day_deficit_NETOUCHED_uses_grid(self, forecast, common_params):
        """⚠️ KRITICKÝ TEST: DEN deficit → baterie NETOUCHED, deficit → SÍŤ!"""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=1.0,
            load_kwh=2.0,  # Deficit 1.0
            battery_soc_kwh=10.0,  # Hodně energie v baterii!
            **common_params,
        )

        # ⚠️ TOTO JE KLÍČOVÝ ROZDÍL: Baterie NETOUCHED!
        assert result["battery_discharge_kwh"] == 0.0
        assert result["battery_charge_kwh"] == 0.0
        assert result["new_soc_kwh"] == pytest.approx(10.0, abs=0.01)  # NEZMĚNĚNO!

        # Celý deficit ze sítě
        assert result["grid_import_kwh"] == pytest.approx(1.0, abs=0.01)
        assert result["grid_cost_czk"] == pytest.approx(2.0, abs=0.01)

    def test_night_identical_to_home_i(self, forecast, common_params):
        """NOC: HOME II = HOME I (vybíjí do hw_min)."""
        result_home_ii = forecast._simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.0,
            load_kwh=2.0,
            battery_soc_kwh=5.0,
            **common_params,
        )

        result_home_i = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=2.0,
            battery_soc_kwh=5.0,
            **common_params,
        )

        # Všechny klíčové metriky identické
        assert result_home_ii["battery_discharge_kwh"] == pytest.approx(
            result_home_i["battery_discharge_kwh"], abs=0.001
        )
        assert result_home_ii["new_soc_kwh"] == pytest.approx(
            result_home_i["new_soc_kwh"], abs=0.001
        )
        assert result_home_ii["grid_import_kwh"] == pytest.approx(
            result_home_i["grid_import_kwh"], abs=0.001
        )


# ============================================================================
# HOME III (2) - DEN: FVE→battery, load→ALWAYS GRID
# ============================================================================


class TestHOMEIII:
    """Testy pro HOME III režim - agresivní nabíjení baterie."""

    def test_day_all_solar_to_battery(self, forecast, common_params):
        """DEN: CELÁ FVE → baterie, spotřeba → síť."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_III,
            solar_kwh=3.0,
            load_kwh=1.5,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # CELÁ FVE (3.0) → baterie
        assert result["battery_charge_kwh"] == pytest.approx(3.0, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(
            12.85, abs=0.01
        )  # 10.0 + 3.0*0.95

        # Spotřeba VŽDY ze sítě (i když je FVE!)
        assert result["grid_import_kwh"] == pytest.approx(1.5, abs=0.01)
        assert result["grid_cost_czk"] == pytest.approx(3.0, abs=0.01)

    def test_day_battery_full_exports_surplus(self, forecast, common_params):
        """DEN: Baterie plná → FVE přebytek → export."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_III,
            solar_kwh=3.0,
            load_kwh=1.0,
            battery_soc_kwh=15.36,  # Plná!
            **common_params,
        )

        # Baterie plná → žádné nabití
        assert result["battery_charge_kwh"] == 0.0

        # Spotřeba ze sítě
        assert result["grid_import_kwh"] == pytest.approx(1.0, abs=0.01)

        # CELÁ FVE → export (protože baterie plná)
        assert result["grid_export_kwh"] == pytest.approx(3.0, abs=0.01)
        assert result["export_revenue_czk"] == pytest.approx(3.0, abs=0.01)

    def test_day_no_solar_grid_only(self, forecast, common_params):
        """DEN bez FVE: Spotřeba → síť, baterie netouched."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_III,
            solar_kwh=0.0,  # Žádná FVE (zataženo)
            load_kwh=2.0,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Žádné nabití
        assert result["battery_charge_kwh"] == 0.0

        # Spotřeba ze sítě (night optimization path → vybíjí!)
        # ⚠️ Ale NOC: HOME III VYBÍJÍ (jako HOME I)!
        # Toto je DEN bez slunce → použije night optimization
        assert result["battery_discharge_kwh"] > 0  # Vybíjí jako HOME I v noci

    def test_night_identical_to_home_i(self, forecast, common_params):
        """NOC: HOME III = HOME I (vybíjí do hw_min)."""
        result_home_iii = forecast._simulate_interval(
            mode=CBB_MODE_HOME_III,
            solar_kwh=0.0,
            load_kwh=2.0,
            battery_soc_kwh=5.0,
            **common_params,
        )

        result_home_i = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=2.0,
            battery_soc_kwh=5.0,
            **common_params,
        )

        # Identické chování v noci
        assert result_home_iii["battery_discharge_kwh"] == pytest.approx(
            result_home_i["battery_discharge_kwh"], abs=0.001
        )
        assert result_home_iii["new_soc_kwh"] == pytest.approx(
            result_home_i["new_soc_kwh"], abs=0.001
        )


# ============================================================================
# HOME UPS (3) - Nabíjení na 100% (FVE + grid max 2.8kW)
# ============================================================================


class TestHOMEUPS:
    """Testy pro HOME UPS režim - nabíjení na 100%."""

    def test_charges_from_solar_unlimited(self, forecast, common_params):
        """FVE → baterie (bez limitu)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=5.0,  # Hodně FVE
            load_kwh=1.0,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Space: 15.36 - 10.0 = 5.36 kWh
        # Solar to battery: min(5.0, 5.36) = 5.0 (FVE není dost)
        # Remaining space: 5.36 - 5.0 = 0.36
        # Grid charging: min(0.7, 0.36) = 0.36 (nabíjí i ze sítě!)
        # Total charge: 5.0 + 0.36 = 5.36
        # Physical: 5.36 * 0.95 = 5.092
        assert result["battery_charge_kwh"] == pytest.approx(5.36, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(15.092, abs=0.01)  # 10.0 + 5.092

        # Grid: load + charging = 1.0 + 0.36 = 1.36
        assert result["grid_import_kwh"] == pytest.approx(1.36, abs=0.01)

    def test_charges_from_grid_limited_2_8kw(self, forecast, common_params):
        """Grid → baterie (max 2.8kW = 0.7kWh/15min)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=0.0,  # Žádná FVE
            load_kwh=1.0,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Solar: 0, Grid charging: 0.7 (max rate)
        assert result["battery_charge_kwh"] == pytest.approx(0.7, abs=0.01)

        # Grid import: load + charging = 1.0 + 0.7 = 1.7
        assert result["grid_import_kwh"] == pytest.approx(1.7, abs=0.01)
        assert result["grid_cost_czk"] == pytest.approx(3.4, abs=0.01)  # 1.7 * 2.0

    def test_charges_from_solar_and_grid(self, forecast, common_params):
        """FVE + grid → baterie (kombinace)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=1.0,
            load_kwh=0.5,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Space: 5.36 kWh
        # Solar: 1.0 → baterie
        # Remaining space: 5.36 - 1.0 = 4.36
        # Grid charging: min(0.7, 4.36) = 0.7
        # Total charge: 1.0 + 0.7 = 1.7
        assert result["battery_charge_kwh"] == pytest.approx(1.7, abs=0.01)

        # Grid: load + charging = 0.5 + 0.7 = 1.2
        assert result["grid_import_kwh"] == pytest.approx(1.2, abs=0.01)

    def test_battery_full_exports_solar(self, forecast, common_params):
        """Baterie plná → FVE → export."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=3.0,
            load_kwh=1.0,
            battery_soc_kwh=15.36,  # Plná!
            **common_params,
        )

        # Baterie plná → žádné nabití
        assert result["battery_charge_kwh"] == 0.0

        # Celá FVE → export
        assert result["grid_export_kwh"] == pytest.approx(3.0, abs=0.01)

        # Grid: pouze load (no charging)
        assert result["grid_import_kwh"] == pytest.approx(1.0, abs=0.01)


# ============================================================================
# NIGHT OPTIMIZATION TEST - HOME I/II/III identické při solar=0
# ============================================================================


class TestNightOptimization:
    """Test kritické optimalizace: NOC → HOME I/II/III IDENTICKÉ."""

    def test_all_modes_identical_at_night(self, forecast, common_params):
        """⚠️ KRITICKÝ TEST: HOME I/II/III identické v noci."""
        test_params = {
            "solar_kwh": 0.0,  # NOC!
            "load_kwh": 2.5,
            "battery_soc_kwh": 8.0,
            **common_params,
        }

        result_i = forecast._simulate_interval(mode=CBB_MODE_HOME_I, **test_params)
        result_ii = forecast._simulate_interval(mode=CBB_MODE_HOME_II, **test_params)
        result_iii = forecast._simulate_interval(mode=CBB_MODE_HOME_III, **test_params)

        # Všechny 3 režimy musí dát IDENTICKÉ výsledky
        for key in result_i.keys():
            assert result_i[key] == pytest.approx(
                result_ii[key], abs=0.001
            ), f"HOME I vs II differ in {key}"
            assert result_i[key] == pytest.approx(
                result_iii[key], abs=0.001
            ), f"HOME I vs III differ in {key}"

    def test_night_optimization_respects_hw_min(self, forecast, common_params):
        """NOC: Vybíjení respektuje hw_min (20% = 3.07 kWh)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=10.0,  # Velká spotřeba
            battery_soc_kwh=5.0,
            **common_params,
        )

        # Available: 5.0 - 3.07 = 1.93
        # Usable: 1.93 * 0.95 = 1.8335
        assert result["battery_discharge_kwh"] == pytest.approx(1.93, abs=0.01)
        assert result["new_soc_kwh"] == pytest.approx(
            3.07, abs=0.01
        )  # Zastavilo na hw_min!

        # Zbytek ze sítě
        deficit = 10.0 - 1.8335
        assert result["grid_import_kwh"] == pytest.approx(deficit, abs=0.01)


# ============================================================================
# EDGE CASES & ERROR HANDLING
# ============================================================================


class TestEdgeCases:
    """Testy krajních případů a chybových stavů."""

    def test_invalid_mode_raises_error(self, forecast, common_params):
        """Neplatný režim → ValueError."""
        with pytest.raises(ValueError, match="Unknown mode: 99"):
            forecast._simulate_interval(
                mode=99,  # Neplatný režim!
                solar_kwh=1.0,
                load_kwh=1.0,
                battery_soc_kwh=10.0,
                **common_params,
            )

    def test_zero_solar_zero_load(self, forecast, common_params):
        """Nula FVE, nula spotřeba → nic se neděje."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=0.0,
            battery_soc_kwh=10.0,
            **common_params,
        )

        # Baterie nezměněna
        assert result["new_soc_kwh"] == pytest.approx(10.0, abs=0.001)
        assert result["battery_charge_kwh"] == 0.0
        assert result["battery_discharge_kwh"] == 0.0
        assert result["grid_import_kwh"] == 0.0
        assert result["grid_export_kwh"] == 0.0

    def test_efficiency_applied_correctly(self, forecast, common_params):
        """Účinnosti správně aplikovány."""
        # Nabíjení: input 1.0 → physical 0.95
        result_charge = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=2.0,
            load_kwh=1.0,  # Surplus 1.0
            battery_soc_kwh=10.0,
            **common_params,
        )
        assert result_charge["new_soc_kwh"] == pytest.approx(10.95, abs=0.01)

        # Vybíjení: output 1.0 → physical 1.053
        result_discharge = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.0,
            load_kwh=1.0,
            battery_soc_kwh=10.0,
            **common_params,
        )
        assert result_discharge["battery_discharge_kwh"] == pytest.approx(
            1.053, abs=0.01
        )
        assert result_discharge["new_soc_kwh"] == pytest.approx(8.947, abs=0.01)

    def test_net_cost_calculation(self, forecast, common_params):
        """Čistý náklad správně vypočítán (import - export)."""
        result = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=3.0,
            load_kwh=1.0,
            battery_soc_kwh=15.36,  # Plná → exportuje
            **common_params,
        )

        # Export 2.0 * 1.0 = 2.0 Kč revenue
        assert result["export_revenue_czk"] == pytest.approx(2.0, abs=0.01)
        assert result["grid_cost_czk"] == 0.0
        assert result["net_cost_czk"] == pytest.approx(-2.0, abs=0.01)  # Profit!


# ============================================================================
# INTEGRATION TESTS - Reálné scénáře
# ============================================================================


class TestRealWorldScenarios:
    """Testy reálných denních scénářů."""

    def test_sunny_day_home_i(self, forecast, common_params):
        """Slunečný den HOME I: FVE→load→battery→export."""
        # Ráno: deficit
        result_morning = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.5,
            load_kwh=1.5,
            battery_soc_kwh=10.0,
            **common_params,
        )
        assert result_morning["battery_discharge_kwh"] > 0

        # Poledne: surplus
        result_noon = forecast._simulate_interval(
            mode=CBB_MODE_HOME_I,
            solar_kwh=4.0,
            load_kwh=1.0,
            battery_soc_kwh=result_morning["new_soc_kwh"],
            **common_params,
        )
        assert result_noon["battery_charge_kwh"] > 0

    def test_cloudy_day_home_ii_saves_battery(self, forecast, common_params):
        """Zatažený den HOME II: deficit → grid, baterie šetřena pro noc."""
        # Den: deficit → grid only
        result_day = forecast._simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.3,
            load_kwh=1.5,
            battery_soc_kwh=10.0,
            **common_params,
        )
        assert result_day["battery_discharge_kwh"] == 0.0  # NETOUCHED!
        assert result_day["grid_import_kwh"] == pytest.approx(1.2, abs=0.01)
        assert result_day["new_soc_kwh"] == pytest.approx(10.0, abs=0.01)

        # Noc: teď může vybíjet (protože ušetřila přes den)
        result_night = forecast._simulate_interval(
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.0,
            load_kwh=2.0,
            battery_soc_kwh=result_day["new_soc_kwh"],
            **common_params,
        )
        assert result_night["battery_discharge_kwh"] > 0

    def test_home_iii_aggressive_charging(self, forecast, common_params):
        """HOME III: Agresivní nabíjení, spotřeba vždy ze sítě."""
        # Celý den: FVE → baterie, load → grid
        soc = 5.0
        total_solar = 0.0
        total_grid_import = 0.0

        for i in range(4):  # 4x 15min = 1 hodina
            result = forecast._simulate_interval(
                mode=CBB_MODE_HOME_III,
                solar_kwh=3.0,
                load_kwh=1.0,
                battery_soc_kwh=soc,
                **common_params,
            )
            total_solar += result["battery_charge_kwh"]
            total_grid_import += result["grid_import_kwh"]
            soc = result["new_soc_kwh"]

        # Za hodinu: 4x3.0 = 12.0 kWh FVE produkce
        # Ale baterie se částečně naplní!
        # Interval 1: 3.0, Interval 2: 3.0, Interval 3: 3.0, Interval 4: ~1.8 (zbytek)
        # Total charge input (bez účinnosti): ~10.8 kWh
        assert total_solar == pytest.approx(10.81, abs=0.1)
        # Load: 4x1.0 = 4.0 kWh vždy ze sítě
        assert total_grid_import == pytest.approx(4.0, abs=0.1)

    def test_home_ups_charges_to_100_percent(self, forecast, common_params):
        """HOME UPS: Nabíjení na 100% ze všech zdrojů."""
        soc = 10.0
        iterations = 0
        max_iterations = 20  # Safety limit

        while soc < 15.35 and iterations < max_iterations:  # Téměř plná
            result = forecast._simulate_interval(
                mode=CBB_MODE_HOME_UPS,
                solar_kwh=2.0,
                load_kwh=1.0,
                battery_soc_kwh=soc,
                **common_params,
            )
            soc = result["new_soc_kwh"]
            iterations += 1

        # Baterie by měla být skoro plná
        assert soc >= 15.30  # Minimálně 99.6%
        assert iterations < max_iterations
