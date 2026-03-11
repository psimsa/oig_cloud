# Zdroj telemetrie (Cloud vs. Local)

Integrace umí číst telemetrii ze dvou zdrojů:

- **Cloud (OIG Cloud API)** – standardní režim, nic dalšího nepotřebujete.
- **Local (lokální entity)** – pro rychlejší odezvu v Home Assistant a možnost fungovat i při dočasných problémech cloudu.

Tato stránka vysvětluje, co jednotlivé režimy dělají, jak je nastavit a jak ověřit, odkud integrace právě čte data.

## Režimy

Nastavení najdete v průvodci/rekonfiguraci v kroku **Interval aktualizace**:

- **☁️ Cloud only** (`data_source_mode=cloud_only`)
  - Integrace čte telemetrii výhradně z OIG Cloud API.
  - Doporučené, pokud nemáte lokální proxy.

- **🏠 Local only (fallback na cloud při výpadku)** (`data_source_mode=local_only`)
  - Primárně čte telemetrii z lokálních entit `sensor.oig_local_<box_id>_*`.
  - Pokud lokální proxy „ztichne“ déle než limit, integrace se dočasně přepne na cloud a po obnovení lokálních dat se vrátí zpět.

## Co je potřeba pro Local režim

Local režim předpokládá, že v Home Assistant existují:

- lokální telemetrické entity ve tvaru `sensor.oig_local_<box_id>_*`
- proxy status entity:
  - `sensor.oig_local_oig_proxy_proxy_status_last_data`
  - `sensor.oig_local_oig_proxy_proxy_status_box_device_id`

Pokud tyto entity neexistují (nebo jsou `unknown/unavailable`), integrace Local režim neaktivuje a zůstane na cloudu.

## Fallback na cloud (kdy a proč)

V Local režimu integrace sleduje „čerstvost“ lokálních dat:

- `Fallback na cloud po (minut)` (`local_proxy_stale_minutes`)
  - Pokud nepřijde žádná lokální aktualizace déle než tento limit, integrace přepne na cloud.

Když lokální data znovu začnou chodit, integrace se automaticky vrátí na local.

## Debounce (rychlost vs. počet aktualizací)

`Local event debounce (ms)` (`local_event_debounce_ms`) určuje, jak agresivně se mají aktualizovat entity při změnách lokálních senzorů:

- nižší hodnota = rychlejší reakce UI, ale více aktualizací
- vyšší hodnota = méně aktualizací, ale mírně pomalejší reakce

## Jak ověřit, odkud se data berou

Základní kontrola je přes entitu:

- `sensor.oig_XXXXX_data_source`
  - stav `cloud` nebo `local`
  - attributes:
    - `configured_mode` (nastavený režim)
    - `effective_mode` (aktuálně použitý režim)
    - `local_available` (zda jsou lokální data dostupná)
    - `last_local_data` (čas posledních lokálních dat)
    - `reason` (důvod rozhodnutí/fallbacku)

## Doporučené nastavení

- Začněte s **Cloud only**.
- Local režim zapínejte až když:
  - máte ověřené lokální entity (`sensor.oig_local_*`) a proxy status entity,
  - a chcete rychlejší UI nebo odolnost proti výpadkům cloudu.

