# Průvodce konfigurací OIG Cloud

Tento průvodce vás krok po kroku provede nastavením OIG Cloud integrace do Home Assistant.

## 📋 Před začátkem

### Co budete potřebovat

✅ **Povinné:**

- Home Assistant verze **2023.1 nebo novější**
- Účet v [OIG Cloud portálu](https://portal.oig.cz)
- E-mail a heslo pro přihlášení
- OIG Battery Box připojený k internetu

⚠️ **Volitelné:**

- API klíč pro solární předpověď ([Forecast.solar](https://forecast.solar))
- Informace o distributorovi a dodavateli elektřiny (pro spot ceny)

### Odhadovaný čas nastavení

- 🚀 **Rychlé nastavení:** 2-3 minuty (pouze základní funkce)
- ⚙️ **Kompletní nastavení:** 5-10 minut (všechny funkce)

---

## 🎯 Krok 1: Přidání integrace

1. Otevřete Home Assistant
2. Přejděte do **Nastavení** → **Zařízení a služby**
3. Klikněte na tlačítko **+ Přidat integraci** (vpravo dole)
4. Do vyhledávacího pole napište: **OIG Cloud**
5. Vyberte **OIG Cloud** ze seznamu

---

## 🎉 Krok 2: Uvítání

První obrazovka vás přivítá a vysvětlí, co integrace umí:

```
🎉 Vítejte v průvodci nastavením OIG Cloud!

Tato integrace propojí váš OIG Box s Home Assistant a přidá:

⚡ Monitorování energie v reálném čase
🔧 Ovládání režimů (box, grid delivery, boiler)
🛡️ ServiceShield - ochrana před nechtěnými změnami
📊 Interaktivní dashboard s grafy
💰 Spot ceny elektřiny z burzy
☀️ Předpověď solární výroby

📝 Co budete potřebovat:
• E-mail a heslo k OIG Cloud účtu
• (Volitelně) API klíč pro solární předpověď

⏱️ Průvodce zabere ~2-3 minuty.
```

✅ Klikněte na **Pokračovat**

---

## 🔐 Krok 3: Přihlašovací údaje

Zadejte své přihlašovací údaje k OIG Cloud:

### E-mail

```
📧 Váš e-mail pro přihlášení do OIG Cloud portálu
```

**Kde najdu:**

- E-mail, který jste použili při registraci
- Najdete v aplikaci OIG nebo na portálu https://portal.oig.cz

**Příklad:** `jan.novak@example.com`

### Heslo

```
🔑 Heslo k vašemu OIG Cloud účtu
```

**Kde najdu:**

- Heslo, které jste si nastavili při registraci
- Pokud jste ho zapomněli, můžete ho resetovat na portálu

**💡 Tip:** Heslo je bezpečně uloženo v Home Assistant a je šifrované.

### Co se stane po kliknutí na "Pokračovat"?

Integrace ověří, že se může připojit k vašemu OIG Cloud účtu. Pokud se přihlášení nezdaří, zkontrolujte:

- ✅ Správně napsaný e-mail
- ✅ Správné heslo (pozor na velikost písmen)
- ✅ Funkční internetové připojení

---

## ⚙️ Krok 4: Základní nastavení

### Interval aktualizace (v sekundách)

```
⏱️ Jak často se mají data aktualizovat
```

**Výchozí hodnota:** `300` sekund (5 minut)

**💡 Doporučení:**
| Interval | Popis | Kdy použít |
|----------|-------|------------|
| **60s** | Rychlá aktualizace | Chcete vidět změny téměř okamžitě, nevadí vám vyšší zátěž |
| **300s** ⭐ | Vyvážené (doporučeno) | Ideální kompromis mezi aktuálností a zátěží |
| **600s** | Úspora dat | Nepotřebujete častou aktualizaci, šetříte zátěž API |

**⚠️ Poznámka:** Příliš krátký interval (pod 30s) může způsobit problémy s API.

---

## ✨ Krok 5: Výběr funkcí

Zde si vyberte, které pokročilé funkce chcete použít. Všechny můžete později změnit v nastavení integrace.

### 🛡️ ServiceShield (DOPORUČENO)

```
[✓] ServiceShield - ochrana před nechtěnými změnami
```

**Co to je:**

- Fronta požadavků - vidíte, co se právě děje
- Validace změn - kontrola, zda změna proběhla správně
- Historie - přehled všech provedených změn
- Ochrana - zabrání náhodným změnám režimů

**Proč zapnout:**

- ✅ Víte vždy, co se děje s vašim systémem
- ✅ Minimalizace chyb při ovládání
- ✅ Přehledná fronta v dashboardu

**Kdy NEzapnout:**

- ❌ Chcete co nejjednodušší setup bez extra funkcí

**💡 Doporučení:** **Zapnuto** - Výrazně zlepšuje UX ovládání

---

### ☀️ Solární předpověď

```
[ ] Solární předpověď (Forecast.solar)
```

**Co to je:**

- Odhad výroby FVE na dnes a zítra
- Graf předpovědi v dashboardu
- Využití pro optimalizaci nabíjení baterie

**Co potřebujete:**

- ⚠️ **API klíč** od Forecast.solar (zdarma)
- Zeměpisné souřadnice (automaticky z HA)

**Proč zapnout:**

- ✅ Předpověď pomáhá optimalizovat nabíjení
- ✅ Vidíte, kolik energie očekávat
- ✅ Lepší plánování spotřeby

**Kdy NEzapnout:**

- ❌ Nemáte API klíč (můžete přidat později)
- ❌ Nepotřebujete předpověď

**💡 Doporučení:** Zapnuto pokud máte API klíč

---

### 💰 Spot ceny elektřiny

```
[ ] Spot ceny elektřiny (OTE)
```

**Co to je:**

- Aktuální burzovní ceny za 15minutové intervaly
- Graf vývoje cen přes den
- Automatická kalkulace výkupních cen
- Predikce úspor

**Co potřebujete:**

- Nic! Funguje automaticky z veřejného OTE API

**Proč zapnout:**

- ✅ Vidíte, kdy je elektřina nejlevnější
- ✅ Můžete automatizovat nabíjení baterie
- ✅ Optimalizace spotřeby podle cen

**Kdy NEzapnout:**

- ❌ Nemáte dynamickou cenu elektřiny
- ❌ Nezajímají vás burz ovní ceny

**💡 Doporučení:** Zapnuto pokud máte dynamickou cenu nebo chcete optimalizovat spotřebu

---

### 📊 Webový dashboard

```
[✓] Webový energetický dashboard
```

**Co to je:**

- Interaktivní flow diagram (tok energie)
- Grafy výroby a spotřeby (ApexCharts)
- Ovládací panel pro změnu režimů
- ServiceShield fronta v reálném čase
- Detailní informace o systému

**Kde ho najdu:**

- 📍 Boční panel → **OIG Dashboard**

**Proč zapnout:**

- ✅ Nejlepší UX pro monitoring a ovládání
- ✅ Vše na jednom místě
- ✅ Krásný design přizpůsobený pro mobil i desktop

**Kdy NEzapnout:**

- ❌ Chcete používat pouze vlastní dashboard
- ❌ Preferujete klasické entity karty

**💡 Doporučení:** **Zapnuto** - Dashboard je hlavní hodnota této integrace!

---

## 🛡️ Krok 6: ServiceShield nastavení (volitelné)

Pokud jste zapnuli ServiceShield, můžete upravit pokročilá nastavení:

### Timeout pro dokončení změny

```
Timeout: [900] sekund (15 minut)
```

**Co to znamená:**

- Po zavolání služby (např. změna režimu) má systém tento čas na dokončení
- Pokud se změna neprovede, ServiceShield hlásí chybu

**💡 Doporučení:** `900s` (15 minut) je vhodné pro všechny změny

### Interval kontroly stavu

```
Interval: [15] sekund
```

**Co to znamená:**

- Jak často ServiceShield kontroluje, zda se změna provedla

**💡 Doporučení:** `15s` je optimální balance

**⚠️ Pro většinu uživatelů:** Nechte výchozí hodnoty!

---

## ☀️ Krok 7: Solární předpověď (volitelné)

Pokud jste zapnuli solární předpověď:

### API klíč

```
API klíč: [_____________________]
```

**Kde získat API klíč:**

1. Navštivte: [https://forecast.solar](https://forecast.solar)
2. Klikněte na **"Get API Key"** nebo **"Sign Up"**
3. Vytvořte bezplatný účet
4. Zkopírujte API klíč z dashboardu
5. Vložte ho sem

**💡 Tip:** Základní účet je zdarma a stačí pro běžné použití!

### Zeměpisné souřadnice

```
Zeměpisná šířka:  [50.0875] (automaticky)
Zeměpisná délka:  [14.4213] (automaticky)
```

**Co to je:**

- Poloha vaší FVE pro přesnou předpověď
- Automaticky vyplněno z Home Assistant
- Můžete upravit, pokud je box na jiné adrese

---

## 💰 Krok 8: Tarify (volitelné)

Pokud jste zapnuli spot ceny, můžete zadat svého distributora a dodavatele:

### Distributor elektřiny

```
Distributor: [_________________]
```

**Příklady:**

- ČEZ Distribuce
- EG.D (E.ON)
- PREdistribuce

**Kde najdu:**

- Na vyúčtování elektřiny
- V smlouvě o připojení

### Dodavatel elektřiny

```
Dodavatel: [_________________]
```

**Příklady:**

- ČEZ Prodej
- E.ON Energie
- Pražská energetika

**Kde najdu:**

- Na vyúčtování elektřiny
- V smlouvě o dodávce

**💡 Poznámka:** Toto je volitelné - spot ceny fungují i bez těchto údajů.

---

## ✅ Krok 9: Souhrn a dokončení

Na konci průvodce uvidíte přehled vaší konfigurace:

```
✅ Konfigurace dokončena!

👤 Účet: jan.novak@example.com
⏱️ Aktualizace: každých 300s

✨ Zapnuté funkce:
  🛡️ ServiceShield
  📊 Webový dashboard

📋 Další kroky:
  1. Integrace se připojí k OIG Cloud
  2. Entity se objeví v zařízení 'OIG Box'
  3. Dashboard: Boční panel → OIG Dashboard

💡 Všechno můžete změnit později v nastavení!
```

Klikněte na **Dokončit** a integrace se nastaví!

---

## 🎉 Po dokončení

### Co se stane:

1. **Vytvoří se zařízení**

   - Název: `OIG Box` (nebo podle ID vašeho boxu)
   - Najdete v: **Nastavení → Zařízení a služby → Zařízení**

2. **Přidají se entity**

   - ~50+ senzorů s aktuálními daty
   - Seznam entit: [ENTITIES.md](ENTITIES.md)

3. **Dashboard se aktivuje** (pokud zapnut)
   - Otevřete boční panel
   - Vyberte **OIG Dashboard**
   - Prohlédněte si flow diagram!

### První kroky:

1. **Zkontrolujte zařízení**

   - Přejděte do **Nastavení → Zařízení a služby → Zařízení**
   - Najděte **OIG Box**
   - Zkontrolujte, že entity mají hodnoty

2. **Otevřete dashboard** (pokud zapnut)

   - Boční panel → **OIG Dashboard**
   - Prozkoumejte flow diagram
   - Vyzkoušejte ovládání režimů

3. **Přidejte do energy dashboardu**

   - **Nastavení → Dashboardy → Energie**
   - Přidejte entity:
     - Výroba: `sensor.oig_XXXXX_dc_in_fv_ad`
     - Odběr ze sítě: `sensor.oig_XXXXX_ac_in_ac_ad`
     - Dodávka do sítě: `sensor.oig_XXXXX_ac_in_ac_pd`

4. **Vytvořte první automatizaci**
   - Viz: [AUTOMATIONS.md](AUTOMATIONS.md)

---

## 🔧 Změna nastavení

Chcete změnit konfiguraci? Žádný problém!

1. Přejděte do **Nastavení → Zařízení a služby**
2. Najděte **OIG Cloud**
3. Klikněte na **⋮ (tři tečky)** → **Znovu nakonfigurovat**
4. Proveďte změny
5. Uložte

**💡 Tip:** Změna nastavení nevyžaduje restart Home Assistant!

---

## ❓ Často kladené otázky

### Q: Musím mít všechny funkce zapnuté?

**A:** Ne! Začněte se základním nastavením a funkce přidávejte postupně podle potřeby.

### Q: Co když nemám API klíč pro solární předpověď?

**A:** Nevadí! Můžete ho přidat později. Integrace funguje i bez něj.

### Q: Můžu změnit interval aktualizace později?

**A:** Ano! V nastavení integrace (Znovu nakonfigurovat).

### Q: Dashboard nefunguje, co dělat?

**A:** Zkontrolujte:

1. Je dashboard zapnutý v konfiguraci?
2. Restartovali jste Home Assistant po instalaci?
3. Podívejte se do logů (Nastavení → Systém → Logy)

### Q: Entity nemají hodnoty

**A:** Počkejte 5-10 minut na první aktualizaci. Pokud problém přetrvává, viz [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## 🆘 Potřebujete pomoc?

- 📖 **Dokumentace:** [README.md](../../README.md)
- ❓ **FAQ:** [FAQ.md](FAQ.md)
- 🔧 **Řešení problémů:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- 💬 **Diskuse:** [GitHub Discussions](https://github.com/psimsa/oig_cloud/discussions)
- 🐛 **Hlášení chyb:** [GitHub Issues](https://github.com/psimsa/oig_cloud/issues)

---

**Gratulujeme! Vaše OIG Cloud integrace je připravena k použití!** 🎉
