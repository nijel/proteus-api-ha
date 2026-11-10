"""Solar production forecasts for the Home Assistant Energy dashboard."""

from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_solar_forecast(
    hass: HomeAssistant, config_entry_id: str
) -> dict[str, dict[str, float]] | None:
    """Return the account's combined forecast in Wh per interval start."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry_id)
    if entry_data is None:
        return None

    wh_hours: dict[str, float] = {}
    for inverter_info in entry_data["inverters"].values():
        coordinator = inverter_info["coordinator"]
        if not coordinator.last_update_success or coordinator.data is None:
            continue
        for timestamp, energy in coordinator.data.get(
            "production_forecast", {}
        ).items():
            wh_hours[timestamp] = wh_hours.get(timestamp, 0.0) + energy

    return {"wh_hours": dict(sorted(wh_hours.items()))} if wh_hours else None
