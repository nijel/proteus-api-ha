"""Config flow for Proteus API integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .proteus_api import AuthenticationError, ProteusAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoInverters(HomeAssistantError):
    """Error to indicate no inverters found."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # Create API instance without inverter_id to test credentials
    # Empty string is acceptable here as we only need to authenticate and fetch inverters list
    api = ProteusAPI("", data["email"], data["password"])

    try:
        # Test the connection by fetching inverters list
        inverters = await api.fetch_inverters()
    except AuthenticationError as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        raise InvalidAuth from ex
    except Exception as ex:
        _LOGGER.error("Connection failed: %s", ex)
        raise CannotConnect from ex
    finally:
        # Always close the API session
        await api.close()

    if not inverters:
        raise NoInverters

    # Store the email as the title
    return {"title": f"Proteus API ({data['email']})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Proteus API."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
            )

        errors = {}
        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Check if this account is already configured
            # Use normalized email as unique identifier since we're discovering all inverters
            normalized_email = user_input["email"].strip().casefold()
            await self.async_set_unique_id(normalized_email)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Proteus API integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    def _get_options_schema(self) -> vol.Schema:
        """Get the options schema with current values."""
        return vol.Schema(
            {
                vol.Required("email", default=self.config_entry.data.get("email")): str,
                vol.Required("password"): str,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Validate the new credentials
            errors = {}
            try:
                info = await validate_input(self.hass, user_input)
            except AuthenticationError as ex:
                _LOGGER.error("Authentication failed: %s", ex)
                errors["base"] = "invalid_auth"
            except NoInverters:
                errors["base"] = "no_inverters"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Update the config entry with new credentials
                # Preserve existing data and only update email/password
                updated_data = dict(self.config_entry.data)
                updated_data["email"] = user_input["email"]
                updated_data["password"] = user_input["password"]

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=updated_data,
                    title=info["title"],
                )
                # Reload the config entry to apply new credentials
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

            # Show form with errors
            return self.async_show_form(
                step_id="init",
                data_schema=self._get_options_schema(),
                errors=errors,
            )

        # Show form with current email
        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(),
        )
