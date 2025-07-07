from homeassistant import config_entries
import voluptuous as vol
from homeassistant.const import CONF_NAME
from .const import DOMAIN

class ProteusAPIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            return self.async_create_entry(
                title="Proteus API",
                data={
                    "inverter_id_entity": user_input["inverter_id_entity"],
                    "session_cookie_entity": user_input["session_cookie_entity"],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("inverter_id_entity"): vol.EntitySelector({
                    "domain": "input_text"
                }),
                vol.Required("session_cookie_entity"): vol.EntitySelector({
                    "domain": "input_text"
                }),
            }),
            errors=errors,
        )
