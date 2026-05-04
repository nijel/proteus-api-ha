"""Tests for switch platform behavior."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.proteus_api.const import CONTROL_TYPES, FLEXIBILITY_CAPABILITIES
from custom_components.proteus_api.switch import (
    ProteusAutomaticModeSwitch,
    ProteusFlexibilityModeSwitch,
    ProteusManualControlSwitch,
)


class StubCoordinator:
    """Coordinator test double with mutable data."""

    def __init__(
        self,
        data: dict[str, Any] | None,
        *,
        last_update_success: bool = True,
    ) -> None:
        """Initialize the stub coordinator."""
        self.data = data
        self.last_update_success = last_update_success


def test_custom_switch_availability_respects_failed_coordinator_update() -> None:
    """Custom availability should still include coordinator update health."""
    api = AsyncMock()
    inverter_id = "inverter-1"
    inverter = {}
    control_type = CONTROL_TYPES[0]
    manual_coordinator = StubCoordinator(
        {
            "control_enabled": True,
            "control_mode": "MANUAL",
            "manual_controls": {control_type: True},
        },
    )
    automatic_coordinator = StubCoordinator(
        {"control_enabled": True, "control_mode": "AUTOMATIC"},
    )
    flexibility_coordinator = StubCoordinator(
        {
            "control_enabled": True,
            "flexibility_capabilities": list(FLEXIBILITY_CAPABILITIES),
        },
    )

    manual_switch = ProteusManualControlSwitch(
        manual_coordinator,
        object(),
        api,
        inverter_id,
        inverter,
        control_type,
    )
    automatic_switch = ProteusAutomaticModeSwitch(
        automatic_coordinator,
        object(),
        api,
        inverter_id,
        inverter,
    )
    flexibility_switch = ProteusFlexibilityModeSwitch(
        flexibility_coordinator,
        object(),
        api,
        inverter_id,
        inverter,
    )

    assert manual_switch.available is True
    assert automatic_switch.available is True
    assert flexibility_switch.available is True

    manual_coordinator.last_update_success = False
    automatic_coordinator.last_update_success = False
    flexibility_coordinator.last_update_success = False

    assert manual_switch.available is False
    assert automatic_switch.available is False
    assert flexibility_switch.available is False


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
