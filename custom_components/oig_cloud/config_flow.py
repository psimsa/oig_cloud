import voluptuous as vol

from homeassistant import config_entries
from custom_components.oig_cloud.const import CONF_NO_TELEMETRY, DEFAULT_NAME, DOMAIN, CONF_USERNAME, CONF_PASSWORD
from custom_components.oig_cloud.api.oig_cloud_api import OigCloudApi


class OigCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            oig = OigCloudApi(user_input[CONF_USERNAME], user_input[CONF_PASSWORD], user_input[CONF_NO_TELEMETRY],
                           self.hass)
            valid = await oig.authenticate()
            if valid:
                state = await oig.get_stats()
                box_id = list(state.keys())[0]
                full_name = f"{DEFAULT_NAME}"
                
                return self.async_create_entry(
                    title=full_name, data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str,
                 vol.Required(CONF_NO_TELEMETRY): bool}
            )
        )
