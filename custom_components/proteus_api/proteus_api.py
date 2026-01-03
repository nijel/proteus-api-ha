"""API client for Proteus."""

from __future__ import annotations

from datetime import datetime
import json
from json import JSONDecodeError
import logging
from typing import Any

import aiohttp
from aiohttp.client_exceptions import ClientConnectionError
from aiohttp_retry import ExponentialRetry, RetryClient

from .const import (
    API_BASE_URL,
    API_CONTROL_ENDPOINT,
    API_ENABLED_ENDPOINT,
    API_ENDPOINT,
    API_FLEXIBILITY_ENDPOINT,
    API_LOGIN_ENDPOINT,
    API_MODE_ENDPOINT,
    COMMAND_NONE,
    UPDATE_INTERVAL,
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

    def get_headers(self) -> dict[str, str]:
        """Build HTTP headers for the next request.

        Includes CSRF header if session is open.
        """
        result = {
            "Content-Type": "application/json",
            "Origin": "https://proteus.deltagreen.cz",
        }
        if self._session is not None:
            result["x-proteus-csrf"] = self._session.cookie_jar.filter_cookies(
                API_BASE_URL
            )["proteus_csrf"].value
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

    async def _get_client(self) -> RetryClient:
        session = await self._get_session()
        retry_options = ExponentialRetry(
            factor=2,
            attempts=10,
            max_timeout=UPDATE_INTERVAL,
            exceptions={ConnectionError, ClientConnectionError},
        )
        return RetryClient(client_session=session, retry_options=retry_options)

    async def _log_error(self, response: aiohttp.ClientResponse) -> None:
        try:
            data = await response.json()
        except JSONDecodeError:
            _LOGGER.error(
                "API %s request %s failed with status %s",
                response.method,
                response.url,
                response.status,
            )
        else:
            _LOGGER.error(
                "API %s request %s failed with status %s (%s)",
                response.method,
                response.url,
                response.status,
                data,
            )

    async def get_data(self) -> dict[str, Any] | None:
        """Fetch data from Proteus API."""
        try:
            client = await self._get_client()

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

        except Exception:
            _LOGGER.exception("Error fetching data")
            return None

    def _parse_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw API data into structured format."""
        if len(raw_data) != 5:
            _LOGGER.error("Missing data: %s", raw_data)
            return {}
        try:
            parsed = {}

            # Basic info
            detail = raw_data[0]["result"]["data"]["json"]
            parsed["flexibility_state"] = detail["household"]["flexibilityState"]
            parsed["control_mode"] = detail["controlMode"]
            parsed["control_enabled"] = detail["controlEnabled"]

            # Flexibility rewards
            rewards = raw_data[1]["result"]["data"]["json"]
            parsed["flexibility_today"] = round(rewards["todayWithVat"], 2)
            parsed["flexibility_month"] = round(rewards["monthToDateWithVat"], 2)
            parsed["flexibility_total"] = round(rewards["totalWithVat"], 2)

            # Manual controls
            controls = raw_data[2]["result"]["data"]["json"]
            manual_controls = controls["manualControls"]
            parsed["manual_controls"] = {}
            for control in manual_controls:
                parsed["manual_controls"][control["type"]] = (
                    control["state"] == "ENABLED"
                )

            parsed["flexibility_capabilities"] = controls[
                "flexibilityCapabilitiesEnabled"
            ]

            # Current command
            command_data = raw_data[3]["result"]["data"]["json"]
            if command_data.get("command"):
                parsed["current_command"] = command_data["command"]["type"]
                parsed["command_end"] = datetime.fromisoformat(
                    command_data["command"]["endAt"]
                )
            else:
                parsed["current_command"] = COMMAND_NONE
                parsed["command_end"] = None

            # Current step metadata
            current_step = raw_data[4]["result"]["data"]["json"]
            if current_step is not None:
                metadata = current_step["metadata"]
                parsed["flexalgo_battery"] = metadata.get("flexalgoBattery")
                parsed["flexalgo_battery_fallback"] = metadata.get(
                    "flexalgoBatteryFallback"
                )
                parsed["flexalgo_pv"] = metadata.get("flexalgoPv")
                parsed["target_soc"] = metadata.get("targetSoC")
                parsed["predicted_production"] = metadata.get("predictedProduction")
                parsed["predicted_consumption"] = metadata.get("predictedConsumption")

        except Exception:
            _LOGGER.exception("Error parsing data")
            return {}

        return parsed

    async def update_manual_control(self, control_type: str, state: str) -> bool:
        """Update manual control state."""
        try:
            client = await self._get_client()

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

        except Exception:
            _LOGGER.exception("Error updating manual control")
            return False

    async def update_control_enabled(self, enabled: bool) -> bool:
        """Update control enabled."""
        try:
            client = await self._get_client()

            payload = {
                "0": {
                    "json": {
                        "inverterId": self.inverter_id,
                        "controlEnabled": enabled,
                    }
                }
            }

            async with client.post(
                f"{API_BASE_URL}{API_ENABLED_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(),
            ) as response:
                return response.status == 200

        except Exception:
            _LOGGER.exception("Error updating enabled mode")
            return False

    async def update_control_mode(self, mode: str) -> bool:
        """Update control mode."""
        try:
            client = await self._get_client()

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

        except Exception:
            _LOGGER.exception("Error updating control mode")
            return False

    async def update_flexibility_mode(self, mode: list[str]) -> bool:
        """Update flexibility mode."""
        try:
            client = await self._get_client()

            payload = {
                "0": {
                    "json": {
                        "inverterId": self.inverter_id,
                        "flexibilityCapabilitiesEnabled": mode,
                    }
                }
            }

            async with client.post(
                f"{API_BASE_URL}{API_FLEXIBILITY_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(),
            ) as response:
                return response.status == 200

        except Exception:
            _LOGGER.exception("Error updating flexibility mode")
            return False

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
