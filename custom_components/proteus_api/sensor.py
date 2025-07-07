"""Sensor platform for Proteus API."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Proteus API sensor based on a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    
    sensors = [
        ProteusFlexibilityStatusSensor(coordinator, config_entry),
        ProteusModeSensor(coordinator, config_entry),
        ProteusFlexibilityTodaySensor(coordinator, config_entry),
        ProteusFlexibilityMonthSensor(coordinator, config_entry),
        ProteusFlexibilityTotalSensor(coordinator, config_entry),
        ProteusCommandSensor(coordinator, config_entry),
        ProteusCommandEndSensor(coordinator, config_entry),
        ProteusBatteryModeSensor(coordinator, config_entry),
        ProteusBatteryFallbackSensor(coordinator, config_entry),
        ProteusPvModeSensor(coordinator, config_entry),
        ProteusTargetSocSensor(coordinator, config_entry),
        ProteusPredictedProductionSensor(coordinator, config_entry),
        ProteusPredictedConsumptionSensor(coordinator, config_entry),
    ]
    
    async_add_entities(sensors)


class ProteusBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Proteus sensors."""

    def __init__(self, coordinator, config_entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Proteus Inverter",
            "manufacturer": "Delta Green",
            "model": "Proteus",
        }


class ProteusFlexibilityStatusSensor(ProteusBaseSensor):
    """Flexibility status sensor."""

    _attr_name = "Proteus flexibilita dostupná"
    _attr_unique_id = "proteus_flex_status"
    _attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self):
        """Return the native value of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("flexibility_state")

class ProteusModeSensor(ProteusBaseSensor):
    """Mode sensor."""

    _attr_name = "Proteus režim"
    _attr_unique_id = "proteus_mode"
    _attr_icon = "mdi:cog"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("control_mode")


class ProteusFlexibilityTodaySensor(ProteusBaseSensor):
    """Flexibility today sensor."""

    _attr_name = "Proteus obchodování flexibility dnes"
    _attr_unique_id = "proteus_flexibility_today"
    _attr_native_unit_of_measurement = "Kč"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:currency-czk"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexibility_today")


class ProteusFlexibilityMonthSensor(ProteusBaseSensor):
    """Flexibility month sensor."""

    _attr_name = "Proteus obchodování flexibility za měsíc"
    _attr_unique_id = "proteus_flexibility_month"
    _attr_native_unit_of_measurement = "Kč"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:currency-czk"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexibility_month")


class ProteusFlexibilityTotalSensor(ProteusBaseSensor):
    """Flexibility total sensor."""

    _attr_name = "Proteus obchodování flexibility celkem"
    _attr_unique_id = "proteus_flexibility_total"
    _attr_native_unit_of_measurement = "Kč"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:currency-czk"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexibility_total")


class ProteusCommandSensor(ProteusBaseSensor):
    """Command sensor."""

    _attr_name = "Proteus příkaz flexibility"
    _attr_unique_id = "proteus_command"
    _attr_icon = "mdi:flash"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("current_command")


class ProteusCommandEndSensor(ProteusBaseSensor):
    """Command end sensor."""

    _attr_name = "Proteus konec flexibility"
    _attr_unique_id = "proteus_command_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("command_end")


class ProteusBatteryModeSensor(ProteusBaseSensor):
    """Battery mode sensor."""

    _attr_name = "Proteus režim baterie"
    _attr_unique_id = "proteus_flexalgo_battery"
    _attr_icon = "mdi:battery"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexalgo_battery")


class ProteusBatteryFallbackSensor(ProteusBaseSensor):
    """Battery fallback sensor."""

    _attr_name = "Proteus záložní režim baterie"
    _attr_unique_id = "proteus_flexalgo_battery_fallback"
    _attr_icon = "mdi:battery-outline"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexalgo_battery_fallback")


class ProteusPvModeSensor(ProteusBaseSensor):
    """PV mode sensor."""

    _attr_name = "Proteus režim výroby"
    _attr_unique_id = "proteus_flexalgo_pv"
    _attr_icon = "mdi:solar-panel"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("flexalgo_pv")


class ProteusTargetSocSensor(ProteusBaseSensor):
    """Target SoC sensor."""

    _attr_name = "Proteus cílový SOC"
    _attr_unique_id = "proteus_target_soc"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-charging"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("target_soc")


class ProteusPredictedProductionSensor(ProteusBaseSensor):
    """Predicted production sensor."""

    _attr_name = "Proteus odhad výroby"
    _attr_unique_id = "proteus_predicted_production"
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:solar-power"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("predicted_production")


class ProteusPredictedConsumptionSensor(ProteusBaseSensor):
    """Predicted consumption sensor."""

    _attr_name = "Proteus odhad spotřeby"
    _attr_unique_id = "proteus_predicted_consumption"
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-lightning-bolt"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        return self.coordinator.data.get("predicted_consumption")
