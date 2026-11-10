"""Tests for the solar forecast Energy platform."""

from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proteus_api.const import DOMAIN
from custom_components.proteus_api.energy import async_get_solar_forecast
from homeassistant.components.config import config_entries
from homeassistant.components.energy.websocket_api import async_get_energy_platforms
from homeassistant.setup import async_setup_component


async def test_energy_discovers_proteus_forecast(
    hass, enable_custom_integrations
) -> None:
    """The Energy dashboard must discover Proteus as a solar forecast provider."""
    assert await async_setup_component(hass, DOMAIN, {})
    platforms = await async_get_energy_platforms(hass)
    assert platforms[DOMAIN] is async_get_solar_forecast


async def test_forecast_is_offered_by_energy_settings(
    hass, hass_ws_client, enable_custom_integrations
) -> None:
    """Energy's frontend requests only service entries from forecast domains."""
    assert await async_setup_component(hass, "http", {})
    config_entries.async_setup(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, title="Proteus API")
    entry.add_to_hass(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "config_entries/get",
            "domain": DOMAIN,
            "type_filter": ["service"],
        }
    )
    result = await client.receive_json()
    assert result["success"] is True
    assert [item["entry_id"] for item in result["result"]] == [entry.entry_id]


async def test_forecast_sums_inverters_without_mixing_accounts(hass) -> None:
    """Energy selects an account entry, so combine its inverters only."""
    first = "2026-11-10T08:00:00+00:00"
    second = "2026-11-10T09:00:00+00:00"
    hass.data[DOMAIN] = {
        "account": {
            "inverters": {
                "one": {
                    "coordinator": SimpleNamespace(
                        last_update_success=True,
                        data={"production_forecast": {first: 500.0, second: 0.0}},
                    )
                },
                "two": {
                    "coordinator": SimpleNamespace(
                        last_update_success=True,
                        data={"production_forecast": {first: 250.0}},
                    )
                },
                "failed": {
                    "coordinator": SimpleNamespace(
                        last_update_success=False,
                        data={"production_forecast": {first: 1000.0}},
                    )
                },
            }
        },
        "other": {
            "inverters": {
                "three": {
                    "coordinator": SimpleNamespace(
                        last_update_success=True,
                        data={"production_forecast": {first: 999.0}},
                    )
                }
            }
        },
    }

    assert await async_get_solar_forecast(hass, "account") == {
        "wh_hours": {first: 750.0, second: 0.0}
    }


async def test_missing_forecast(hass) -> None:
    """Unloaded entries and missing data must not produce a forecast."""
    assert await async_get_solar_forecast(hass, "missing") is None
    hass.data[DOMAIN] = {
        "account": {
            "inverters": {
                "one": {
                    "coordinator": SimpleNamespace(last_update_success=True, data={})
                },
                "two": {
                    "coordinator": SimpleNamespace(last_update_success=False, data=None)
                },
            }
        }
    }
    assert await async_get_solar_forecast(hass, "account") is None
