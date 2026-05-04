"""Tests for integration setup behavior."""

from __future__ import annotations

from typing import Any

from aiohttp.client_exceptions import ClientConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.proteus_api as proteus_integration
from custom_components.proteus_api.const import DOMAIN
from homeassistant.exceptions import ConfigEntryNotReady


class FakeProteusAPI:
    """Proteus API test double that records created clients."""

    instances: list[FakeProteusAPI] = []

    def __init__(self, inverter_id: str, email: str, password: str) -> None:
        """Initialize the fake client."""
        self.inverter_id = inverter_id
        self.email = email
        self.password = password
        self.close_calls = 0
        self.instances.append(self)

    async def fetch_inverters(self) -> list[dict[str, str]]:
        """Return two fake inverters."""
        return [{"id": "inv-1"}, {"id": "inv-2"}]

    async def get_data(self) -> dict[str, Any]:
        """Return fake inverter data."""
        return {}

    async def close(self) -> None:
        """Record that the fake client was closed."""
        self.close_calls += 1


class FailingSecondCoordinator:
    """Coordinator test double that fails the second inverter refresh."""

    def __init__(
        self,
        *args: Any,
        name: str,
        update_method: Any,
        update_interval: Any,
    ) -> None:
        """Initialize the fake coordinator."""
        self.name = name

    async def async_config_entry_first_refresh(self) -> None:
        """Fail while refreshing the second inverter."""
        if self.name == "proteus_api_inv-2":
            raise RuntimeError("refresh failed")


class ConnectionFailingProteusAPI(FakeProteusAPI):
    """Proteus API test double that fails during inverter discovery."""

    async def fetch_inverters(self) -> list[dict[str, str]]:
        """Raise a raw aiohttp transport error."""
        raise ClientConnectionError("cannot connect")


@pytest.mark.asyncio
async def test_setup_closes_created_api_clients_when_inverter_refresh_fails(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Partial setup should not leak API sessions."""
    FakeProteusAPI.instances.clear()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    monkeypatch.setattr(proteus_integration, "ProteusAPI", FakeProteusAPI)
    monkeypatch.setattr(
        proteus_integration,
        "ProteusDataUpdateCoordinator",
        FailingSecondCoordinator,
    )

    with pytest.raises(RuntimeError, match="refresh failed"):
        await proteus_integration.async_setup_entry(hass, entry)

    assert [api.inverter_id for api in FakeProteusAPI.instances] == [
        "",
        "inv-1",
        "inv-2",
    ]
    assert [api.close_calls for api in FakeProteusAPI.instances] == [1, 1, 1]
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_setup_retries_raw_aiohttp_connection_errors(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Startup transport failures should ask Home Assistant to retry setup."""
    FakeProteusAPI.instances.clear()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"email": "user@example.com", "password": "secret"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    monkeypatch.setattr(proteus_integration, "ProteusAPI", ConnectionFailingProteusAPI)

    with pytest.raises(ConfigEntryNotReady, match="cannot connect"):
        await proteus_integration.async_setup_entry(hass, entry)

    assert len(FakeProteusAPI.instances) == 1
    assert FakeProteusAPI.instances[0].close_calls == 1
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
