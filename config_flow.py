import voluptuous as vol
from .oig_cloud import OigCloud
from homeassistant import config_entries

from .const import CONF_NO_TELEMETRY, DEFAULT_NAME, DOMAIN, CONF_USERNAME, CONF_PASSWORD


class OigCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            oig = OigCloud(user_input[CONF_USERNAME], user_input[CONF_PASSWORD], user_input[CONF_NO_TELEMETRY])
            valid = await oig.authenticate()
            if valid:
                state = await oig.get_stats()
                box_id = list(state.keys())[0]
                is_queen = state[box_id]["queen"]
                if is_queen:
                    full_name = f"{DEFAULT_NAME} Queen {box_id}"
                else:
                    full_name = f"{DEFAULT_NAME} Home {box_id}"

                return self.async_create_entry(
                    title=full_name, data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str, vol.Required(CONF_NO_TELEMETRY): bool}
            )
        )
