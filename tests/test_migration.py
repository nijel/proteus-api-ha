"""Tests for config entry migration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proteus_api import async_migrate_entry
from custom_components.proteus_api.const import DOMAIN


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
