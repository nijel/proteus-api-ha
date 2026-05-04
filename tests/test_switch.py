"""Tests for switch platform behavior."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.proteus_api.const import FLEXIBILITY_CAPABILITIES
from custom_components.proteus_api.switch import ProteusFlexibilityModeSwitch


class StubCoordinator:
    """Coordinator test double with mutable data."""

    last_update_success = True

    def __init__(self, data: dict[str, Any] | None) -> None:
        """Initialize the stub coordinator."""
        self.data = data


@pytest.mark.asyncio
async def test_flexibility_mode_switch_uses_optimistic_state_before_backend_data(
    monkeypatch,
) -> None:
    """Flexibility mode should keep optimistic state until coordinator refresh."""
    coordinator = StubCoordinator({"flexibility_capabilities": []})
    api = AsyncMock()
    api.update_flexibility_mode = AsyncMock(return_value=True)
    switch = ProteusFlexibilityModeSwitch(
        coordinator,
        object(),
        api,
        "inverter-1",
        {},
    )
    monkeypatch.setattr(switch, "async_write_ha_state", lambda: None)

    assert switch.is_on is False

    await switch.async_turn_on()

    api.update_flexibility_mode.assert_awaited_once_with(list(FLEXIBILITY_CAPABILITIES))
    assert coordinator.data == {"flexibility_capabilities": []}
    assert switch.is_on is True
