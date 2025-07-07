import aiohttp
import async_timeout
import logging
from .const import API_URL

_LOGGER = logging.getLogger(__name__)

class ProteusApi:
    def __init__(self, inverter_id, session_cookie):
        self.inverter_id = inverter_id
        self.session_cookie = session_cookie

    async def fetch_data(self, session: aiohttp.ClientSession):
        payload = {
            "0": {"json": {"inverterId": self.inverter_id}},
            "1": {"json": {"inverterId": self.inverter_id}},
            "2": {"json": {"inverterId": self.inverter_id}},
            "3": {"json": {"inverterId": self.inverter_id}},
            "4": {"json": {"inverterId": self.inverter_id}},
        }

        headers = {
            "Content-Type": "application/json",
            "Cookie": f"proteus_session={self.session_cookie}",
            "Origin": "https://proteus.deltagreen.cz",
        }

        try:
            async with async_timeout.timeout(25):
                async with session.get(API_URL, headers=headers, params={"batch": 1, "input": str(payload)}) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        _LOGGER.error("Error fetching data from Proteus API: HTTP %s", resp.status)
                        return None
        except Exception as e:
            _LOGGER.error("Exception during Proteus API call: %s", e)
            return None