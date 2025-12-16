# Příklady automatizací

Praktické příklady automatizací pro optimální využití OIG systému.

## 📋 Obsah

- [Základní automatizace](#základní-automatizace)
- [Optimalizace podle spot ceny](#optimalizace-podle-spot-ceny)
- [Správa baterie](#správa-baterie)
- [Grid delivery management](#grid-delivery-management)
- [Bojler automatizace](#bojler-automatizace)
- [Notifikace a alerty](#notifikace-a-alerty)
- [Sezónní úpravy](#sezónní-úpravy)
- [Pokročilé scénáře](#pokročilé-scénáře)

---

## 🌟 Základní automatizace

### 1. Denní rutina - Eco přes den, Backup v noci

**Účel:** Standardní provoz s ochranou baterie v noci.

```yaml
automation:
  - alias: "OIG: Eco režim ráno"
    description: "Přepnutí na Eco režim každé ráno v 6:00"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true

  - alias: "OIG: Backup režim večer"
    description: "Přepnutí na Backup režim každý večer ve 22:00"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Backup"
          acknowledgement: true
```

**💡 Vylepšení:**

```yaml
automation:
  - alias: "OIG: Denní režim (chytrý)"
    description: "Eco jen pokud není nízká baterie"
    trigger:
      - platform: time
        at: "06:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        above: 30 # Eco jen pokud SOC > 30%
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true
```

### 2. Automatický výkup podle režimu

**Účel:** Grid delivery podle režimu Box.

```yaml
automation:
  - alias: "OIG: Grid ON při Eco"
    description: "Zapnout výkup když Box v Eco režimu"
    trigger:
      - platform: state
        entity_id: sensor.oig_2206237016_box_prms_mode
        to: "Eco"
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "On"
          acknowledgement: true

  - alias: "OIG: Grid OFF při Backup"
    description: "Vypnout výkup když Box v Backup režimu"
    trigger:
      - platform: state
        entity_id: sensor.oig_2206237016_box_prms_mode
        to: "Backup"
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "Off"
          acknowledgement: true
```

---

## 💰 Optimalizace podle spot ceny

### 3. Nabíjení při levné elektřině

**Účel:** Automatické nabíjení baterie když je elektřina levná.

```yaml
automation:
  - alias: "OIG: Nabíjení při spot < 1.5 Kč"
    description: "Charge režim když spot cena klesne pod 1.5 Kč/kWh"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_spot_price_current_15min
        below: 1.5
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        below: 90 # Nabíjet jen pokud není plná
      - condition: time
        after: "00:00:00"
        before: "06:00:00" # Jen v noci
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Charge"
          acknowledgement: true
      - service: notify.mobile_app_phone
        data:
          message: "⚡ Nabíjení baterie - levná elektřina ({{ states('sensor.oig_2206237016_spot_price_current_15min') }} Kč/kWh)"
```

### 4. Vybíjení při drahé elektřině

**Účel:** Dodávka do sítě nebo krytí spotřeby z baterie při vysokých cenách.

```yaml
automation:
  - alias: "OIG: Vybíjení při spot > 4 Kč"
    description: "Discharge režim když spot cena přesáhne 4 Kč/kWh"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_spot_price_current_15min
        above: 4.0
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        above: 30 # Vybíjet jen pokud SOC > 30%
      - condition: time
        after: "06:00:00"
        before: "22:00:00" # Jen přes den
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Discharge"
          acknowledgement: true
      - service: notify.mobile_app_phone
        data:
          message: "💰 Vybíjení baterie - drahá elektřina ({{ states('sensor.oig_2206237016_spot_price_current_15min') }} Kč/kWh)"
```

### 5. Návrat na Eco při normální ceně

**Účel:** Automatický návrat z Charge/Discharge zpět na Eco.

```yaml
automation:
  - alias: "OIG: Zpět na Eco"
    description: "Návrat na Eco když cena normální (1.5-4 Kč)"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_spot_price_current_15min
        above: 1.5
        below: 4.0
        for:
          minutes: 15 # Stabilní 15 minut
    condition:
      - condition: or
        conditions:
          - condition: state
            entity_id: sensor.oig_2206237016_box_prms_mode
            state: "Charge"
          - condition: state
            entity_id: sensor.oig_2206237016_box_prms_mode
            state: "Discharge"
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true
```

### 6. Komplexní spot strategie

**Účel:** Plně automatická optimalizace podle spot ceny.

```yaml
automation:
  - alias: "OIG: Spot strategie"
    description: "Komplexní řízení podle spot ceny"
    trigger:
      - platform: state
        entity_id: sensor.oig_2206237016_spot_price_current_15min
      - platform: time_pattern
        minutes: "/15"  # Kontrola každých 15 minut
    action:
      - choose:
          # Velmi levná elektřina (< 1 Kč) = Nabíjení maximálně
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_spot_price_current_15min
                below: 1.0
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                below: 95
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Charge"
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "Off"  # Neprodávat za takovou cenu
                  acknowledgement: true

          # Levná elektřina (1-2 Kč) = Nabíjení pokud nízká baterie
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_spot_price_current_15min
                above: 1.0
                below: 2.0
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                below: 70
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Charge"
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "Limited"
                  limit: 3000
                  acknowledgement: true

          # Drahá elektřina (4-6 Kč) = Vybíjení
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_spot_price_current_15min
                above: 4.0
                below: 6.0
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                above: 40
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Discharge"
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "On"  # Maximální prodej
                  acknowledgement: true

          # Velmi drahá elektřina (> 6 Kč) = Vybíjení i při nižším SOC
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_spot_price_current_15min
                above: 6.0
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                above: 20
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Discharge"
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "On"
                  acknowledgement: true

          # Jinak Eco (normální cena 2-4 Kč)
          default:
            - service: oig_cloud.set_box_mode
              data:
                mode: "Eco"
                acknowledgement: true
            - service: oig_cloud.set_grid_delivery
              data:
                mode: "On"
                acknowledgement: true
```

---

## 🔋 Správa baterie

### 7. Ochrana před vybíjením

**Účel:** Přepnutí na Backup když baterie nízká.

```yaml
automation:
  - alias: "OIG: Backup při SOC < 20%"
    description: "Ochrana baterie při nízkém stavu"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        below: 20
        for:
          minutes: 2 # Stabilní 2 minuty
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Backup"
          acknowledgement: true
      - service: notify.mobile_app_phone
        data:
          message: "⚠️ Baterie pod 20% - přepnuto na Backup"
          data:
            priority: high
```

### 8. Nabití na 100% přes noc

**Účel:** Pravidelné plné nabití baterie.

```yaml
automation:
  - alias: "OIG: Nabití na 100% v neděli"
    description: "Každou neděli nabít baterii plně pro údržbu"
    trigger:
      - platform: time
        at: "02:00:00"
    condition:
      - condition: time
        weekday:
          - sun # Jen v neděli
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Charge"
          acknowledgement: true
      - wait_template: >
          {{ states('sensor.oig_2206237016_bat_soc')|float >= 100 }}
        timeout: "04:00:00" # Max 4 hodiny
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true
```

### 9. Maximalizace životnosti baterie

**Účel:** Udržovat SOC v optimálním rozsahu 20-80%.

```yaml
automation:
  - alias: "OIG: SOC management (20-80%)"
    description: "Udržovat baterii v optimálním rozsahu"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        above: 80
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        below: 20
    action:
      - choose:
          # SOC > 80% = Povolit vybíjení
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                above: 80
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Eco" # Normální provoz
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "On" # Povolit výkup
                  acknowledgement: true

          # SOC < 20% = Ochrana před vybíjením
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                below: 20
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Backup" # Nepoužívat baterii
                  acknowledgement: true
```

---

## 🔌 Grid delivery management

### 10. Výkup jen přes den

**Účel:** Dodávka do sítě pouze když je to výhodné.

```yaml
automation:
  - alias: "OIG: Grid delivery časové řízení"
    description: "ON přes den (6-22h), OFF v noci"
    trigger:
      - platform: time
        at: "06:00:00"
      - platform: time
        at: "22:00:00"
    action:
      - choose:
          - conditions:
              - condition: time
                after: "06:00:00"
                before: "22:00:00"
            sequence:
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "On"
                  acknowledgement: true
          default:
            - service: oig_cloud.set_grid_delivery
              data:
                mode: "Off"
                acknowledgement: true
```

### 11. Dynamický limit podle výkonu FVE

**Účel:** Omezení výkupu podle aktuální výroby.

```yaml
automation:
  - alias: "OIG: Dynamický grid limit"
    description: "Limit podle FVE výkonu"
    trigger:
      - platform: state
        entity_id: sensor.oig_2206237016_actual_fv_total
      - platform: time_pattern
        minutes: "/5"  # Kontrola každých 5 minut
    action:
      - choose:
          # Vysoký výkon FVE (> 5 kW) = Vysoký limit
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_actual_fv_total
                above: 5000
            sequence:
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "Limited"
                  limit: 8000
                  acknowledgement: true

          # Střední výkon (2-5 kW) = Střední limit
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_actual_fv_total
                above: 2000
                below: 5000
            sequence:
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "Limited"
                  limit: 5000
                  acknowledgement: true

          # Nízký výkon (< 2 kW) = Nízký limit
          default:
            - service: oig_cloud.set_grid_delivery
              data:
                mode: "Limited"
                limit: 2000
                acknowledgement: true
```

### 12. Vypnutí výkupu při negativních cenách

**Účel:** Ochrana před ztrátou při negativních spot cenách.

```yaml
automation:
  - alias: "OIG: Grid OFF při negativní ceně"
    description: "Vypnout výkup když cena záporná"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_export_price_current_15min
        below: 0
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "Off"
          acknowledgement: true
      - service: notify.mobile_app_phone
        data:
          message: "⚠️ Negativní ceny elektřiny - výkup vypnut"

  - alias: "OIG: Grid ON při kladné ceně"
    description: "Zapnout výkup když cena kladná"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_export_price_current_15min
        above: 0.5
        for:
          minutes: 15
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "On"
          acknowledgement: true
```

---

## 🌡️ Bojler automatizace

### 13. Inteligentní ohřev bojleru

**Účel:** Ohřev jen když je dostatek FVE nebo levná elektřina.

```yaml
automation:
  - alias: "OIG: Bojler podle FVE"
    description: "CBB režim když je dostatek FVE"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_actual_fv_total
        above: 3000 # Přebytek > 3 kW
        for:
          minutes: 5
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_2206237016_boiler_temperature
        below: 55 # Ohřívat jen pokud < 55°C
    action:
      - service: oig_cloud.set_boiler_mode
        data:
          mode: "CBB"
          acknowledgement: true
      - service: notify.mobile_app_phone
        data:
          message: "🌡️ Ohřev bojleru z FVE ({{ states('sensor.oig_2206237016_actual_fv_total')|int }} W)"
```

### 14. Vypnutí bojleru v noci

**Účel:** Úspora elektřiny, bojler jen přes den.

```yaml
automation:
  - alias: "OIG: Bojler denní režim"
    description: "CBB přes den, Manual v noci"
    trigger:
      - platform: time
        at: "06:00:00"
      - platform: time
        at: "22:00:00"
    action:
      - choose:
          - conditions:
              - condition: time
                after: "06:00:00"
                before: "22:00:00"
            sequence:
              - service: oig_cloud.set_boiler_mode
                data:
                  mode: "CBB"
                  acknowledgement: true
          default:
            - service: oig_cloud.set_boiler_mode
              data:
                mode: "Manual"
                acknowledgement: true
```

---

## 🔔 Notifikace a alerty

### 15. Alert při nízké baterii

```yaml
automation:
  - alias: "OIG: Alert nízká baterie"
    description: "Notifikace když SOC < 15%"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_2206237016_bat_soc
        below: 15
    action:
      - service: notify.mobile_app_phone
        data:
          message: "🔋 Kriticky nízká baterie ({{ states('sensor.oig_2206237016_bat_soc') }}%)"
          data:
            priority: high
            tag: "battery_low"
            actions:
              - action: "SET_BACKUP"
                title: "Přepnout na Backup"
```

### 16. Denní souhrn

```yaml
automation:
  - alias: "OIG: Denní report"
    description: "Večerní souhrn výroby a spotřeby"
    trigger:
      - platform: time
        at: "21:00:00"
    action:
      - service: notify.mobile_app_phone
        data:
          message: >
            ☀️ FVE dnes: {{ states('sensor.oig_2206237016_dc_in_fv_ad') }} kWh
            🔋 Nabito: {{ states('sensor.oig_2206237016_computed_batt_charge_energy_today') }} kWh
            🏠 Spotřeba: {{ states('sensor.oig_2206237016_ac_out_aco_ad') }} kWh
            📤 Výkup: {{ states('sensor.oig_2206237016_ac_in_ac_pd') }} kWh
            📥 Odběr: {{ states('sensor.oig_2206237016_ac_in_ac_ad') }} kWh
```

### 17. ServiceShield monitoring

```yaml
automation:
  - alias: "OIG: ServiceShield alert"
    description: "Upozornění na selhání služby"
    trigger:
      - platform: event
        event_type: oig_cloud_shield_failed
    action:
      - service: notify.mobile_app_phone
        data:
          message: "❌ ServiceShield: Selhání služby {{ trigger.event.data.service }}"
          data:
            priority: high
```

---

## 🌍 Sezónní úpravy

### 18. Letní vs. zimní strategie

```yaml
automation:
  - alias: "OIG: Sezónní režim"
    description: "Různá strategie podle ročního období"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - choose:
          # Léto (květen-srpen): Maximální využití FVE
          - conditions:
              - condition: template
                value_template: >
                  {{ now().month in [5, 6, 7, 8] }}
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Eco"
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "On"  # Maximální výkup
                  acknowledgement: true

          # Zima (listopad-únor): Ochrana baterie
          - conditions:
              - condition: template
                value_template: >
                  {{ now().month in [11, 12, 1, 2] }}
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Backup"  # Šetřit baterii
                  acknowledgement: true
              - service: oig_cloud.set_grid_delivery
                data:
                  mode: "Limited"
                  limit: 3000
                  acknowledgement: true

          # Jaro/Podzim: Balanced
          default:
            - service: oig_cloud.set_box_mode
              data:
                mode: "Eco"
                acknowledgement: true
            - service: oig_cloud.set_grid_delivery
              data:
                mode: "Limited"
                limit: 5000
                acknowledgement: true
```

---

## 🚀 Pokročilé scénáře

### 19. AI optimalizace podle předpovědi

```yaml
automation:
  - alias: "OIG: AI optimalizace"
    description: "Strategie podle solární předpovědi"
    trigger:
      - platform: time
        at: "05:00:00" # Ranní plánování
    action:
      - choose:
          # Předpověď slunečný den (> 25 kWh)
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_solar_forecast
                above: 25
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                below: 50
            sequence:
              # Nenabíjet baterii - bude dostatek FVE
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Eco"
                  acknowledgement: true
              - service: notify.mobile_app_phone
                data:
                  message: "☀️ Slunečný den předpovězen ({{ states('sensor.oig_2206237016_solar_forecast') }} kWh) - Eco režim"

          # Předpověď zataženo (< 10 kWh)
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_solar_forecast
                below: 10
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_bat_soc
                below: 70
            sequence:
              # Nabít baterii ze sítě (pokud levná elektřina)
              - condition: numeric_state
                entity_id: sensor.oig_2206237016_spot_price_current_15min
                below: 2.0
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Charge"
                  acknowledgement: true
              - service: notify.mobile_app_phone
                data:
                  message: "⛅ Zataženo předpovězeno ({{ states('sensor.oig_2206237016_solar_forecast') }} kWh) - nabíjím baterii"
```

### 20. Master automatizace

**Účel:** Centrální řízení všech automatizací.

```yaml
input_boolean:
  oig_automation_master:
    name: OIG Master Automation
    initial: true

automation:
  - alias: "OIG: MASTER kontroler"
    description: "Hlavní logika - spouští se každých 5 minut"
    trigger:
      - platform: time_pattern
        minutes: "/5"
    condition:
      - condition: state
        entity_id: input_boolean.oig_automation_master
        state: "on"
    action:
      - service: python_script.oig_optimizer
        data:
          soc: "{{ states('sensor.oig_2206237016_bat_soc')|float }}"
          fve: "{{ states('sensor.oig_2206237016_actual_fv_total')|float }}"
          spot: "{{ states('sensor.oig_2206237016_spot_price_current_15min')|float }}"
          forecast: "{{ states('sensor.oig_2206237016_solar_forecast')|float }}"
```

---

## 📚 Související dokumenty

- 📖 [README.md](../../README.md)
- 🎛️ [CONFIGURATION.md](CONFIGURATION.md)
- 📋 [ENTITIES.md](ENTITIES.md)
- 🔧 [SERVICES.md](SERVICES.md)
- ❓ [FAQ.md](FAQ.md)

---

**Příklady automatizací aktualizovány k verzi 2.0** 🤖
