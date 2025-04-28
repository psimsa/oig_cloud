import voluptuous as vol

from homeassistant import config_entries
from .const import (
    CONF_NO_TELEMETRY,
    DEFAULT_NAME,
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
)
from .api.oig_cloud_api import OigCloudApi

# Nové konstanty pro skenovací intervaly
CONF_STANDARD_SCAN_INTERVAL = "standard_scan_interval"
CONF_EXTENDED_SCAN_INTERVAL = "extended_scan_interval"

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
                        CONF_STANDARD_SCAN_INTERVAL: user_input[CONF_STANDARD_SCAN_INTERVAL],
                        CONF_EXTENDED_SCAN_INTERVAL: user_input[CONF_EXTENDED_SCAN_INTERVAL],
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
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_STANDARD_SCAN_INTERVAL, default=self.config_entry.options.get(CONF_STANDARD_SCAN_INTERVAL, 30)): vol.All(int, vol.Range(min=10)),
                    vol.Optional(CONF_EXTENDED_SCAN_INTERVAL, default=self.config_entry.options.get(CONF_EXTENDED_SCAN_INTERVAL, 300)): vol.All(int, vol.Range(min=300)),
                }
            ),
        )