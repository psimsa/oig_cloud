# Seznam entit - OIG Cloud

Kompletní přehled všech senzorů a jejich význam.

## 📋 Obsah

- [Solární výroba (FVE)](#solární-výroba-fve)
- [Baterie](#baterie)
- [Spotřeba domu](#spotřeba-domu)
- [Síť](#síť)
- [Bojler](#bojler-volitelné)
- [Box systém](#box-systém)
- [Spot ceny](#spot-ceny-volitelné)
- [Předpovědi](#předpovědi-volitelné)
- [ServiceShield](#serviceshield)

---

## ☀️ Solární výroba (FVE)

### Aktuální výkon

| Entity ID                          | Název            | Jednotka | Popis                                 |
| ---------------------------------- | ---------------- | -------- | ------------------------------------- |
| `sensor.oig_XXXXX_actual_fv_total` | FVE výkon celkem | W        | Celkový aktuální výkon z obou stringů |
| `sensor.oig_XXXXX_dc_in_fv_p1`     | FVE String 1     | W        | Výkon z prvního stringu               |
| `sensor.oig_XXXXX_dc_in_fv_p2`     | FVE String 2     | W        | Výkon z druhého stringu               |

**💡 Použití:**

- Monitoring výroby v reálném čase
- Automatizace podle výroby
- Detekce problémů s panely

### Denní statistiky

| Entity ID                        | Název        | Jednotka | Popis                             |
| -------------------------------- | ------------ | -------- | --------------------------------- |
| `sensor.oig_XXXXX_dc_in_fv_ad`   | FVE dnes     | kWh      | Celková výroba za dnešek          |
| `sensor.oig_XXXXX_dc_in_fv_proc` | FVE procenta | %        | Výkon jako % z maximální kapacity |

### Detaily stringů

| Entity ID                                 | Název           | Jednotka | Popis                    |
| ----------------------------------------- | --------------- | -------- | ------------------------ |
| `sensor.oig_XXXXX_extended_fve_voltage_1` | Napětí String 1 | V        | Napětí na prvním stringu |
| `sensor.oig_XXXXX_extended_fve_current_1` | Proud String 1  | A        | Proud z prvního stringu  |
| `sensor.oig_XXXXX_extended_fve_voltage_2` | Napětí String 2 | V        | Napětí na druhém stringu |
| `sensor.oig_XXXXX_extended_fve_current_2` | Proud String 2  | A        | Proud z druhého stringu  |

**📊 Příklad hodnot:**

```yaml
FVE výkon celkem: 3200 W
FVE String 1: 1600 W  (380V, 4.2A)
FVE String 2: 1600 W  (380V, 4.2A)
FVE dnes: 24.5 kWh
FVE procenta: 45%
```

---

## 🔋 Baterie

### Základní info

| Entity ID                  | Název              | Jednotka | Popis                                 |
| -------------------------- | ------------------ | -------- | ------------------------------------- |
| `sensor.oig_XXXXX_bat_soc` | Stav baterie (SOC) | %        | State of Charge - stav nabití         |
| `sensor.oig_XXXXX_bat_p`   | Výkon baterie      | W        | Kladný = nabíjení, Záporný = vybíjení |

### Detaily

| Entity ID                                       | Název           | Jednotka | Popis                      |
| ----------------------------------------------- | --------------- | -------- | -------------------------- |
| `sensor.oig_XXXXX_extended_battery_voltage`     | Napětí baterie  | V        | Napětí bateriového systému |
| `sensor.oig_XXXXX_extended_battery_current`     | Proud baterie   | A        | Nabíjecí/vybíjecí proud    |
| `sensor.oig_XXXXX_extended_battery_temperature` | Teplota baterie | °C       | Teplota BMS                |

### Denní statistiky

| Entity ID                                                 | Název               | Jednotka | Popis                       |
| --------------------------------------------------------- | ------------------- | -------- | --------------------------- |
| `sensor.oig_XXXXX_computed_batt_charge_energy_today`      | Nabito dnes celkem  | kWh      | Celková energie nabitá dnes |
| `sensor.oig_XXXXX_computed_batt_charge_fve_energy_today`  | Nabito z FVE dnes   | kWh      | Energie nabitá z FVE        |
| `sensor.oig_XXXXX_computed_batt_charge_grid_energy_today` | Nabito ze sítě dnes | kWh      | Energie nabitá ze sítě      |
| `sensor.oig_XXXXX_computed_batt_discharge_energy_today`   | Vybito dnes         | kWh      | Energie vybitá z baterie    |

**📊 Příklad hodnot:**

```yaml
Stav baterie:         85%
Výkon baterie:        1200 W  (nabíjení)
Napětí:               48.2 V
Proud:                24.9 A
Teplota:              23°C

Dnes:
  Nabito celkem:      15.2 kWh
    └─ Z FVE:         12.1 kWh
    └─ Ze sítě:        3.1 kWh
  Vybito:              8.5 kWh
```

**💡 Použití:**

- Monitoring stavu baterie
- Automatizace nabíjení/vybíjení
- Detekce problémů (vysoká teplota, nízké napětí)
- Optimalizace podle SOC

---

## 🏠 Spotřeba domu

### Aktuální výkon

| Entity ID                        | Název         | Jednotka | Popis                     |
| -------------------------------- | ------------- | -------- | ------------------------- |
| `sensor.oig_XXXXX_actual_aco_p`  | Spotřeba domu | W        | Celková aktuální spotřeba |
| `sensor.oig_XXXXX_ac_out_aco_pr` | Spotřeba L1   | W        | Fáze 1                    |
| `sensor.oig_XXXXX_ac_out_aco_ps` | Spotřeba L2   | W        | Fáze 2                    |
| `sensor.oig_XXXXX_ac_out_aco_pt` | Spotřeba L3   | W        | Fáze 3                    |

### Denní statistiky

| Entity ID                        | Název         | Jednotka | Popis                      |
| -------------------------------- | ------------- | -------- | -------------------------- |
| `sensor.oig_XXXXX_ac_out_aco_ad` | Spotřeba dnes | kWh      | Celková spotřeba za dnešek |

**📊 Příklad hodnot:**

```yaml
Spotřeba domu:        4100 W
  L1:                 1200 W
  L2:                 1500 W
  L3:                 1400 W
Spotřeba dnes:        28.5 kWh
```

**💡 Použití:**

- Monitoring spotřeby
- Detekce špičkové zátěže
- Automatizace podle spotřeby
- Balanc ování fází

---

## 🔌 Síť

### Aktuální výkon

| Entity ID                            | Název          | Jednotka | Popis                             |
| ------------------------------------ | -------------- | -------- | --------------------------------- |
| `sensor.oig_XXXXX_actual_aci_wtotal` | Výkon sítě     | W        | Kladný = odběr, Záporný = dodávka |
| `sensor.oig_XXXXX_ac_in_aci_f`       | Frekvence sítě | Hz       | Frekvence AC sítě                 |

### Denní statistiky

| Entity ID                      | Název                | Jednotka | Popis                    |
| ------------------------------ | -------------------- | -------- | ------------------------ |
| `sensor.oig_XXXXX_ac_in_ac_ad` | Odběr ze sítě dnes   | kWh      | Energie odebraná ze sítě |
| `sensor.oig_XXXXX_ac_in_ac_pd` | Dodávka do sítě dnes | kWh      | Energie dodaná do sítě   |

### Detaily fází

| Entity ID                        | Název     | Jednotka | Popis         |
| -------------------------------- | --------- | -------- | ------------- |
| `sensor.oig_XXXXX_ac_in_aci_vr`  | Napětí L1 | V        | Napětí fáze 1 |
| `sensor.oig_XXXXX_actual_aci_wr` | Výkon L1  | W        | Výkon fáze 1  |
| `sensor.oig_XXXXX_ac_in_aci_vs`  | Napětí L2 | V        | Napětí fáze 2 |
| `sensor.oig_XXXXX_actual_aci_ws` | Výkon L2  | W        | Výkon fáze 2  |
| `sensor.oig_XXXXX_ac_in_aci_vt`  | Napětí L3 | V        | Napětí fáze 3 |
| `sensor.oig_XXXXX_actual_aci_wt` | Výkon L3  | W        | Výkon fáze 3  |

**📊 Příklad hodnot:**

```yaml
Výkon sítě: 300 W  (odběr)
Frekvence: 49.98 Hz

Dnes:
  Odběr: 2.5 kWh
  Dodávka: 8.2 kWh

Fáze:
  L1: 0.1 kW  380V
  L2: 0.1 kW  380V
  L3: 0.1 kW  380V
```

**💡 Použití:**

- Monitoring odběru/dodávky
- Automatizace podle ceny
- Kontrola symetrie fází
- Detekce problémů se sítí

---

## 🌡️ Bojler (volitelné)

### Základní info

| Entity ID                             | Název           | Jednotka | Popis           |
| ------------------------------------- | --------------- | -------- | --------------- |
| `sensor.oig_XXXXX_boiler_manual_mode` | Režim bojleru   | -        | CBB nebo Manual |
| `sensor.oig_XXXXX_boiler_status`      | Stav bojleru    | -        | On/Off/Heating  |
| `sensor.oig_XXXXX_boiler_temperature` | Teplota bojleru | °C       | Teplota vody    |

### Výkon

| Entity ID                               | Název          | Jednotka | Popis                  |
| --------------------------------------- | -------------- | -------- | ---------------------- |
| `sensor.oig_XXXXX_boiler_current_cbb_w` | Aktuální výkon | W        | Okamžitý výkon bojleru |
| `sensor.oig_XXXXX_boiler_day_w`         | Spotřeba dnes  | Wh       | Spotřeba za dnešek     |

**📊 Příklad hodnot:**

```yaml
Režim bojleru: Inteligentní (CBB)
Stav: Ohřev
Teplota: 55°C
Aktuální výkon: 1200 W
Spotřeba dnes: 8500 Wh (8.5 kWh)
```

**💡 Použití:**

- Monitoring ohřevu
- Automatizace podle přebytků FVE
- Optimalizace spotřeby
- Kontrola teploty

---

## 📦 Box systém

### Režimy

| Entity ID                                        | Název         | Hodnoty                     | Popis                     |
| ------------------------------------------------ | ------------- | --------------------------- | ------------------------- |
| `sensor.oig_XXXXX_box_prms_mode`                 | Režim Box     | Eco/Backup/Charge/Discharge | Aktuální pracovní režim   |
| `sensor.oig_XXXXX_invertor_prms_to_grid`         | Grid delivery | On/Off/Limited              | Režim dodávky do sítě     |
| `sensor.oig_XXXXX_invertor_prm1_p_max_feed_grid` | Grid limit    | W                           | Maximální dodávka do sítě |

### Stav systému

| Entity ID                         | Název          | Jednotka | Popis             |
| --------------------------------- | -------------- | -------- | ----------------- |
| `sensor.oig_XXXXX_box_temp`       | Teplota box    | °C       | Teplota invertoru |
| `sensor.oig_XXXXX_bypass_status`  | Bypass         | On/Off   | Stav bypassu      |
| `sensor.oig_XXXXX_current_tariff` | Aktuální tarif | -        | VT/NT             |

### Notifikace

| Entity ID                                    | Název                 | Jednotka | Popis              |
| -------------------------------------------- | --------------------- | -------- | ------------------ |
| `sensor.oig_XXXXX_notification_count_unread` | Nepřečtené notifikace | -        | Počet nepřečtených |
| `sensor.oig_XXXXX_notification_count_error`  | Chybové notifikace    | -        | Počet chyb         |

**📊 Příklad hodnot:**

```yaml
Režim Box: Eco
Grid delivery: S omezením
Grid limit: 5000 W
Teplota box: 35°C
Bypass: Aktivní
Tarif: VT (vysoký)
Notifikace: 2 nepřečtené (1 chyba)
```

**💡 Použití:**

- Monitoring režimů
- Automatizace přepínání
- Kontrola teploty
- Alert y na notifikace

---

## 💰 Spot ceny (volitelné)

### Aktuální ceny

| Entity ID                                     | Název        | Jednotka | Popis                   |
| --------------------------------------------- | ------------ | -------- | ----------------------- |
| `sensor.oig_XXXXX_spot_price_current_15min`   | Spot cena    | Kč/kWh   | Aktuální burzovní cena  |
| `sensor.oig_XXXXX_export_price_current_15min` | Výkupní cena | Kč/kWh   | Cena za dodávku do sítě |

**📊 Příklad hodnot:**

```yaml
Spot cena: 2.15 Kč/kWh
Výkupní cena: 1.50 Kč/kWh
```

**💡 Použití:**

- Automatizace nabíjení podle ceny
- Optimalizace spotřeby
- Maximalizace zisku z výkupu

---

## ☀️ Předpovědi (volitelné)

### Solární předpověď

| Entity ID                                  | Název           | Jednotka | Popis              |
| ------------------------------------------ | --------------- | -------- | ------------------ |
| `sensor.oig_XXXXX_solar_forecast`          | Předpověď dnes  | kWh      | Odhad výroby dnes  |
| `sensor.oig_XXXXX_solar_forecast_tomorrow` | Předpověď zítra | kWh      | Odhad výroby zítra |

### Battery forecast

| Entity ID                           | Název            | Jednotka | Popis                   |
| ----------------------------------- | ---------------- | -------- | ----------------------- |
| `sensor.oig_XXXXX_battery_forecast` | Predikce baterie | -        | Předpověď stavu baterie (timeline v attributes) |

**Související entity (plánovač / statistiky):**

| Entity ID                                 | Název                         | Jednotka | Popis |
| ----------------------------------------- | ----------------------------- | -------- | ----- |
| `sensor.oig_XXXXX_grid_charging_planned`  | Plánované nabíjení ze sítě    | -        | Indikace + intervaly a cena v attributes |
| `sensor.oig_XXXXX_battery_efficiency`     | Efektivita baterie (měsíc)    | %        | Round‑trip účinnost baterie |
| `sensor.oig_XXXXX_battery_health`         | Kvalita baterie / SoH         | %        | Odhad kapacity/SoH z historie |
| `sensor.oig_XXXXX_adaptive_load_profiles` | Adaptivní profily spotřeby    | -        | Profiling spotřeby a 72h predikce |
| `sensor.oig_XXXXX_battery_balancing`      | Stav balancování baterie      | -        | Diagnostika balancování |

**📊 Příklad hodnot:**

```yaml
Předpověď dnes: 28.5 kWh
Předpověď zítra: 32.1 kWh
```

**💡 Použití:**

- Plánování spotřeby
- Automatizace nabíjení
- Optimalizace podle předpovědi
- Vysvětlení chování plánovače v dashboardu

Podrobnosti: `./PLANNER.md` a `./STATISTICS.md`.

---

## 🛡️ ServiceShield

### Stav

| Entity ID                                  | Název    | Hodnoty           | Popis                   |
| ------------------------------------------ | -------- | ----------------- | ----------------------- |
| `sensor.oig_XXXXX_service_shield_status`   | Status   | Aktivní/Neaktivní | Stav ServiceShield      |
| `sensor.oig_XXXXX_service_shield_queue`    | Fronta   | -                 | Počet položek ve frontě |
| `sensor.oig_XXXXX_service_shield_activity` | Aktivita | -                 | Aktuálně běžící služba  |

**📊 Příklad hodnot:**

```yaml
Status: Aktivní
Fronta: 2 (1 běžící + 1 čekající)
Aktivita: set_box_mode
```

**💡 Použití:**

- Monitoring změn
- Debugging problémů
- Přehled fronty

---

## 🔍 Jak najít entity

### 1. Přes Nastavení

```
Nastavení → Zařízení a služby → Zařízení → OIG Box
```

### 2. Přes Vývojářské nástroje

```
Vývojářské nástroje → Stavy → Filtr: "oig_"
```

### 3. Přes vyhledávání

```
Rychlé akce (Ctrl+K) → "oig" → Zobrazit všechny entity
```

---

## 📊 Příklady použití v automatizacích

### Nabíjení při levné elektřině

```yaml
automation:
  - alias: "Nabíjení při spot < 1.5 Kč"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        below: 1.5
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        below: 80
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Charge"
          acknowledgement: true
```

### Alert při nízké baterii

```yaml
automation:
  - alias: "Baterie pod 20%"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        below: 20
    action:
      - service: notify.mobile_app
        data:
          message: "⚠️ Baterie je pod 20%"
```

### Vypnutí dodávky v noci

```yaml
automation:
  - alias: "Grid OFF v noci"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "Off"
          acknowledgement: true
```

---

## 💡 Tipy

### 1. Přidání do Energy dashboardu

```
Nastavení → Dashboardy → Energie
→ Výroba: sensor.oig_XXXXX_dc_in_fv_ad
→ Odběr:  sensor.oig_XXXXX_ac_in_ac_ad
→ Dodávka: sensor.oig_XXXXX_ac_in_ac_pd
```

### 2. Custom karty

Všechny entity lze přidat do custom karet na dashboardu:

- Gauge karty (SOC, výkon)
- Grafy (historie)
- Entity karty (detaily)

### 3. Friendly names

Entity mají automatické friendly names v češtině.
Můžete je změnit v:

```
Nastavení → Entity → [vyber entitu] → Jméno
```

---

## ❓ Časté otázky

**Q: Entity nemají hodnoty**
A: Počkejte 5-10 minut na první aktualizaci.

**Q: Jak často se aktualizují?**
A: Podle nastaveného intervalu (výchozí 300s = 5 minut).

**Q: Mohu změnit interval?**
A: Ano, v nastavení integrace.

**Q: Které entity jsou nejdůležitější?**
A: SOC baterie, výkon FVE, spotřeba domu, výkon sítě.

---

## 🆘 Podpora

- 📖 [README.md](../../README.md)
- 📊 [DASHBOARD.md](DASHBOARD.md)
- ❓ [FAQ.md](FAQ.md)
- 🔧 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**Kompletní seznam entity aktualizován k verzi 2.0** ⚡
