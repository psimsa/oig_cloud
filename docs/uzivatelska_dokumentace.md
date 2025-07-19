# OIG Cloud 2.0.0-beta - Uživatelská dokumentace

## 📋 Obsah

1. [Úvod](#úvod)
2. [Instalace](#instalace)
3. [Nastavení integrace](#nastavení-integrace)
4. [ServiceShield](#serviceshield)
5. [Senzory a entity](#senzory-a-entity)
6. [Služby](#služby)
7. [Telemetrie a monitoring](#telemetrie-a-monitoring)
8. [Pokročilé funkce](#pokročilé-funkce)
9. [Řešení problémů](#řešení-problémů)
10. [Často kladené otázky](#často-kladené-otázky)

## 🎯 Úvod

OIG Cloud je integrace pro Home Assistant, která umožňuje ovládání a monitoring ČEZ Battery Box systémů. Verze 2.0.0-beta přináší kompletně přepsaný ServiceShield, telemetrii, solární předpověď a pokročilé statistiky.

### Hlavní funkce:

- **Monitoring energie** - sledování výroby, spotřeby a stavu baterie
- **ServiceShield** - ochrana před neočekávanými změnami
- **Telemetrie** - automatické odesílání dat pro analýzu
- **Solární předpověď** - predikce výroby na základě počasí
- **Spot ceny** - sledování aktuálních cen elektřiny
- **Pokročilé statistiky** - detailní analýzy a ROI kalkulace

## 🚀 Instalace

### Přes HACS (doporučeno)

1. Otevřete HACS v Home Assistant
2. Přejděte do sekce "Integrations"
3. Klikněte na "⋮" → "Custom repositories"
4. Přidejte URL: `https://github.com/martinhorak/oig_cloud`
5. Kategorie: "Integration"
6. Klikněte "Add"
7. Najděte "OIG Cloud" a klikněte "Download"
8. Restartujte Home Assistant

### Manuální instalace

1. Stáhněte nejnovější release z GitHub
2. Rozbalte do složky `config/custom_components/oig_cloud/`
3. Restartujte Home Assistant

## ⚙️ Nastavení integrace

### Základní nastavení

Po instalaci přejděte do **Nastavení** → **Zařízení a služby** → **Přidat integraci** → **OIG Cloud**.

#### Povinné údaje:

- **Uživatelské jméno** (`username`): Přihlašovací jméno do OIG portálu
- **Heslo** (`password`): Heslo do OIG portálu

#### Volitelná nastavení:

##### Základní konfigurace

- **Interval aktualizace** (`update_interval`)

  - **Výchozí**: 20 sekund
  - **Popis**: Jak často se aktualizují základní data
  - **Rozsah**: 10-300 sekund

- **Standardní interval skenování** (`standard_scan_interval`)

  - **Výchozí**: 30 sekund
  - **Popis**: Interval pro běžné senzory
  - **Doporučení**: 30-60 sekund

- **Rozšířený interval skenování** (`extended_scan_interval`)
  - **Výchozí**: 300 sekund (5 minut)
  - **Popis**: Interval pro statistické senzory
  - **Doporučení**: 300-600 sekund

##### Funkcionální nastavení

- **Povolit statistiky** (`enable_statistics`)

  - **Výchozí**: false
  - **Popis**: Zapne pokročilé statistiky a analýzy
  - **Upozornění**: Zvyšuje zátěž systému

- **Povolit cenové optimalizace** (`enable_pricing`)

  - **Výchozí**: false
  - **Popis**: Aktivuje cenové optimalizace na základě spot cen
  - **Vyžaduje**: `enable_spot_prices = true`

- **Povolit spot ceny** (`enable_spot_prices`)

  - **Výchozí**: false
  - **Popis**: Sledování aktuálních cen elektřiny na burze
  - **Funkce**: Real-time ceny, optimalizace, grafy

- **Interval aktualizace spot cen** (`spot_prices_update_interval`)
  - **Výchozí**: 3600 sekund (1 hodina)
  - **Popis**: Jak často se aktualizují spot ceny
  - **Rozsah**: 300-7200 sekund

##### Telemetrie a debugging

- **Zakázat telemetrii** (`no_telemetry`)

  - **Výchozí**: false
  - **Popis**: Vypne odesílání telemetrie do New Relic
  - **Upozornění**: Znemožní vzdálenou diagnostiku

- **Úroveň logování** (`log_level`)

  - **Výchozí**: INFO
  - **Možnosti**: DEBUG, INFO, WARNING, ERROR
  - **Popis**: Podrobnost logování do Home Assistant logů

- **Timeout** (`timeout`)
  - **Výchozí**: 30 sekund
  - **Popis**: Timeout pro API volání
  - **Rozsah**: 10-120 sekund

## 🛡️ ServiceShield

ServiceShield je systém ochrany před neočekávanými změnami v Battery Box systému.

### Jak ServiceShield funguje:

1. **Intercept** - zachytí všechna volání služeb
2. **Analýza** - zkontroluje očekávané změny
3. **Queue** - zařadí do fronty při kolizi
4. **Monitoring** - sleduje dokončení změn
5. **Telemetrie** - zaznamenává všechny akce

### ServiceShield senzory:

#### `service_shield_status`

- **Popis**: Aktuální stav ServiceShield
- **Hodnoty**:
  - `active` - ServiceShield běží
  - `inactive` - ServiceShield neaktivní
- **Ikona**: 🛡️

#### `service_shield_queue`

- **Popis**: Počet služeb ve frontě
- **Jednotka**: počet
- **Význam**: Kolik požadavků čeká na zpracování

#### `service_shield_activity`

- **Popis**: Aktuálně běžící služba
- **Hodnoty**:
  - `idle` - žádná aktivita
  - `set_boiler_mode` - mění se režim kotle
  - `set_box_mode` - mění se režim battery boxu
  - `set_grid_delivery` - mění se dodávka do sítě

### Atributy ServiceShield senzorů:

#### Společné atributy:

- `total_requests` - celkový počet požadavků
- `running_count` - počet běžících služeb
- `queue_length` - délka fronty
- `last_telemetry_update` - poslední aktualizace telemetrie

#### Běžící požadavky (`running_requests`):

```yaml
- service: "set_boiler_mode"
  description: "Změna boiler mode"
  changes:
    - "boiler_manual_mode: 'CBB' → 'Manuální' (nyní: 'CBB')"
  started_at: "10.07.2025 15:33:48"
  duration_seconds: 45.2
  is_primary: true
```

#### Požadavky ve frontě (`queued_requests`):

```yaml
- position: 1
  service: "set_box_mode"
  description: "Změna box mode"
  changes:
    - "box_prms_mode: 'Home 1' → 'Home 2'"
  queued_at: "10.07.2025 15:34:15"
  params:
    mode: "Home 2"
```

### ServiceShield služby:

#### `oig_cloud.shield_status`

- **Popis**: Vrátí aktuální stav ServiceShield
- **Parametry**: žádné
- **Událost**: `oig_cloud_shield_status`

#### `oig_cloud.shield_queue_info`

- **Popis**: Vrátí informace o frontě
- **Parametry**: žádné
- **Událost**: `oig_cloud_shield_queue_info`

## 📊 Senzory a entity

### Základní senzory baterie:

- `battery_level` - úroveň nabití baterie (%)
- `battery_power` - aktuální výkon baterie (W)
- `battery_energy_today` - energie za dnešní den (kWh)

### Solární senzory:

- `solar_power` - aktuální výkon solárních panelů (W)
- `solar_energy_today` - solární energie za den (kWh)
- `solar_forecast_tomorrow` - předpověď na zítra (kWh)

### Síťové senzory:

- `grid_power` - aktuální tok ze/do sítě (W)
- `grid_energy_imported` - odebraná energie ze sítě (kWh)
- `grid_energy_exported` - dodaná energie do sítě (kWh)

### Spotřební senzory:

- `house_consumption` - spotřeba domácnosti (W)
- `consumption_today` - celková spotřeba za den (kWh)

### Stavové senzory:

- `boiler_manual_mode` - režim kotle (CBB/Manuální)
- `box_prms_mode` - režim battery boxu (Home 1-3, UPS)
- `invertor_prms_to_grid` - dodávka do sítě (Zapnuto/Vypnuto)

### Spot ceny (pokud zapnuto):

- `spot_price_current` - aktuální spot cena (CZK/MWh)
- `spot_price_next_hour` - cena za hodinu (CZK/MWh)
- `spot_price_today_avg` - průměrná cena dnes (CZK/MWh)
- `spot_price_tomorrow_avg` - průměrná cena zítra (CZK/MWh)

### Statistické senzory (pokud zapnuto):

- `efficiency_battery` - efektivita baterie (%)
- `efficiency_solar` - efektivita solárních panelů (%)
- `roi_calculation` - výpočet návratnosti (roky)
- `carbon_footprint` - uhlíková stopa (kg CO2)

## 🔧 Služby

### Základní ovládací služby:

#### `oig_cloud.set_boiler_mode`

**Popis**: Nastavuje režim ohřevu vody
**Parametry**:

- `mode` (povinný):
  - `CBB` - ohřev z baterie
  - `Manual` - manuální režim
- `acknowledgement` (volitelný): `true` pro potvrzení

**Příklad**:

```yaml
service: oig_cloud.set_boiler_mode
data:
  mode: "Manual"
  acknowledgement: true
```

#### `oig_cloud.set_box_mode`

**Popis**: Nastavuje režim Battery Box
**Parametry**:

- `mode` (povinný):
  - `0` nebo `"Home 1"` - základní režim
  - `1` nebo `"Home 2"` - optimalizovaný režim
  - `2` nebo `"Home 3"` - úsporný režim
  - `3` nebo `"Home UPS"` - UPS režim

**Příklad**:

```yaml
service: oig_cloud.set_box_mode
data:
  mode: "Home 2"
```

#### `oig_cloud.set_grid_delivery`

**Popis**: Nastavuje dodávka energie do sítě
**Parametry** (jeden z):

- `mode`: `"Zapnuto"` nebo `"Vypnuto"`
- `limit`: číslo (W) - limit výkonu do sítě

**Příklady**:

```yaml
# Zapnutí/vypnutí dodávky
service: oig_cloud.set_grid_delivery
data:
  mode: "Zapnuto"

# Nastavení limitu
service: oig_cloud.set_grid_delivery
data:
  limit: 5000
```

### Servisní služby:

#### `oig_cloud.force_update`

**Popis**: Vynutí okamžitou aktualizaci dat
**Parametry**: žádné

#### `oig_cloud.reset_statistics`

**Popis**: Resetuje statistiky (pokud zapnuto)
**Parametry**: žádné

## 📈 Telemetrie a monitoring

### Co je telemetrie?

Telemetrie automaticky odesílá anonymní data o fungování integrace do New Relic pro:

- **Diagnostiku problémů** - rychlejší řešení chyb
- **Optimalizaci výkonu** - vylepšování integrace
- **Analýzu používání** - statistiky o funkcích

### Odesílaná data:

- **API volání** - jaké služby se volají a jak často
- **Chyby a varování** - problémy při komunikaci
- **Výkonnostní metriky** - rychlost odpovědí, timeouty
- **ServiceShield aktivita** - úspěšnost ochrany

### Osobní údaje:

- **NEODESÍLAJÍ SE** žádné osobní údaje
- **Uživatelské jméno** je hashované (SHA256)
- **Home Assistant ID** je hashované
- **IP adresa** není součástí dat

### Vypnutí telemetrie:

```yaml
# V konfiguraci integrace
no_telemetry: true
```

### Struktura telemetrických dat:

```json
{
  "timestamp": "2025-07-10T15:33:48.643974+02:00",
  "component": "service_shield",
  "event_type": "change_requested",
  "service_name": "oig_cloud.set_boiler_mode",
  "trace_id": "ebb3d8e3",
  "params": {
    "mode": "CBB",
    "acknowledgement": true
  },
  "api_endpoint": "Device.Set.Value.php",
  "api_table": "boiler_prms",
  "api_column": "manual",
  "api_value": 0
}
```

## 🌟 Pokročilé funkce

### Solární předpověď

**Požadavky**: Weather integrace v Home Assistant

**Konfigurace**:

```yaml
enable_statistics: true
```

**Funkce**:

- Předpověď výroby na 1-7 dní
- Optimalizace nabíjení baterie
- Plánování spotřeby podle předpovědi
- Grafy a trendy

### Spot ceny elektřiny

**Konfigurace**:

```yaml
enable_spot_prices: true
spot_prices_update_interval: 3600 # 1 hodina
```

**Funkce**:

- Real-time spot ceny z burzy
- Notifikace při výhodných cenách
- Automatické přepínání režimů
- Historické grafy a analýzy

### Cenová optimalizace

**Požadavky**: `enable_spot_prices: true`

**Konfigurace**:

```yaml
enable_pricing: true
```

**Funkce**:

- Automatické nabíjení v levných hodinách
- Vybíjení v drahých hodinách
- Kalkulace úspor
- Prediktivní algoritmy

### ROI kalkulace

**Požadavky**: `enable_statistics: true`

**Výpočty**:

- Návratnost investice do Battery Box
- Úspory na elektrické energii
- Porovnání s a bez systému
- Projekce na budoucnost

## 🔍 Řešení problémů

### Časté problémy:

#### Integrace se nepřipojí

**Příznaky**: Chyba při přihlášení
**Řešení**:

1. Ověřte uživatelské jméno a heslo
2. Zkontrolujte připojení k internetu
3. Zkuste zvýšit timeout na 60 sekund

#### ServiceShield nefunguje

**Příznaky**: Senzory ukazují "unavailable"
**Řešení**:

1. Restartujte Home Assistant
2. Zkontrolujte logy: `custom_components.oig_cloud.service_shield`
3. Ověřte, že máte správně nakonfigurovanou integraci

#### Vysoká zátěž CPU

**Příznaky**: Home Assistant pomalý
**Řešení**:

1. Zvyšte intervaly aktualizace:
   ```yaml
   update_interval: 60
   standard_scan_interval: 120
   extended_scan_interval: 600
   ```
2. Vypněte statistiky: `enable_statistics: false`
3. Vypněte spot ceny: `enable_spot_prices: false`

#### Telemetrie nefunguje

**Příznaky**: Chyby v logu o telemetrii
**Řešení**:

1. Zkontrolujte internetové připojení
2. Vypněte telemetrii: `no_telemetry: true`
3. Restartujte Home Assistant

### Debug logování:

```yaml
logger:
  default: warning
  logs:
    custom_components.oig_cloud: debug
    custom_components.oig_cloud.service_shield: debug
    custom_components.oig_cloud.api: debug
```

### Užitečné příkazy pro vývojáře:

```bash
# Sledování logů
tail -f home-assistant.log | grep oig_cloud

# Kontrola konfigurace
ha core check

# Restart integrace
ha core restart
```

## ❓ Často kladené otázky

### Q: Jsou moje data v bezpečí?

**A**: Ano. Odesíláme pouze anonymní technická data. Osobní údaje jako hesla nebo uživatelská jména jsou hashovány nebo se neodesílají vůbec.

### Q: Proč je integrace pomalá?

**A**: Zkuste zvýšit intervaly aktualizace nebo vypnout pokročilé funkce. OIG API má omezení rychlosti.

### Q: Můžu používat více Battery Box systémů?

**A**: Aktuálně není podporováno. Integrace je navržena pro jeden systém na instanci.

### Q: Jak vypnout ServiceShield?

**A**: ServiceShield se nedá vypnout, je součástí architektury integrace. Poskytuje ochranu před konflikty.

### Q: Co když mi nefunguje solární předpověď?

**A**: Ověřte, že máte nainstalovanou a funkční Weather integraci v Home Assistant.

### Q: Jak často se aktualizují spot ceny?

**A**: Standardně každou hodinu. Můžete změnit v nastavení `spot_prices_update_interval`.

### Q: Integrace spotřebovává moc paměti?

**A**: Vypněte statistiky a prodlužte intervaly. Beta verze může mít vyšší spotřebu paměti.

### Q: Podporuje integrace Home Assistant Core?

**A**: Ano, ale doporučujeme Home Assistant OS nebo Supervised pro plnou funkcionalnost.

### Q: Kdy bude stabilní verze 2.0.0?

**A**: Po důkladném testování beta verze a opravě všech nalezených problémů.

### Q: Kde najdu technickou podporu?

**A**:

- GitHub Issues: https://github.com/martinhorak/oig_cloud/issues
- Home Assistant Community: https://community.home-assistant.io/
- Dokumentace: https://github.com/martinhorak/oig_cloud/wiki

---

**Verze dokumentace**: 2.0.0-beta
**Datum aktualizace**: 10.07.2025
**Autor**: Martin Horák
**Licence**: MIT
