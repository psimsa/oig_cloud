# Živá data (povinné)

Integrace `oig_cloud` potřebuje v OIG Cloud mobilní aplikaci zapnutá **Živá data**. Pokud nejsou aktivní, OIG Cloud API typicky vrací chyby (často 500) nebo neposkytuje aktuální telemetrii – integrace pak nemá z čeho stavovat senzory.

## Jak zapnout

1. Otevřete mobilní aplikaci **OIG Cloud**.
2. Najděte nastavení pro **Živá data** (Live data) u Battery Boxu.
3. Zapněte je a ověřte, že se v aplikaci začnou objevovat aktuální hodnoty (výkon, SOC, toky).

## Jak poznat, že to není zapnuté

- V Home Assistant jsou entity `unknown` / `unavailable`.
- Logy obsahují chyby při volání OIG Cloud API (např. HTTP 500).
- V OIG aplikaci nejsou vidět aktuální hodnoty v reálném čase.

## Další kroky

- Po zapnutí živých dat restartujte Home Assistant nebo reloadněte integraci.
- Pokud problém přetrvává, viz `./TROUBLESHOOTING.md`.
