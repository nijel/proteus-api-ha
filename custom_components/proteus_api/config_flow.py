import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

class ProteusApiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Proteus API", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("inverter_id"): str,
                vol.Required("session_cookie"): str,
            }),
            errors=errors,
        )
