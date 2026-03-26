"""Tests for config entry migration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proteus_api import (
    _async_remove_stale_devices,
    async_migrate_entry,
)
from custom_components.proteus_api.const import DOMAIN
from homeassistant.helpers import device_registry as dr, entity_registry as er


@pytest.mark.asyncio
async def test_migrates_legacy_entry_to_account_scope(hass) -> None:
    """Legacy single-inverter entries should be rewritten to account scope."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "email": " User@Example.com ",
            "password": "secret",
            "inverter_id": "inv-1",
        },
        version=1,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.data == {"email": " User@Example.com ", "password": "secret"}
    assert entry.title == "Proteus API ( User@Example.com )"
    assert entry.unique_id == "user@example.com"
    assert entry.version == 2


@pytest.mark.asyncio
async def test_removes_duplicate_legacy_entry_during_migration(hass) -> None:
    """Duplicate legacy entries for one account should be collapsed."""
    current_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "email": "User@Example.com",
            "password": "secret",
            "inverter_id": "inv-1",
        },
        version=1,
    )
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        unique_id="user@example.com",
        version=2,
    )
    current_entry.add_to_hass(hass)
    existing_entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, current_entry)

    assert result is False
    assert hass.config_entries.async_get_entry(current_entry.entry_id) is None


@pytest.mark.asyncio
async def test_removes_stale_device_without_entities(hass) -> None:
    """Orphaned devices from older installs should be removed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        unique_id="user@example.com",
        version=2,
    )
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    stale_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "stale-inverter")},
        manufacturer="Vendor",
        model="Proteus",
        name="Vendor Inverter",
    )
    active_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "active-inverter")},
        manufacturer="Vendor",
        model="Proteus",
        name="Vendor Inverter",
    )

    _async_remove_stale_devices(hass, entry, {"active-inverter"})

    assert device_registry.async_get(stale_device.id) is None
    assert device_registry.async_get(active_device.id) is not None


@pytest.mark.asyncio
async def test_keeps_stale_device_if_entities_still_exist(hass) -> None:
    """Devices with registry entities should not be removed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        unique_id="user@example.com",
        version=2,
    )
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    stale_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "stale-inverter")},
        manufacturer="Vendor",
        model="Proteus",
        name="Vendor Inverter",
    )

    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "proteus_mode_stale-inverter",
        config_entry=entry,
        device_id=stale_device.id,
        original_name="Mode",
    )

    _async_remove_stale_devices(hass, entry, {"active-inverter"})

    assert device_registry.async_get(stale_device.id) is not None
