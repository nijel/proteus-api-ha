"""Tests for config flow behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proteus_api.const import DOMAIN


@pytest.mark.asyncio
async def test_updates_unique_id_when_email_changes(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Options flow should update both entry data and unique id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "old@example.com", "password": "secret"},
        unique_id="old@example.com",
        title="Proteus API (old@example.com)",
    )
    entry.add_to_hass(hass)

    monkeypatch.setattr(
        "custom_components.proteus_api.config_flow.validate_input",
        AsyncMock(return_value={"title": "Proteus API (new@example.com)"}),
    )
    setup_entry_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "custom_components.proteus_api.async_setup_entry",
        setup_entry_mock,
    )

    init_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert init_result["type"] == "form"

    result = await hass.config_entries.options.async_configure(
        init_result["flow_id"], {"email": " New@Example.com ", "password": "updated"}
    )

    assert result["type"] == "create_entry"
    assert entry.data["email"] == " New@Example.com "
    assert entry.data["password"] == "updated"
    assert entry.unique_id == "new@example.com"
    assert entry.title == "Proteus API (new@example.com)"
    setup_entry_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejects_duplicate_unique_id_when_email_changes(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Options flow should block rebinding to an already configured account."""
    current_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "old@example.com", "password": "secret"},
        unique_id="old@example.com",
    )
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "taken@example.com", "password": "secret"},
        unique_id="taken@example.com",
    )
    current_entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)

    monkeypatch.setattr(
        "custom_components.proteus_api.config_flow.validate_input",
        AsyncMock(return_value={"title": "Proteus API (taken@example.com)"}),
    )

    init_result = await hass.config_entries.options.async_init(current_entry.entry_id)
    assert init_result["type"] == "form"

    result = await hass.config_entries.options.async_configure(
        init_result["flow_id"], {"email": "Taken@Example.com", "password": "updated"}
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    assert current_entry.unique_id == "old@example.com"
