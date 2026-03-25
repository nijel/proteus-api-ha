"""Switch platform for Proteus API."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROL_TYPES, DOMAIN, FLEXIBILITY_CAPABILITIES, format_vendor_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Proteus API switch based on a config entry."""
    inverters_data = hass.data[DOMAIN][config_entry.entry_id]["inverters"]

    switches = []
    for inverter_id, inverter_info in inverters_data.items():
        coordinator = inverter_info["coordinator"]
        api = inverter_info["api"]
        inverter = inverter_info["inverter"]

        # Add manual control switches
        for control_type, friendly_name in CONTROL_TYPES.items():
            switches.append(
                ProteusManualControlSwitch(
                    coordinator,
                    config_entry,
                    api,
                    inverter_id,
                    inverter,
                    control_type,
                    friendly_name,
                )
            )

        # Add automatic mode switch
        switches.append(
            ProteusControlEnabledSwitch(
                coordinator, config_entry, api, inverter_id, inverter
            )
        )
        switches.append(
            ProteusAutomaticModeSwitch(
                coordinator, config_entry, api, inverter_id, inverter
            )
        )
        switches.append(
            ProteusFlexibilityModeSwitch(
                coordinator, config_entry, api, inverter_id, inverter
            )
        )

    async_add_entities(switches)


class ProteusBaseSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for Proteus switches."""

    def __init__(self, coordinator, config_entry, api, inverter_id, inverter):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._api = api
        self._inverter_id = inverter_id
        self._inverter = inverter
        vendor_name = format_vendor_name(inverter.get("vendor", "Unknown"))
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inverter_id)},
            "name": f"{vendor_name} Inverter",
            "manufacturer": vendor_name,
            "model": "Proteus",
        }

    def _get_unique_id(self, base_id: str) -> str:
        """Get unique ID with inverter_id suffix."""
        return f"{base_id}_{self._inverter_id}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._clear_optimistic_state()
        super()._handle_coordinator_update()

    def _clear_optimistic_state(self) -> None:
        """Clear any optimistic state held by the entity."""


class ProteusOptimisticSwitch(ProteusBaseSwitch):
    """Base class for switches using optimistic state updates."""

    def __init__(self, coordinator, config_entry, api, inverter_id, inverter):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api, inverter_id, inverter)
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data is None:
            return None
        return self._get_backend_state()

    def _get_backend_state(self) -> bool:
        """Return the latest backend state for the entity."""
        raise NotImplementedError

    def _set_optimistic_state(self, state: bool | None) -> None:
        """Update optimistic state and refresh the entity."""
        self._optimistic_state = state
        self.async_write_ha_state()

    def _clear_optimistic_state(self) -> None:
        """Clear optimistic state once coordinator data catches up."""
        if self._optimistic_state is not None:
            self._set_optimistic_state(None)

    async def _apply_optimistic_update(
        self,
        enabled: bool,
        update_call,
        *,
        failure_message: str,
    ) -> None:
        """Apply an optimistic state change and clear it on failure."""
        self._set_optimistic_state(enabled)
        success = await update_call()
        if not success:
            self._set_optimistic_state(None)
            _LOGGER.error(failure_message)


class ProteusManualControlSwitch(ProteusOptimisticSwitch):
    """Switch for manual control states."""

    def __init__(
        self,
        coordinator,
        config_entry,
        api,
        inverter_id,
        inverter,
        control_type,
        friendly_name,
    ):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api, inverter_id, inverter)
        self._control_type = control_type
        self._attr_name = f"Proteus {friendly_name}"
        self._attr_unique_id = self._get_unique_id(
            f"proteus_switch_{control_type.lower()}"
        )
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
    def available(self) -> bool:
        """Return entity availability."""
        if self.coordinator.data is None:
            return False
        return (
            self.coordinator.data.get("control_enabled")
            and self.coordinator.data.get("control_mode") == "MANUAL"
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data is None:
            return None
        return self._get_backend_state()

    def _get_backend_state(self) -> bool | None:
        """Return the latest backend state for this control."""
        manual_controls = self.coordinator.data.get("manual_controls")
        if manual_controls is None:
            return None
        return manual_controls.get(self._control_type)

    async def _set_manual_control(self, enabled: bool) -> None:
        """Apply a manual control change with optimistic UI state."""
        await self._apply_optimistic_update(
            enabled,
            lambda: self._api.update_manual_control(
                self._control_type, "ENABLED" if enabled else "DISABLED"
            ),
            failure_message=(
                f"Failed to turn {'on' if enabled else 'off'} {self._control_type}"
            ),
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._set_manual_control(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._set_manual_control(False)


class ProteusControlEnabledSwitch(ProteusOptimisticSwitch):
    """Switch for control enabled."""

    def __init__(self, coordinator, config_entry, api, inverter_id, inverter):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api, inverter_id, inverter)
        self._attr_name = "Proteus řízení FVE"
        self._attr_unique_id = self._get_unique_id("proteus_switch_control_enabled")
        self._attr_icon = "mdi:network"

    def _get_backend_state(self) -> bool:
        """Return the latest backend state for this control."""
        return self.coordinator.data.get("control_enabled")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable automatic enabled)."""
        await self._apply_optimistic_update(
            True,
            lambda: self._api.update_control_enabled(True),
            failure_message="Failed to enable automatic enabled",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (enable manual enabled)."""
        await self._apply_optimistic_update(
            False,
            lambda: self._api.update_control_enabled(False),
            failure_message="Failed to enable manual enabled",
        )


class ProteusAutomaticModeSwitch(ProteusOptimisticSwitch):
    """Switch for automatic mode."""

    def __init__(self, coordinator, config_entry, api, inverter_id, inverter):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api, inverter_id, inverter)
        self._attr_name = "Proteus optimalizace algoritmem"
        self._attr_unique_id = self._get_unique_id("proteus_switch_automatic_mode")
        self._attr_icon = "mdi:creation"

    def _get_backend_state(self) -> bool:
        """Return the latest backend state for this control."""
        return self.coordinator.data.get("control_mode") == "AUTOMATIC"

    @property
    def available(self) -> bool:
        """Return entity availability."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get("control_enabled")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable automatic mode)."""
        await self._apply_optimistic_update(
            True,
            lambda: self._api.update_control_mode("AUTOMATIC"),
            failure_message="Failed to enable automatic mode",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (enable manual mode)."""
        await self._apply_optimistic_update(
            False,
            lambda: self._api.update_control_mode("MANUAL"),
            failure_message="Failed to disable manual mode",
        )


class ProteusFlexibilityModeSwitch(ProteusOptimisticSwitch):
    """Switch for flexibility mode."""

    def __init__(self, coordinator, config_entry, api, inverter_id, inverter):
        """Initialize the switch."""
        super().__init__(coordinator, config_entry, api, inverter_id, inverter)
        self._attr_name = "Proteus obchodování flexibility"
        self._attr_unique_id = self._get_unique_id("proteus_switch_flexibility_mode")
        self._attr_icon = "mdi:robot"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (automatic mode)."""
        if self.coordinator.data is None:
            return None
        capabilities = self.coordinator.data.get("flexibility_capabilities")
        if capabilities is None:
            return None
        return capabilities != []
      
    def _get_backend_state(self) -> bool:
        """Return the latest backend state for this control."""
        return self.coordinator.data.get("flexibility_capabilities") != []

    @property
    def available(self) -> bool:
        """Return entity availability."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get("control_enabled")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable automatic mode)."""
        await self._apply_optimistic_update(
            True,
            lambda: self._api.update_flexibility_mode(list(FLEXIBILITY_CAPABILITIES)),
            failure_message="Failed to enable flexibility",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (enable manual mode)."""
        await self._apply_optimistic_update(
            False,
            lambda: self._api.update_flexibility_mode([]),
            failure_message="Failed to disable flexibility",
        )
