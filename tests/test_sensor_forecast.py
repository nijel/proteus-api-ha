"""Tests for visible daily PV forecast entities."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from custom_components.proteus_api.const import DOMAIN
from custom_components.proteus_api.sensor import async_setup_entry
from homeassistant.components.sensor import SensorDeviceClass


@pytest.mark.parametrize(
    ("day", "last_today", "first_tomorrow"),
    [
        (
            datetime(2026, 11, 10),
            "2026-11-10T22:00:00+00:00",
            "2026-11-10T23:00:00+00:00",
        ),
        (
            datetime(2026, 3, 29),
            "2026-03-29T21:00:00+00:00",
            "2026-03-29T22:00:00+00:00",
        ),
        (
            datetime(2026, 10, 25),
            "2026-10-25T22:00:00+00:00",
            "2026-10-25T23:00:00+00:00",
        ),
    ],
)
async def test_daily_forecasts_are_created_and_follow_local_days(
    hass, monkeypatch, day, last_today, first_tomorrow
):
    """Entities expose daily kWh and hourly Wh, including DST and midnight rollover."""
    day = day.replace(tzinfo=ZoneInfo("Europe/Prague"))
    monkeypatch.setattr(
        "custom_components.proteus_api.sensor.dt_util.start_of_local_day", lambda: day
    )
    coordinator = SimpleNamespace(
        data={"production_forecast": {last_today: 1250, first_tomorrow: 2500}},
        async_add_listener=lambda _: lambda: None,
    )
    entry = SimpleNamespace(entry_id="account")
    hass.data[DOMAIN] = {
        "account": {
            "inverters": {"inverter": {"coordinator": coordinator, "inverter": {}}}
        }
    }
    entities = []
    await async_setup_entry(hass, entry, entities.extend)
    sensors = {entity.unique_id: entity for entity in entities}
    today = sensors["proteus_production_forecast_today_inverter"]
    tomorrow = sensors["proteus_production_forecast_tomorrow_inverter"]
    assert today.native_value == 1.25
    assert tomorrow.native_value == 2.5
    assert today.extra_state_attributes == {"wh_hours": {last_today: 1250}}
    assert tomorrow.extra_state_attributes == {"wh_hours": {first_tomorrow: 2500}}
    assert today.native_unit_of_measurement == "kWh"
    assert today.device_class == SensorDeviceClass.ENERGY
    assert today.state_class is None
    assert today.translation_key == "production_forecast_today"
    assert tomorrow.translation_key == "production_forecast_tomorrow"

    monkeypatch.setattr(
        "custom_components.proteus_api.sensor.dt_util.start_of_local_day",
        lambda: day + timedelta(days=1),
    )
    assert today.native_value == 2.5
    assert tomorrow.native_value is None

    coordinator.data = {"production_forecast": {first_tomorrow: 0}}
    assert today.native_value == 0
    coordinator.data = {}
    assert today.native_value is None
    coordinator.data = None
    assert today.native_value is None
