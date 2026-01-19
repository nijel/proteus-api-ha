"""Config flow for Proteus API integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .proteus_api import ProteusAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("inverter_id"): str,
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class InvalidInverterId(HomeAssistantError):
    """Error to indicate the inverter ID format is invalid."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # Validate inverter ID format: 25 lowercase letters and digits
    inverter_id = data["inverter_id"]
    if not re.match(r"^[a-z0-9]{25}$", inverter_id):
        raise InvalidInverterId

    api = ProteusAPI(inverter_id, data["email"], data["password"])

    try:
        # Test the connection using executor job for synchronous API
        result = await hass.async_add_executor_job(api.get_data)
    except Exception as ex:
        _LOGGER.error("Connection failed: %s", ex)
        raise CannotConnect from ex
    if not result:
        raise InvalidAuth

    return {"title": f"Proteus API ({inverter_id[:8]}...)"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Proteus API."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "inverter_id_help": "ID invertoru z URL (např. z https://proteus.deltagreen.cz/cs/device/inverter/XXX)",
                    "email_help": "E-mail",
                    "password_help": "Heslo, musíte mít nastavené přihlašování přes heslo",
                },
            )

        errors = {}
        try:
            info = await validate_input(self.hass, user_input)
        except InvalidInverterId:
            errors["inverter_id"] = "invalid_inverter_id"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
