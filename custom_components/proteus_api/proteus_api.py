"""API client for Proteus."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

import aiohttp
from aiohttp_retry import RetryClient, ExponentialRetry

from .const import (
    API_BASE_URL,
    API_CONTROL_ENDPOINT,
    API_ENDPOINT,
    API_LOGIN_ENDPOINT,
    API_MODE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


class ProteusAPI:
    """Proteus API client."""

    def __init__(self, inverter_id: str, email: str, password: str) -> None:
        """Initialize the API client."""
        self.inverter_id = inverter_id
        self.email = email
        self.password = password
        self._session = None

    def get_headers(self) -> dict[str,str]:
        result = {
            "Content-Type": "application/json",
            "Origin": "https://proteus.deltagreen.cz",
        }
        if self._session is not None:
            result["x-proteus-csrf"] =  self._session.cookie_jar.filter_cookies(API_BASE_URL)["proteus_csrf"].value
        return result

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25),
                headers=self.get_headers(),
            )

            payload = {
                "json": {
                    "tenantId": "TID_DELTA_GREEN",
                    "email": self.email,
                    "password": self.password,
                }
            }

            # Authenticate
            async with self._session.post(
                f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
                json=payload,
            ) as response:
                if response.status != 200:
                    await self._log_error(response)

        return self._session

    async def _log_error(self, response: aiohttp.ClientResponse) -> None:
        try:
            data = await response.json()
            _LOGGER.error(
                "API %s request %s failed with status %s (%s)", response.method, response.url, response.status, data
            )
        except Exception:
            _LOGGER.error("API %s request %s failed with status %s", response.method, response.url, response.status)

    async def get_data(self) -> Dict[str, Any] | None:
        """Fetch data from Proteus API."""
        try:
            session = await self._get_session()

            client = RetryClient(client_session=session)

            params = {
                "batch": "1",
                "input": json.dumps(
                    {
                        "0": {"json": {"inverterId": self.inverter_id}},
                        "1": {"json": {"inverterId": self.inverter_id}},
                        "2": {"json": {"inverterId": self.inverter_id}},
                        "3": {"json": {"inverterId": self.inverter_id}},
                        "4": {"json": {"inverterId": self.inverter_id}},
                    }
                ),
            }

            async with client.get(
                f"{API_BASE_URL}{API_ENDPOINT}",
                params=params,
                headers=self.get_headers(),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_data(data)
                await self._log_error(response)
                return None

        except Exception as ex:
            _LOGGER.error("Error fetching data: %s", ex)
            return None

    def _parse_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse raw API data into structured format."""
        try:
            parsed = {}

            # Basic info
            if "0" in raw_data and "result" in raw_data["0"]:
                detail = raw_data["0"]["result"]["data"]["json"]
                parsed["flexibility_state"] = detail["household"]["flexibilityState"]
                parsed["control_mode"] = detail["controlMode"]

            # Flexibility rewards
            if "1" in raw_data and "result" in raw_data["1"]:
                rewards = raw_data["1"]["result"]["data"]["json"]
                parsed["flexibility_today"] = rewards["todayWithVat"]
                parsed["flexibility_month"] = rewards["monthToDateWithVat"]
                parsed["flexibility_total"] = rewards["totalWithVat"]

            # Manual controls
            if "2" in raw_data and "result" in raw_data["2"]:
                controls = raw_data["2"]["result"]["data"]["json"]["manualControls"]
                parsed["manual_controls"] = {}
                for control in controls:
                    parsed["manual_controls"][control["type"]] = (
                        control["state"] == "ENABLED"
                    )

            # Current command
            if "3" in raw_data and "result" in raw_data["3"]:
                command_data = raw_data["3"]["result"]["data"]["json"]
                if command_data.get("command"):
                    parsed["current_command"] = command_data["command"]["type"]
                    parsed["command_end"] = command_data["command"]["endAt"]
                else:
                    parsed["current_command"] = "NONE"
                    parsed["command_end"] = None

            # Current step metadata
            if "4" in raw_data and "result" in raw_data["4"]:
                metadata = raw_data["4"]["result"]["data"]["json"]["metadata"]
                parsed["flexalgo_battery"] = metadata.get("flexalgoBattery")
                parsed["flexalgo_battery_fallback"] = metadata.get(
                    "flexalgoBatteryFallback"
                )
                parsed["flexalgo_pv"] = metadata.get("flexalgoPv")
                parsed["target_soc"] = metadata.get("targetSoC")
                parsed["predicted_production"] = metadata.get("predictedProduction")
                parsed["predicted_consumption"] = metadata.get("predictedConsumption")

            return parsed

        except Exception as ex:
            _LOGGER.error("Error parsing data: %s", ex)
            return {}

    async def update_manual_control(self, control_type: str, state: str) -> bool:
        """Update manual control state."""
        try:
            session = await self._get_session()

            client = RetryClient(client_session=session)

            payload = {
                "0": {
                    "json": {
                        "type": control_type,
                        "inverterId": self.inverter_id,
                        "state": state,
                    }
                }
            }

            async with client.post(
                f"{API_BASE_URL}{API_CONTROL_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(),
            ) as response:
                return response.status == 200

        except Exception as ex:
            _LOGGER.error("Error updating manual control: %s", ex)
            return False

    async def update_control_mode(self, mode: str) -> bool:
        """Update control mode."""
        try:
            session = await self._get_session()

            client = RetryClient(client_session=session)

            payload = {
                "0": {
                    "json": {
                        "inverterId": self.inverter_id,
                        "controlMode": mode,
                    }
                }
            }

            async with client.post(
                f"{API_BASE_URL}{API_MODE_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(),
            ) as response:
                return response.status == 200

        except Exception as ex:
            _LOGGER.error("Error updating control mode: %s", ex)
            return False

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
