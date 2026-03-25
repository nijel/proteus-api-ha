"""Tests for API payload parsing."""

from __future__ import annotations

from custom_components.proteus_api.proteus_api import parse_data


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

    assert parsed["price_consumption_kwh"] == 8.4173
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
