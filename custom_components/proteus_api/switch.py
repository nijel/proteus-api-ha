"""Switch platform for Proteus API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROL_TYPES, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Proteus API switch based on a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    switches = []

    # Add manual control switches
    for control_type, friendly_name in CONTROL_TYPES.items():
        switches.append(
            ProteusManualControlSwitch(
                coordinator, config_entry, api, control_type, friendly_name
            )
        )

    # Add automatic mode switch
    switches.append(ProteusAutomaticModeSwitch(coordinator, config_entry, api))
    switches.append(ProteusFlexibilityModeSwitch(coordinator, config_entry, api))

    async_add_entities(switches)


class ProteusBaseSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for Proteus switches."""

    def __init__(self, coordinator, config_entry, api):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._api = api
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Proteus Inverter",
            "manufacturer": "Delta Green",
            "model": "Proteus",
        }


class ProteusManualControlSwitch(ProteusBaseSwitch):
    """Switch for manual control states."""

    def __init__(self, coordinator, config_entry, api, control_type, friendly_name):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api)
        self._control_type = control_type
        self._attr_name = f"Proteus {friendly_name}"
        self._attr_unique_id = f"proteus_switch_{control_type.lower()}"
        self._attr_icon = self._get_icon_for_control_type(control_type)

    def _get_icon_for_control_type(self, control_type: str) -> str:
        """Get icon for control type."""
        icons = {
            "SELLING_INSTEAD_OF_BATTERY_CHARGE": "mdi:transmission-tower-export",
            "SELLING_FROM_BATTERY": "mdi:battery-arrow-up",
            "USING_FROM_GRID_INSTEAD_OF_BATTERY": "mdi:battery-lock",
            "SAVING_TO_BATTERY": "mdi:battery-arrow-down",
            "BLOCKING_GRID_OVERFLOW": "mdi:transmission-tower-off",
        }
        return icons.get(control_type, "mdi:toggle-switch")

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        manual_controls = self.coordinator.data.get("manual_controls", {})
        return manual_controls.get(self._control_type, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        success = await self._api.update_manual_control(self._control_type, "ENABLED")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn on %s", self._control_type)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        success = await self._api.update_manual_control(self._control_type, "DISABLED")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn off %s", self._control_type)


class ProteusAutomaticModeSwitch(ProteusBaseSwitch):
    """Switch for automatic mode."""

    def __init__(self, coordinator, config_entry, api):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api)
        self._attr_name = "Proteus optimalizace algoritmem"
        self._attr_unique_id = "proteus_switch_automatic_mode"
        self._attr_icon = "mdi:creation"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (automatic mode)."""
        return self.coordinator.data.get("control_mode") == "AUTOMATIC"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable automatic mode)."""
        success = await self._api.update_control_mode("AUTOMATIC")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to enable automatic mode")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (enable manual mode)."""
        success = await self._api.update_control_mode("MANUAL")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to enable manual mode")


class ProteusFlexibilityModeSwitch(ProteusBaseSwitch):
    """Switch for flexibilith mode."""

    def __init__(self, coordinator, config_entry, api):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api)
        self._attr_name = "Proteus obchodování flexiblity"
        self._attr_unique_id = "proteus_switch_flexibility_mode"
        self._attr_icon = "mdi:robot"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (automatic mode)."""
        return self.coordinator.data.get("flexibility_mode") != "NONE"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable automatic mode)."""
        success = await self._api.update_flexibility_mode("FULL")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to enable automatic mode")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (enable manual mode)."""
        success = await self._api.update_flexibility_mode("NONE")
        if success:
            # Wait a bit and then refresh data
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to enable manual mode")
