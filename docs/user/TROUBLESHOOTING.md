# Řešení problémů - Troubleshooting

Kompletní průvodce diagnostikou a řešením problémů s OIG Cloud integrací.

## 📋 Obsah

- [Diagnostické nástroje](#diagnostické-nástroje)
- [Problémy s instalací](#problémy-s-instalací)
- [Problémy s připojením](#problémy-s-připojením)
- [Problémy s entitami](#problémy-s-entitami)
- [Problémy se službami](#problémy-se-službami)
- [Problémy s dashboardem](#problémy-s-dashboardem)
- [ServiceShield problémy](#serviceshield-problémy)
- [Problémy s automatizacemi](#problémy-s-automatizacemi)
- [Výkonnostní problémy](#výkonnostní-problémy)
- [Logování a debugging](#logování-a-debugging)

---

## 🔍 Diagnostické nástroje

### 1. System Health

```
Nastavení → Systém → Opravy → System Health
```

**Co kontrolovat:**

- Home Assistant verze (2023.x+)
- Python verze (3.11+)
- Připojení k internetu
- Dostupný disk

### 2. Logy

```
Nastavení → Systém → Protokoly
```

**Filtr:**

```
custom_components.oig_cloud
```

**CLI:**

```bash
tail -f /config/home-assistant.log | grep oig_cloud
```

### 3. Developer Tools

**Stavy entit:**

```
Vývojářské nástroje → Stavy → Filtr: "oig_"
```

**Služby:**

```
Vývojářské nástroje → Služby → oig_cloud.*
```

**Events:**

```
Vývojářské nástroje → Events → Poslouchat: oig_cloud_*
```

### 4. Integration info

```
Nastavení → Zařízení a služby → OIG Cloud → ... → Systémové možnosti
```

**Co zkontrolovat:**

- Stav integrace (Načteno)
- Počet entit
- Verze integrace
- Chybové zprávy

---

## 📦 Problémy s instalací

### ❌ "Integration not found"

**Příčina:** Integrace není správně nainstalovaná.

**Řešení:**

1. **Zkontrolujte cestu:**

```bash
ls /config/custom_components/oig_cloud/
# Musí obsahovat: __init__.py, manifest.json
```

2. **HACS instalace:**

```
HACS → Integrace → OIG Cloud → Download
```

3. **Manuální instalace:**

```bash
cd /config/custom_components/
git clone https://github.com/your-repo/oig_cloud.git
```

4. **Restart HA:**

```
Nastavení → Systém → Restart
```

### ❌ "Invalid manifest"

**Příčina:** Poškozený `manifest.json`.

**Řešení:**

1. **Zkontrolujte soubor:**

```bash
cat /config/custom_components/oig_cloud/manifest.json
```

2. **Validujte JSON:**

```bash
python3 -m json.tool manifest.json
```

3. **Reinstalujte:**

```bash
rm -rf /config/custom_components/oig_cloud/
# Pak znovu nainstalujte
```

### ❌ "Missing dependencies"

**Příčina:** Chybějící Python knihovny.

**Řešení:**

1. **Zkontrolujte manifest.json:**

```json
"requirements": ["aiohttp>=3.8.0", ...]
```

2. **Manuální instalace:**

```bash
pip install aiohttp
```

3. **Restart HA:**

```
Nastavení → Systém → Restart
```

---

## 🔌 Problémy s připojením

### ❌ "Unable to connect to OIG API"

**Příčina:** Nedostupné API nebo špatné credentials.

**Diagnostika:**

1. **Zkontrolujte internet:**

```bash
ping api.oig.cz
```

2. **Test přihlášení:**

```
Options → Znovu zadejte username/password
```

3. **Zkontrolujte logy:**

```bash
grep "Authentication failed" /config/home-assistant.log
```

**Řešení:**

- ✅ Zkontrolujte username/password
- ✅ Zkontrolujte internetové připojení
- ✅ Zkontrolujte firewall/proxy
- ✅ Zkuste znovu za 5 minut (API může být dočasně nedostupné)

### ❌ "Connection timeout"

**Příčina:** Pomalé připojení nebo přetížené API.

**Řešení:**

1. **Zvyšte timeout v kódu:**

```python
# custom_components/oig_cloud/const.py
API_TIMEOUT = 30  # Zvýšte z 10 na 30
```

2. **Zkontrolujte rychlost internetu:**

```bash
speedtest-cli
```

3. **Zkuste jiné DNS:**

```
Router → DNS → 8.8.8.8, 8.8.4.4
```

### ❌ "SSL certificate verify failed"

**Příčina:** Problém s SSL certifikátem.

**Řešení:**

1. **Update certifikátů:**

```bash
apt-get update
apt-get install ca-certificates
```

2. **Zkontrolujte čas systému:**

```bash
date
# Musí být správný datum a čas
```

3. **Disable SSL verify (POUZE PRO DEBUGGING):**

```python
# NEDOPORUČENO pro produkci!
aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
```

---

## 📊 Problémy s entitami

### ❌ Entity jsou "unavailable"

**Příčina:** Data nejsou dostupná nebo integrace nefunguje.

**Diagnostika:**

1. **Zkontrolujte stav integrace:**

```
Nastavení → Zařízení a služby → OIG Cloud
```

2. **Zkontrolujte entity:**

```
Vývojářské nástroje → Stavy → oig_XXXXX_bat_soc
```

3. **Podívejte se do logů:**

```bash
grep "unavailable" /config/home-assistant.log | grep oig
```

**Řešení:**

**Varianta A: První spuštění**

```
Počkejte 5-10 minut na první sync
```

**Varianta B: Chybné přihlášení**

```
Options → Znovu zadejte credentials → Reload integration
```

**Varianta C: API nedostupné**

```
Zkontrolujte OIG mobilní aplikaci
→ Pokud nefunguje ani tam = API down
```

**Varianta D: Reload integrace**

```
Vývojářské nástroje → Služby → homeassistant.reload_config_entry
→ entry_id: [ID vaší integrace]
```

### ❌ Entity se neaktualizují

**Příčina:** Polling interval, API problém, nebo freeze.

**Diagnostika:**

1. **Zkontrolujte last_updated:**

```
Vývojářské nástroje → Stavy → sensor.oig_XXXXX_bat_soc
→ last_updated: 2024-01-01 10:30:00
```

2. **Zkontrolujte polling interval:**

```
Options → Interval aktualizace dat
```

3. **Zkontrolujte logy:**

```bash
grep "Coordinator update" /config/home-assistant.log
```

**Řešení:**

**Varianta A: Dlouhý interval**

```yaml
# Snižte interval
polling_interval: 60 # Z 300 na 60 sekund
```

**Varianta B: Force update**

```
Vývojářské nástroje → Služby → homeassistant.update_entity
→ entity_id: sensor.oig_XXXXX_bat_soc
```

**Varianta C: Restart integration**

```bash
# V Developer Tools → Services
service: homeassistant.reload_config_entry
data:
  entry_id: "..."
```

### ❌ Špatné hodnoty entit

**Příčina:** Chyba v API nebo parsing.

**Diagnostika:**

1. **Porovnejte s OIG aplikací:**

```
Otevřete OIG mobilní app
→ Porovnejte SOC, výkon FVE, atd.
```

2. **Zkontrolujte raw data:**

```python
# V logách hledejte:
"API response: {...}"
```

3. **Zkontrolujte atributy entity:**

```
Vývojářské nástroje → Stavy → sensor.oig_XXXXX_bat_soc
→ Attributes → unit_of_measurement, device_class
```

**Řešení:**

**Varianta A: Chyba v API**

```
Počkejte na další update (5-10 min)
→ Pokud přetrvává = kontaktujte OIG support
```

**Varianta B: Chyba v parsování**

```bash
# Nahlaste issue na GitHubu s logy:
grep "Parsing error" /config/home-assistant.log
```

---

## 🔧 Problémy se službami

### ❌ "Service not found"

**Příčina:** Integrace není načtená nebo služby nejsou registrované.

**Řešení:**

1. **Reload integrace:**

```
Nastavení → Zařízení a služby → OIG Cloud → Reload
```

2. **Restart HA:**

```
Nastavení → Systém → Restart
```

3. **Zkontrolujte dostupné služby:**

```
Vývojářské nástroje → Služby → Filtr: "oig_cloud"
```

### ❌ "Missing required parameter: acknowledgement"

**Příčina:** Zapomenuté `acknowledgement: true`.

**Řešení:**

```yaml
# ŠPATNĚ
service: oig_cloud.set_box_mode
data:
  mode: "Eco"

# SPRÁVNĚ
service: oig_cloud.set_box_mode
data:
  mode: "Eco"
  acknowledgement: true
```

### ❌ "Invalid mode value"

**Příčina:** Špatná hodnota parametru.

**Řešení:**

```yaml
# set_box_mode
mode: "Eco"  # Ne "eco" nebo "ECO"

# set_grid_delivery
mode: "On"   # Ne "on" nebo "ON"

# set_boiler_mode
mode: "CBB"  # Ne "cbb" nebo "Cbb"
```

**Povolené hodnoty:**

```yaml
set_box_mode:
  mode: ["Eco", "Backup", "Charge", "Discharge"]

set_grid_delivery:
  mode: ["On", "Off", "Limited"]

set_boiler_mode:
  mode: ["CBB", "Manual"]
```

### ❌ Služba selže s "API error"

**Příčina:** API odmítlo požadavek.

**Diagnostika:**

1. **Zkontrolujte logy:**

```bash
grep "API error" /config/home-assistant.log | tail -20
```

2. **Zkontrolujte ServiceShield frontu:**

```
Dashboard → ServiceShield panel → Failed items
```

3. **Test v OIG aplikaci:**

```
Zkuste stejnou změnu v mobilní aplikaci
→ Pokud nefunguje ani tam = problém na straně OIG
```

**Řešení:**

**Varianta A: API dočasně nedostupné**

```
Počkejte 5 minut a zkuste znovu
→ ServiceShield automaticky retry 3x
```

**Varianta B: Nevalidní požadavek**

```bash
# Zkontrolujte parametry v logách
grep "Request data" /config/home-assistant.log
```

**Varianta C: Box offline**

```
Zkontrolujte OIG aplikaci
→ Pokud Box offline = počkejte na obnovení
```

---

## 📊 Problémy s dashboardem

### ❌ Dashboard se nenačte (404)

**Příčina:** Soubor neexistuje nebo špatná cesta.

**Diagnostika:**

1. **Zkontrolujte existenci:**

```bash
ls -la /config/www/oig_cloud/dashboard.html
```

2. **Zkontrolujte URL:**

```
http://homeassistant.local:8123/local/oig_cloud/dashboard.html?entity=oig_XXXXX
                                 ^^^^^^ musí být "local", ne "www"
```

**Řešení:**

**Varianta A: Soubor chybí**

```bash
# Zkopírujte z integrace
cp /config/custom_components/oig_cloud/www/dashboard.html \
   /config/www/oig_cloud/
```

**Varianta B: Špatné oprávnění**

```bash
chmod 644 /config/www/oig_cloud/dashboard.html
```

**Varianta C: Restart HA**

```
Nastavení → Systém → Restart
```

### ❌ Dashboard je prázdný / bílá stránka

**Příčina:** JavaScript error nebo špatné entity ID.

**Diagnostika:**

1. **Otevřete Developer Console:**

```
F12 → Console → Hledejte errory
```

2. **Zkontrolujte entity ID v URL:**

```
?entity=oig_2206237016
         ^^^^^^^^^^^^^^ musí odpovídat vašemu Box ID
```

3. **Zkontrolujte entity:**

```
Vývojářské nástroje → Stavy → Filtr: "oig_2206237016"
```

**Řešení:**

**Varianta A: Špatné entity ID**

```
Změňte URL na správné ID:
?entity=oig_XXXXX
```

**Varianta B: JavaScript error**

```
Vyčistěte cache: Ctrl+Shift+R
```

**Varianta C: Staré cachedverze**

```
F12 → Network → Disable cache → Reload
```

### ❌ Dashboard se neaktualizuje

**Příčina:** Cache nebo entity unavailable.

**Řešení:**

1. **Force reload:**

```
Ctrl+Shift+R (Chrome/Firefox)
Cmd+Shift+R (Mac)
```

2. **Disable cache:**

```
F12 → Network → ☑ Disable cache
```

3. **Zkontrolujte entity:**

```
Vývojářské nástroje → Stavy → oig_XXXXX_bat_soc
→ Pokud unavailable = problém s entitami, ne dashboardem
```

### ❌ Control panel nefunguje

**Příčina:** ServiceShield neaktivní nebo JavaScript error.

**Diagnostika:**

1. **Zkontrolujte ServiceShield:**

```
sensor.oig_XXXXX_service_shield_status → Musí být "Aktivní"
```

2. **Console errors:**

```
F12 → Console → Hledejte "ServiceShield" errors
```

3. **Test služby manuálně:**

```
Vývojářské nástroje → Služby → oig_cloud.set_box_mode
```

**Řešení:**

**Varianta A: ServiceShield disabled**

```
Options → ☑ Povolit ServiceShield
```

**Varianta B: JavaScript error**

```
Reload dashboard: Ctrl+R
```

**Varianta C: Služby nefungují**

```
Viz sekce "Problémy se službami" výše
```

---

## 🛡️ ServiceShield problémy

### ❌ ServiceShield fronta zaseknuta

**Příčina:** API timeout nebo freeze.

**Diagnostika:**

1. **Zkontrolujte frontu:**

```
Dashboard → ServiceShield panel → Running item
```

2. **Zkontrolujte logy:**

```bash
grep "ServiceShield" /config/home-assistant.log | tail -50
```

3. **Zkontrolujte last_activity:**

```
sensor.oig_XXXXX_service_shield_activity
→ last_updated: ...
```

**Řešení:**

**Varianta A: Restart ServiceShield**

```python
# V Developer Tools → Services
service: homeassistant.reload_config_entry
```

**Varianta B: Clear queue**

```yaml
# Není veřejná služba, musíte restartovat integraci
Nastavení → Zařízení a služby → OIG Cloud → Reload
```

**Varianta C: Restart HA**

```
Nastavení → Systém → Restart
```

### ❌ "ServiceShield is disabled"

**Příčina:** ServiceShield je vypnutý v Options.

**Řešení:**

```
Nastavení → Zařízení a služby → OIG Cloud → KONFIGUROVAT
→ Krok ServiceShield → ☑ Povolit ServiceShield
```

### ❌ Všechna volání failují

**Příčina:** API nedostupné nebo špatné credentials.

**Diagnostika:**

```bash
grep "ServiceShield.*failed" /config/home-assistant.log
```

**Řešení:**

1. **Zkontrolujte API dostupnost:**

```bash
curl -v https://api.oig.cz
```

2. **Zkontrolujte credentials:**

```
Options → Znovu zadejte username/password
```

3. **Počkejte a zkuste znovu:**

```
API může být dočasně nedostupné
```

---

## 🤖 Problémy s automatizacemi

### ❌ Automatizace se nespouští

**Příčina:** Špatný trigger nebo condition.

**Diagnostika:**

1. **Test automatizace:**

```
Nastavení → Automatizace → [vyber] → ⋮ → Spustit
```

2. **Zkontrolujte logy:**

```bash
grep "Automation.*triggered" /config/home-assistant.log
```

3. **Zkontrolujte trace:**

```
Nastavení → Automatizace → [vyber] → ⋮ → Trasování
```

**Řešení:**

**Varianta A: Špatný trigger**

```yaml
# ŠPATNĚ - entity neexistuje
trigger:
  - platform: state
    entity_id: sensor.nonexistent

# SPRÁVNĚ
trigger:
  - platform: state
    entity_id: sensor.oig_XXXXX_bat_soc
```

**Varianta B: Nesplněná condition**

```yaml
# Zkontrolujte aktuální hodnoty
condition:
  - condition: numeric_state
    entity_id: sensor.oig_XXXXX_bat_soc
    below: 20 # Je skutečně SOC < 20%?
```

**Varianta C: Vypnutá automatizace**

```
Nastavení → Automatizace → [vyber] → ☑ Zapnuto
```

### ❌ Automatizace se spouští neustále

**Příčina:** Chybějící condition nebo smyčka.

**Řešení:**

```yaml
# Přidejte "for" pro debounce
trigger:
  - platform: numeric_state
    entity_id: sensor.oig_XXXXX_bat_soc
    below: 20
    for:
      minutes: 5 # Spustí až když < 20% po dobu 5 minut

# Přidejte condition pro prevenci smyčky
condition:
  - condition: template
    value_template: >
      {{ states('sensor.oig_XXXXX_box_prms_mode') != 'Backup' }}
```

---

## ⚡ Výkonnostní problémy

### ❌ Vysoké CPU usage

**Příčina:** Krátký polling interval nebo moc automatizací.

**Diagnostika:**

```bash
# Zkontrolujte load
top -p $(pgrep -f home-assistant)

# Profiling
python3 -m cProfile -o profile.stats hass
```

**Řešení:**

**Varianta A: Zvyšte interval**

```yaml
polling_interval: 600 # Z 60 na 600 sekund
```

**Varianta B: Vypněte nepoužívané featury**

```yaml
enable_solar: false
enable_pricing: false
enable_boiler: false
```

**Varianta C: Optimalizujte automatizace**

```yaml
# Používejte "for" pro debounce
# Minimalizujte počet triggerů
```

### ❌ Vysoké RAM usage

**Příčina:** Moc dat v cache nebo memory leak.

**Řešení:**

1. **Restart HA:**

```
Nastavení → Systém → Restart
```

2. **Zkontrolujte recorder:**

```yaml
# configuration.yaml
recorder:
  purge_keep_days: 3 # Snižte z 10 na 3
  exclude:
    entities:
      - sensor.oig_*_extended_* # Exclude extended sensors
```

3. **Update HA:**

```
Nastavení → Systém → Aktualizace
```

---

## 📝 Logování a debugging

### Povolení debug logů

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.oig_cloud: debug
```

**Restart HA:**

```
Nastavení → Systém → Restart
```

### Filtrování logů

```bash
# Všechny OIG logy
grep "oig_cloud" /config/home-assistant.log

# Pouze errory
grep "oig_cloud.*ERROR" /config/home-assistant.log

# ServiceShield logy
grep "ServiceShield" /config/home-assistant.log

# API volání
grep "API.*request" /config/home-assistant.log

# Live tail
tail -f /config/home-assistant.log | grep oig_cloud
```

### Export logů

```bash
# Export pro GitHub issue
grep "oig_cloud" /config/home-assistant.log > oig_debug.log

# Posledních 100 řádků
tail -100 /config/home-assistant.log | grep oig_cloud > oig_recent.log

# S timestampy
grep "oig_cloud" /config/home-assistant.log | grep "$(date +%Y-%m-%d)" > oig_today.log
```

### Debug v Pythonu

```python
# custom_components/oig_cloud/__init__.py
import logging
_LOGGER = logging.getLogger(__name__)

# Debug print
_LOGGER.debug(f"SOC value: {soc}, type: {type(soc)}")
_LOGGER.info(f"API request to: {url}")
_LOGGER.warning(f"Retrying after timeout")
_LOGGER.error(f"Failed to parse: {data}")
```

---

## 🆘 Kdy kontaktovat support

**Kontaktujte support když:**

1. ❌ Problém přetrvává i po troubleshootingu
2. ❌ Chyba v logách typu "Traceback" (Python crash)
3. ❌ API vrací neočekávané odpovědi
4. ❌ Entity mají trvale špatné hodnoty
5. ❌ ServiceShield fronta zaseknuta natrvalo

**Co připravit:**

- 📋 Popis problému
- 📝 Kroky k reprodukci
- 📊 Logy (debug level)
- 💻 Verze HA a integrace
- 🔍 Screenshot chyby

**Kontakt:**

- GitHub Issues: [github.com/your-repo/issues](https://github.com/your-repo/issues)
- Email: support@...
- Forum: [community.home-assistant.io](https://community.home-assistant.io)

---

## 📚 Související dokumenty

- 📖 [README.md](../../README.md)
- 🎛️ [CONFIGURATION.md](CONFIGURATION.md)
- 📊 [ENTITIES.md](ENTITIES.md)
- 🔧 [SERVICES.md](SERVICES.md)
- ❓ [FAQ.md](FAQ.md)

---

**Troubleshooting guide aktualizován k verzi 2.0** 🛠️
