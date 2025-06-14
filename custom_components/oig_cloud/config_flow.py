import voluptuous as vol
import logging

from homeassistant import config_entries
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

# Nové konstanty pro skenovací intervaly
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"

CONF_SOLAR_FORECAST_ENABLED = "solar_forecast_enabled"
CONF_SOLAR_FORECAST_API_KEY = "solar_forecast_api_key"
CONF_SOLAR_FORECAST_LATITUDE = "solar_forecast_latitude"
CONF_SOLAR_FORECAST_LONGITUDE = "solar_forecast_longitude"
CONF_SOLAR_FORECAST_DECLINATION = "solar_forecast_declination"
CONF_SOLAR_FORECAST_AZIMUTH = "solar_forecast_azimuth"
CONF_SOLAR_FORECAST_KWP = "solar_forecast_kwp"
CONF_SOLAR_FORECAST_INTERVAL = "solar_forecast_interval"


class OigCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            oig = OigCloudApi(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_NO_TELEMETRY],
                self.hass,
            )
            valid = await oig.authenticate()
            if valid:
                state = await oig.get_stats()
                box_id = list(state.keys())[0]
                full_name = f"{DEFAULT_NAME}"

                return self.async_create_entry(
                    title=full_name,
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_NO_TELEMETRY: user_input[CONF_NO_TELEMETRY],
                        CONF_STANDARD_SCAN_INTERVAL: user_input[
                            CONF_STANDARD_SCAN_INTERVAL
                        ],
                        CONF_EXTENDED_SCAN_INTERVAL: user_input[
                            CONF_EXTENDED_SCAN_INTERVAL
                        ],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_NO_TELEMETRY, default=False): bool,
                    vol.Optional(CONF_STANDARD_SCAN_INTERVAL, default=30): vol.All(
                        int, vol.Range(min=10)
                    ),
                    vol.Optional(CONF_EXTENDED_SCAN_INTERVAL, default=300): vol.All(
                        int, vol.Range(min=300)
                    ),
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return OigCloudOptionsFlowHandler(config_entry)


class OigCloudOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Získání GPS z HA
        ha_latitude = self.hass.config.latitude
        ha_longitude = self.hass.config.longitude

        # Získání instalovaného výkonu FVE ze senzorů
        default_kwp = await self._get_fve_installed_power()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_STANDARD_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_STANDARD_SCAN_INTERVAL, 30
                        ),
                    ): vol.All(int, vol.Range(min=10)),
                    vol.Optional(
                        CONF_EXTENDED_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_EXTENDED_SCAN_INTERVAL, 300
                        ),
                    ): vol.All(int, vol.Range(min=300)),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_ENABLED,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_ENABLED, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_SOLAR_FORECAST_API_KEY,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_API_KEY, ""
                        ),
                    ): str,
                    vol.Optional(
                        CONF_SOLAR_FORECAST_LATITUDE,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_LATITUDE, ha_latitude
                        ),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_LONGITUDE,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_LONGITUDE, ha_longitude
                        ),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_DECLINATION,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_DECLINATION, 30
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_AZIMUTH,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_AZIMUTH, 180
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_KWP,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_KWP, default_kwp
                        ),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_SOLAR_FORECAST_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SOLAR_FORECAST_INTERVAL, 60
                        ),
                    ): vol.In([30, 60]),
                }
            ),
        )

    async def _get_fve_installed_power(self) -> float:
        """Získání instalovaného výkonu FVE ze senzorů."""
        try:
            # Oprava: správné získání entity registry
            entity_registry = er.async_get(self.hass)

            # Hledáme entity s FVE výkonem
            for entity_id in entity_registry.entities:
                if entity_id.startswith("sensor.oig_") and (
                    "fve_installed_power" in entity_id
                    or "dc_in_fv_p_max" in entity_id
                    or "fv_p_max" in entity_id
                ):

                    state = self.hass.states.get(entity_id)
                    if state and state.state not in ["unknown", "unavailable"]:
                        try:
                            # Převedeme na kWp (pokud je ve W)
                            power_w = float(state.state)
                            return power_w / 1000.0  # W -> kWp
                        except (ValueError, TypeError):
                            continue

            # Fallback: zkusíme spočítat z aktuálních dat coordinatoru
            return await self._calculate_fve_power_from_coordinator()

        except Exception as e:
            _LOGGER.warning(f"Could not get FVE installed power: {e}")
            return 10.0  # Fallback default

    async def _calculate_fve_power_from_coordinator(self) -> float:
        """Výpočet FVE výkonu z coordinator dat."""
        try:
            # Získáme coordinator z domain data
            domain_data = self.hass.data.get(DOMAIN, {})
            for entry_id, entry_data in domain_data.items():
                if "coordinator" in entry_data:
                    coordinator = entry_data["coordinator"]
                    if coordinator.data:
                        data = coordinator.data
                        pv_data = list(data.values())[0]

                        # Zkusíme různé možné klíče pro max výkon
                        possible_keys = [
                            ["dc_in", "fv_p_max"],
                            ["box_prms", "fv_p_max"],
                            ["invertor_prms", "p_max"],
                        ]

                        for key_path in possible_keys:
                            try:
                                value = pv_data
                                for key in key_path:
                                    value = value[key]
                                if value and float(value) > 0:
                                    return float(value) / 1000.0  # W -> kWp
                            except (KeyError, ValueError, TypeError):
                                continue

                        # Poslední pokus: součet aktuálních maxim
                        try:
                            fv1_max = float(pv_data.get("dc_in", {}).get("fv_p1", 0))
                            fv2_max = float(pv_data.get("dc_in", {}).get("fv_p2", 0))
                            if fv1_max > 0 or fv2_max > 0:
                                # Odhad: aktuální výkon * 3 (hrubý odhad max výkonu)
                                estimated_max = (fv1_max + fv2_max) * 3
                                return estimated_max / 1000.0  # W -> kWp
                        except (ValueError, TypeError):
                            pass

                        break

        except Exception as e:
            _LOGGER.debug(f"Could not calculate FVE power from coordinator: {e}")

        return 10.0  # Ultimate fallback
