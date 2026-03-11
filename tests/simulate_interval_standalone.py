"""
Standalone implementace _simulate_interval() pro testování.

Tato verze je čistě funkční (bez class dependencies) pro snadné testování.
"""

# CBB Mode konstanty
CBB_MODE_HOME_I = 0
CBB_MODE_HOME_II = 1
CBB_MODE_HOME_III = 2
CBB_MODE_HOME_UPS = 3


def simulate_interval(
    mode: int,  # 0=HOME I, 1=HOME II, 2=HOME III, 3=HOME UPS
    solar_kwh: float,  # FVE produkce (kWh/15min)
    load_kwh: float,  # Spotřeba (kWh/15min)
    battery_soc_kwh: float,  # Aktuální SoC (kWh)
    capacity_kwh: float,  # Max kapacita (kWh)
    hw_min_capacity_kwh: float,  # Fyzické minimum 20% (kWh) - INVERTOR LIMIT
    spot_price_czk: float,  # Nákupní cena (Kč/kWh)
    export_price_czk: float,  # Prodejní cena (Kč/kWh)
    charge_efficiency: float = 0.95,  # AC→DC + DC→battery efficiency
    discharge_efficiency: float = 0.95,  # battery→DC + DC→AC efficiency
    home_charge_rate_kwh_15min: float = 0.7,  # HOME UPS: 2.8kW = 0.7kWh/15min
) -> dict:
    """
    Simulovat jeden 15min interval s konkrétním CBB režimem.

    ZDROJ PRAVDY: CBB_MODES_DEFINITIVE.md

    Toto je standalone verze (bez class dependencies) pro testování.
    Kód je IDENTICKÝ s metodou _simulate_interval() v oig_cloud_battery_forecast.py.

    Returns:
        dict:
            new_soc_kwh: Nový SoC (kWh)
            grid_import_kwh: Import ze sítě (kWh)
            grid_export_kwh: Export do sítě (kWh)
            battery_charge_kwh: Nabití baterie (kWh)
            battery_discharge_kwh: Vybití baterie (kWh)
            grid_cost_czk: Náklady na import (Kč)
            export_revenue_czk: Příjem z exportu (Kč)
            net_cost_czk: Čisté náklady (Kč)
    """
    # Initialize result
    result = {
        "new_soc_kwh": battery_soc_kwh,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
        "grid_cost_czk": 0.0,
        "export_revenue_czk": 0.0,
        "net_cost_czk": 0.0,
    }

    # =====================================================================
    # CRITICAL OPTIMIZATION: NOC (solar == 0) → HOME I/II/III IDENTICKÉ!
    # =====================================================================

    if solar_kwh < 0.001 and mode in [
        CBB_MODE_HOME_I,
        CBB_MODE_HOME_II,
        CBB_MODE_HOME_III,
    ]:
        # NOC: Společná logika - vybíjení baterie do hw_min
        available_battery = max(0.0, battery_soc_kwh - hw_min_capacity_kwh)
        usable_from_battery = available_battery * discharge_efficiency

        battery_discharge_kwh = min(load_kwh, usable_from_battery)

        if battery_discharge_kwh > 0.001:
            result["battery_discharge_kwh"] = (
                battery_discharge_kwh / discharge_efficiency
            )
            result["new_soc_kwh"] = battery_soc_kwh - result["battery_discharge_kwh"]

        covered_by_battery = battery_discharge_kwh
        deficit = load_kwh - covered_by_battery

        if deficit > 0.001:
            result["grid_import_kwh"] = deficit
            result["grid_cost_czk"] = deficit * spot_price_czk

        result["net_cost_czk"] = result["grid_cost_czk"]
        return result

    # =====================================================================
    # HOME I (0) - DEN: FVE → spotřeba → baterie, deficit vybíjí
    # =====================================================================

    if mode == CBB_MODE_HOME_I:
        if solar_kwh >= load_kwh:
            # FVE pokrývá spotřebu, přebytek → baterie
            surplus = solar_kwh - load_kwh
            battery_space = capacity_kwh - battery_soc_kwh
            charge_amount = min(surplus, battery_space)

            if charge_amount > 0.001:
                result["battery_charge_kwh"] = charge_amount
                physical_charge = charge_amount * charge_efficiency
                result["new_soc_kwh"] = min(
                    battery_soc_kwh + physical_charge, capacity_kwh
                )

            remaining_surplus = surplus - charge_amount
            if remaining_surplus > 0.001:
                result["grid_export_kwh"] = remaining_surplus
                result["export_revenue_czk"] = remaining_surplus * export_price_czk

        else:
            # FVE < load → deficit vybíjí baterii
            deficit = load_kwh - solar_kwh
            available_battery = max(0.0, battery_soc_kwh - hw_min_capacity_kwh)
            usable_from_battery = available_battery * discharge_efficiency

            battery_discharge_kwh = min(deficit, usable_from_battery)

            if battery_discharge_kwh > 0.001:
                result["battery_discharge_kwh"] = (
                    battery_discharge_kwh / discharge_efficiency
                )
                result["new_soc_kwh"] = (
                    battery_soc_kwh - result["battery_discharge_kwh"]
                )

            remaining_deficit = deficit - battery_discharge_kwh
            if remaining_deficit > 0.001:
                result["grid_import_kwh"] = remaining_deficit
                result["grid_cost_czk"] = remaining_deficit * spot_price_czk

        result["net_cost_czk"] = result["grid_cost_czk"] - result["export_revenue_czk"]
        return result

    # =====================================================================
    # HOME II (1) - DEN: FVE → spotřeba, přebytek → baterie, deficit → SÍŤ!
    # =====================================================================

    elif mode == CBB_MODE_HOME_II:
        if solar_kwh >= load_kwh:
            # FVE pokrývá spotřebu, přebytek → baterie
            surplus = solar_kwh - load_kwh
            battery_space = capacity_kwh - battery_soc_kwh
            charge_amount = min(surplus, battery_space)

            if charge_amount > 0.001:
                result["battery_charge_kwh"] = charge_amount
                physical_charge = charge_amount * charge_efficiency
                result["new_soc_kwh"] = min(
                    battery_soc_kwh + physical_charge, capacity_kwh
                )

            remaining_surplus = surplus - charge_amount
            if remaining_surplus > 0.001:
                result["grid_export_kwh"] = remaining_surplus
                result["export_revenue_czk"] = remaining_surplus * export_price_czk

        else:
            # FVE < load → deficit ze SÍTĚ (baterie NETOUCHED!)
            deficit = load_kwh - solar_kwh
            result["grid_import_kwh"] = deficit
            result["grid_cost_czk"] = deficit * spot_price_czk
            # result["new_soc_kwh"] zůstává battery_soc_kwh (NETOUCHED)

        result["net_cost_czk"] = result["grid_cost_czk"] - result["export_revenue_czk"]
        return result

    # =====================================================================
    # HOME III (2) - DEN: FVE → baterie, spotřeba → VŽDY SÍŤ
    # =====================================================================

    elif mode == CBB_MODE_HOME_III:
        # CELÁ FVE → baterie (agresivní nabíjení)
        battery_space = capacity_kwh - battery_soc_kwh
        charge_amount = min(solar_kwh, battery_space)

        if charge_amount > 0.001:
            result["battery_charge_kwh"] = charge_amount
            physical_charge = charge_amount * charge_efficiency
            result["new_soc_kwh"] = min(battery_soc_kwh + physical_charge, capacity_kwh)

        # Spotřeba VŽDY ze sítě (i když je FVE!)
        result["grid_import_kwh"] = load_kwh
        result["grid_cost_czk"] = load_kwh * spot_price_czk

        # Export přebytku (pokud baterie plná)
        remaining_solar = solar_kwh - charge_amount
        if remaining_solar > 0.001:
            result["grid_export_kwh"] = remaining_solar
            result["export_revenue_czk"] = remaining_solar * export_price_czk

        result["net_cost_czk"] = result["grid_cost_czk"] - result["export_revenue_czk"]
        return result

    # =====================================================================
    # HOME UPS (3) - Nabíjení na 100% ze VŠECH zdrojů (FVE + síť)
    # =====================================================================

    elif mode == CBB_MODE_HOME_UPS:
        battery_space = capacity_kwh - battery_soc_kwh

        # FVE → baterie (bez limitu)
        solar_to_battery = min(solar_kwh, battery_space)

        # Grid → baterie (max home_charge_rate)
        remaining_space = battery_space - solar_to_battery
        grid_to_battery = min(home_charge_rate_kwh_15min, remaining_space)

        # Celkové nabití
        total_charge = solar_to_battery + grid_to_battery

        if total_charge > 0.001:
            result["battery_charge_kwh"] = total_charge
            physical_charge = total_charge * charge_efficiency
            result["new_soc_kwh"] = min(battery_soc_kwh + physical_charge, capacity_kwh)

        # Spotřeba + grid charging ze sítě
        result["grid_import_kwh"] = load_kwh + grid_to_battery
        result["grid_cost_czk"] = result["grid_import_kwh"] * spot_price_czk

        # Export přebytku FVE (pokud baterie plná)
        remaining_solar = solar_kwh - solar_to_battery
        if remaining_solar > 0.001:
            result["grid_export_kwh"] = remaining_solar
            result["export_revenue_czk"] = remaining_solar * export_price_czk

        result["net_cost_czk"] = result["grid_cost_czk"] - result["export_revenue_czk"]
        return result

    else:
        raise ValueError(f"Unknown mode: {mode} (expected 0-3)")
