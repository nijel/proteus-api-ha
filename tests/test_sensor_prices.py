"""Tests for price sensor setup."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.proteus_api.sensor import async_setup_entry


class _FakeCoordinator:
    """Minimal coordinator stub for entity tests."""

    def __init__(self, data):
        self.data = data

    def async_add_listener(self, update_callback):
        """Register a listener."""
        return lambda: None


@pytest.mark.asyncio
async def test_price_sensors_are_created_with_expected_values(hass) -> None:
    """Price entities should be created from coordinator data."""
    entry = SimpleNamespace(entry_id="entry-id")
    hass.data = {
        "proteus_api": {
            "entry-id": {
                "inverters": {
                    "inv-1": {
                        "coordinator": _FakeCoordinator(
                            {
                                "price_consumption_kwh": 8.4173,
                                "price_consumption_mwh": 8417.258278,
                                "price_production_kwh": 3.7114,
                                "price_production_mwh": 3711.4218,
                                "distribution_tariff_type": "HT",
                                "price_components": {
                                    "price_mwh": 4161.4218,
                                    "distribution_price": 2252.45,
                                    "distribution_tariff_type": "HT",
                                    "fee_electricity_buy": 350,
                                    "fee_electricity_sell": 450,
                                    "tax_electricity": 28.3,
                                    "system_services": 164.24,
                                    "poze": 0,
                                    "vat_rate": 0.21,
                                },
                            }
                        ),
                        "inverter": {"vendor": "VICTRON_ENERGY"},
                    }
                }
            }
        }
    }

    added_entities = []

    def _add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, _add_entities)

    by_unique_id = {entity.unique_id: entity for entity in added_entities}

    consumption = by_unique_id["proteus_price_consumption_inv-1"]
    assert consumption.native_value == 8.4173
    assert consumption.suggested_display_precision == 2
    assert consumption.extra_state_attributes == {
        "price_mwh": 4161.4218,
        "distribution_price": 2252.45,
        "distribution_tariff_type": "HT",
        "fee_electricity_buy": 350,
        "fee_electricity_sell": 450,
        "tax_electricity": 28.3,
        "system_services": 164.24,
        "poze": 0,
        "vat_rate": 0.21,
        "price_consumption_mwh": 8417.258278,
    }

    production = by_unique_id["proteus_price_production_inv-1"]
    assert production.native_value == 3.7114
    assert production.suggested_display_precision == 2
    assert production.extra_state_attributes == {
        "price_production_mwh": 3711.4218,
    }

    tariff = by_unique_id["proteus_distribution_tariff_type_inv-1"]
    assert tariff.native_value == "HT"
