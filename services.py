import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .api.oig_cloud import OigCloud

MODES = {
    "Home 1": "0",
    "Home 2": "1",
    "Home 3": "2",
    "Home UPS": "3",
}


async def async_setup_entry_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    async def async_set_box_mode(call):
        client: OigCloud = hass.data[DOMAIN][entry.entry_id]
        mode = call.data.get("Mode")
        mode_value = MODES.get(mode)
        success = await client.set_box_mode(mode_value)

    # async def async_set_grid_delivery(call):
    #     entity_ids = await async_extract_entity_ids(hass, call)
    #     enabled = call.data.get("enabled")
    #     for entity_id in entity_ids:
    #         entity = hass.data[DOMAIN].get(entity_id)
    #         if entity:
    #             success = await client.set_grid_delivery(enabled)
    #             if success:
    #                 entity.async_write_ha_state()

    hass.services.async_register(
        DOMAIN,
        "set_box_mode",
        async_set_box_mode,
        schema=vol.Schema(
            {
                vol.Required("Mode"): vol.In(
                    [
                        "Home 1",
                        "Home 2",
                        "Home 3",
                        "Home UPS",
                    ]
                ),
                vol.Required("Acknowledgement"): vol.Boolean(1),
            }
        ),
    )

    # hass.services.async_register(
    #     DOMAIN, "set_grid_delivery", async_set_grid_delivery, schema=vol.Schema({vol.Required("enabled"): bool})
    # )
