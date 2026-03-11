# ČHMÚ meteorologická varování (volitelný modul)

OIG Cloud integrace umí volitelně načítat meteorologické výstrahy z **ČHMÚ (CAP XML)** a vystavit je jako entity v Home Assistant. Podle výstrah může UI zobrazovat indikaci a integrace může data použít i pro plánování (pokud máte zapnuté příslušné části dashboardu).

## Zapnutí modulu

- Při prvotním nastavení (wizard): zapněte volbu `🌦️ Varování ČHMÚ`.
- Dodatečně v **Options**: zapněte `enable_chmu_warnings`.

## Co se vytváří v Home Assistant

Vytvářené entity jsou ve výchozím stavu typicky **vypnuté** (disabled), protože nejde o základní funkci – po zapnutí modulu si je aktivujte v UI podle potřeby.

Typicky dostupné entity:

- `sensor.oig_<box_id>_chmu_warning_level` – lokální úroveň výstrahy (0–4)
- `sensor.oig_<box_id>_chmu_warning_level_global` – nejvyšší úroveň výstrahy v ČR (0–4)
- `binary_sensor.oig_<box_id>_chmu_warning_active` – `on` pokud lokální úroveň ≥ 2 (Moderate)

Úrovně:

- `0` – žádné varování
- `1` – Minor (žluté)
- `2` – Moderate (oranžové)
- `3` – Severe (červené)
- `4` – Extreme (fialové)

## Poznámky

- Data se berou z veřejného ČHMÚ CAP feedu a jsou cacheovaná (typicky hodinová aktualizace).
- Lokální výstrahy vyžadují, aby integrace měla k dispozici rozumnou GPS polohu (např. z nastavení HA / Solar Forecast).
