from typing import Any, Dict, Optional, Awaitable
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant # Should not be used directly, self.hass is available
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

from .const import (
    CONF_NO_TELEMETRY,
    DEFAULT_NAME,
    DOMAIN,
    # Assuming these are defined in const.py as per problem description
    CONF_STANDARD_SCAN_INTERVAL,
    CONF_EXTENDED_SCAN_INTERVAL,
    DEFAULT_STANDARD_SCAN_INTERVAL,
    DEFAULT_EXTENDED_SCAN_INTERVAL,
)
from .api.oig_cloud_api import OigCloudApi, OigCloudAuthError

_LOGGER = logging.getLogger(__name__)

class OigCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1 # Required for config flows

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Awaitable[ConfigFlowResult]:
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Extract typed data from user_input
            username: str = user_input[CONF_USERNAME]
            password: str = user_input[CONF_PASSWORD]
            no_telemetry: bool = user_input[CONF_NO_TELEMETRY]
            # These will be used from user_input for data, defaults are for schema
            standard_scan_interval: int = user_input[CONF_STANDARD_SCAN_INTERVAL]
            extended_scan_interval: int = user_input[CONF_EXTENDED_SCAN_INTERVAL]

            try:
                # self.hass is an instance of HomeAssistant, correctly typed by the base class
                oig: OigCloudApi = OigCloudApi(
                    username,
                    password,
                    no_telemetry,
                    self.hass, # Pass HomeAssistant instance
                    standard_scan_interval # Pass scan interval to API if it uses it
                )
                
                # Check unique ID to prevent duplicate entries
                # Using username as a unique identifier for the config entry
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()

                valid_auth: bool = await oig.authenticate()
                if valid_auth:
                    # Optionally, get stats to confirm API access and maybe get a device name/ID
                    # state: Optional[Dict[str, Any]] = await oig.get_stats()
                    # box_id: Optional[str] = None
                    # if state and isinstance(state, dict) and state.keys():
                    #     box_id = list(state.keys())[0]
                    
                    # Using username for the title to make it more descriptive
                    title_name: str = f"{DEFAULT_NAME} {username}"

                    return self.async_create_entry(
                        title=title_name,
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: password, # Note: Storing password might be a security concern
                            CONF_NO_TELEMETRY: no_telemetry,
                            CONF_STANDARD_SCAN_INTERVAL: standard_scan_interval,
                            CONF_EXTENDED_SCAN_INTERVAL: extended_scan_interval,
                        },
                    )
                else:
                    # This case should ideally be caught by OigCloudAuthError
                    errors["base"] = "auth"
            except OigCloudAuthError:
                _LOGGER.error("Authentication failed for OIG Cloud")
                errors["base"] = "auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during OIG Cloud setup")
                errors["base"] = "unknown"

        # Show form if user_input is None or if there were errors
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_NO_TELEMETRY, default=False): bool,
                    vol.Optional(
                        CONF_STANDARD_SCAN_INTERVAL, default=DEFAULT_STANDARD_SCAN_INTERVAL
                    ): vol.All(int, vol.Range(min=10)),
                    vol.Optional(
                        CONF_EXTENDED_SCAN_INTERVAL, default=DEFAULT_EXTENDED_SCAN_INTERVAL
                    ): vol.All(int, vol.Range(min=300)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow: # Type hint return
        return OigCloudOptionsFlowHandler(config_entry)


class OigCloudOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry: ConfigEntry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Awaitable[ConfigFlowResult]:
        if user_input is not None:
            # Ensure data is correctly typed if further processing is needed
            # For options flow, user_input directly becomes the options data
            return self.async_create_entry(title="", data=user_input)

        # Get current values for defaults in the form
        current_standard_scan_interval: int = self.config_entry.options.get(
            CONF_STANDARD_SCAN_INTERVAL, DEFAULT_STANDARD_SCAN_INTERVAL
        )
        current_extended_scan_interval: int = self.config_entry.options.get(
            CONF_EXTENDED_SCAN_INTERVAL, DEFAULT_EXTENDED_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_STANDARD_SCAN_INTERVAL, default=current_standard_scan_interval
                    ): vol.All(int, vol.Range(min=10)),
                    vol.Optional(
                        CONF_EXTENDED_SCAN_INTERVAL, default=current_extended_scan_interval
                    ): vol.All(int, vol.Range(min=300)),
                }
            ),
        )