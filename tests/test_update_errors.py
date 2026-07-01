"""Tests for update error propagation."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
from unittest.mock import AsyncMock

from aiohttp.client_exceptions import ClientConnectionError
import pytest

from custom_components.proteus_api import ProteusDataUpdateCoordinator
from custom_components.proteus_api.const import UPDATE_INTERVAL
from custom_components.proteus_api.proteus_api import AuthenticationError, ProteusAPI
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


class StubProteusAPI(ProteusAPI):
    """Proteus API client with network access replaced by test doubles."""

    def __init__(self) -> None:
        """Initialize the stub client."""
        super().__init__("inverter-1", "user@example.com", "secret")
        self.client = object()
        self.parsed_data: dict[str, Any] = {}
        self.price_result: tuple[Any | None, bool] = (None, False)
        self.status_exception: Exception | None = None
        self.status_result: tuple[Any | None, bool] = ([], False)
        self._next_price_update = float("inf")

    def set_cached_data(self, data: dict[str, Any]) -> None:
        """Set the cached status data."""
        self._last_data = data

    async def _get_client(self) -> object:
        """Return a stub client."""
        return self.client

    async def _fetch_trpc_batch(
        self, *args: Any, scope: str
    ) -> tuple[Any | None, bool]:
        """Return stubbed status or price responses."""
        if scope == "status":
            if self.status_exception is not None:
                raise self.status_exception
            return self.status_result
        return self.price_result

    def _parse_data(self, raw_data: Any) -> dict[str, Any]:
        """Return stubbed parser output."""
        return self.parsed_data


class ExposedProteusDataUpdateCoordinator(ProteusDataUpdateCoordinator):
    """Coordinator exposing one update call for unit tests."""

    async def update_once(self) -> Any:
        """Run the protected coordinator update implementation."""
        return await self._async_update_data()


class FailingLoginSession:
    """aiohttp session test double that fails login transport."""

    instances: list[FailingLoginSession] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Record the created session."""
        self.closed = False
        self.instances.append(self)

    def post(self, *args: Any, **kwargs: Any) -> Any:
        """Return a request context that fails before a response is available."""
        return FailingRequestContext(ClientConnectionError("connection reset"))

    async def close(self) -> None:
        """Record session cleanup."""
        self.closed = True


class FailingRequestContext:
    """Request context manager that fails before yielding a response."""

    def __init__(self, exception: BaseException) -> None:
        """Initialize with the exception to raise."""
        self.exception = exception

    async def __aenter__(self) -> Any:
        """Raise the configured transport failure."""
        raise self.exception

    async def __aexit__(self, *args: object) -> bool:
        """Do not suppress exceptions."""
        return False


class FailingRequestClient:
    """Retry client test double that fails GET transport."""

    def get(self, *args: Any, **kwargs: Any) -> Any:
        """Return a request context that raises a raw socket reset."""
        return FailingRequestContext(ConnectionResetError())


class DiscoveryFailingProteusAPI(ProteusAPI):
    """Proteus API client with failing inverter discovery transport."""

    async def _get_client(self) -> FailingRequestClient:
        """Return a failing retry client test double."""
        return FailingRequestClient()


@pytest.mark.asyncio
async def test_login_transport_errors_are_connection_errors(monkeypatch) -> None:
    """Login transport errors should not leak aiohttp exceptions."""
    FailingLoginSession.instances.clear()
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.aiohttp.ClientSession",
        FailingLoginSession,
    )
    api = ProteusAPI("", "user@example.com", "secret")

    with pytest.raises(ConnectionError, match="Failed to connect to Proteus API"):
        await api.fetch_inverters()

    assert len(FailingLoginSession.instances) == 1
    assert FailingLoginSession.instances[0].closed is True


@pytest.mark.asyncio
async def test_inverter_discovery_transport_errors_are_connection_errors() -> None:
    """Discovery transport errors should be normalized by the API client."""
    api = DiscoveryFailingProteusAPI("", "user@example.com", "secret")

    with pytest.raises(ConnectionError, match="ConnectionResetError"):
        await api.fetch_inverters()


@pytest.mark.asyncio
async def test_get_data_propagates_authentication_error() -> None:
    """Authentication failures should reach the coordinator."""
    api = StubProteusAPI()
    api.status_exception = AuthenticationError("expired session")

    with pytest.raises(AuthenticationError, match="expired session"):
        await api.get_data()


@pytest.mark.asyncio
async def test_get_data_raises_when_status_fetch_fails() -> None:
    """A failed status fetch should be an update failure, not None data."""
    api = StubProteusAPI()
    api.status_result = (None, False)

    with pytest.raises(ConnectionError, match="could not be fetched"):
        await api.get_data()


@pytest.mark.asyncio
async def test_get_data_raises_when_status_payload_has_no_usable_data() -> None:
    """Unusable status payloads should fail the coordinator update."""
    api = StubProteusAPI()
    api.status_result = ([{"result": {"data": {"json": {}}}}], False)
    api.parsed_data = {}

    with pytest.raises(ConnectionError, match="did not contain usable data"):
        await api.get_data()


@pytest.mark.asyncio
async def test_get_data_returns_cached_status_during_status_cooldown() -> None:
    """Rate-limited status refreshes should keep previous data when available."""
    api = StubProteusAPI()
    cached_data = {"state": "ok"}
    api.set_cached_data(cached_data)
    api.status_result = (None, True)

    assert await api.get_data() == cached_data


@pytest.mark.asyncio
async def test_get_data_raises_during_status_cooldown_without_cached_status() -> None:
    """A first update with no status data should not return None."""
    api = StubProteusAPI()
    api.status_result = (None, True)

    with pytest.raises(ConnectionError, match="did not contain usable data"):
        await api.get_data()


@pytest.mark.asyncio
async def test_coordinator_converts_authentication_errors(hass) -> None:
    """Authentication errors should trigger Home Assistant reauth handling."""
    update_method = AsyncMock(side_effect=AuthenticationError("expired session"))
    coordinator = ExposedProteusDataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        "Proteus API",
        update_method,
        timedelta(seconds=UPDATE_INTERVAL),
    )

    with pytest.raises(ConfigEntryAuthFailed, match="expired session"):
        await coordinator.update_once()


@pytest.mark.asyncio
async def test_coordinator_converts_connection_errors_to_update_failed(hass) -> None:
    """Connection errors should trigger Home Assistant update failure handling."""
    update_method = AsyncMock(side_effect=ConnectionError("status unavailable"))
    coordinator = ExposedProteusDataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        "Proteus API",
        update_method,
        timedelta(seconds=UPDATE_INTERVAL),
    )

    with pytest.raises(UpdateFailed, match="status unavailable"):
        await coordinator.update_once()
