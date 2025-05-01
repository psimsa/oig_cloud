import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_LOG_LEVEL,
    CONF_NO_TELEMETRY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
)
from .api.oig_cloud_api import OigCloudApi


class OigCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OIG Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            oig: OigCloudApi = OigCloudApi(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_NO_TELEMETRY],
                self.hass,
            )
            valid: bool = await oig.authenticate()
            if valid:
                state: Dict[str, Any] = await oig.get_stats()
                box_id: str = list(state.keys())[0]
                full_name: str = f"{DEFAULT_NAME}"

                return self.async_create_entry(title=full_name, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_NO_TELEMETRY, default=False): bool,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OigCloudOptionsFlow(config_entry)


class OigCloudOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the OIG Cloud integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=self._config_entry.options.get(
                    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30,
                    max=180,
                    step=10,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_NO_TELEMETRY,
                default=self._config_entry.options.get(
                    CONF_NO_TELEMETRY,
                    self._config_entry.data.get(CONF_NO_TELEMETRY, False),
                ),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_LOG_LEVEL,
                default=self._config_entry.options.get(CONF_LOG_LEVEL, "info"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "debug", "label": "Debug"},
                        {"value": "info", "label": "Info"},
                        {"value": "warning", "label": "Warning"},
                        {"value": "error", "label": "Error"},
                    ]
                )
            ),
        }

        return self.async_show_form(step_id="init", data_schema=vol.Schema(options))
