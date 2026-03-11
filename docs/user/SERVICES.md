# Služby - OIG Cloud

Kompletní dokumentace všech služeb pro ovládání systému.

## 📋 Obsah

- [set_box_mode](#set_box_mode---změna-režimu-box)
- [set_grid_delivery](#set_grid_delivery---ovládání-dodávky-do-sítě)
- [set_boiler_mode](#set_boiler_mode---ovládání-bojleru)
- [ServiceShield](#serviceshield)
- [Příklady použití](#příklady-použití)

---

## 🔧 set_box_mode - Změna režimu Box

Přepíná pracovní režim invertoru.

### Parametry

| Parametr          | Typ     | Povinný | Hodnoty                        | Popis           |
| ----------------- | ------- | ------- | ------------------------------ | --------------- |
| `mode`            | string  | ✅      | Eco, Backup, Charge, Discharge | Režim Box       |
| `acknowledgement` | boolean | ✅      | true/false                     | Potvrzení změny |

### Režimy Box

#### 🌿 Eco (Ekonomický)

**Kdy použít:** Standardní provoz, optimalizace spotřeby

**Chování:**

- ✅ Preferuje solární výrobu
- ✅ Používá baterii při nedostatku FVE
- ✅ Nabíjí baterii z přebytků
- ✅ Odebírá ze sítě jen při nutnosti
- ✅ Dodává přebytky do sítě (pokud je Grid delivery ON)

**Příklad:**

```yaml
service: oig_cloud.set_box_mode
data:
  mode: "Eco"
  acknowledgement: true
```

#### 🛡️ Backup (Záloha)

**Kdy použít:** Příprava na výpadek, ochrana baterie

**Chování:**

- 🔋 Nabíjí baterii na 100%
- 🚫 NEPOUŽÍVÁ baterii pro spotřebu
- ✅ Spotřeba z FVE + síť
- ✅ Dodává přebytky do sítě
- ⚡ Baterie připravena pro výpadek

**Příklad:**

```yaml
service: oig_cloud.set_box_mode
data:
  mode: "Backup"
  acknowledgement: true
```

**⚠️ Upozornění:**

- Zvyšuje odběr ze sítě
- Baterie se nevybíjí
- Vhodné pro krátké období

#### ⚡ Charge (Nabíjení)

**Kdy použít:** Nabíjení při levné elektřině

**Chování:**

- 🔌 Nabíjí ze sítě + FVE
- ⚡ Maximální nabíjecí výkon
- 📊 Ignoruje spotřebu domu
- 💰 Ideální při spot cena < 1.5 Kč/kWh

**Příklad:**

```yaml
service: oig_cloud.set_box_mode
data:
  mode: "Charge"
  acknowledgement: true
```

**💡 Tip:**
Kombinovat s automatizací podle spot ceny:

```yaml
automation:
  - alias: "Nabíjení při levné elektřině"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        below: 1.5
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        below: 90
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Charge"
          acknowledgement: true
```

#### 🔋 Discharge (Vybíjení)

**Kdy použít:** Vybíjení při vysoké ceně elektřiny

**Chování:**

- 💰 Vybíjí baterii do sítě
- 📤 Maximální dodávka do sítě
- ⚡ Spotřeba domu z baterie
- 💸 Ideální při spot cena > 4 Kč/kWh

**Příklad:**

```yaml
service: oig_cloud.set_box_mode
data:
  mode: "Discharge"
  acknowledgement: true
```

**💡 Tip:**
Kombinovat s automatizací podle spot ceny:

```yaml
automation:
  - alias: "Vybíjení při drahé elektřině"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        above: 4.0
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        above: 30
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Discharge"
          acknowledgement: true
```

### acknowledgement - Co to znamená?

`acknowledgement: true` znamená:

- ✅ Potvrzuji, že vím co dělám
- ✅ Rozumím důsledkům změny
- ✅ Beru na vědomí možné dopady

**Proč je to povinné?**

- Změna režimu má velký dopad na spotřebu
- Může zvýšit náklady (Charge ze sítě)
- Může snížit životnost baterie
- Chráníme vás před neúmyslnými změnami

---

## 🔌 set_grid_delivery - Ovládání dodávky do sítě

Řídí režim dodávky přebytečné energie do distribuční sítě.

### Parametry

| Parametr          | Typ     | Povinný | Hodnoty          | Popis                       |
| ----------------- | ------- | ------- | ---------------- | --------------------------- |
| `mode`            | string  | ✅      | On, Off, Limited | Režim dodávky               |
| `limit`           | integer | ⚠️      | 0-10000          | Limit v W (jen pro Limited) |
| `acknowledgement` | boolean | ✅      | true/false       | Potvrzení změny             |

### Režimy Grid Delivery

#### ✅ On (Zapnuto)

**Kdy použít:** Maximální výkup, žádné omezení

**Chování:**

- ✅ Neomezená dodávka do sítě
- 💰 Maximální zisk z výkupu
- ⚡ Veškeré přebytky jdou do sítě

**Příklad:**

```yaml
service: oig_cloud.set_grid_delivery
data:
  mode: "On"
  acknowledgement: true
```

#### ❌ Off (Vypnuto)

**Kdy použít:** Nulový výkup, jen spotřeba

**Chování:**

- 🚫 ŽÁDNÁ dodávka do sítě
- 🔋 Přebytky do baterie
- 🌡️ Přebytky do bojleru
- 🔌 Zbytek se omezí (invertor)

**Příklad:**

```yaml
service: oig_cloud.set_grid_delivery
data:
  mode: "Off"
  acknowledgement: true
```

**⚠️ Upozornění:**

- Přebytky se "ztratí" pokud baterie plná
- Vhodné při negativních cenách
- Bojler může pomoct využít přebytky

#### ⚡ Limited (S omezením)

**Kdy použít:** Částečný výkup, kontrola dodávky

**Chování:**

- 📊 Dodávka omezena na `limit` W
- 🔋 Zbytek do baterie
- 💰 Kontrola nad výkupem

**Příklad:**

```yaml
service: oig_cloud.set_grid_delivery
data:
  mode: "Limited"
  limit: 5000
  acknowledgement: true
```

**💡 Tip - Proč omezovat?**

1. **Distributor má limit:** Např. 10 kW povolená dodávka
2. **Optimalizace výkupu:** Část do baterie, část na prodej
3. **Ochrana sítě:** Při přetížení distribučky

### Limit parametr

**Jak ho nastavit:**

- 🔍 Zjistěte max. povolený výkup (smlouva s distributorem)
- 📊 Nastavte limit trochu níž (rezerva)
- ⚡ Typicky: 5000-10000 W

**Příklady:**

```yaml
# Malá FVE, omezení 5 kW
limit: 5000

# Střední FVE, omezení 10 kW
limit: 10000

# Žádný výkup
limit: 0  # Raději použijte mode: "Off"
```

---

## 🌡️ set_boiler_mode - Ovládání bojleru

Přepíná režim ohřevu bojleru (pouze pokud máte bojler OIG).

### Parametry

| Parametr          | Typ     | Povinný | Hodnoty     | Popis           |
| ----------------- | ------- | ------- | ----------- | --------------- |
| `mode`            | string  | ✅      | CBB, Manual | Režim bojleru   |
| `acknowledgement` | boolean | ✅      | true/false  | Potvrzení změny |

### Režimy bojleru

#### 🤖 CBB (Inteligentní)

**Kdy použít:** Standardní provoz, auto optimalizace

**Chování:**

- 🤖 Automatické řízení
- ☀️ Ohřev z přebytků FVE
- 🔋 Preferuje FVE před baterií
- 💰 Optimalizace nákladů
- 📊 Učení se vašich zvyků

**Příklad:**

```yaml
service: oig_cloud.set_boiler_mode
data:
  mode: "CBB"
  acknowledgement: true
```

**💡 Výhody:**

- Automatické využití přebytků
- Nižší náklady na ohřev
- Žádné ruční zásahy

#### 👤 Manual (Manuální)

**Kdy použít:** Vlastní řízení, speciální potřeby

**Chování:**

- 👤 Ručnímá kontrola
- 🔌 Ohřev na požádání
- ⚡ Žádná automatika
- 📊 Vy rozhodujete kdy a jak

**Příklad:**

```yaml
service: oig_cloud.set_boiler_mode
data:
  mode: "Manual"
  acknowledgement: true
```

**⚠️ Upozornění:**

- Musíte řídit sami
- Přebytky se nevyužijí automaticky
- Vyšší náklady na ohřev

---

## 🧰 Další služby (dashboard / diagnostika)

### 🌞 update_solar_forecast

Manuálně aktualizuje data solární předpovědi (forecast.solar), bez ohledu na interval.

```yaml
service: oig_cloud.update_solar_forecast
data: {}
```

### 🔁 check_balancing

Spustí manuální kontrolu balancování (diagnostika) a vrátí výsledek v odpovědi služby.

```yaml
service: oig_cloud.check_balancing
data:
  box_id: "2206237016"   # volitelné
  force: false          # volitelné
```

### 💾 save_dashboard_tiles / 📥 get_dashboard_tiles

Používá OIG Dashboard pro synchronizaci „Vlastních dlaždic“ mezi zařízeními/prohlížeči.

Poznámka: Běžný uživatel to typicky nemusí volat ručně – řeší to dashboard.

---

## 🛡️ ServiceShield

**Co je ServiceShield?**

- 🛡️ Ochranný systém pro API volání
- 📋 Fronta služeb
- ✅ Validace před odesláním
- ⏱️ Prevence přetížení API

**Jak to funguje:**

1. **Zavoláte službu** (`set_box_mode`)
2. **ServiceShield přidá do fronty**
3. **Ověří parametry**
4. **Odešle na API** (max 1 za 2s)
5. **Čeká na potvrzení**
6. **Aktualizuje entitu**

**Výhody:**

- ✅ Žádné chyby API
- ✅ Žádné přetížení
- ✅ Viditelná fronta na dashboardu
- ✅ Retry při selhání

**Monitoring:**

- 📊 Dashboard: ServiceShield panel
- 🔍 Entity: `sensor.oig_XXXXX_service_shield_queue`
- 📋 Logy: `custom_components/oig_cloud/service_shield.py`

---

## 💡 Příklady použití

### 1. Automatizace podle času

#### Eco přes den, Backup v noci

```yaml
automation:
  - alias: "Eco režim ráno"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true

  - alias: "Backup večer"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Backup"
          acknowledgement: true
```

### 2. Automatizace podle spot ceny

#### Nabíjení při levné, vybíjení při drahé

```yaml
automation:
  - alias: "Charge při spot < 1.5"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        below: 1.5
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        below: 90
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Charge"
          acknowledgement: true

  - alias: "Discharge při spot > 4"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        above: 4.0
    condition:
      - condition: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        above: 30
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Discharge"
          acknowledgement: true

  - alias: "Zpět na Eco při normální ceně"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_spot_price_current_15min
        above: 1.5
        below: 4.0
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Eco"
          acknowledgement: true
```

### 3. Automatizace podle SOC

#### Backup při nízké baterii

```yaml
automation:
  - alias: "Backup při SOC < 20%"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_bat_soc
        below: 20
    action:
      - service: oig_cloud.set_box_mode
        data:
          mode: "Backup"
          acknowledgement: true
      - service: notify.mobile_app
        data:
          message: "⚠️ Baterie pod 20%, přepnuto na Backup"
```

### 4. Grid delivery podle výkupu

#### OFF při negativních cenách

```yaml
automation:
  - alias: "Grid OFF při spot < 0"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_export_price_current_15min
        below: 0
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "Off"
          acknowledgement: true
      - service: notify.mobile_app
        data:
          message: "⚡ Negativní ceny, výkup vypnut"

  - alias: "Grid ON při kladných cenách"
    trigger:
      - platform: numeric_state
        entity_id: sensor.oig_XXXXX_export_price_current_15min
        above: 0.5
    action:
      - service: oig_cloud.set_grid_delivery
        data:
          mode: "On"
          acknowledgement: true
```

### 5. Bojler automatizace

#### Inteligentní bojler přes den

```yaml
automation:
  - alias: "Bojler CBB přes den"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: oig_cloud.set_boiler_mode
        data:
          mode: "CBB"
          acknowledgement: true

  - alias: "Bojler Manual v noci"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: oig_cloud.set_boiler_mode
        data:
          mode: "Manual"
          acknowledgement: true
```

### 6. Komplexní scénář

#### Maximalizace zisku

```yaml
automation:
  - alias: "Optimální strategie"
    trigger:
      - platform: time_pattern
        minutes: "/15"  # Každých 15 minut
    action:
      - choose:
          # Levná elektřina + nízká baterie = Nabíjení
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_XXXXX_spot_price_current_15min
                below: 1.5
              - condition: numeric_state
                entity_id: sensor.oig_XXXXX_bat_soc
                below: 80
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Charge"
                  acknowledgement: true

          # Drahá elektřina + vysoká baterie = Vybíjení
          - conditions:
              - condition: numeric_state
                entity_id: sensor.oig_XXXXX_spot_price_current_15min
                above: 4.0
              - condition: numeric_state
                entity_id: sensor.oig_XXXXX_bat_soc
                above: 40
            sequence:
              - service: oig_cloud.set_box_mode
                data:
                  mode: "Discharge"
                  acknowledgement: true

          # Jinak Eco
          default:
            - service: oig_cloud.set_box_mode
              data:
                mode: "Eco"
                acknowledgement: true
```

---

## 📊 Porovnání režimů

### Box režimy

| Režim         | Nabíjení        | Vybíjení   | Dodávka do sítě | Použití                |
| ------------- | --------------- | ---------- | --------------- | ---------------------- |
| **Eco**       | FVE + přebytky  | Ano (auto) | Ano             | Standardní 🌿          |
| **Backup**    | FVE + síť       | Ne         | Ano             | Příprava na výpadek 🛡️ |
| **Charge**    | FVE + síť (max) | Ne         | Ne              | Levná elektřina ⚡     |
| **Discharge** | FVE             | Ano (max)  | Ano             | Drahá elektřina 💰     |

### Grid delivery režimy

| Režim       | Dodávka   | Omezení     | Použití            |
| ----------- | --------- | ----------- | ------------------ |
| **On**      | Neomezená | Ne          | Maximální výkup ✅ |
| **Off**     | Žádná     | Ano (0W)    | Nulový výkup ❌    |
| **Limited** | Omezená   | Ano (limit) | Částečný výkup ⚡  |

---

## ❓ Časté otázky

**Q: Co se stane když zapomenu `acknowledgement`?**
A: Služba selže s chybou.

**Q: Mohu volat více služeb najednou?**
A: Ano, ServiceShield je seřadí do fronty.

**Q: Jak dlouho trvá změna režimu?**
A: 2-5 sekund (API + synchronizace).

**Q: Co když služba selže?**
A: ServiceShield automaticky opakuje (3x).

**Q: Vidím změnu na dashboardu?**
A: Ano, okamžitě ve frontě, pak po potvrzení v entitách.

**Q: Mohu volat služby z automatizací?**
A: Ano, běžný use case.

**Q: Jak nastavit limit Grid delivery?**
A: Zjistěte max. povolený výkup ze smlouvy s distributorem.

**Q: Co je CBB režim bojleru?**
A: Clever Battery & Boiler - inteligentní řízení.

---

## 🆘 Podpora

- 📖 [README.md](../../README.md)
- 📊 [ENTITIES.md](ENTITIES.md)
- 🎛️ [DASHBOARD.md](DASHBOARD.md)
- ❓ [FAQ.md](FAQ.md)
- 🔧 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**Dokumentace služeb aktualizována k verzi 2.0** 🚀
