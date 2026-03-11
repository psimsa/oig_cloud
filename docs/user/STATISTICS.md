# Statistiky, metriky a diagnostika (plánovač, baterie, profiling)

Tato stránka popisuje nejdůležitější metriky, které integrace počítá nad daty z Battery Boxu. Většina z nich se zobrazuje v OIG Dashboardu v sekci „Predikce a statistiky“.

## Efektivita baterie (round‑trip)

Entita: `sensor.oig_XXXXX_battery_efficiency` (stav v %)

Co to znamená:

- **round‑trip efficiency** = kolik energie se vám reálně vrátí z baterie vzhledem k energii, kterou jste do ní nabil(a)
- integrace počítá efektivitu primárně za **minulý kompletní měsíc** (stabilní metrika) a paralelně průběžně i za aktuální měsíc

Výpočet (zjednodušeně):

- `efficiency = (effective_discharge / charge) * 100`
- `effective_discharge = discharge - ΔE_battery`

Kde:

- `charge`/`discharge` jsou měsíční energie nabití/vybití (kWh)
- `ΔE_battery` je změna uložené energie v baterii mezi začátkem a koncem období

## Kvalita baterie / SoH (Battery health)

Entita: `sensor.oig_XXXXX_battery_health` (stav typicky SoH %)

Co to dělá:

- 1× denně analyzuje historii (recorder) a hledá „čisté“ nabíjecí intervaly, kde SOC monotonicky roste alespoň o ~50 %
- z takového intervalu odhadne reálnou kapacitu a z ní odvodí SoH (State of Health)
- ukládá výsledky do HA storage a zobrazuje průměry/trendy (např. 30 dní)

Poznámky:

- Výsledky jsou orientační (závisí na kvalitě historických dat a „čistotě“ cyklů).
- Pokud HA neukládá historii (recorder) nebo chybí relevantní entity, SoH nebude k dispozici.

## Profiling spotřeby (adaptivní profily, 72h)

Entita: `sensor.oig_XXXXX_adaptive_load_profiles`

Co to dělá:

- vytváří adaptivní profily spotřeby z historických dat (typicky po hodinách)
- průběžně hledá nejpodobnější profil a z něj odvozuje predikci spotřeby na horizontu ~72 hodin

K čemu to je:

- plánovač může používat realistickou predikci spotřeby (místo „plochého“ odhadu)
- dashboard umí ukázat, jaký profil byl vybrán a proč

## Balancování baterie

Entita: `sensor.oig_XXXXX_battery_balancing`

Co to znamená:

- Battery Box/BMS občas potřebuje „balancovat“ (vyrovnávat články) – typicky se to děje při vyšším SOC a v určitých režimech
- integrace drží stav/diagnostiku: kdy proběhlo poslední balancování, kolik dní uplynulo, zda je plánované další, apod.

Pro manuální kontrolu (diagnostika): viz služba `oig_cloud.check_balancing` v `./SERVICES.md`.

## Statistiky pro plánovač

Nejčastěji používané entity pro plánování a jeho vysvětlení v UI:

- `sensor.oig_XXXXX_battery_forecast` – plán/timeline a atributy (min/target dosažitelnost, shortage, detail tabs)
- `binary_sensor.oig_XXXXX_grid_charging_planned` / `sensor.oig_XXXXX_grid_charging_planned` – kdy je plánované nabíjení ze sítě a s jakou cenou/energií
- `sensor.oig_XXXXX_battery_efficiency` – účinnost baterie (ovlivňuje výpočty nabíjení/vybíjení)
- `sensor.oig_XXXXX_adaptive_load_profiles` – profily spotřeby (ovlivňuje predikci spotřeby)
- `sensor.oig_XXXXX_battery_balancing` – balancování (může vynutit odlišné chování)
