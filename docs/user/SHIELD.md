# ServiceShield - Ochranný systém

Podrobná dokumentace ServiceShield systému pro ochranu API a správu front.

## 📋 Obsah

- [Co je ServiceShield](#co-je-serviceshield)
- [Proč je to potřeba](#proč-je-to-potřeba)
- [Jak to funguje](#jak-to-funguje)
- [Komponenty systému](#komponenty-systému)
- [Stavy fronty](#stavy-fronty)
- [Validace a bezpečnost](#validace-a-bezpečnost)
- [Monitoring a události](#monitoring-a-události)
- [Pokročilá konfigurace](#pokročilá-konfigurace)
- [Troubleshooting](#troubleshooting)

---

## 🛡️ Co je ServiceShield

ServiceShield je **inteligentní ochranný systém** který:

### Základní funkce

- 🛡️ **Chrání OIG API** před přetížením
- 📋 **Řadí volání do fronty** pro postupné zpracování
- ✅ **Validuje parametry** před odesláním
- 🔄 **Automaticky opakuje** selhané požadavky
- 📊 **Poskytuje monitoring** pro uživatele a vývojáře

### Proč existuje?

**Bez ServiceShield:**

```python
# Nebezpečné - rychlé volání
await set_box_mode("Eco")      # OK
await set_grid_delivery("On")   # OK
await set_boiler_mode("CBB")    # ❌ API ERROR: Too many requests
```

**S ServiceShield:**

```python
# Bezpečné - fronta
await shield.add(set_box_mode, "Eco")      # → Fronta [1]
await shield.add(set_grid_delivery, "On")   # → Fronta [1,2]
await shield.add(set_boiler_mode, "CBB")    # → Fronta [1,2,3]
# ✅ Postupné zpracování s prodlevami
```

---

## ⚠️ Proč je to potřeba

### Problém: API rate limiting

OIG API má omezení:

- **Max 1 request za 2 sekundy** na stejný endpoint
- **Max 10 requestů za minutu** celkem
- **Timeout 30 sekund** na response

**Bez ochrany:**

```
[00:00:00] set_box_mode → API
[00:00:00] set_grid_delivery → API
[00:00:00] set_boiler_mode → API
         ↓
❌ API vrací: 429 Too Many Requests
❌ Všechna volání selhala
❌ Uživatel neví co se děje
```

**S ServiceShield:**

```
[00:00:00] set_box_mode → Fronta [pending]
[00:00:00] set_grid_delivery → Fronta [pending]
[00:00:00] set_boiler_mode → Fronta [pending]
         ↓
[00:00:00] set_box_mode → API [running]
[00:00:02] set_box_mode ✅ [completed]
[00:00:02] set_grid_delivery → API [running]
[00:00:04] set_grid_delivery ✅ [completed]
[00:00:04] set_boiler_mode → API [running]
[00:00:06] set_boiler_mode ✅ [completed]
```

### Výhody ServiceShield

| Bez ServiceShield   | Se ServiceShield           |
| ------------------- | -------------------------- |
| ❌ Chyby API        | ✅ Žádné chyby             |
| ❌ Ztracené změny   | ✅ Všechny změny provedeny |
| ❌ Chaos ve fronteě | ✅ Transparentní fronta    |
| ❌ Žádný feedback   | ✅ Real-time monitoring    |
| ❌ Manuální retry   | ✅ Automatický retry       |

---

## ⚙️ Jak to funguje

### Životní cyklus požadavku

```
1. PŘÍJEM
   ↓
   Uživatel volá službu
   ↓
   service: oig_cloud.set_box_mode
   data: {mode: "Eco", acknowledgement: true}

2. VALIDACE
   ↓
   ServiceShield ověří:
   ✓ Povinné parametry přítomny?
   ✓ Hodnoty validní?
   ✓ acknowledgement = true?
   ↓
   [VALID] → Pokračovat
   [INVALID] → Chyba + stop

3. FRONTA
   ↓
   Přidat do fronty:
   {
     id: "req_123",
     service: "set_box_mode",
     params: {mode: "Eco"},
     status: "pending",
     timestamp: "2024-01-01 10:00:00"
   }
   ↓
   Fire event: oig_cloud_shield_queue_info
   ↓
   Dashboard zobrazí ve frontě ⏳

4. ZPRACOVÁNÍ
   ↓
   Čekat na frontu (min 2s mezi voláními)
   ↓
   Změnit status: "pending" → "running"
   ↓
   Fire event: oig_cloud_shield_queue_info
   ↓
   Dashboard zobrazí běžící ▶️
   ↓
   Odeslat na API
   ↓
   Čekat na odpověď (max 30s)

5. VÝSLEDEK
   ↓
   [SUCCESS]
   ↓
   Změnit status: "running" → "completed"
   ↓
   Fire event: oig_cloud_shield_completed
   ↓
   Dashboard zobrazí hotovo ✅
   ↓
   Aktualizovat entity
   ↓
   [FAIL]
   ↓
   Retry (max 3x)
   ↓
   Stále fail? → status: "failed"
   ↓
   Fire event: oig_cloud_shield_failed
   ↓
   Dashboard zobrazí chybu ❌
   ↓
   Log error

6. CLEANUP
   ↓
   Po 60 sekundách odstranit z fronty
   ↓
   Fire event: oig_cloud_shield_queue_info
```

---

## 🧩 Komponenty systému

### 1. ServiceShield Manager

**Soubor:** `custom_components/oig_cloud/service_shield.py`

**Odpovědnost:**

- Správa fronty
- Validace požadavků
- Řízení API volání
- Event systém
- Retry logika

**Klíčové metody:**

```python
class ServiceShieldManager:
    async def add_call(self, service, params):
        """Přidat volání do fronty"""

    async def _process_queue(self):
        """Zpracovat frontu (main loop)"""

    async def _validate_params(self, service, params):
        """Validovat parametry"""

    async def _start_call(self, item):
        """Spustit API volání"""

    async def _retry_call(self, item):
        """Opakovat selhané volání"""
```

### 2. Queue Storage

**Datová struktura:**

```python
{
    "id": "req_1704110400_123",
    "service": "set_box_mode",
    "params": {
        "mode": "Eco",
        "acknowledgement": True
    },
    "status": "pending",  # pending, running, completed, failed
    "timestamp": "2024-01-01 10:00:00",
    "retry_count": 0,
    "error": None
}
```

**Stavy:**

- `pending` - Čeká ve frontě
- `running` - Právě se zpracovává
- `completed` - Úspěšně dokončeno
- `failed` - Selhalo (po všech retry)

### 3. Event System

**Eventy:**

```yaml
# Fronta se změnila
event: oig_cloud_shield_queue_info
data:
  total: 3
  pending: 2
  running: 1
  completed: 0
  items: [...]

# Volání dokončeno
event: oig_cloud_shield_completed
data:
  service: "set_box_mode"
  params: {mode: "Eco"}
  duration: 2.3

# Volání selhalo
event: oig_cloud_shield_failed
data:
  service: "set_box_mode"
  params: {mode: "Eco"}
  error: "API timeout"
  retry_count: 3
```

### 4. Rate Limiter

**Pravidla:**

```python
MIN_DELAY_BETWEEN_CALLS = 2.0  # sekundy
MAX_RETRIES = 3
RETRY_DELAY = 5.0  # sekundy
API_TIMEOUT = 30.0  # sekundy
QUEUE_CLEANUP_DELAY = 60.0  # sekundy
```

**Implementace:**

```python
async def _process_queue(self):
    while True:
        if self._queue:
            item = self._queue[0]

            # Respektovat min delay
            if time.time() - self._last_call < MIN_DELAY_BETWEEN_CALLS:
                await asyncio.sleep(0.5)
                continue

            # Zpracovat
            await self._start_call(item)
            self._last_call = time.time()

        await asyncio.sleep(0.5)
```

---

## 📊 Stavy fronty

### Pending (⏳ Čeká)

**Co to znamená:**

- Požadavek přijat
- Validace OK
- Čeká na zpracování

**Dashboard:**

```
ServiceShield Fronta:
  ⏳ set_box_mode (Eco) - Pending
```

**Co dělat:**

- ✅ Nic, systém se o to postará
- ℹ️ Čas čekání závisí na frontě (2s × počet před vámi)

### Running (▶️ Běží)

**Co to znamená:**

- Požadavek se zpracovává
- API volání probíhá
- Čeká se na odpověď

**Dashboard:**

```
ServiceShield Fronta:
  ▶️ set_box_mode (Eco) - Running (2s)
```

**Co dělat:**

- ✅ Počkejte na dokončení (2-5s)
- ⚠️ Nepřerušujte (restart HA, reload integrace)

### Completed (✅ Hotovo)

**Co to znamená:**

- Požadavek úspěšně dokončen
- API potvrdilo změnu
- Entity aktualizovány

**Dashboard:**

```
ServiceShield Fronta:
  ✅ set_box_mode (Eco) - Completed
```

**Co dělat:**

- ✅ Hotovo! Zkontrolujte entity
- ℹ️ Zmizí z fronty za 60s

### Failed (❌ Selhalo)

**Co to znamená:**

- Požadavek selhal
- Retry 3x neúspěšný
- Chyba zalogována

**Dashboard:**

```
ServiceShield Fronta:
  ❌ set_box_mode (Eco) - Failed (API timeout)
```

**Co dělat:**

- 🔍 Zkontrolujte logy
- 🔄 Zkuste znovu později
- 📞 Kontaktujte support pokud přetrvává

---

## ✅ Validace a bezpečnost

### Validační pravidla

#### set_box_mode

```python
VALID_MODES = ["Eco", "Backup", "Charge", "Discharge"]

def validate_box_mode(params):
    if "mode" not in params:
        raise ValueError("Missing 'mode' parameter")

    if params["mode"] not in VALID_MODES:
        raise ValueError(f"Invalid mode: {params['mode']}")

    if "acknowledgement" not in params or not params["acknowledgement"]:
        raise ValueError("Missing or false 'acknowledgement'")

    return True
```

#### set_grid_delivery

```python
VALID_MODES = ["On", "Off", "Limited"]

def validate_grid_delivery(params):
    if "mode" not in params:
        raise ValueError("Missing 'mode' parameter")

    if params["mode"] not in VALID_MODES:
        raise ValueError(f"Invalid mode: {params['mode']}")

    if params["mode"] == "Limited":
        if "limit" not in params:
            raise ValueError("Missing 'limit' for Limited mode")

        limit = params["limit"]
        if not isinstance(limit, int) or limit < 0 or limit > 10000:
            raise ValueError(f"Invalid limit: {limit} (must be 0-10000)")

    if "acknowledgement" not in params or not params["acknowledgement"]:
        raise ValueError("Missing or false 'acknowledgement'")

    return True
```

#### set_boiler_mode

```python
VALID_MODES = ["CBB", "Manual"]

def validate_boiler_mode(params):
    if "mode" not in params:
        raise ValueError("Missing 'mode' parameter")

    if params["mode"] not in VALID_MODES:
        raise ValueError(f"Invalid mode: {params['mode']}")

    if "acknowledgement" not in params or not params["acknowledgement"]:
        raise ValueError("Missing or false 'acknowledgement'")

    return True
```

### Bezpečnostní mechanismy

**1. Rate limiting**

```python
# Max 1 call per 2 seconds
if time.time() - self._last_call < 2.0:
    await asyncio.sleep(2.0 - (time.time() - self._last_call))
```

**2. Timeout protection**

```python
# Max 30s per call
try:
    async with asyncio.timeout(30.0):
        response = await api_call()
except asyncio.TimeoutError:
    # Retry or fail
```

**3. Retry logic**

```python
# Max 3 retries with exponential backoff
for retry in range(3):
    try:
        response = await api_call()
        break
    except Exception:
        await asyncio.sleep(5.0 * (retry + 1))
```

**4. Queue overflow protection**

```python
# Max 50 items in queue
if len(self._queue) >= 50:
    raise ValueError("Queue full (max 50 items)")
```

---

## 📡 Monitoring a události

### Entity pro monitoring

```yaml
# Status ServiceShield
sensor.oig_XXXXX_service_shield_status:
  state: "Aktivní"
  attributes:
    enabled: true
    queue_size: 2
    last_activity: "2024-01-01 10:00:00"

# Počet ve frontě
sensor.oig_XXXXX_service_shield_queue:
  state: 2
  attributes:
    pending: 1
    running: 1
    completed: 0
    failed: 0

# Aktuální aktivita
sensor.oig_XXXXX_service_shield_activity:
  state: "set_box_mode"
  attributes:
    params: { mode: "Eco" }
    status: "running"
    duration: 2.3
```

### Event listening

**Automatizace na completed:**

```yaml
automation:
  - alias: "ServiceShield completed handler"
    trigger:
      - platform: event
        event_type: oig_cloud_shield_completed
    action:
      - service: notify.mobile_app
        data:
          message: "✅ {{ trigger.event.data.service }} dokončeno"
```

**Automatizace na failed:**

```yaml
automation:
  - alias: "ServiceShield failed handler"
    trigger:
      - platform: event
        event_type: oig_cloud_shield_failed
    action:
      - service: notify.mobile_app
        data:
          message: "❌ {{ trigger.event.data.service }} selhalo: {{ trigger.event.data.error }}"
          data:
            priority: high
```

### Dashboard monitoring

**Custom card:**

```yaml
type: entities
title: ServiceShield
entities:
  - entity: sensor.oig_XXXXX_service_shield_status
  - entity: sensor.oig_XXXXX_service_shield_queue
  - entity: sensor.oig_XXXXX_service_shield_activity
```

---

## ⚙️ Pokročilá konfigurace

### Vypnutí ServiceShield

**⚠️ NEDOPORUČENO** - bez ochrany API!

```
Nastavení → Zařízení a služby → OIG Cloud → KONFIGUROVAT
→ Krok ServiceShield → ☐ Povolit ServiceShield
```

**Důsledky:**

- ❌ Žádná ochrana API
- ❌ Možné chyby "Too many requests"
- ❌ Ztracené změny
- ❌ Žádný monitoring

**Kdy vypnout?**

- Debugging (krátkodobě)
- API má problémy a chcete direct access
- **NIKDY v produkci!**

### Úprava parametrů

**⚠️ Pouze pro pokročilé!**

**Soubor:** `custom_components/oig_cloud/service_shield.py`

```python
# Zpomalení (více ochranné, pomalejší)
MIN_DELAY_BETWEEN_CALLS = 5.0  # Z 2.0 na 5.0

# Zrychlení (méně ochranné, rychlejší)
MIN_DELAY_BETWEEN_CALLS = 1.0  # Z 2.0 na 1.0 (RISKY!)

# Více retry (pro nestabilní API)
MAX_RETRIES = 5  # Z 3 na 5

# Delší timeout (pro pomalé API)
API_TIMEOUT = 60.0  # Z 30.0 na 60.0

# Rychlejší cleanup
QUEUE_CLEANUP_DELAY = 30.0  # Z 60.0 na 30.0
```

**Restart po změně:**

```
Nastavení → Systém → Restart
```

---

## 🔧 Troubleshooting

### Fronta zaseknuta

**Problém:** Running item nepostupuje.

**Diagnostika:**

```bash
# Logy
grep "ServiceShield.*running" /config/home-assistant.log | tail -20

# Entity
sensor.oig_XXXXX_service_shield_activity
→ last_updated: ...
```

**Řešení:**

```
1. Počkejte 30s (možná dlouhý API response)
2. Reload integrace (Nastavení → Zařízení → OIG Cloud → Reload)
3. Restart HA (Nastavení → Systém → Restart)
```

### Všechna volání failují

**Problém:** Žádné volání neprochází.

**Diagnostika:**

```bash
grep "ServiceShield.*failed" /config/home-assistant.log
```

**Možné příčiny:**

- API nedostupné
- Špatné credentials
- Síťový problém
- Firewall

**Řešení:**

```
1. Test API: curl -v https://api.oig.cz
2. Test credentials: Options → Znovu zadat
3. Test v OIG app: Funguje mobilní aplikace?
4. Počkejte 5 min: API může být dočasně down
```

### Vysoká latence

**Problém:** Volání trvají dlouho.

**Měření:**

```bash
grep "ServiceShield.*completed.*duration" /config/home-assistant.log
```

**Normální:**

```
duration: 2.3s  ✅
duration: 3.1s  ✅
duration: 4.5s  ⚠️
```

**Problematické:**

```
duration: 15.2s  ❌
duration: 28.9s  ❌
duration: 30.0s  ❌ (timeout)
```

**Řešení:**

- Zkontrolujte rychlost internetu
- Zkontrolujte zatížení HA
- Zvyšte API_TIMEOUT (jen pokud nutné)

### Fronta přeplněna

**Problém:** "Queue full (max 50 items)"

**Příčina:**

- Moc automatizací volá služby najednou
- Smyčka v automatizaci
- API velmi pomalé

**Řešení:**

```yaml
# Optimalizujte automatizace
automation:
  - alias: "Optimalizováno"
    trigger:
      - platform: ...
    condition:
      # Přidejte condition pro prevenci smyčky
      - condition: template
        value_template: >
          {{ states('sensor.oig_XXXXX_box_prms_mode') != 'Eco' }}
    action:
      # Používejte "for" pro debounce
      - delay:
          seconds: 5
      - service: ...
```

---

## 📚 Související dokumenty

- 📖 [README.md](../../README.md)
- 🔧 [SERVICES.md](SERVICES.md)
- 📊 [DASHBOARD.md](DASHBOARD.md)
- 🛠️ [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- 🤖 [AUTOMATIONS.md](AUTOMATIONS.md)

---

**ServiceShield dokumentace aktualizována k verzi 2.0** 🛡️
