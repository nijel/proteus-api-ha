from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy, UnitOfElectricPotential, PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .api import ProteusApi
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    inverter_id = hass.states.get("input_text.proteus_inverter_id").state
    session_cookie = hass.states.get("input_text.proteus_session_cookie").state

    api = ProteusApi(inverter_id, session_cookie)
    session = hass.helpers.aiohttp_client.async_get_clientsession()

    data = await api.fetch_data(session)
    if not data:
        _LOGGER.error("No data received from Proteus API")
        return

    entities = []

    try:
        entities.append(ProteusSensor("Proteus flexibilita dostupná", data[0]["result"]["data"]["json"]["household"]["flexibilityState"], "proteus.flex_status", None))
        entities.append(ProteusSensor("Proteus režim", data[0]["result"]["data"]["json"]["controlMode"], "proteus.mode", None))
        entities.append(ProteusSensor("Proteus obchodování flexibility dnes", data[1]["result"]["data"]["json"]["todayWithVat"], "proteus.flexibility", "Kč"))
        # ... a další senzory podle YAML konfigurace
    except Exception as e:
        _LOGGER.error("Error parsing Proteus data: %s", e)
        return

    async_add_entities(entities, update_before_add=True)

class ProteusSensor(SensorEntity):
    def __init__(self, name, state, unique_id, unit):
        self._attr_name = name
        self._attr_native_value = state
        self._attr_unique_id = unique_id
        self._attr_native_unit_of_measurement = unit
        self._attr_should_poll = False

    async def async_update(self):
        pass  # polling zatím neřešíme, pracujeme s daty na setup
