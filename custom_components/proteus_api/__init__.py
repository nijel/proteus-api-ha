"""Proteus API integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .proteus_api import AuthenticationError, ProteusAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Proteus API from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Check if this is an old config entry with inverter_id
    if "inverter_id" in entry.data:
        # Migration: old single-inverter config
        inverter_id = entry.data["inverter_id"]
        _LOGGER.info("Migrating old config entry with inverter_id %s", inverter_id)

        # Create API instance for the single inverter
        api = ProteusAPI(inverter_id, email, password)

        # Fetch inverter info for device metadata
        temp_api = ProteusAPI("", email, password)
        try:
            inverters = await temp_api.fetch_inverters()
        except AuthenticationError as ex:
            _LOGGER.error("Authentication failed during migration: %s", ex)
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {ex}"
            ) from ex
        except Exception:
            _LOGGER.exception("Failed to fetch inverter info during migration")
            inverters = []
        finally:
            await temp_api.close()

        # Find matching inverter or use default info
        inverter = None
        for inv in inverters:
            if inv["id"] == inverter_id:
                inverter = inv
                break

        if inverter is None:
            # Fallback if we can't find the inverter in the list
            inverter = {
                "id": inverter_id,
                "vendor": "Delta Green",
                "featureFlags": [],
                "controlMode": "UNKNOWN",
                "controlEnabled": False,
            }

        # Create coordinator for this inverter
        coordinator = ProteusDataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"proteus_api_{inverter_id}",
            update_method=api.get_data,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        await coordinator.async_config_entry_first_refresh()

        inverter_data = {
            inverter_id: {
                "coordinator": coordinator,
                "api": api,
                "inverter": inverter,
            }
        }
    else:
        # New multi-inverter config
        # Create a temporary API instance to fetch available inverters
        # Empty string for inverter_id is acceptable as we only need to authenticate
        temp_api = ProteusAPI("", email, password)
        try:
            inverters = await temp_api.fetch_inverters()
        except AuthenticationError as ex:
            _LOGGER.error("Authentication failed: %s", ex)
            raise ConfigEntryAuthFailed(f"Authentication failed: {ex}") from ex
        except ConnectionError as ex:
            _LOGGER.error("Failed to fetch inverters: %s", ex)
            raise ConfigEntryNotReady(f"Failed to fetch inverters: {ex}") from ex
        finally:
            await temp_api.close()

        if not inverters:
            _LOGGER.warning("No inverters found for account %s", email)
            raise ConfigEntryNotReady(
                "No inverters found for this account. Please check your account status."
            )

        # Create coordinators for all discovered inverters
        inverter_data = {}
        for inverter in inverters:
            inverter_id = inverter["id"]
            _LOGGER.info(
                "Setting up inverter %s (%s)",
                inverter_id,
                inverter.get("vendor", "Unknown"),
            )

            # Create API instance for this inverter
            api = ProteusAPI(inverter_id, email, password)

            # Create coordinator for this inverter
            coordinator = ProteusDataUpdateCoordinator(
                hass,
                _LOGGER,
                name=f"proteus_api_{inverter_id}",
                update_method=api.get_data,
                update_interval=timedelta(seconds=UPDATE_INTERVAL),
            )

            await coordinator.async_config_entry_first_refresh()

            inverter_data[inverter_id] = {
                "coordinator": coordinator,
                "api": api,
                "inverter": inverter,
            }

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "inverters": inverter_data,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Close all API sessions
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        for inverter_id, inverter_info in entry_data["inverters"].items():
            api = inverter_info["api"]
            await api.close()
            _LOGGER.debug("Closed API session for inverter %s", inverter_id)

    return unload_ok


class ProteusDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Proteus API."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        update_method,
        update_interval: timedelta,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_method=update_method,
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Update data via library."""
        try:
            return await self.update_method()
        except AuthenticationError as exception:
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {exception}"
            ) from exception
        except Exception as exception:
            raise UpdateFailed(exception) from exception
