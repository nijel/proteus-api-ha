"""Binary sensor platform for Proteus API."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROL_TYPES, DOMAIN
from .entity import build_device_info, get_control_type_icon

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

        binary_sensors.extend(
            ProteusManualControlBinarySensor(
                coordinator,
                config_entry,
                inverter_id,
                inverter,
                control_type,
            )
            for control_type in CONTROL_TYPES
        )

    async_add_entities(binary_sensors)


class ProteusBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base class for Proteus binary sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, inverter_id, inverter):
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._inverter_id = inverter_id
        self._inverter = inverter
        self._attr_device_info = build_device_info(inverter_id, inverter)

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
    ):
        """Initialize the binary sensor."""
        super().__init__(coordinator, config_entry, inverter_id, inverter)
        self._control_type = control_type
        self._attr_translation_key = control_type.lower()
        self._attr_unique_id = self._get_unique_id(f"proteus_{control_type.lower()}")
        self._attr_icon = get_control_type_icon(control_type)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None
        manual_controls = self.coordinator.data.get("manual_controls")
        if manual_controls is None:
            return None
        return manual_controls.get(self._control_type)
