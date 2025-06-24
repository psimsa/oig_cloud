import voluptuous as vol
import logging
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
            description="Povolit pokročilé statistiky a predikce",
        ): bool,
        vol.Optional(
            "enable_pricing",
            default=False,
            description="Povolit cenové senzory a spotové ceny",
        ): bool,
        vol.Optional(
            "enable_extended_sensors",
            default=False,
            description="Povolit rozšířené senzory (napětí, proudy, teploty)",
        ): bool,
    }
)


class OigCloudOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for OIG Cloud integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Reload integration after options change
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=user_input)

        # Get current configuration values - oprava chybějících konstant
        current_interval = self.config_entry.data.get("standard_scan_interval", 30)
        current_extended_sensors = self.config_entry.options.get(
            "reconfigure_extended_sensors", False
        )
        current_solar_forecast = self.config_entry.options.get(
            "reconfigure_solar_forecast", False
        )
        current_pricing = self.config_entry.options.get("pricing_info", False)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "standard_scan_interval", default=current_interval
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                    vol.Optional(
                        "reconfigure_extended_sensors", default=current_extended_sensors
                    ): bool,
                    vol.Optional(
                        "reconfigure_solar_forecast", default=current_solar_forecast
                    ): bool,
                    vol.Optional("pricing_info", default=current_pricing): bool,
                }
            ),
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
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Uložit všechny volby do options
            return self.async_create_entry(
                title=info["title"],
                data={
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
                options={
                    "enable_solar_forecast": user_input.get(
                        "enable_solar_forecast", False
                    ),
                    "enable_statistics": user_input.get("enable_statistics", False),
                    "enable_spot_prices": user_input.get("enable_spot_prices", False),
                },
            )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_options(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Zpracování konfiguračních možností."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Získáme současné hodnoty
        current_options = self.config_entry.options

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "enable_statistics",
                        default=current_options.get("enable_statistics", True),
                        description={
                            "suggested_value": current_options.get(
                                "enable_statistics", True
                            )
                        },
                    ): vol.Coerce(bool),
                    vol.Optional(
                        "enable_extended_sensors",
                        default=current_options.get("enable_extended_sensors", False),
                        description={
                            "suggested_value": current_options.get(
                                "enable_extended_sensors", False
                            )
                        },
                    ): vol.Coerce(bool),
                    vol.Optional(
                        "enable_solar_forecast",
                        default=current_options.get("enable_solar_forecast", False),
                        description={
                            "suggested_value": current_options.get(
                                "enable_solar_forecast", False
                            )
                        },
                    ): vol.Coerce(bool),
                    vol.Optional(
                        "enable_pricing",
                        default=current_options.get("enable_pricing", False),
                        description={
                            "suggested_value": current_options.get(
                                "enable_pricing", False
                            )
                        },
                    ): vol.Coerce(bool),
                }
            ),
            description_placeholders={
                "enable_statistics_desc": "Povolit statistické senzory (medián spotřeby, predikce)",
                "enable_extended_sensors_desc": "Rozšířené senzory baterie, FVE a sítě",
                "enable_solar_forecast_desc": "Solární předpověď (vyžaduje další konfiguraci)",
                "enable_pricing_desc": "Cenové senzory elektřiny",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OigCloudOptionsFlowHandler:
        """Create the options flow."""
        return OigCloudOptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for OIG Cloud."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Úplně odstraníme - base třída to už poskytuje
        super().__init__()
        self._user_data: Dict[str, Any] = {}

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Aktualizujeme options v config entry
            return self.async_create_entry(title="", data=user_input)

        # Získáme aktuální options z config entry
        current_options = dict(self.config_entry.options)

        # Základní schema s intervalem
        schema_fields = {
            vol.Optional(
                "standard_scan_interval",
                default=current_options.get("standard_scan_interval", 30),
                description="Interval aktualizace základních dat (sekundy)",
            ): vol.All(int, vol.Range(min=10, max=300)),
            vol.Optional(
                "enable_statistics",
                default=current_options.get("enable_statistics", True),
                description="📊 Statistiky a analýzy - medián spotřeby, predikce baterie, analýzy podle času",
            ): bool,
            vol.Optional(
                "enable_extended_sensors",
                default=current_options.get("enable_extended_sensors", False),
                description="🔌 Rozšířené senzory - napětí, proudy, teploty (vyžaduje nastavení)",
            ): bool,
            vol.Optional(
                "enable_solar_forecast",
                default=current_options.get("enable_solar_forecast", False),
                description="☀️ Solární předpověď - prognóza výroby FVE (vyžaduje nastavení)",
            ): bool,
            vol.Optional(
                "enable_pricing",
                default=current_options.get("enable_pricing", False),
                description="💰 Cenové informace - spotové ceny elektřiny (vyžaduje nastavení)",
            ): bool,
        }

        # Přidáme solar_forecast_mode a rekonfiguraci pouze pokud je solar forecast zapnutý
        if current_options.get("enable_solar_forecast", False):
            if current_options.get("solar_forecast_api_key"):
                schema_fields[
                    vol.Optional(
                        "solar_forecast_mode",
                        default=current_options.get("solar_forecast_mode", "manual"),
                        description="Režim automatických aktualizací solární předpovědi",
                    )
                ] = vol.In(
                    {
                        "manual": "Manuální (pouze přes službu)",
                        "daily_optimized": "3x denně (6:00, 12:00, 16:00) - DOPORUČENO",
                        "daily": "Jednou denně (6:00)",
                        "every_4h": "Každé 4 hodiny",
                        "hourly": "Každou hodinu (pouze pro testování)",
                    }
                )

            # Přidáme tlačítko pro rekonfiguraci solar forecast
            schema_fields[
                vol.Optional(
                    "reconfigure_solar_forecast",
                    default=False,
                    description="🔧 Změnit nastavení solární předpovědi (API klíč, GPS, parametry FVE)",
                )
            ] = bool

        # Přidáme tlačítko pro rekonfiguraci extended sensors pokud jsou zapnuté
        if current_options.get("enable_extended_sensors", False):
            schema_fields[
                vol.Optional(
                    "reconfigure_extended_sensors",
                    default=False,
                    description="🔧 Změnit nastavení rozšířených senzorů (intervaly, kategorie)",
                )
            ] = bool

        # Přidáme tlačítko pro rekonfiguraci pricing pokud je zapnutý
        if current_options.get("enable_pricing", False):
            schema_fields[
                vol.Optional(
                    "reconfigure_pricing",
                    default=False,
                    description="🔧 Změnit nastavení cenových informací (tarify, distribuční oblast)",
                )
            ] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "step_description": "⚙️ Konfigurujte pokročilé funkce integrace podle vašich potřeb.",
                "interval_info": "⏱️ Základní interval ovlivňuje frekvenci získávání dat z OIG Cloud API",
                "modules_info": "📦 Každý modul přidává specifické funkce a senzory",
                "reload_info": "🔄 Změny se projeví automaticky - integrace se restartuje",
                "performance_info": "⚡ Vypnuté moduly šetří výkon systému",
            },
        )

    async def async_step_extended_config(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Konfigurace rozšířených senzorů."""
        if user_input is not None:
            self._user_data.update(user_input)
            # Ujistíme se, že jsou extended sensors zapnuté
            self._user_data["enable_extended_sensors"] = True

            # Pokračuj na další kroky podle potřeby
            if self._user_data.get(
                "enable_solar_forecast", False
            ) and not self.config_entry.options.get("solar_forecast_api_key"):
                return await self.async_step_solar_forecast()
            elif self._user_data.get(
                "enable_pricing", False
            ) and not self.config_entry.options.get("pricing_configured"):
                return await self.async_step_pricing()
            else:
                result = self.async_create_entry(title="", data=self._user_data)

                # Vždy provedeme reload po změně konfigurace
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )

                return result

        # Získáme současné hodnoty
        current_options = self.config_entry.options

        schema_fields = {
            vol.Optional(
                "extended_scan_interval",
                default=current_options.get("extended_scan_interval", 300),
                description="⏱️ Interval aktualizace rozšířených senzorů (sekundy)",
            ): vol.All(int, vol.Range(min=60, max=3600)),
            vol.Optional(
                "enable_extended_battery_sensors",
                default=current_options.get("enable_extended_battery_sensors", True),
                description="🔋 Baterie - napětí, proudy, teplota a detailní stav",
            ): bool,
            vol.Optional(
                "enable_extended_fve_sensors",
                default=current_options.get("enable_extended_fve_sensors", True),
                description="☀️ Fotovoltaika - výkon a proudy jednotlivých stringů",
            ): bool,
            vol.Optional(
                "enable_extended_grid_sensors",
                default=current_options.get("enable_extended_grid_sensors", True),
                description="⚡ Síť a spotřeba - napětí, frekvence a výkon po fázích",
            ): bool,
        }

        return self.async_show_form(
            step_id="extended_config",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={
                "step_description": "📊 Konfigurace pokročilých senzorů pro detailní monitoring systému",
                "interval_info": "💡 Doporučený interval: 300 sekund (5 minut) pro optimální výkon",
                "battery_info": "🔋 Monitoruje: napětí článků, nabíjecí/vybíjecí proudy, teplotu, stav zdraví baterie",
                "fve_info": "☀️ Monitoruje: výkon každého stringu samostatně, proudy DC, efektivitu konverze",
                "grid_info": "⚡ Monitoruje: napětí L1/L2/L3, frekvenci sítě, výkon na každé fázi, cos φ",
                "reload_info": "🔄 Změny se projeví okamžitě - integrace se automaticky restartuje",
                "performance_note": "⚠️ Vypnuté senzory se přestanou aktualizovat a šetří výkon systému",
                "tip": "💡 Tip: Můžete kdykoliv zapnout/vypnout jednotlivé kategorie podle potřeby",
            },
        )

    async def async_step_solar_forecast(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Konfigurace solární předpovědi."""
        errors = {}

        if user_input is not None:
            # Validace GPS souřadnic
            try:
                lat = float(user_input.get("solar_forecast_latitude", 50.1219800))
                lon = float(user_input.get("solar_forecast_longitude", 13.9373742))
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    errors["base"] = "invalid_coordinates"
            except (ValueError, TypeError):
                errors["base"] = "invalid_coordinates"

            # Validace String 1 parametrů (povinný)
            try:
                string1_kwp = float(user_input.get("solar_forecast_string1_kwp", 5.4))
                string1_declination = int(
                    user_input.get("solar_forecast_string1_declination", 10)
                )
                string1_azimuth = int(
                    user_input.get("solar_forecast_string1_azimuth", 138)
                )

                if not (0 < string1_kwp <= 50):
                    errors["solar_forecast_string1_kwp"] = "invalid_kwp"
                if not (0 <= string1_declination <= 90):
                    errors["solar_forecast_string1_declination"] = "invalid_declination"
                if not (0 <= string1_azimuth <= 360):
                    errors["solar_forecast_string1_azimuth"] = "invalid_azimuth"
            except (ValueError, TypeError):
                errors["base"] = "invalid_string1_params"

            # Validace String 2 parametrů (pokud je povolen)
            if user_input.get("solar_forecast_string2_enabled", False):
                try:
                    string2_kwp = float(user_input.get("solar_forecast_string2_kwp", 0))
                    string2_declination = int(
                        user_input.get("solar_forecast_string2_declination", 10)
                    )
                    string2_azimuth = int(
                        user_input.get("solar_forecast_string2_azimuth", 138)
                    )

                    if not (0 < string2_kwp <= 50):
                        errors["solar_forecast_string2_kwp"] = "invalid_kwp"
                    if not (0 <= string2_declination <= 90):
                        errors["solar_forecast_string2_declination"] = (
                            "invalid_declination"
                        )
                    if not (0 <= string2_azimuth <= 360):
                        errors["solar_forecast_string2_azimuth"] = "invalid_azimuth"
                except (ValueError, TypeError):
                    errors["base"] = "invalid_string2_params"

            if not errors:
                # Uložení konfigurace včetně zapnutí solar forecast
                self._user_data.update(user_input)
                # Ujistíme se, že je solar forecast zapnutý
                self._user_data["enable_solar_forecast"] = True
                result = self.async_create_entry(title="", data=self._user_data)

                # Vždy provedeme reload po změně konfigurace
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )

                return result

        # Získání současných hodnot pro prefill
        current_options = self.config_entry.options if self.config_entry else {}

        schema = vol.Schema(
            {
                vol.Optional(
                    "solar_forecast_mode",
                    default=current_options.get(
                        "solar_forecast_mode", "daily_optimized"
                    ),
                ): vol.In(
                    {
                        "manual": "Manuální aktualizace (pouze přes službu)",
                        "daily_optimized": "3x denně (6:00, 12:00, 16:00) - DOPORUČENO",
                        "daily": "Jednou denně (6:00)",
                        "every_4h": "Každé 4 hodiny",
                        "hourly": "Každou hodinu (pouze pro testování)",
                    }
                ),
                vol.Optional(
                    "solar_forecast_api_key",
                    default=current_options.get("solar_forecast_api_key", ""),
                ): str,
                vol.Optional(
                    "solar_forecast_latitude",
                    default=current_options.get("solar_forecast_latitude", 50.1219800),
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_longitude",
                    default=current_options.get("solar_forecast_longitude", 13.9373742),
                ): vol.Coerce(float),
                # String 1 konfigurace (povinná)
                vol.Optional(
                    "solar_forecast_string1_kwp",
                    default=current_options.get("solar_forecast_string1_kwp", 5.4),
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_string1_declination",
                    default=current_options.get(
                        "solar_forecast_string1_declination", 10
                    ),
                ): vol.Coerce(int),
                vol.Optional(
                    "solar_forecast_string1_azimuth",
                    default=current_options.get("solar_forecast_string1_azimuth", 138),
                ): vol.Coerce(int),
                # String 2 konfigurace (volitelná)
                vol.Optional(
                    "solar_forecast_string2_enabled",
                    default=current_options.get(
                        "solar_forecast_string2_enabled", False
                    ),
                ): bool,
                vol.Optional(
                    "solar_forecast_string2_kwp",
                    default=current_options.get("solar_forecast_string2_kwp", 0),
                ): vol.Coerce(float),
                vol.Optional(
                    "solar_forecast_string2_declination",
                    default=current_options.get(
                        "solar_forecast_string2_declination", 10
                    ),
                ): vol.Coerce(int),
                vol.Optional(
                    "solar_forecast_string2_azimuth",
                    default=current_options.get("solar_forecast_string2_azimuth", 138),
                ): vol.Coerce(int),
            }
        )

        return self.async_show_form(
            step_id="solar_forecast",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "info": "Konfigurace solární předpovědi pomocí forecast.solar API. "
                "Bez API klíče máte limit 12 volání/den. S API klíčem až 50 volání/den.",
                "string1_info": "String 1 je povinný - zadejte parametry hlavního stringu FVE",
                "string2_info": "String 2 je volitelný - pro FVE se dvěma stringy s různými parametry",
                "coordinates_info": "GPS souřadnice vaší FVE (můžete najít na Google Maps)",
                "declination_info": "Sklon panelů (0° = vodorovně, 90° = svisle)",
                "azimuth_info": "Orientace panelů (0° = sever, 90° = východ, 180° = jih, 270° = západ)",
            },
        )

    async def async_step_pricing(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Konfigurace cenových funkcí."""
        if user_input is not None:
            self._user_data.update(user_input)
            self._user_data["pricing_configured"] = True
            result = self.async_create_entry(title="", data=self._user_data)

            # Automatický reload po změně konfigurace
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )

            return result

        return self.async_show_form(
            step_id="pricing",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "fixed_price_vt",
                        default=4.50,
                        description="Vaše cena VT (Kč/kWh)",
                    ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=20.0)),
                    vol.Required(
                        "fixed_price_nt",
                        default=3.20,
                        description="Vaše cena NT (Kč/kWh)",
                    ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=20.0)),
                    vol.Optional(
                        "distribution_area",
                        default="PRE",
                        description="Distribuční společnost",
                    ): vol.In(["PRE", "CEZ", "EGD"]),
                }
            ),
            description_placeholders={
                "step_description": "Nastavte vaše aktuální ceny elektřiny pro porovnání se spotovými cenami."
            },
        )

    async def _get_fve_installed_power(self) -> float:
        """Pokusí se detekovat instalovaný výkon FVE."""
        try:
            # Získáme data z koordinátoru
            if hasattr(self.config_entry, "runtime_data"):
                coordinator = self.config_entry.runtime_data.get("coordinator")
                if coordinator and coordinator.data:
                    pv_data = list(coordinator.data.values())[0]
                    # Zkusíme najít max výkon z parametrů
                    max_power = pv_data.get("box_prms", {}).get("pv_max_p", 10000)
                    return max_power / 1000  # Převod na kWp
        except:
            pass
        return 10.0  # Výchozí hodnota

    FLOW_SCHEMA = vol.Schema(
        {
            # ...existing fields...
            vol.Optional("enable_solar_forecast", default=False): bool,
            vol.Optional("solar_forecast_mode", default="daily_optimized"): vol.In(
                ["manual", "daily_optimized", "daily", "every_4h", "hourly"]
            ),
            vol.Optional("solar_forecast_api_key", default=""): str,
            vol.Optional("solar_forecast_latitude", default=50.1219800): vol.Coerce(
                float
            ),
            vol.Optional("solar_forecast_longitude", default=13.9373742): vol.Coerce(
                float
            ),
            vol.Optional("solar_forecast_string1_kwp", default=5.4): vol.Coerce(float),
            vol.Optional("solar_forecast_string1_declination", default=10): vol.Coerce(
                int
            ),
            vol.Optional("solar_forecast_string1_azimuth", default=138): vol.Coerce(
                int
            ),
            vol.Optional("solar_forecast_string2_enabled", default=False): bool,
            vol.Optional("solar_forecast_string2_kwp", default=0): vol.Coerce(float),
            vol.Optional("solar_forecast_string2_declination", default=10): vol.Coerce(
                int
            ),
            vol.Optional("solar_forecast_string2_azimuth", default=138): vol.Coerce(
                int
            ),
        }
    )
