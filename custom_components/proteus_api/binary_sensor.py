"""Binary sensor platform for Proteus API."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    """Set up Proteus API binary sensor based on a config entry."""
    inverters_data = hass.data[DOMAIN][config_entry.entry_id]["inverters"]

    binary_sensors = []
    for inverter_id, inverter_info in inverters_data.items():
        coordinator = inverter_info["coordinator"]
        inverter = inverter_info["inverter"]

        for control_type, friendly_name in CONTROL_TYPES.items():
            binary_sensors.append(
                ProteusManualControlBinarySensor(
                    coordinator,
                    config_entry,
                    inverter_id,
                    inverter,
                    control_type,
                    friendly_name,
                )
            )

    async_add_entities(binary_sensors)


class ProteusBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base class for Proteus binary sensors."""

    def __init__(self, coordinator, config_entry, inverter_id, inverter):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._inverter_id = inverter_id
        self._inverter = inverter
        vendor_name = inverter.get("vendor", "Unknown")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, inverter_id)},
            "name": f"{vendor_name} Inverter",
            "manufacturer": vendor_name,
            "model": "Proteus",
        }

    def _get_unique_id(self, base_id: str) -> str:
        """Get unique ID with inverter_id suffix."""
        return f"{base_id}_{self._inverter_id}"


class ProteusManualControlBinarySensor(ProteusBaseBinarySensor):
    """Binary sensor for manual control states."""

    def __init__(
        self,
        coordinator,
        config_entry,
        inverter_id,
        inverter,
        control_type,
        friendly_name,
    ):
        """Initialize the binary sensor."""
        super().__init__(coordinator, config_entry, inverter_id, inverter)
        self._control_type = control_type
        self._attr_name = f"Proteus {friendly_name}"
        self._attr_unique_id = self._get_unique_id(f"proteus_{control_type.lower()}")
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
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None
        manual_controls = self.coordinator.data.get("manual_controls", {})
        return manual_controls.get(self._control_type, False)
