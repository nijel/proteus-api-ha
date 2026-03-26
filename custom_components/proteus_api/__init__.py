"""Proteus API integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL, normalize_email
from .proteus_api import AuthenticationError, ProteusAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, current_inverter_ids: set[str]
) -> None:
    """Remove orphaned Proteus devices left behind by older installs."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        proteus_ids = {
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        }
        if not proteus_ids:
            continue
        if proteus_ids & current_inverter_ids:
            continue
        if er.async_entries_for_device(
            entity_registry,
            device_entry.id,
            include_disabled_entities=True,
        ):
            continue

        _LOGGER.info(
            "Removing stale device entry %s for missing inverter identifiers %s",
            device_entry.id,
            sorted(proteus_ids),
        )
        device_registry.async_remove_device(device_entry.id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy single-inverter config entries to the account-wide format."""
    if entry.version >= 2:
        return True

    _LOGGER.info(
        "Migrating config entry %s from version %s", entry.entry_id, entry.version
    )

    if "inverter_id" not in entry.data:
        hass.config_entries.async_update_entry(entry, version=2)
        return True

    normalized_email = normalize_email(entry.data["email"])

    for other_entry in hass.config_entries.async_entries(DOMAIN):
        if other_entry.entry_id == entry.entry_id:
            continue

        if normalize_email(other_entry.data.get("email", "")) != normalized_email:
            continue

        _LOGGER.info(
            "Removing duplicate legacy config entry %s for account %s during migration",
            entry.entry_id,
            entry.data["email"],
        )
        await hass.config_entries.async_remove(entry.entry_id)
        return False

    hass.config_entries.async_update_entry(
        entry,
        data={
            "email": entry.data["email"],
            "password": entry.data["password"],
        },
        title=f"Proteus API ({entry.data['email']})",
        unique_id=normalized_email,
        version=2,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Proteus API from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Empty string for inverter_id is acceptable here as we only need to
    # authenticate and fetch the list of available inverters.
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

    inverter_data = {}
    for inverter in inverters:
        inverter_id = inverter["id"]
        _LOGGER.info(
            "Setting up inverter %s (%s)",
            inverter_id,
            inverter.get("vendor", "Unknown"),
        )

        api = ProteusAPI(inverter_id, email, password)
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

    _async_remove_stale_devices(hass, entry, set(inverter_data))

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
