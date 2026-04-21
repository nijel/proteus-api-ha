"""Tests for API payload parsing."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

import pytest

from custom_components.proteus_api.const import PRICE_UPDATE_DELAY
from custom_components.proteus_api.proteus_api import (
    get_seconds_until_next_price_update,
    parse_data,
    parse_price_data,
)


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
        {
            "result": {
                "data": {
                    "json": {
                        "priceMwh": 4161.4218,
                        "priceConsumptionMwh": 8417.258278,
                        "priceProductionMwh": 3711.4218,
                        "priceComponents": {
                            "distributionPrice": 2252.45,
                            "distributionTariffType": "HT",
                            "feeElectricityBuy": 350,
                            "feeElectricitySell": 450,
                            "taxElectricity": 28.3,
                            "systemServices": 164.24,
                            "poze": 0,
                            "vatRate": 0.21,
                        },
                    }
                }
            }
        },
    ]


def test_sets_full_mode_for_all_capabilities() -> None:
    """All supported capabilities should map to FULL mode."""
    parsed = parse_data(
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
    parsed = parse_data(_build_payload(["UP_POWER"]))

    assert parsed["flexibility_mode"] == "PARTIAL"


def test_sets_none_mode_for_empty_capabilities() -> None:
    """No enabled capabilities should map to NONE mode."""
    parsed = parse_data(_build_payload([]))

    assert parsed["flexibility_mode"] == "NONE"


def test_parses_distribution_prices() -> None:
    """Distribution prices should be converted to per-kWh sensors."""
    parsed = parse_data(_build_payload(["UP_POWER"]))

    assert parsed["price_consumption_mwh"] == 8417.258278
    assert parsed["price_consumption_kwh"] == 8.4173
    assert parsed["price_production_mwh"] == 3711.4218
    assert parsed["price_production_kwh"] == 3.7114
    assert parsed["distribution_tariff_type"] == "HT"
    assert parsed["price_components"] == {
        "price_mwh": 4161.4218,
        "distribution_price": 2252.45,
        "distribution_tariff_type": "HT",
        "fee_electricity_buy": 350,
        "fee_electricity_sell": 450,
        "tax_electricity": 28.3,
        "system_services": 164.24,
        "poze": 0,
        "vat_rate": 0.21,
    }


def test_parses_current_up_flexibility_price() -> None:
    """Up command price should be selected from structured command prices."""
    payload = _build_payload(["UP_POWER"])
    payload[3] = {
        "result": {
            "data": {
                "json": {
                    "command": {
                        "id": "command-1",
                        "source": "API",
                        "type": "UP_TEST_POWER",
                        "startAt": "2026-04-21T14:48:06.576Z",
                        "endAt": "2026-04-21T14:59:59.000Z",
                        "effectiveEndAt": "2026-04-21T14:59:29.000Z",
                        "isTesting": False,
                    },
                    "price": {"priceUp": 9.793001261, "priceDown": None},
                }
            }
        }
    }

    parsed = parse_data(payload)

    assert parsed["current_command"] == "UP_TEST_POWER"
    assert parsed["command_id"] == "command-1"
    assert parsed["command_source"] == "API"
    assert parsed["command_start"] == datetime(
        2026, 4, 21, 14, 48, 6, 576000, tzinfo=UTC
    )
    assert parsed["command_effective_end"] == datetime(
        2026, 4, 21, 14, 59, 29, tzinfo=UTC
    )
    assert parsed["command_is_testing"] is False
    assert parsed["flexibility_price_up_kwh"] == 9.793001261
    assert parsed["flexibility_price_down_kwh"] is None
    assert parsed["flexibility_price_mwh"] == pytest.approx(9793.001261)
    assert parsed["flexibility_price_kwh"] == 9.793


def test_parses_current_down_flexibility_price() -> None:
    """Down command price should be selected from structured command prices."""
    payload = _build_payload(["DOWN_SOLAR_CURTAILMENT_POWER"])
    payload[3] = {
        "result": {
            "data": {
                "json": {
                    "command": {
                        "type": "DOWN_TEST_POWER",
                        "endAt": "2026-04-21T14:59:59.000Z",
                    },
                    "price": {"priceUp": None, "priceDown": 8.123456789},
                }
            }
        }
    }

    parsed = parse_data(payload)

    assert parsed["current_command"] == "DOWN_TEST_POWER"
    assert parsed["flexibility_price_up_kwh"] is None
    assert parsed["flexibility_price_down_kwh"] == 8.123456789
    assert parsed["flexibility_price_mwh"] == pytest.approx(8123.456789)
    assert parsed["flexibility_price_kwh"] == 8.1235


def test_logs_unexpected_current_flexibility_price(caplog) -> None:
    """Unexpected command price payloads should be logged for diagnosis."""
    payload = _build_payload(["UP_POWER"])
    payload[3] = {
        "result": {
            "data": {
                "json": {
                    "command": {
                        "type": "UP_POWER",
                        "endAt": "2026-04-21T12:15:00+00:00",
                    },
                    "price": {"amount": 1234.5678},
                }
            }
        }
    }

    with caplog.at_level(
        logging.WARNING, logger="custom_components.proteus_api.proteus_api"
    ):
        parsed = parse_data(payload)

    assert "flexibility_price_mwh" not in parsed
    assert "expected price field for command type UP_POWER" in caplog.text
    assert "'price': {'amount': 1234.5678}" in caplog.text


def test_parses_standalone_distribution_prices() -> None:
    """Standalone distribution price responses should parse like batched payloads."""
    parsed = parse_price_data([_build_payload(["UP_POWER"])[5]])

    assert parsed["price_consumption_mwh"] == 8417.258278
    assert parsed["price_consumption_kwh"] == 8.4173
    assert parsed["price_production_mwh"] == 3711.4218
    assert parsed["price_production_kwh"] == 3.7114
    assert parsed["distribution_tariff_type"] == "HT"
    assert parsed["price_components"] == {
        "price_mwh": 4161.4218,
        "distribution_price": 2252.45,
        "distribution_tariff_type": "HT",
        "fee_electricity_buy": 350,
        "fee_electricity_sell": 450,
        "tax_electricity": 28.3,
        "system_services": 164.24,
        "poze": 0,
        "vat_rate": 0.21,
    }


def test_schedules_prices_after_next_quarter_hour_boundary() -> None:
    """Price refreshes should align to quarter-hour tariff changes."""
    assert (
        get_seconds_until_next_price_update((16 * 60 * 60) + (14 * 60) + 50)
        == 10 + PRICE_UPDATE_DELAY
    )
    assert (
        get_seconds_until_next_price_update((16 * 60 * 60) + (15 * 60))
        == (15 * 60) + PRICE_UPDATE_DELAY
    )


def test_missing_prices_do_not_break_existing_fields() -> None:
    """Legacy 5-item payloads should still parse existing fields."""
    parsed = parse_data(_build_payload(["UP_POWER"])[:5])

    assert parsed["flexibility_mode"] == "PARTIAL"
    assert "price_consumption_kwh" not in parsed


def test_malformed_prices_do_not_break_existing_fields() -> None:
    """Malformed price payloads should not break the rest of the parse."""
    payload = _build_payload(["UP_POWER"])
    payload[5] = {"result": {"data": {"json": {"priceComponents": "invalid"}}}}

    parsed = parse_data(payload)

    assert parsed["flexibility_mode"] == "PARTIAL"
    assert "price_consumption_kwh" not in parsed
    assert "price_components" not in parsed
