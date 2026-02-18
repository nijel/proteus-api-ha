"""Proteus API integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .proteus_api import ProteusAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Proteus API from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Create a temporary API instance to fetch available inverters
    temp_api = ProteusAPI("", email, password)
    inverters = await temp_api.fetch_inverters()
    
    if not inverters:
        _LOGGER.error("No inverters found for account %s", email)
        return False

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
        hass.data[DOMAIN].pop(entry.entry_id)

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
        except Exception as exception:
            raise UpdateFailed(exception) from exception
