[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![GitHub manifest version (path)](https://img.shields.io/github/manifest-json/v/psimsa/oig_cloud?filename=custom_components%2Foig_cloud%2Fmanifest.json)
![GitHub Release Date - Published_At](https://img.shields.io/github/release-date/psimsa/oig_cloud)
[![Validate with hassfest](https://github.com/psimsa/oig_cloud/actions/workflows/hassfest.yml/badge.svg)](https://github.com/psimsa/oig_cloud/actions/workflows/hassfest.yml)
[![HACS Action](https://github.com/psimsa/oig_cloud/actions/workflows/hacs.yml/badge.svg)](https://github.com/psimsa/oig_cloud/actions/workflows/hacs.yml)
[![CodeFactor](https://www.codefactor.io/repository/github/psimsa/oig_cloud/badge)](https://www.codefactor.io/repository/github/psimsa/oig_cloud)

---

# OIG Cloud Integrace pro Home Assistant

Tato integrace umožňuje propojení ČEZ Battery Box s Home Assistantem skrze OIG Cloud. Poskytuje základní informace o stavu baterie, výroby, spotřeby a historických dat. Obsahuje také potřebné entity pro použití stránky Energie a umožňuje také nastavit pracovní režim boxu a regulovat přetoky do distribuční sítě.

## Instalace

Nejjednodušší způsob instalace je přes [HACS](https://hacs.xyz/). V nastavení HACS zvolte "Integrations" a vyhledejte "OIG Cloud". Po instalaci je nutné restartovat Home Assistant.

## Konfigurace

Při konfiguraci je třeba zadat přihlašovací údaje do OIG Cloudu (stejné jako pro mobilní aplikaci). Volitelně lze také zakázat odesílání anonymní telemetrie.

![Konfigurace](./docs/login.png)

## Použití

Po instalaci a konfiguraci se vytvoří nové zařízení a entity. Všechny entity jsou dostupné v entitním registru a lze je tak přidat do UI. K aktualizaci dat dochází každou minutu.

## Energie

Integrace obsahuje statistické entity, které lze přímo využít v panelu Energie. Jde o položky:

- Dnešní odběr ze sítě
- Dnešní dodávka do sítě
- Dnešní výroba
- Dnešní nabíjení baterie
- Dnešní vybíjení baterie

![Energie](./docs/energy.png)

---

# ✨ Novinky ve verzi `1.6.0`

- **Nové rozšířené senzory**:

  - Přidány nové computed senzory pro sledování nabíjení a vybíjení baterie po dnech, měsících a rocích.
  - Přidáno měření energie nabíjení baterie **z FVE** a **ze sítě** zvlášť.

- **Nastavitelná frekvence aktualizace**:

  - Přidána možnost nastavit interval obnovy standardních a rozšířených statistik přímo v GUI Home Assistantu.

- **Přesnější měření energie**:

  - Výpočty energie baterie využívají vlastní integraci s podobným principem jako Riemannův součet (přesnější součet výkonu v čase).

- **Zlepšená přesnost měření bojleru**:

  - Výpočet výkonu bojleru nyní zohledňuje aktuální výkon FVE, domácí spotřebu a export do sítě.

- **Další vylepšení**:
  - Přidán reset statistik na konci dne, měsíce a roku.
  - Vylepšené logování pro snadnější debugování.
  - Úprava struktury kódu pro vyšší spolehlivost a rozšiřitelnost.

---

# 📜 Licence

Tento projekt je pod licencí MIT.

---
