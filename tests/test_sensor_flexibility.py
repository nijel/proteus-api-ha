"""Tests for flexibility earnings sensors and the Energy dashboard carrier."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.proteus_api.sensor import async_setup_entry
from custom_components.proteus_api.volume import VOLUME_FIELDS
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory


class _FakeCoordinator:
    """Minimal coordinator stub for entity tests."""

    def __init__(self, data):
        self.data = data

    def async_add_listener(self, update_callback):
        """Register a listener."""
        return lambda: None


async def _setup_sensors(hass, data):
    entry = SimpleNamespace(entry_id="entry-id")
    hass.data = {
        "proteus_api": {
            "entry-id": {
                "inverters": {
                    "inv-1": {
                        "coordinator": _FakeCoordinator(data),
                        "inverter": {"vendor": "SOLAX"},
                    }
                }
            }
        }
    }

    added_entities = []
    await async_setup_entry(hass, entry, added_entities.extend)
    return {entity.unique_id: entity for entity in added_entities}


@pytest.mark.asyncio
async def test_flexibility_total_is_usable_as_energy_compensation(hass) -> None:
    """The total earnings sensor should have a currency unit and sum statistics."""
    by_unique_id = await _setup_sensors(
        hass,
        {
            "flexibility_today": 20.37,
            "flexibility_month": 102.65,
            "flexibility_total": 3874.5,
            "flexibility_currency": "CZK",
        },
    )

    total = by_unique_id["proteus_flexibility_total_inv-1"]
    assert total.native_value == 3874.5
    assert total.native_unit_of_measurement == "CZK"
    assert total.device_class == SensorDeviceClass.MONETARY
    assert total.state_class == SensorStateClass.TOTAL

    for unique_id in (
        "proteus_flexibility_today_inv-1",
        "proteus_flexibility_month_inv-1",
    ):
        sensor = by_unique_id[unique_id]
        assert sensor.native_unit_of_measurement == "CZK"
        assert sensor.device_class == SensorDeviceClass.MONETARY
        assert sensor.state_class is None


@pytest.mark.asyncio
async def test_flexibility_earnings_energy_carrier_stays_at_zero(hass) -> None:
    """The Energy dashboard carrier should be a 0 kWh total energy sensor."""
    by_unique_id = await _setup_sensors(hass, {"flexibility_total": 3874.5})

    carrier = by_unique_id["proteus_flexibility_earnings_energy_inv-1"]
    assert carrier.native_value == 0.0
    assert carrier.native_unit_of_measurement == "kWh"
    assert carrier.device_class == SensorDeviceClass.ENERGY
    assert carrier.state_class == SensorStateClass.TOTAL
    assert carrier.entity_category == EntityCategory.DIAGNOSTIC


@pytest.mark.asyncio
async def test_flexibility_earnings_energy_carrier_is_unknown_without_data(
    hass,
) -> None:
    """Without coordinator data the carrier should not report a value."""
    by_unique_id = await _setup_sensors(hass, None)

    assert (
        by_unique_id["proteus_flexibility_earnings_energy_inv-1"].native_value is None
    )


@pytest.mark.asyncio
async def test_flexibility_earnings_use_api_currency(hass) -> None:
    """Earnings sensors should report the currency sent by the API."""
    by_unique_id = await _setup_sensors(
        hass, {"flexibility_total": 12.5, "flexibility_currency": "RON"}
    )

    for unique_id in (
        "proteus_flexibility_today_inv-1",
        "proteus_flexibility_month_inv-1",
        "proteus_flexibility_total_inv-1",
    ):
        assert by_unique_id[unique_id].native_unit_of_measurement == "RON"


@pytest.mark.asyncio
async def test_flexibility_earnings_default_to_czk(hass) -> None:
    """Without a currency from the API the sensors should fall back to CZK."""
    by_unique_id = await _setup_sensors(hass, {"flexibility_total": 12.5})
    assert (
        by_unique_id["proteus_flexibility_total_inv-1"].native_unit_of_measurement
        == "CZK"
    )
    by_unique_id = await _setup_sensors(hass, None)
    assert (
        by_unique_id["proteus_flexibility_total_inv-1"].native_unit_of_measurement
        == "CZK"
    )


@pytest.mark.asyncio
async def test_daily_volume_sensors_have_explicit_reset(hass) -> None:
    """Daily totals support statistics and corrections without false resets."""
    reset = datetime(2026, 10, 12, tzinfo=UTC)
    data = {
        **dict.fromkeys(VOLUME_FIELDS, 1.25),
        "flexibility_volume_last_reset": reset,
    }
    entities = await _setup_sensors(hass, data)
    for key in VOLUME_FIELDS:
        sensor = entities[f"proteus_{key}_inv-1"]
        assert sensor.native_value == 1.25
        assert sensor.native_unit_of_measurement == "kWh"
        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.state_class == SensorStateClass.TOTAL
        assert sensor.last_reset == reset
        data[key] = 0.5
        assert sensor.native_value == 0.5
        assert sensor.last_reset == reset
    empty = await _setup_sensors(hass, None)
    for key in VOLUME_FIELDS:
        assert empty[f"proteus_{key}_inv-1"].native_value is None
        assert empty[f"proteus_{key}_inv-1"].last_reset is None
