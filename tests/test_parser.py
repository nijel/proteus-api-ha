"""Tests for API payload parsing."""

from __future__ import annotations

from custom_components.proteus_api.proteus_api import ProteusAPI


def _build_payload(capabilities: list[str]) -> list[dict]:
    """Build a minimal payload for parser tests."""
    return [
        {
            "result": {
                "data": {
                    "json": {
                        "household": {"flexibilityState": "USABLE"},
                        "controlMode": "AUTOMATIC",
                        "controlEnabled": True,
                    }
                }
            }
        },
        {
            "result": {
                "data": {
                    "json": {
                        "todayWithVat": 1.0,
                        "monthToDateWithVat": 2.0,
                        "totalWithVat": 3.0,
                    }
                }
            }
        },
        {
            "result": {
                "data": {
                    "json": {
                        "manualControls": [],
                        "flexibilityCapabilitiesEnabled": capabilities,
                    }
                }
            }
        },
        {"result": {"data": {"json": {}}}},
        {"result": {"data": {"json": None}}},
    ]


def test_sets_full_mode_for_all_capabilities() -> None:
    """All supported capabilities should map to FULL mode."""
    api = ProteusAPI("inverter-id", "user@example.com", "secret")
    parsed = api._parse_data(  # noqa: SLF001
        _build_payload(
            [
                "UP_POWER",
                "DOWN_BATTERY_POWER",
                "DOWN_SOLAR_CURTAILMENT_POWER",
            ]
        )
    )

    assert parsed["flexibility_mode"] == "FULL"


def test_sets_partial_mode_for_subset_of_capabilities() -> None:
    """A subset of capabilities should map to PARTIAL mode."""
    api = ProteusAPI("inverter-id", "user@example.com", "secret")
    parsed = api._parse_data(_build_payload(["UP_POWER"]))  # noqa: SLF001

    assert parsed["flexibility_mode"] == "PARTIAL"


def test_sets_none_mode_for_empty_capabilities() -> None:
    """No enabled capabilities should map to NONE mode."""
    api = ProteusAPI("inverter-id", "user@example.com", "secret")
    parsed = api._parse_data(_build_payload([]))  # noqa: SLF001

    assert parsed["flexibility_mode"] == "NONE"
