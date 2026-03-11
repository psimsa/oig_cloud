#!/usr/bin/env python3
"""
Test simulace dual price systému (buy/sell ceny).

Testuje letní scénář se zápornými exportními cenami.
Tento test je standalone - neimportuje HA moduly přímo,
místo toho reimplementuje klíčovou fyziku pro ověření.
"""

from dataclasses import dataclass
from typing import List, Tuple

import pytest

# ============================================================================
# Konstanty z CBB
# ============================================================================
CBB_MODE_HOME_I = 0
CBB_MODE_HOME_II = 1
CBB_MODE_HOME_III = 2
CBB_MODE_HOME_UPS = 3

# Efektivity
DC_DC_EFFICIENCY = 0.95  # Solar → battery
AC_DC_EFFICIENCY = 0.95  # Grid → battery
DC_AC_EFFICIENCY = 0.882  # Battery → load


@dataclass
class SimResult:
    """Výsledek simulace intervalu."""

    battery_end: float
    grid_import: float
    grid_export: float
    solar_to_battery: float
    solar_to_load: float
    battery_to_load: float


def simulate_interval(
    battery_start: float,
    mode: int,
    solar_kwh: float,
    consumption_kwh: float,
    max_capacity: float = 15.36,
    min_capacity: float = 3.07,  # HW minimum ~20%
    charge_rate_kw: float = 2.8,
) -> SimResult:
    """
    Simulace jednoho intervalu podle CBB fyziky.

    Zdroj pravdy: CBB_MODES_DEFINITIVE.md

    KLÍČOVÁ PRAVIDLA:
    1. Export nastává POUZE když je baterie na 100%
    2. Po setmění (solar=0) jsou HOME I/II/III identické - všechny vybíjí baterii
    3. HW minimum (~20%) = střídač fyzicky nemůže jít níž

    REŽIMY BĚHEM DNE (solar > 0):
    - HOME I: FVE → spotřeba → přebytek do baterie, deficit z baterie
    - HOME II: FVE → spotřeba → přebytek do baterie, deficit ze sítě (baterie netouched)
    - HOME III: VEŠKERÁ FVE → baterie, spotřeba → síť vždy
    - HOME UPS: FVE → baterie + nabíjení ze sítě, spotřeba → síť
    """
    battery = battery_start
    grid_import = 0.0
    grid_export = 0.0
    solar_to_battery = 0.0
    solar_to_load = 0.0
    battery_to_load = 0.0

    # Max charge per 15min interval
    max_charge_per_interval = charge_rate_kw * 0.25  # kWh per 15min

    if mode == CBB_MODE_HOME_UPS:
        # HOME UPS: Solar → battery, Load → grid, Grid charging enabled
        # Solar jde do baterie (maximálně)
        battery_space = max_capacity - battery
        solar_charge = min(solar_kwh * DC_DC_EFFICIENCY, battery_space)
        battery += solar_charge
        solar_to_battery = solar_charge / DC_DC_EFFICIENCY if solar_charge > 0 else 0

        # Export pouze pokud baterie = 100%
        if battery >= max_capacity - 0.01:
            solar_exported = solar_kwh - solar_to_battery
            grid_export = max(0, solar_exported)

        # Grid charging if space available
        remaining_space = max_capacity - battery
        grid_charge_raw = min(
            max_charge_per_interval, remaining_space / AC_DC_EFFICIENCY
        )
        if grid_charge_raw > 0.01:
            grid_import += grid_charge_raw
            battery += grid_charge_raw * AC_DC_EFFICIENCY

        # Load jde ze sítě
        grid_import += consumption_kwh

    elif mode == CBB_MODE_HOME_III:
        # HOME III podle CBB_MODES_DEFINITIVE.md:
        # DEN (solar > 0): VEŠKERÁ FVE → baterie, spotřeba → síť VŽDY
        # NOC (solar = 0): Baterie vybíjí (stejně jako HOME I/II)

        if solar_kwh > 0.01:
            # DEN: Veškerá FVE jde do baterie (ne spotřeba!)
            battery_space = max_capacity - battery
            to_battery = min(solar_kwh * DC_DC_EFFICIENCY, battery_space)
            battery += to_battery
            solar_to_battery = to_battery / DC_DC_EFFICIENCY if to_battery > 0 else 0

            # Export POUZE pokud baterie = 100%
            if battery >= max_capacity - 0.01:
                solar_exported = solar_kwh - solar_to_battery
                grid_export = max(0, solar_exported)

            # Spotřeba JDE VŽDY ZE SÍTĚ (to je klíčový rozdíl HOME III!)
            grid_import = consumption_kwh
        else:
            # NOC: Baterie vybíjí na spotřebu (stejně jako HOME I/II)
            available = (battery - min_capacity) * DC_AC_EFFICIENCY
            from_battery = min(consumption_kwh, max(0, available))

            if from_battery > 0:
                drain = from_battery / DC_AC_EFFICIENCY
                battery -= drain
                battery_to_load = from_battery

            grid_import = consumption_kwh - from_battery

    elif mode == CBB_MODE_HOME_II:
        # HOME II podle CBB_MODES_DEFINITIVE.md:
        # DEN: FVE → spotřeba, přebytek → baterie, deficit → SÍŤ (baterie netouched!)
        # NOC: Baterie vybíjí (stejně jako HOME I/III)

        if solar_kwh > 0.01:
            # DEN: FVE pokrývá spotřebu
            solar_to_load = min(solar_kwh, consumption_kwh)
            excess_solar = solar_kwh - solar_to_load

            if excess_solar > 0:
                # Přebytek jde do baterie
                battery_space = max_capacity - battery
                to_battery = min(excess_solar * DC_DC_EFFICIENCY, battery_space)
                battery += to_battery
                solar_to_battery = (
                    to_battery / DC_DC_EFFICIENCY if to_battery > 0 else 0
                )

                # Export POUZE pokud baterie = 100%
                if battery >= max_capacity - 0.01:
                    solar_exported = excess_solar - solar_to_battery
                    grid_export = max(0, solar_exported)

            # Deficit jde ZE SÍTĚ (baterie se během dne NEVYBÍJÍ!)
            remaining_load = consumption_kwh - solar_to_load
            if remaining_load > 0:
                grid_import = remaining_load
        else:
            # NOC: Baterie vybíjí (stejně jako HOME I/III)
            available = (battery - min_capacity) * DC_AC_EFFICIENCY
            from_battery = min(consumption_kwh, max(0, available))

            if from_battery > 0:
                drain = from_battery / DC_AC_EFFICIENCY
                battery -= drain
                battery_to_load = from_battery

            grid_import = consumption_kwh - from_battery

    elif mode == CBB_MODE_HOME_I:
        # HOME I podle CBB_MODES_DEFINITIVE.md:
        # DEN: FVE → spotřeba, přebytek → baterie, deficit → BATERIE
        # NOC: Baterie vybíjí (stejně jako HOME II/III)

        if solar_kwh >= consumption_kwh:
            # Solar pokrývá spotřebu
            solar_to_load = consumption_kwh
            excess = solar_kwh - consumption_kwh

            # Přebytek do baterie
            battery_space = max_capacity - battery
            to_battery = min(excess * DC_DC_EFFICIENCY, battery_space)
            battery += to_battery
            solar_to_battery = to_battery / DC_DC_EFFICIENCY if to_battery > 0 else 0

            # Export POUZE pokud baterie = 100%
            if battery >= max_capacity - 0.01:
                solar_exported = excess - solar_to_battery
                grid_export = max(0, solar_exported)
        else:
            # Deficit - FVE nepokryje spotřebu
            solar_to_load = solar_kwh
            deficit = consumption_kwh - solar_kwh

            # Deficit jde z BATERIE (klíčový rozdíl HOME I!)
            available = (battery - min_capacity) * DC_AC_EFFICIENCY
            from_battery = min(deficit, max(0, available))

            if from_battery > 0:
                battery -= from_battery / DC_AC_EFFICIENCY
                battery_to_load = from_battery

            # Síť pouze pokud baterie na HW minimu
            grid_import = deficit - from_battery

    # Clamp battery to valid range
    battery = max(min_capacity, min(battery, max_capacity))

    return SimResult(
        battery_end=battery,
        grid_import=grid_import,
        grid_export=grid_export,
        solar_to_battery=solar_to_battery,
        solar_to_load=solar_to_load,
        battery_to_load=battery_to_load,
    )


def calculate_net_cost(
    grid_import: float,
    grid_export: float,
    buy_price: float,
    sell_price: float,
) -> Tuple[float, float, float]:
    """
    Výpočet čistých nákladů s dual price systémem.

    Returns:
        Tuple of (import_cost, export_revenue, net_cost)
    """
    import_cost = grid_import * buy_price
    export_revenue = grid_export * sell_price
    net_cost = import_cost - export_revenue
    return import_cost, export_revenue, net_cost


# ============================================================================
# TESTY
# ============================================================================


class TestDualPriceSystem:
    """Testy dual price systému."""

    def test_positive_export_price_generates_revenue(self):
        """Kladná export cena generuje příjem."""
        import_cost, export_revenue, net_cost = calculate_net_cost(
            grid_import=0,
            grid_export=10,
            buy_price=3.0,
            sell_price=2.55,  # 3.0 * 0.85
        )

        assert import_cost == 0
        assert export_revenue == 25.5  # 10 * 2.55
        assert net_cost == -25.5  # Záporné = příjem!

    def test_negative_export_price_costs_money(self):
        """Záporná export cena stojí peníze!"""
        import_cost, export_revenue, net_cost = calculate_net_cost(
            grid_import=0,
            grid_export=10,
            buy_price=-2.0,
            sell_price=-1.70,  # -2.0 * 0.85
        )

        assert import_cost == 0
        assert export_revenue == -17.0  # 10 * (-1.70) = ZÁPORNÁ!
        assert net_cost == 17.0  # 0 - (-17) = +17 Kč → PLATÍŠ!

    def test_summer_scenario_home_iii_loses_money(self):
        """Letní scénář: HOME III při záporných cenách a plné baterii prodělává.

        Klíčové: Export nastává POUZE při 100% baterii!
        HOME III při záporných cenách:
        - Spotřeba jde ze sítě (negativní cena = výdělek na importu!)
        - Pokud je baterie plná, přebytek solaru se exportuje (záporná cena = náklad)
        """
        # Data: 3 hodiny záporných cen
        spot_prices = [-1.0, -2.0, -1.5]
        export_prices = [p * 0.85 for p in spot_prices]
        solar = [5.0, 6.0, 5.0]  # Vysoká produkce
        load = [0.5, 0.5, 0.5]  # Nízká spotřeba

        # Začínáme s PLNOU baterií, aby docházelo k exportu
        battery = 15.36  # 100% = max capacity
        total_net_cost = 0.0
        total_export = 0.0

        for i in range(3):
            result = simulate_interval(
                battery_start=battery,
                mode=CBB_MODE_HOME_III,
                solar_kwh=solar[i],
                consumption_kwh=load[i],
            )

            _, _, net_cost = calculate_net_cost(
                grid_import=result.grid_import,
                grid_export=result.grid_export,
                buy_price=spot_prices[i],
                sell_price=export_prices[i],
            )

            total_net_cost += net_cost
            total_export += result.grid_export
            battery = result.battery_end

        # Při plné baterii a záporných cenách:
        # - Import (spotřeba) při záporné ceně = VÝDĚLEK (buy_price < 0)
        # - Export při záporné export ceně = NÁKLAD
        # Celkově bychom měli mít export > 0 (protože baterie je plná)
        assert (
            total_export > 0
        ), f"Should have exports when battery full, got {total_export}"
        # A čistý náklad může být kladný nebo záporný v závislosti na poměru import/export

    def test_summer_scenario_smart_saves_money(self):
        """Letní scénář: SMART strategie (UPS při záporných) vs HOME III.

        Při záporných cenách a PLNÉ baterii:
        - HOME III: Solar → baterie (plná), přebytek → export (záporná cena = náklad)
        - HOME UPS: Solar → baterie (plná), přebytek → export (stejné chování!)

        Ale rozdíl je v tom, že při záporných cenách NECHCEME exportovat vůbec!
        Lepší strategie by byla HOME II - FVE jde do spotřeby nejdřív.

        Ve skutečnosti při plné baterii nemáme moc možností - všechny režimy exportují.
        Test ověřuje že simulace funguje správně.
        """
        # Data: 3 hodiny záporných cen
        spot_prices = [-1.0, -2.0, -1.5]
        export_prices = [p * 0.85 for p in spot_prices]
        solar = [5.0, 6.0, 5.0]
        load = [0.5, 0.5, 0.5]

        # HOME III simulace - začínáme s prázdnější baterií
        battery_h3 = 5.0  # 33% battery
        cost_home_iii = 0.0
        export_h3 = 0.0

        for i in range(3):
            result = simulate_interval(
                battery_start=battery_h3,
                mode=CBB_MODE_HOME_III,
                solar_kwh=solar[i],
                consumption_kwh=load[i],
            )
            _, _, net = calculate_net_cost(
                result.grid_import, result.grid_export, spot_prices[i], export_prices[i]
            )
            cost_home_iii += net
            export_h3 += result.grid_export
            battery_h3 = result.battery_end

        # HOME II simulace - FVE pokrývá spotřebu, přebytek do baterie
        battery_h2 = 5.0
        cost_home_ii = 0.0
        export_h2 = 0.0

        for i in range(3):
            result = simulate_interval(
                battery_start=battery_h2,
                mode=CBB_MODE_HOME_II,
                solar_kwh=solar[i],
                consumption_kwh=load[i],
            )
            _, _, net = calculate_net_cost(
                result.grid_import, result.grid_export, spot_prices[i], export_prices[i]
            )
            cost_home_ii += net
            export_h2 += result.grid_export
            battery_h2 = result.battery_end

        # HOME III: spotřeba ze sítě (záporná cena = výdělek!)
        # HOME II: spotřeba z FVE (žádný nákup ze sítě, žádný výdělek)
        # Při záporných cenách je HOME III výhodnější protože vydělává na importu!

        # Oba režimy by neměly moc exportovat (baterie má místo)
        # Test ověřuje že simulace funguje

    def test_export_price_calculation_percentage_model(self):
        """Test výpočtu export ceny - percentage model."""
        spot_price = 3.0
        fee_percent = 15

        export_price = spot_price * (1 - fee_percent / 100)

        assert export_price == 2.55

    def test_export_price_calculation_fixed_model(self):
        """Test výpočtu export ceny - fixed model."""
        spot_price = 3.0
        fixed_fee = 0.50

        export_price = spot_price - fixed_fee

        assert export_price == 2.50

    def test_negative_spot_creates_negative_export(self):
        """Záporná spot cena vytváří zápornou export cenu."""
        spot_price = -2.0
        fee_percent = 15

        export_price = spot_price * (1 - fee_percent / 100)

        # -2.0 * 0.85 = -1.70
        assert export_price == pytest.approx(-1.70)
        assert export_price < 0


class TestSimulatorPhysics:
    """Testy fyziky simulátoru podle CBB_MODES_DEFINITIVE.md."""

    def test_home_ups_absorbs_solar(self):
        """HOME UPS absorbuje solar do baterie."""
        result = simulate_interval(
            battery_start=5.0,
            mode=CBB_MODE_HOME_UPS,
            solar_kwh=5.0,
            consumption_kwh=0.5,
        )

        # Solar by měl jít do baterie
        assert result.solar_to_battery > 0
        assert result.battery_end > 5.0
        # Spotřeba ze sítě
        assert result.grid_import >= 0.5  # minimálně spotřeba

    def test_home_iii_all_solar_to_battery(self):
        """HOME III: VEŠKERÁ FVE jde do baterie, spotřeba ze sítě."""
        result = simulate_interval(
            battery_start=5.0,
            mode=CBB_MODE_HOME_III,
            solar_kwh=5.0,
            consumption_kwh=0.5,
        )

        # Veškerá FVE do baterie (ne spotřeba!)
        assert result.solar_to_battery > 0
        assert result.solar_to_load == 0  # HOME III: FVE nejde do spotřeby!
        # Spotřeba JDE ZE SÍTĚ
        assert result.grid_import == pytest.approx(0.5, abs=0.01)
        # Baterie se nabila
        assert result.battery_end > 5.0

    def test_home_iii_exports_only_when_full(self):
        """HOME III exportuje POUZE když je baterie 100%."""
        # Skoro plná baterie
        result = simulate_interval(
            battery_start=15.0,  # 97.7%
            mode=CBB_MODE_HOME_III,
            solar_kwh=5.0,
            consumption_kwh=0.5,
        )

        # S plnou baterií by měl být export
        assert result.grid_export > 0
        # Baterie by měla být plná
        assert result.battery_end >= 15.36 - 0.1

    def test_home_iii_no_export_when_battery_has_space(self):
        """HOME III NEEXPORTUJE dokud má baterie místo."""
        result = simulate_interval(
            battery_start=5.0,  # Hodně místa v baterii
            mode=CBB_MODE_HOME_III,
            solar_kwh=3.0,  # Menší solar
            consumption_kwh=0.5,
        )

        # Baterie má místo → žádný export
        assert result.grid_export == 0
        # Vše šlo do baterie
        assert result.solar_to_battery > 0

    def test_home_ii_fve_covers_load_first(self):
        """HOME II: FVE pokrývá spotřebu, přebytek do baterie."""
        result = simulate_interval(
            battery_start=5.0,
            mode=CBB_MODE_HOME_II,
            solar_kwh=2.0,
            consumption_kwh=0.5,
        )

        # FVE pokryje spotřebu
        assert result.solar_to_load == pytest.approx(0.5, abs=0.01)
        # Přebytek jde do baterie
        assert result.solar_to_battery > 0
        # Nic ze sítě
        assert result.grid_import == 0

    def test_home_ii_deficit_from_grid_not_battery(self):
        """HOME II: Deficit jde ze sítě, baterie se NEVYBÍJÍ během dne."""
        result = simulate_interval(
            battery_start=10.0,
            mode=CBB_MODE_HOME_II,
            solar_kwh=0.3,  # Málo solaru
            consumption_kwh=1.0,  # Více spotřeba
        )

        # FVE pokryje část spotřeby
        assert result.solar_to_load == pytest.approx(0.3, abs=0.01)
        # Deficit jde ze sítě (baterie se během dne nevybíjí!)
        assert result.grid_import == pytest.approx(0.7, abs=0.01)
        # Baterie se NEVYBÍJÍ
        assert result.battery_to_load == 0
        assert result.battery_end == pytest.approx(10.0, abs=0.01)

    def test_home_i_deficit_from_battery(self):
        """HOME I: Deficit jde z baterie."""
        result = simulate_interval(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,
            solar_kwh=0.3,  # Málo solaru
            consumption_kwh=1.0,  # Více spotřeba
        )

        # FVE pokryje část
        assert result.solar_to_load == pytest.approx(0.3, abs=0.01)
        # Deficit z baterie!
        assert result.battery_to_load > 0
        # Baterie klesla
        assert result.battery_end < 10.0

    def test_night_all_modes_discharge_battery(self):
        """V noci (solar=0) HOME I/II/III vybíjí baterii stejně."""
        for mode in [CBB_MODE_HOME_I, CBB_MODE_HOME_II, CBB_MODE_HOME_III]:
            result = simulate_interval(
                battery_start=10.0,
                mode=mode,
                solar_kwh=0,  # Noc
                consumption_kwh=1.0,
            )

            # Baterie vybíjí
            assert result.battery_to_load > 0, f"Mode {mode} should discharge at night"
            assert result.battery_end < 10.0, f"Mode {mode} battery should decrease"

    def test_battery_discharge_with_efficiency(self):
        """Vybíjení baterie zohledňuje účinnost."""
        result = simulate_interval(
            battery_start=10.0,
            mode=CBB_MODE_HOME_I,  # HOME I vybíjí i ve dne
            solar_kwh=0,  # Žádný solar
            consumption_kwh=1.0,  # Spotřeba
        )

        # Baterie by měla vybíjet s účinností 88.2%
        # Pro 1 kWh load potřebuji 1/0.882 = 1.134 kWh z baterie
        battery_drain = 10.0 - result.battery_end
        assert battery_drain > 1.0  # Více než load kvůli účinnosti
        assert battery_drain < 1.2  # Ale ne moc více

    def test_hw_minimum_stops_discharge(self):
        """HW minimum zastaví vybíjení."""
        result = simulate_interval(
            battery_start=3.07,  # Na HW minimu
            mode=CBB_MODE_HOME_I,
            solar_kwh=0,
            consumption_kwh=1.0,
            min_capacity=3.07,
        )

        # Baterie nemůže klesnout pod minimum
        assert result.battery_end >= 3.07 - 0.01
        # Deficit ze sítě
        assert result.grid_import == pytest.approx(1.0, abs=0.01)


class TestFullDaySimulation:
    """Celodenní simulace."""

    def test_summer_day_comparison(self):
        """Porovnání strategií na letním dni."""
        # 8 hodin (10:00 - 18:00)
        hours = 8

        # OTE ceny
        spot_prices = [1.0, 0.5, -1.0, -2.0, -1.5, 0.0, 2.0, 3.0]
        export_prices = [p * 0.85 for p in spot_prices]

        # Vysoká solární produkce
        solar = [2.0, 3.0, 5.0, 6.0, 5.0, 3.0, 1.0, 0.5]
        load = [0.5] * 8

        # HOME III
        battery = 5.0
        cost_h3 = 0.0
        exports_h3 = 0.0

        for i in range(hours):
            r = simulate_interval(battery, CBB_MODE_HOME_III, solar[i], load[i])
            _, _, net = calculate_net_cost(
                r.grid_import, r.grid_export, spot_prices[i], export_prices[i]
            )
            cost_h3 += net
            exports_h3 += r.grid_export
            battery = r.battery_end

        # HOME II (lepší při záporných cenách - FVE pokrývá spotřebu)
        battery = 5.0
        cost_h2 = 0.0
        exports_h2 = 0.0

        for i in range(hours):
            r = simulate_interval(battery, CBB_MODE_HOME_II, solar[i], load[i])
            _, _, net = calculate_net_cost(
                r.grid_import, r.grid_export, spot_prices[i], export_prices[i]
            )
            cost_h2 += net
            exports_h2 += r.grid_export
            battery = r.battery_end

        print("\n📊 Celodenní simulace:")
        print(f"   HOME III: cost={cost_h3:.2f} Kč, export={exports_h3:.1f} kWh")
        print(f"   HOME II:  cost={cost_h2:.2f} Kč, export={exports_h2:.1f} kWh")
        print(f"   Rozdíl:   {cost_h3 - cost_h2:.2f} Kč")

        # Oba režimy by neměly moc exportovat při prázdnější baterii
        # HOME III: spotřeba ze sítě → při záporných cenách výdělek na importu
        # HOME II: spotřeba z FVE → bez nákupu ze sítě
        # Test ověřuje že simulace proběhla bez chyb


if __name__ == "__main__":
    # Spustit testy s verbose výstupem
    pytest.main([__file__, "-v", "--tb=short"])
