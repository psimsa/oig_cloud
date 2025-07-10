import voluptuous as vol
import logging
import asyncio
from typing import Dict, Any, Optional
from homeassistant import config_entries
from homeassistant.config_entries import FlowResult
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from .const import (
    CONF_NO_TELEMETRY,
    DEFAULT_NAME,
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
)
from .api.oig_cloud_api import OigCloudApi

_LOGGER = logging.getLogger(__name__)


# Exception classes
class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate invalid authentication."""


async def validate_input(hass, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = OigCloudApi(data[CONF_USERNAME], data[CONF_PASSWORD], False, hass)

    if not await api.authenticate():
        raise InvalidAuth

    # Test connection
    try:
        stats = await api.get_stats()
        if not stats:
            raise CannotConnect
    except Exception:
        raise CannotConnect

    return {"title": DEFAULT_NAME}


# Nové konstanty pro skenovací intervaly
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"

# Solar Forecast konstanty
CONF_SOLAR_FORECAST_ENABLED = "solar_forecast_enabled"
CONF_SOLAR_FORECAST_API_KEY = "solar_forecast_api_key"
CONF_SOLAR_FORECAST_LATITUDE = "solar_forecast_latitude"
CONF_SOLAR_FORECAST_LONGITUDE = "solar_forecast_longitude"
CONF_SOLAR_FORECAST_INTERVAL = "solar_forecast_interval"

# String 1
CONF_SOLAR_FORECAST_STRING1_ENABLED = "solar_forecast_string1_enabled"
CONF_SOLAR_FORECAST_STRING1_DECLINATION = "solar_forecast_string1_declination"
CONF_SOLAR_FORECAST_STRING1_AZIMUTH = "solar_forecast_string1_azimuth"
CONF_SOLAR_FORECAST_STRING1_KWP = "solar_forecast_string1_kwp"

# String 2
CONF_SOLAR_FORECAST_STRING2_ENABLED = "solar_forecast_string2_enabled"
CONF_SOLAR_FORECAST_STRING2_DECLINATION = "solar_forecast_string2_declination"
CONF_SOLAR_FORECAST_STRING2_AZIMUTH = "solar_forecast_string2_azimuth"
CONF_SOLAR_FORECAST_STRING2_KWP = "solar_forecast_string2_kwp"

# Statistické parametry
CONF_STATISTICS_ENABLED = "statistics_enabled"
CONF_STATISTICS_SAMPLING_SIZE = "statistics_sampling_size"
CONF_STATISTICS_MAX_AGE_DAYS = "statistics_max_age_days"
CONF_STATISTICS_RESTORE_DATA = "statistics_restore_data"
CONF_STATISTICS_MEDIAN_MINUTES = "statistics_median_minutes"

# Přidat nové konfigurace pro spotové ceny
SPOT_PRICING_SCHEMA = vol.Schema(
    {
        # Obecné nastavení
        vol.Optional("spot_trading_enabled", default=False): bool,
        vol.Optional("distribution_area", default="PRE"): vol.In(["PRE", "CEZ", "EGD"]),
        # Fixní tarif (pro ty, kdo neobchodují na spotu)
        vol.Optional("fixed_price_enabled", default=True): bool,
        vol.Optional("fixed_price_vt", default=4.50): vol.Coerce(float),
        vol.Optional("fixed_price_nt", default=3.20): vol.Coerce(float),
        vol.Optional("fixed_price_single", default=4.00): vol.Coerce(float),
        vol.Optional("tariff_type", default="dual"): vol.In(["single", "dual"]),
        # Spot nákup - fixní poplatky
        vol.Optional("spot_buy_fixed_fee", default=0.0): vol.Coerce(float),
        # Spot nákup - procentní poplatky
        vol.Optional("spot_buy_percent_positive", default=110.0): vol.Coerce(float),
        vol.Optional("spot_buy_percent_negative", default=90.0): vol.Coerce(float),
        # Spot prodej - fixní poplatky
        vol.Optional("spot_sell_fixed_fee", default=0.0): vol.Coerce(float),
        # Spot prodej - procentní poplatky
        vol.Optional("spot_sell_percent_positive", default=85.0): vol.Coerce(float),
        vol.Optional("spot_sell_percent_negative", default=100.0): vol.Coerce(float),
        # Kombinace fixních a procentních poplatků
        vol.Optional("spot_buy_combined_enabled", default=False): bool,
        vol.Optional("spot_sell_combined_enabled", default=False): bool,
    }
)

DISTRIBUTION_SCHEMA = vol.Schema(
    {
        # Základní distribuční poplatky (uživatel zadává)
        vol.Optional("breaker_size", default=25): vol.In(
            [16, 20, 25, 32, 40, 50, 63, 80, 100]
        ),
        vol.Optional("consumption_category", default="C02d"): vol.In(
            ["C01d", "C02d", "C25d", "C26d"]
        ),
        vol.Optional("monthly_consumption_kwh", default=300): vol.Coerce(int),
        vol.Optional("yearly_consumption_kwh", default=3600): vol.Coerce(int),
        # Automaticky načítané poplatky (z databáze)
        vol.Optional("auto_load_distribution_fees", default=True): bool,
    }
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, description={"suggested_value": ""}): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            "enable_solar_forecast",
            default=False,
            description="Povolit solární předpověď",
        ): bool,
        vol.Optional(
            "enable_statistics",
            default=True,
            description="Povolit statistiky a analýzy",
        ): bool,
        vol.Optional(
            "enable_pricing",
            default=False,
            description="Povolit cenové senzory a spotové ceny",
        ): bool,
        vol.Optional(
            "enable_spot_prices",
            default=True,
            description="Povolit spotové ceny elektřiny z OTE",
        ): bool,
        vol.Optional(
            "enable_extended_sensors",
            default=True,
            description="Povolit rozšířené senzory (napětí, proudy, teploty)",
        ): bool,
        vol.Optional(
            "enable_dashboard",
            default=True,
            description="Povolit webový dashboard s grafy",
        ): bool,  # NOVÉ: dashboard option
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OIG Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)

            # NOVÉ: Test OTE API pokud jsou spotové ceny povoleny
            if user_input.get("enable_spot_prices", True):
                try:
                    from .api.ote_api import OteApi

                    ote_api = OteApi()
                    test_data = await ote_api.get_spot_prices()
                    await ote_api.close()
                    if not test_data:
                        _LOGGER.warning("OTE API test failed, but continuing")
                except Exception as e:
                    _LOGGER.warning(f"OTE API test failed: {e}")

        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=info["title"],
                data={
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
                options={
                    "standard_scan_interval": 30,
                    "extended_scan_interval": 300,
                    "enable_solar_forecast": user_input.get(
                        "enable_solar_forecast", False
                    ),
                    "enable_statistics": user_input.get("enable_statistics", True),
                    "enable_extended_sensors": user_input.get(
                        "enable_extended_sensors", True
                    ),
                    "enable_pricing": user_input.get("enable_pricing", False),
                    "enable_spot_prices": user_input.get(
                        "enable_spot_prices", True
                    ),  # NOVÉ
                    # Přidat defaultní extended sensors nastavení
                    "enable_extended_battery_sensors": True,
                    "enable_extended_fve_sensors": True,
                    "enable_extended_grid_sensors": True,
                    "disable_extended_stats_api": False,
                },
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OigCloudOptionsFlowHandler":
        """Get options flow handler."""
        return OigCloudOptionsFlowHandler(config_entry)


class OigCloudOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for OIG Cloud."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options - zobrazit menu s výběrem konfigurace."""
        if user_input is not None:
            # Přesměrování na vybraný krok
            return await getattr(self, f"async_step_{user_input['config_type']}")()

        # Menu pro výběr typu konfigurace
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("config_type"): vol.In(
                        {
                            "basic_config": "🔧 Základní konfigurace (interval, přihlášení)",
                            "extended_sensors": "⚡ Rozšířené senzory (vyžaduje nastavení)",
                            "statistics_config": "📊 Statistiky a analýzy",
                            "solar_forecast": "☀️ Solární předpověď (vyžaduje nastavení)",
                            "battery_prediction": "🔋 Predikce baterie",
                            "pricing_config": "💰 Spotové ceny elektřiny",
                            "dashboard_config": "📈 Webový dashboard",  # NOVÉ
                        }
                    )
                }
            ),
            description_placeholders={
                "info": "Vyberte kategorii nastavení, kterou chcete upravit"
            },
        )

    async def async_step_basic_config(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Základní konfigurace."""
        if user_input is not None:
            # Pokud byly změněny přihlašovací údaje, aktualizuj je v config_entry.data
            new_options = {**self.config_entry.options, **user_input}

            # Kontrola, zda se změnily přihlašovací údaje
            username_changed = user_input.get("username") and user_input.get(
                "username"
            ) != self.config_entry.data.get(CONF_USERNAME)
            password_changed = user_input.get("password") and user_input.get(
                "password"
            ) != self.config_entry.data.get(CONF_PASSWORD)

            if username_changed or password_changed:
                # Aktualizuj také data v config_entry
                new_data = dict(self.config_entry.data)
                if username_changed:
                    new_data[CONF_USERNAME] = user_input["username"]
                if password_changed:
                    new_data[CONF_PASSWORD] = user_input["password"]

                # Aktualizuj config_entry s novými daty
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data, options=new_options
                )

            # Restart integrace pro aplikování všech změn (včetně intervalu)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=new_options)

        current_options = self.config_entry.options
        current_data = self.config_entry.data

        schema = vol.Schema(
            {
                vol.Optional(
                    "standard_scan_interval",
                    default=current_options.get("standard_scan_interval", 30),
                    description="Jak často načítat základní data z OIG Cloud (doporučeno 20-30s)",
                ): vol.All(int, vol.Range(min=10, max=300)),
                vol.Optional(
                    "username",
                    default=current_data.get(CONF_USERNAME, ""),
                    description="E-mail nebo uživatelské jméno pro přihlášení do OIG Cloud",
                ): str,
                vol.Optional(
                    "password",
                    default="",
                    description="Heslo pro OIG Cloud (pokud necháte prázdné, heslo se nezmění)",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="basic_config",
            data_schema=schema,
            description_placeholders={
                "current_username": current_data.get(CONF_USERNAME, ""),
                "info": "Změna přihlašovacích údajů restartuje integraci",
            },
        )

    async def async_step_extended_sensors(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Konfigurace rozšířených senzorů."""
        if user_input is not None:
            new_options = {**self.config_entry.options, **user_input}

            # Logika pro automatické zapnutí/vypnutí sub-modulů
            extended_enabled = user_input.get("enable_extended_sensors", False)
            current_extended_enabled = self.config_entry.options.get(
                "enable_extended_sensors", False
            )

            _LOGGER.info(
                f"Extended sensors: current={current_extended_enabled}, new={extended_enabled}"
            )
            _LOGGER.info(f"User input: {user_input}")

            if extended_enabled:
                if not current_extended_enabled:
                    # Pokud se main modul právě zapnul, zapneme všechny sub-moduly
                    new_options["enable_extended_battery_sensors"] = True
                    new_options["enable_extended_fve_sensors"] = True
                    new_options["enable_extended_grid_sensors"] = True
                    _LOGGER.info("Main modul zapnut - zapínám všechny sub-moduly")
                else:
                    # Pokud je main modul už zapnutý, kontrolujeme sub-moduly
                    battery_enabled = user_input.get(
                        "enable_extended_battery_sensors", True
                    )
                    fve_enabled = user_input.get("enable_extended_fve_sensors", True)
                    grid_enabled = user_input.get("enable_extended_grid_sensors", True)

                    # Pokud není žádný zapnutý, zapneme všechny
                    if not (battery_enabled or fve_enabled or grid_enabled):
                        new_options["enable_extended_battery_sensors"] = True
                        new_options["enable_extended_fve_sensors"] = True
                        new_options["enable_extended_grid_sensors"] = True
                        _LOGGER.info("Žádný sub-modul nebyl zapnutý - zapínám všechny")
            else:
                # DŮLEŽITÉ: Když je main modul vypnutý, VŽDY vypneme všechny sub-moduly
                new_options["enable_extended_battery_sensors"] = False
                new_options["enable_extended_fve_sensors"] = False
                new_options["enable_extended_grid_sensors"] = False
                _LOGGER.info("Main modul vypnut - FORCE vypínám všechny sub-moduly")

            _LOGGER.info(f"New options after: {new_options}")

            # Uložíme změny PŘED reloadem
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )

            # Restart integrace pro aplikování nových nastavení
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=new_options)

        current_options = self.config_entry.options
        extended_enabled = current_options.get("enable_extended_sensors", False)

        # Zobrazujeme VŠECHNY parametry vždy (i sub-moduly), ale s různými popisky
        schema_fields = {
            vol.Optional(
                "enable_extended_sensors",
                default=extended_enabled,
                description="Povolit rozšířené senzory pro detailní monitoring systému",
            ): bool,
            vol.Optional(
                "extended_scan_interval",
                default=current_options.get("extended_scan_interval", 300),
                description=f"{'✅ Jak často načítat rozšířená data (60-3600s)' if extended_enabled else '⏸️ Interval načítání (aktivní po zapnutí)'}",
            ): vol.All(int, vol.Range(min=60, max=3600)),
            vol.Optional(
                "enable_extended_battery_sensors",
                default=current_options.get("enable_extended_battery_sensors", True),
                description=f"{'✅ Napětí článků, proudy, teplota baterie' if extended_enabled else '⏸️ Senzory baterie (aktivní po zapnutí)'}",
            ): bool,
            vol.Optional(
                "enable_extended_fve_sensors",
                default=current_options.get("enable_extended_fve_sensors", True),
                description=f"{'✅ Výkon a proudy stringů fotovoltaiky' if extended_enabled else '⏸️ Senzory FVE (aktivní po zapnutí)'}",
            ): bool,
            vol.Optional(
                "enable_extended_grid_sensors",
                default=current_options.get("enable_extended_grid_sensors", True),
                description=f"{'✅ Napětí L1/L2/L3, frekvence sítě' if extended_enabled else '⏸️ Senzory sítě (aktivní po zapnutí)'}",
            ): bool,
        }

        return self.async_show_form(
            step_id="extended_sensors",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "current_state": "Povoleno" if extended_enabled else "Zakázáno",
                "info": (
                    "⚠️ Rozšířené senzory jsou vypnuté - sub-moduly se aktivují po zapnutí"
                    if not extended_enabled
                    else "✅ Rozšířené senzory jsou zapnuté - vyberte které typy chcete použít"
                ),
            },
        )

    async def async_step_statistics_config(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Configure statistics options."""
        if user_input is not None:
            # Použijeme self.options místo self.config_entry.options
            new_options = {**self.options, **user_input}

            # Restart integrace pro aplikování nových nastavení
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=new_options)

        current_options = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    "enable_statistics",
                    default=current_options.get("enable_statistics", True),
                    description="Medián spotřeby podle času, analýzy a predikce",
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="statistics_config",
            data_schema=schema,
            description_placeholders={
                "current_state": (
                    "Povoleno"
                    if current_options.get("enable_statistics", True)
                    else "Zakázáno"
                ),
                "info": "Statistiky vypočítávají medián spotřeby podle času dne a dne v týdnu pro lepší predikce",
            },
        )

    async def async_step_battery_prediction(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Zobrazit informace o predikci baterie (modul ve vývoji)."""
        if user_input is not None:
            # Pouze návrat do menu - žádné změny nejsou možné
            return await self.async_step_init()

        current_options = self.config_entry.options
        battery_enabled = current_options.get("enable_battery_prediction", False)

        # Read-only schema - pouze informační tlačítko
        schema = vol.Schema(
            {
                vol.Required(
                    "info_only",
                    default="back_to_menu",
                    description="⚠️ MODUL VE VÝVOJI - Změny nejsou možné",
                ): vol.In({"back_to_menu": "⬅️ Zpět do hlavního menu"})
            }
        )

        return self.async_show_form(
            step_id="battery_prediction",
            data_schema=schema,
            description_placeholders={
                "current_state": ("Povolen" if battery_enabled else "Zakázán"),
                "min_capacity": current_options.get("min_capacity_percent", 20.0),
                "charge_rate": current_options.get("home_charge_rate", 2800),
                "percentile": current_options.get("percentile_conf", 80.0),
                "max_price": current_options.get("max_price_conf", 4.0),
                "total_hours": current_options.get("total_hours", 24),
                "dev_status": "🚧 MODUL VE VÝVOJI",
                "info": (
                    "⚠️ POUZE PRO ČTENÍ - MODUL VE VÝVOJI\n\n"
                    "Predikce baterie je momentálně ve vývoji a není dostupná pro konfiguraci. "
                    f"Aktuální stav: {('POVOLEN' if battery_enabled else 'ZAKÁZÁN')}"
                    + (
                        f"\n\nAktuální parametry:\n"
                        f"• Min. kapacita: {current_options.get('min_capacity_percent', 20.0)}%\n"
                        f"• Nabíjecí výkon: {current_options.get('home_charge_rate', 2800)}W\n"
                        f"• Percentil: {current_options.get('percentile_conf', 80.0)}%\n"
                        f"• Max. cena: {current_options.get('max_price_conf', 4.0)} CZK/kWh\n"
                        f"• Horizont: {current_options.get('total_hours', 24)}h"
                        if battery_enabled
                        else ""
                    )
                ),
                "requirements": "POŽADAVKY: Statistiky (📊) + Spotové ceny (💰) musí být zapnuté",
                "features": "PLÁNOVANÉ FUNKCE: • Inteligentní plánování nabíjení • Optimalizace podle spotových cen • Predikce kapacity baterie • Automatické doporučení kdy nabíjet",
                "timeline": "ČASOVÝ PLÁN: Modul bude dokončen v příští verzi integrace",
            },
        )

    async def async_step_solar_forecast(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Konfigurace solární předpovědi."""
        errors = {}

        if user_input is not None:
            new_options = {**self.config_entry.options, **user_input}

            # Logika pro automatické zapnutí/vypnutí stringů
            solar_enabled = user_input.get("enable_solar_forecast", False)
            current_solar_enabled = self.config_entry.options.get(
                "enable_solar_forecast", False
            )

            if solar_enabled:
                # Společné zpracování API klíče pro oba scénáře
                api_key = user_input.get("solar_forecast_api_key")
                # OPRAVA 2: Správné zpracování API klíče včetně None
                if api_key is None:
                    api_key = ""
                else:
                    api_key = str(api_key).strip()

                # VŽDY uložit API klíč (i prázdný)
                new_options["solar_forecast_api_key"] = api_key

                # Debug log pro kontrolu
                _LOGGER.info(
                    f"🔑 Solar forecast API key saved: '{api_key}' (empty: {not bool(api_key)})"
                )

                mode = user_input.get("solar_forecast_mode", "daily_optimized")

                # ROZDĚLENÍ: Pokud se solar forecast právě zapíná (nebyl zapnutý), pouze základní validace
                if not current_solar_enabled:
                    # Validace pouze GPS při prvním zapnutí
                    try:
                        lat = float(
                            user_input.get("solar_forecast_latitude", 50.1219800)
                        )
                        lon = float(
                            user_input.get("solar_forecast_longitude", 13.9373742)
                        )
                        if not (-90 <= lat <= 90):
                            errors["solar_forecast_latitude"] = "invalid_latitude"
                        if not (-180 <= lon <= 180):
                            errors["solar_forecast_longitude"] = "invalid_longitude"
                    except (ValueError, TypeError):
                        errors["base"] = "invalid_coordinates"

                    # Validace módu při prvním zapnutí
                    if mode in ["every_4h", "hourly"] and not api_key:
                        errors["solar_forecast_mode"] = (
                            "api_key_required_for_frequent_updates"
                        )

                    # OPRAVA 1: Při prvním zapnutí TAKÉ validujeme stringy
                    string1_enabled = user_input.get(
                        "solar_forecast_string1_enabled", True
                    )
                    string2_enabled = user_input.get(
                        "solar_forecast_string2_enabled", False
                    )

                    if not string1_enabled and not string2_enabled:
                        errors["base"] = "no_strings_enabled"

                    # Při prvním zapnutí automaticky zapneme String 1 s default hodnoty POUZE pokud není explicitně vypnutý
                    if "solar_forecast_string1_enabled" not in user_input:
                        new_options["solar_forecast_string1_enabled"] = True
                    if "solar_forecast_string2_enabled" not in user_input:
                        new_options["solar_forecast_string2_enabled"] = False

                    _LOGGER.info("Solar forecast zapínám - nastavuji default String 1")

                else:
                    # PLNÁ validace - solar forecast už byl zapnutý, uživatel upravuje parametry
                    try:
                        lat = float(
                            user_input.get("solar_forecast_latitude", 50.1219800)
                        )
                        lon = float(
                            user_input.get("solar_forecast_longitude", 13.9373742)
                        )
                        if not (-90 <= lat <= 90):
                            errors["solar_forecast_latitude"] = "invalid_latitude"
                        if not (-180 <= lon <= 180):
                            errors["solar_forecast_longitude"] = "invalid_longitude"
                    except (ValueError, TypeError):
                        errors["base"] = "invalid_coordinates"

                    # Validace frekvence podle API klíče
                    if mode in ["every_4h", "hourly"] and not api_key:
                        errors["solar_forecast_mode"] = (
                            "api_key_required_for_frequent_updates"
                        )

                    # Ověření, že je alespoň jeden string zapnutý
                    string1_enabled = user_input.get(
                        "solar_forecast_string1_enabled", False
                    )
                    string2_enabled = user_input.get(
                        "solar_forecast_string2_enabled", False
                    )

                    if not string1_enabled and not string2_enabled:
                        errors["base"] = "no_strings_enabled"

                    # Validace String 1 parametrů (pokud je zapnutý)
                    if string1_enabled:
                        try:
                            string1_kwp = float(
                                user_input.get("solar_forecast_string1_kwp", 5.4)
                            )
                            string1_declination = int(
                                user_input.get("solar_forecast_string1_declination", 10)
                            )
                            string1_azimuth = int(
                                user_input.get("solar_forecast_string1_azimuth", 138)
                            )
                            if not (0 < string1_kwp <= 15):
                                errors["solar_forecast_string1_kwp"] = "invalid_kwp"
                            if not (0 <= string1_declination <= 90):
                                errors["solar_forecast_string1_declination"] = (
                                    "invalid_declination"
                                )
                            if not (0 <= string1_azimuth <= 360):
                                errors["solar_forecast_string1_azimuth"] = (
                                    "invalid_azimuth"
                                )
                        except (ValueError, TypeError):
                            errors["base"] = "invalid_string1_params"

                    # Validace String 2 parametrů (pokud je zapnutý)
                    if string2_enabled:
                        try:
                            string2_kwp = float(
                                user_input.get("solar_forecast_string2_kwp", 5.4)
                            )
                            string2_declination = int(
                                user_input.get("solar_forecast_string2_declination", 10)
                            )
                            string2_azimuth = int(
                                user_input.get("solar_forecast_string2_azimuth", 138)
                            )
                            if not (0 < string2_kwp <= 15):
                                errors["solar_forecast_string2_kwp"] = "invalid_kwp"
                            if not (0 <= string2_declination <= 90):
                                errors["solar_forecast_string2_declination"] = (
                                    "invalid_declination"
                                )
                            if not (0 <= string2_azimuth <= 360):
                                errors["solar_forecast_string2_azimuth"] = (
                                    "invalid_azimuth"
                                )
                        except (ValueError, TypeError):
                            errors["base"] = "invalid_string2_params"
            else:
                # OPRAVA 2: API klíč explicitně uložíme i když je modul vypnutý
                api_key = user_input.get("solar_forecast_api_key")
                if api_key is None:
                    api_key = ""
                else:
                    api_key = str(api_key).strip()
                new_options["solar_forecast_api_key"] = api_key

                # Debug log pro kontrolu
                _LOGGER.info(
                    f"🔑 Solar forecast disabled, API key saved: '{api_key}' (empty: {not bool(api_key)})"
                )

                # DŮLEŽITÉ: Když je solar forecast vypnutý, VŽDY vypneme všechny stringy
                # ALE ponecháme všechny parametry pro příští zapnutí
                new_options["solar_forecast_string1_enabled"] = False
                new_options["solar_forecast_string2_enabled"] = False

                _LOGGER.info(
                    "Solar forecast vypnut - vypínám stringy, ale zachovávám parametry"
                )

            if not errors:
                # Restart integrace pro aplikování nových nastavení
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                # Pro solar forecast - spustíme okamžitou aktualizaci dat při zapnutí
                if solar_enabled:
                    # Rozlišujeme mezi prvním zapnutím a změnou už zapnutého modulu
                    if not current_solar_enabled:
                        # PRVNÍ ZAPNUTÍ - senzory se teprve vytváří
                        _LOGGER.info(
                            "🌞 Solar forecast first activation - scheduling delayed update..."
                        )

                        # Naplánujeme update s delším zpožděním přes Home Assistant scheduler
                        async def delayed_solar_update() -> None:
                            await asyncio.sleep(15)  # Delší čekání
                            try:
                                # Místo hledání entity použijeme přímý přístup k integraci
                                from homeassistant.helpers import device_registry as dr

                                # Najdeme naši integraci v device registry
                                device_registry = dr.async_get(self.hass)
                                devices = dr.async_entries_for_config_entry(
                                    device_registry, self.config_entry.entry_id
                                )

                                if devices:
                                    # Spustíme refresh všech dat integrace
                                    await self.hass.services.async_call(
                                        "homeassistant",
                                        "reload_config_entry",
                                        {"entry_id": self.config_entry.entry_id},
                                        blocking=False,
                                    )
                                    _LOGGER.info(
                                        "🌞 Triggered integration reload for solar forecast initialization"
                                    )

                                    # Po dalším kráté době zkusíme update entity
                                    await asyncio.sleep(5)

                                    # Zkusíme najít a updatovat solar forecast entity
                                    entity_registry = er.async_get(self.hass)
                                    for entity in entity_registry.entities.values():
                                        if (
                                            entity.platform == DOMAIN
                                            and entity.domain == "sensor"
                                            and "solar_forecast" in entity.entity_id
                                            and not entity.entity_id.endswith(
                                                "_string1"
                                            )
                                            and not entity.entity_id.endswith(
                                                "_string2"
                                            )
                                        ):
                                            await self.hass.services.async_call(
                                                "homeassistant",
                                                "update_entity",
                                                {"entity_id": entity.entity_id},
                                                blocking=False,
                                            )
                                            _LOGGER.info(
                                                f"🌞 Triggered delayed solar forecast update for {entity.entity_id}"
                                            )
                                            return

                                    _LOGGER.info(
                                        "🌞 Solar forecast entity still not found after reload"
                                    )
                                else:
                                    _LOGGER.warning(
                                        "🌞 No devices found for integration"
                                    )

                            except Exception as e:
                                _LOGGER.warning(
                                    f"🌞 Failed delayed solar forecast update: {e}"
                                )

                        # Spustíme task na pozadí
                        self.hass.async_create_task(delayed_solar_update())

                    else:
                        # ZMĚNA EXISTUJÍCÍHO MODULU - senzory už existují, žádné čekání
                        _LOGGER.info(
                            "🌞 Solar forecast configuration update - triggering immediate update..."
                        )

                        try:
                            entity_registry = er.async_get(self.hass)
                            for entity in entity_registry.entities.values():
                                if (
                                    entity.platform == DOMAIN
                                    and entity.domain == "sensor"
                                    and "solar_forecast" in entity.entity_id
                                    and not entity.entity_id.endswith("_string1")
                                    and not entity.entity_id.endswith("_string2")
                                ):
                                    await self.hass.services.async_call(
                                        "homeassistant",
                                        "update_entity",
                                        {"entity_id": entity.entity_id},
                                        blocking=False,
                                    )
                                    _LOGGER.info(
                                        f"🌞 Triggered immediate solar forecast update for {entity.entity_id}"
                                    )
                                    break
                            else:
                                _LOGGER.warning(
                                    "🌞 Solar forecast entity not found for immediate update"
                                )
                        except Exception as e:
                            _LOGGER.warning(
                                f"🌞 Failed to trigger immediate solar forecast update: {e}"
                            )

                return self.async_create_entry(title="", data=new_options)

        current_options = self.config_entry.options
        solar_enabled = current_options.get("enable_solar_forecast", False)

        # Načtení GPS z Home Assistant nastavení
        hass_latitude = (
            self.hass.config.latitude if self.hass.config.latitude else 50.1219800
        )
        hass_longitude = (
            self.hass.config.longitude if self.hass.config.longitude else 13.9373742
        )

        # Pokus o načtení výkonu FVE ze senzoru
        default_kwp = 5.4
        try:
            # Hledáme senzor s installed_fve_power_wp
            entity_registry = er.async_get(self.hass)
            for entity in entity_registry.entities.values():
                if entity.entity_id.endswith("installed_fve_power_wp"):
                    state = self.hass.states.get(entity.entity_id)
                    if state and state.state not in ("unknown", "unavailable"):
                        # Převod z Wp na kWp, max 15 kWp na string
                        fve_power_wp = float(state.state)
                        total_kwp = round(fve_power_wp / 1000, 1)
                        default_kwp = min(total_kwp, 15.0)  # Max 15 kWp na string
                        break
        except (ValueError, TypeError, AttributeError):
            # Pokud se nepodaří načíst, použije se defaultní hodnota
            pass

        # VŽDY zobrazit všechny parametry, ale výchozí hodnoty podle stavu
        schema_fields = {
            vol.Optional(
                "enable_solar_forecast",
                default=solar_enabled,
                description="Povolit solární předpověď pro optimalizaci baterie a predikce výroby",
            ): bool,
        }

        # VŽDY přidáme všechna pole, ale s defaulty podle stavu
        # Kontrola API klíče pro podmíněné zobrazení režimů
        current_api_key = current_options.get("solar_forecast_api_key", "").strip()
        has_api_key = bool(current_api_key)

        # Dostupné režimy podle API klíče
        if has_api_key:
            mode_options = {
                "manual": "🔧 Pouze na vyžádání",
                "daily_optimized": "3x denně (6:00, 12:00, 16:00) - DOPORUČENO",
                "daily": "Jednou denně (6:00)",
                "every_4h": "Každé 4 hodiny (vyžaduje API klíč)",
                "hourly": "Každou hodinu (vyžaduje API klíč)",
            }
        else:
            mode_options = {
                "manual": "🔧 Pouze na vyžádání",
                "daily_optimized": "3x denně (6:00, 12:00, 16:00) - DOPORUČENO",
                "daily": "Jednou denně (6:00)",
                "every_4h": "Každé 4 hodiny (vyžaduje API klíč) - NEDOSTUPNÉ",
                "hourly": "Každou hodinu (vyžaduje API klíč) - NEDOSTUPNÉ",
            }

        schema_fields.update(
            {
                vol.Optional(
                    "solar_forecast_api_key",
                    default=current_options.get("solar_forecast_api_key", ""),
                    description="API klíč pro forecast.solar (volitelné, umožní častější aktualizace)",
                ): str,
                vol.Optional(
                    "solar_forecast_mode",
                    default=current_options.get(
                        "solar_forecast_mode", "daily_optimized"
                    ),
                    description=f"Jak často aktualizovat předpověď {('(pro častější režimy zadejte API klíč)' if not has_api_key else '')}",
                ): vol.In(mode_options),
                vol.Optional(
                    "solar_forecast_latitude",
                    default=current_options.get(
                        "solar_forecast_latitude", hass_latitude
                    ),
                    description="GPS zeměpisná šířka vaší FVE (-90 až 90)",
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_longitude",
                    default=current_options.get(
                        "solar_forecast_longitude", hass_longitude
                    ),
                    description="GPS zeměpisná délka vaší FVE (-180 až 180)",
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_string1_enabled",
                    default=current_options.get(
                        "solar_forecast_string1_enabled",
                        True,  # Default True - string je dostupný
                    ),
                    description="Zapnout první string panelů (musí být alespoň jeden zapnutý)",
                ): bool,
                vol.Optional(
                    "solar_forecast_string1_kwp",
                    default=current_options.get(
                        "solar_forecast_string1_kwp", default_kwp
                    ),
                    description="Instalovaný výkon 1. stringu v kWp (max 15 kWp)",
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_string1_declination",
                    default=current_options.get(
                        "solar_forecast_string1_declination", 10
                    ),
                    description="Sklon panelů 1. stringu od horizontály (0-90°)",
                ): vol.Coerce(int),
                vol.Optional(
                    "solar_forecast_string1_azimuth",
                    default=current_options.get("solar_forecast_string1_azimuth", 138),
                    description="Orientace panelů 1. stringu (0°=sever, 90°=východ, 180°=jih, 270°=západ)",
                ): vol.Coerce(int),
                vol.Optional(
                    "solar_forecast_string2_enabled",
                    default=current_options.get(
                        "solar_forecast_string2_enabled", False
                    ),
                    description="Zapnout druhý string panelů (volitelné)",
                ): bool,
                vol.Optional(
                    "solar_forecast_string2_kwp",
                    default=current_options.get(
                        "solar_forecast_string2_kwp", default_kwp
                    ),
                    description="Instalovaný výkon 2. stringu v kWp (max 15 kWp)",
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_string2_declination",
                    default=current_options.get(
                        "solar_forecast_string2_declination", 10
                    ),
                    description="Sklon panelů 2. stringu od horizontály (0-90°)",
                ): vol.Coerce(int),
                vol.Optional(
                    "solar_forecast_string2_azimuth",
                    default=current_options.get("solar_forecast_string2_azimuth", 138),
                    description="Orientace panelů 2. stringu (0°=sever, 90°=východ, 180°=jih, 270°=západ)",
                ): vol.Coerce(int),
            }
        )

        return self.async_show_form(
            step_id="solar_forecast",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={
                "current_state": "Povolen" if solar_enabled else "Zakázáno",
                "current_mode": (
                    current_options.get("solar_forecast_mode", "daily_optimized")
                    if solar_enabled
                    else "N/A"
                ),
                "info": (
                    "⚠️ Solar forecast je vypnutý - zapněte jej pro zobrazení dalších možností"
                    if not solar_enabled
                    else f"✅ Solar forecast je zapnutý - nastavte parametry (GPS: {hass_latitude:.4f}, {hass_longitude:.4f}, detekováno: {default_kwp} kWp)"
                ),
            },
        )

    async def async_step_pricing_config(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle pricing configuration including spot prices."""
        current_options = self.config_entry.options
        errors: Dict[str, str] = {}

        if user_input is not None:
            # NOVÁ VALIDACE: Kontrola spotových cen konfigurace
            spot_enabled = user_input.get("enable_spot_prices", False)

            if spot_enabled:
                pricing_model = user_input.get("spot_pricing_model", "percentage")

                try:
                    if pricing_model == "percentage":
                        # Validace procentního modelu - pouze relevantní pole
                        positive_fee = float(
                            user_input.get("spot_positive_fee_percent", 0)
                        )
                        negative_fee = float(
                            user_input.get("spot_negative_fee_percent", 0)
                        )

                        if positive_fee <= 0:
                            errors["spot_positive_fee_percent"] = "invalid_positive_fee"
                        if negative_fee <= 0:
                            errors["spot_negative_fee_percent"] = "invalid_negative_fee"

                    elif pricing_model == "fixed":
                        # Validace fixního modelu - pouze relevantní pole
                        fixed_fee = float(user_input.get("spot_fixed_fee_mwh", 0))

                        if fixed_fee <= 0:
                            errors["spot_fixed_fee_mwh"] = "invalid_fixed_fee"

                    # Validace fixních obchodních cen (pokud jsou povoleny)
                    if pricing_model == "fixed_prices":
                        fixed_vt = float(user_input.get("fixed_commercial_price_vt", 0))
                        fixed_nt = float(user_input.get("fixed_commercial_price_nt", 0))

                        if fixed_vt <= 0:
                            errors["fixed_commercial_price_vt"] = "invalid_fixed_price"
                        if fixed_nt <= 0:
                            errors["fixed_commercial_price_nt"] = "invalid_fixed_price"

                    # Validace distribučních poplatků (vždy povinné)
                    distribution_fee_vt = float(
                        user_input.get("distribution_fee_vt_kwh", 0)
                    )

                    if distribution_fee_vt < 0:  # Může být 0, ale ne záporný
                        errors["distribution_fee_vt_kwh"] = "invalid_distribution_fee"

                    # Validace DPH
                    vat_rate = float(user_input.get("vat_rate", 21.0))
                    if not (0 <= vat_rate <= 50):
                        errors["vat_rate"] = "invalid_vat_rate"

                    # Validace NT poplatku pouze pokud je dvoutarifní sazba
                    dual_tariff = user_input.get("dual_tariff_enabled", True)
                    if dual_tariff:
                        distribution_fee_nt = float(
                            user_input.get("distribution_fee_nt_kwh", 0)
                        )
                        if distribution_fee_nt < 0:  # Může být 0, ale ne záporný
                            errors["distribution_fee_nt_kwh"] = (
                                "invalid_distribution_fee"
                            )

                        # Validace tarifních časů pouze pro dvoutarifní sazbu
                        def validate_tariff_times(
                            time_str: str, field_name: str
                        ) -> bool:
                            """Validuje formát tarifních časů."""
                            if not time_str.strip():
                                return True  # Prázdné je OK (žádné intervaly)

                            try:
                                hours = [
                                    int(h.strip())
                                    for h in time_str.split(",")
                                    if h.strip()
                                ]
                                for hour in hours:
                                    if not (0 <= hour <= 23):
                                        errors[field_name] = "invalid_hour_range"
                                        return False
                                return True
                            except (ValueError, AttributeError):
                                errors[field_name] = "invalid_hour_format"
                                return False

                        validate_tariff_times(
                            user_input.get("tariff_nt_start_weekday", ""),
                            "tariff_nt_start_weekday",
                        )
                        validate_tariff_times(
                            user_input.get("tariff_vt_start_weekday", ""),
                            "tariff_vt_start_weekday",
                        )
                        validate_tariff_times(
                            user_input.get("tariff_nt_start_weekend", ""),
                            "tariff_nt_start_weekend",
                        )
                        validate_tariff_times(
                            user_input.get("tariff_vt_start_weekend", ""),
                            "tariff_vt_start_weekend",
                        )

                except (ValueError, TypeError):
                    errors["base"] = "invalid_spot_pricing_config"

            # Pokud nejsou chyby, pokračuj
            if not errors:
                new_options = current_options.copy()
                new_options.update(user_input)

                # ZJEDNODUŠENO: Vždy reload integrace po změně cenových senzorů
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data=new_options)

        current_options = self.config_entry.options
        spot_enabled = current_options.get("enable_spot_prices", False)

        # Pokud máme user_input, použij hodnotu odtamtud (pro live preview)
        if user_input is not None:
            spot_enabled = user_input.get("enable_spot_prices", spot_enabled)

        schema_fields: Dict[str, Any] = {
            vol.Optional(
                "enable_spot_prices",
                default=spot_enabled,
                description="Povolit spotové ceny elektřiny z OTE",
            ): bool,
        }

        # OPRAVA: Přidat konfiguraci pouze pokud jsou spotové ceny zapnuté
        if spot_enabled:
            # Získat aktuálně vybraný model (z user_input nebo current_options)
            current_model = "percentage"
            if user_input is not None:
                current_model = user_input.get("spot_pricing_model", current_model)
            else:
                current_model = current_options.get("spot_pricing_model", current_model)

            # Model je vždy povinný
            schema_fields[
                vol.Required(
                    "spot_pricing_model",
                    default=current_model,
                    description="Model výpočtu obchodní ceny",
                )
            ] = vol.In(
                {
                    "percentage": "Procentní model (různé % pro kladné/záporné spotové ceny)",
                    "fixed": "Fixní poplatek za MWh ke spotové ceně",
                    "fixed_prices": "Fixní obchodní ceny VT/NT (bez spotových cen)",
                }
            )

            # Podmíněná pole podle vybraného modelu
            if current_model == "percentage":
                # Pro procentní model - spotové ceny s procenty
                schema_fields.update(
                    {
                        vol.Required(
                            "spot_positive_fee_percent",
                            default=current_options.get(
                                "spot_positive_fee_percent", 15.0
                            ),
                            description="Obchodní přirážka při kladné spotové ceně (%). Např. 15% = cena × 1,15",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=100.0)),
                        vol.Required(
                            "spot_negative_fee_percent",
                            default=current_options.get(
                                "spot_negative_fee_percent", 9.0
                            ),
                            description="Obchodní přirážka při záporné spotové ceně (%). Např. 9% = cena × 0,91",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=100.0)),
                        # Ostatní pole jako nepovinné (skryté)
                        vol.Optional(
                            "spot_fixed_fee_mwh",
                            default=current_options.get("spot_fixed_fee_mwh", 500.0),
                            description="Fixní poplatek (nepoužívá se v procentním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                        vol.Optional(
                            "fixed_commercial_price_vt",
                            default=current_options.get(
                                "fixed_commercial_price_vt", 4.50
                            ),
                            description="Fixní cena VT (nepoužívá se v procentním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                        vol.Optional(
                            "fixed_commercial_price_nt",
                            default=current_options.get(
                                "fixed_commercial_price_nt", 3.20
                            ),
                            description="Fixní cena NT (nepoužívá se v procentním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                    }
                )
            elif current_model == "fixed":
                # Pro fixní model - spotové ceny s fixním poplatkem
                schema_fields.update(
                    {
                        vol.Required(
                            "spot_fixed_fee_mwh",
                            default=current_options.get("spot_fixed_fee_mwh", 500.0),
                            description="Fixní obchodní poplatek v CZK/MWh přičtený ke spotové ceně",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.1)),
                        # Ostatní pole jako nepovinné (skryté)
                        vol.Optional(
                            "spot_positive_fee_percent",
                            default=current_options.get(
                                "spot_positive_fee_percent", 15.0
                            ),
                            description="Obchodní přirážka (nepoužívá se ve fixním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                        vol.Optional(
                            "spot_negative_fee_percent",
                            default=current_options.get(
                                "spot_negative_fee_percent", 9.0
                            ),
                            description="Obchodní přirážka (nepoužívá se ve fixním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                        vol.Optional(
                            "fixed_commercial_price_vt",
                            default=current_options.get(
                                "fixed_commercial_price_vt", 4.50
                            ),
                            description="Fixní cena VT (nepoužívá se ve fixním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                        vol.Optional(
                            "fixed_commercial_price_nt",
                            default=current_options.get(
                                "fixed_commercial_price_nt", 3.20
                            ),
                            description="Fixní cena NT (nepoužívá se ve fixním modelu)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                    }
                )
            elif current_model == "fixed_prices":
                # Pro fixní ceny - bez spotových cen
                schema_fields.update(
                    {
                        vol.Required(
                            "fixed_commercial_price_vt",
                            default=current_options.get(
                                "fixed_commercial_price_vt", 4.50
                            ),
                            description="Fixní obchodní cena VT v CZK/kWh ⚠️ ZADÁVEJTE BEZ DPH!",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                        vol.Required(
                            "fixed_commercial_price_nt",
                            default=current_options.get(
                                "fixed_commercial_price_nt", 3.20
                            ),
                            description="Fixní obchodní cena NT v CZK/kWh ⚠️ ZADÁVEJTE BEZ DPH!",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=20.0)),
                        # Ostatní pole jako nepovinné (skryté)
                        vol.Optional(
                            "spot_positive_fee_percent",
                            default=current_options.get(
                                "spot_positive_fee_percent", 15.0
                            ),
                            description="Obchodní přirážka (nepoužívá se s fixními cenami)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                        vol.Optional(
                            "spot_negative_fee_percent",
                            default=current_options.get(
                                "spot_negative_fee_percent", 9.0
                            ),
                            description="Obchodní přirážka (nepoužívá se s fixními cenami)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                        vol.Optional(
                            "spot_fixed_fee_mwh",
                            default=current_options.get("spot_fixed_fee_mwh", 500.0),
                            description="Fixní poplatek (nepoužívá se s fixními cenami)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                    }
                )

            # Distribuční poplatky jsou vždy povinné (VT a NT)
            schema_fields.update(
                {
                    vol.Required(
                        "dual_tariff_enabled",
                        default=current_options.get("dual_tariff_enabled", True),
                        description="Povolit dvoutarifní sazbu (VT/NT). Pokud ne, bude se používat pouze VT sazba",
                    ): bool,
                    vol.Required(
                        "distribution_fee_vt",
                        default=current_options.get("distribution_fee_vt_kwh", 1.35),
                        description="Distribuční poplatek VT (vysoký tarif) v CZK/kWh ⚠️ ZADÁVEJTE BEZ DPH!",
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                    vol.Required(
                        "vat_rate",
                        default=current_options.get("vat_rate", 21.0),
                        description="Sazba DPH v procentech (obvykle 21%)",
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=50.0)),
                }
            )

            # Podmíněné zobrazení NT parametrů pouze pro dvoutarifní sazbu
            dual_tariff = current_options.get("dual_tariff_enabled", True)
            if user_input is not None:
                dual_tariff = user_input.get("dual_tariff_enabled", dual_tariff)

            if dual_tariff:
                schema_fields.update(
                    {
                        vol.Required(
                            "distribution_fee_nt",
                            default=current_options.get(
                                "distribution_fee_nt_kwh", 1.05
                            ),
                            description="Distribuční poplatek NT (nízký tarif) v CZK/kWh ⚠️ ZADÁVEJTE BEZ DPH!",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                        vol.Required(
                            "tariff_nt_start_weekday",
                            default=current_options.get(
                                "tariff_nt_start_weekday", "22,2"
                            ),
                            description="Začátky NT tarifu v pracovní dny (pondělí-pátek), hodiny oddělené čárkou. Např: '22,2' = 22:00-6:00 a 2:00-6:00",
                        ): str,
                        vol.Required(
                            "tariff_vt_start_weekday",
                            default=current_options.get("tariff_vt_start_weekday", "6"),
                            description="Začátky VT tarifu v pracovní dny (pondělí-pátek), hodiny oddělené čárkou. Např: '6' = 6:00-22:00",
                        ): str,
                        vol.Required(
                            "tariff_nt_start_weekend",
                            default=current_options.get("tariff_nt_start_weekend", "0"),
                            description="Začátky NT tarifu o víkendu (sobota-neděle), hodiny oddělené čárkou. Např: '0' = celý víkend NT",
                        ): str,
                        vol.Required(
                            "tariff_vt_start_weekend",
                            default=current_options.get("tariff_vt_start_weekend", ""),
                            description="Začátky VT tarifu o víkendu (sobota-neděle), hodiny oddělené čárkou. Prázdné = žádný VT o víkendu",
                        ): str,
                    }
                )
            else:
                # Pro jednotarifní sazbu skryjeme NT parametry ale uložíme defaulty
                schema_fields.update(
                    {
                        vol.Optional(
                            "distribution_fee_nt",
                            default=current_options.get(
                                "distribution_fee_nt_kwh", 1.05
                            ),
                            description="Distribuční poplatek NT (nepoužívá se v jednotarifní sazbě)",
                        ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                        vol.Optional(
                            "tariff_nt_start_weekday",
                            default=current_options.get(
                                "tariff_nt_start_weekday", "22,2"
                            ),
                            description="Začátky NT tarifu v týdnu (nepoužívá se v jednotarifní sazbě)",
                        ): str,
                        vol.Optional(
                            "tariff_vt_start_weekday",
                            default=current_options.get("tariff_vt_start_weekday", "6"),
                            description="Začátky VT tarifu v týdnu (nepoužívá se v jednotarifní sazbě)",
                        ): str,
                        vol.Optional(
                            "tariff_nt_start_weekend",
                            default=current_options.get("tariff_nt_start_weekend", "0"),
                            description="Začátky NT tarifu o víkendu (nepoužívá se v jednotarifní sazbě)",
                        ): str,
                        vol.Optional(
                            "tariff_vt_start_weekend",
                            default=current_options.get("tariff_vt_start_weekend", ""),
                            description="Začátky VT tarifu o víkendu (nepoužívá se v jednotarifní sazbě)",
                        ): str,
                    }
                )

        return self.async_show_form(
            step_id="pricing_config",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={
                "current_state": "Povolen" if spot_enabled else "Zakázáno",
                "current_model": current_options.get(
                    "spot_pricing_model", "percentage"
                ),
                "positive_fee": current_options.get("spot_positive_fee_percent", 15.0),
                "negative_fee": current_options.get("spot_negative_fee_percent", 9.0),
                "fixed_fee": current_options.get("spot_fixed_fee_mwh", 500.0),
                "distribution_fee_vt": current_options.get(
                    "distribution_fee_vt_kwh", 1.35
                ),
                "distribution_fee_nt": current_options.get(
                    "distribution_fee_nt_kwh", 1.05
                ),
                "dual_tariff": (
                    "Dvoutarifní"
                    if current_options.get("dual_tariff_enabled", True)
                    else "Jednotarifní"
                ),
                "pricing_type": (
                    "Fixní obchodní ceny"
                    if current_options.get("spot_pricing_model") == "fixed_prices"
                    else "Spotové ceny"
                ),
                "tariff_times_weekday": (
                    f"NT: {current_options.get('tariff_nt_start_weekday', '22,2')}, VT: {current_options.get('tariff_vt_start_weekday', '6')}"
                    if current_options.get("dual_tariff_enabled", True)
                    else "Pouze VT"
                ),
                "tariff_times_weekend": (
                    f"NT: {current_options.get('tariff_nt_start_weekend', '0')}, VT: {current_options.get('tariff_vt_start_weekend', '')}"
                    if current_options.get("dual_tariff_enabled", True)
                    else "Pouze VT"
                ),
                "update_interval": "denně ve 13:00",
                "info": (
                    "⚠️ Spotové ceny jsou vypnuté - zapněte je pro zobrazení dalších možností"
                    if not spot_enabled
                    else f"✅ Ceny jsou zapnuté - Model: {current_options.get('spot_pricing_model', 'percentage')}, Tarif: {('Dvoutarifní' if current_options.get('dual_tariff_enabled', True) else 'Jednotarifní')}, Distribuce VT: {current_options.get('distribution_fee_vt_kwh', 1.35)} CZK/kWh{(', NT: ' + str(current_options.get('distribution_fee_nt_kwh', 1.05)) + ' CZK/kWh') if current_options.get('dual_tariff_enabled', True) else ''} ⚠️ VŠECHNY CENY BEZ DPH!"
                ),
            },
        )

    async def async_step_dashboard_config(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Zobrazit informace o dashboard (modul ve vývoji)."""
        if user_input is not None:
            # Pouze návrat do menu - žádné změny nejsou možné
            return await self.async_step_init()

        current_options = self.config_entry.options
        dashboard_enabled = current_options.get("enable_dashboard", False)

        # Read-only schema - pouze informační tlačítko
        schema = vol.Schema(
            {
                vol.Required(
                    "info_only",
                    default="back_to_menu",
                    description="⚠️ MODUL VE VÝVOJI - Změny nejsou možné",
                ): vol.In({"back_to_menu": "⬅️ Zpět do hlavního menu"})
            }
        )

        return self.async_show_form(
            step_id="dashboard_config",
            data_schema=schema,
            description_placeholders={
                "current_state": ("Povolen" if dashboard_enabled else "Zakázán"),
                "dev_status": "🚧 MODUL VE VÝVOJI",
                "info": (
                    "⚠️ POUZE PRO ČTENÍ - MODUL VE VÝVOJI\n\n"
                    "Webový dashboard je momentálně ve vývoji a není dostupný pro konfiguraci. "
                    f"Aktuální stav: {('POVOLEN' if dashboard_enabled else 'ZAKÁZÁN')}\n\n"
                    "Dashboard bude automaticky dostupný v levém menu Home Assistant po dokončení vývoje."
                ),
                "features": "PLÁNOVANÉ FUNKCE:\n• Predikce kapacity baterie\n• Solární předpověď\n• Spotové ceny elektřiny\n• Interaktivní grafy s Apex Charts\n• Real-time monitoring\n• Exporty dat",
                "timeline": "ČASOVÝ PLÁN: Dashboard bude dokončen v příští verzi integrace",
                "access": "PŘÍSTUP: Po dokončení bude dostupný přes levé menu → 'OIG Dashboard'",
            },
        )
