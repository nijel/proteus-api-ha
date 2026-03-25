"""API client for Proteus."""

from __future__ import annotations

from datetime import datetime
import json
from json import JSONDecodeError
import logging
from typing import Any, TypedDict, cast

import aiohttp
from aiohttp.client_exceptions import ClientConnectionError
from aiohttp_retry import ExponentialRetry, RetryClient

from .const import (
    API_BASE_URL,
    API_CONTROL_ENDPOINT,
    API_ENABLED_ENDPOINT,
    API_ENDPOINT,
    API_FLEXIBILITY_ENDPOINT,
    API_LIST_ENDPOINT,
    API_LOGIN_ENDPOINT,
    API_MODE_ENDPOINT,
    COMMAND_NONE,
    FLEXIBILITY_CAPABILITIES,
    TID_DELTA_GREEN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Exception raised for authentication failures."""


class InverterDict(TypedDict):
    """Inverter definition as retrieved from the API."""

    id: str
    featureFlags: list[str]
    controlMode: str
    controlEnabled: bool
    vendor: str


class ProteusAPI:
    """Proteus API client."""

    def __init__(
        self,
        inverter_id: str,
        email: str,
        password: str,
        tenant: str = TID_DELTA_GREEN,
    ) -> None:
        """Initialize the API client."""
        self.inverter_id = inverter_id
        self.email = email
        self.password = password
        self.tenant = tenant
        self._session = None

    def get_headers(self, *, for_post: bool = False) -> dict[str, str]:
        """Build HTTP headers for the next request.

        Includes CSRF header if session is open.
        """
        result = {
            "Content-Type": "application/json",
            "Origin": "https://proteus.deltagreen.cz",
            "Accept": "*/*",
            "Referer": "https://proteus.deltagreen.cz",
        }
        if for_post:
            result["trpc-accept"] = "application/jsonl"
        if self._session is not None:
            result["x-proteus-csrf"] = self._session.cookie_jar.filter_cookies(
                API_BASE_URL
            )["proteus_csrf"].value
        return result

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            _LOGGER.debug(
                "Creating new API session for %s / %s",
                self.tenant,
                self.inverter_id,
            )
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25),
                headers=self.get_headers(),
            )

            payload = {
                "json": {
                    "tenantId": self.tenant,
                    "email": self.email,
                    "password": self.password,
                }
            }

            # Authenticate
            async with self._session.post(
                f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
                json=payload,
            ) as response:
                if response.status == 401:
                    await self._log_error(response)
                    # Close session on auth failure to prevent resource leak
                    await self._session.close()
                    self._session = None
                    raise AuthenticationError("Invalid email or password")
                if response.status != 200:
                    error_message = await self._extract_error_message(response)
                    await self._log_error(response)
                    # Close session on failure to prevent resource leak
                    await self._session.close()
                    self._session = None
                    if response.status == 400:
                        raise AuthenticationError(
                            error_message
                            or f"Authentication failed (HTTP {response.status})"
                        )
                    raise ConnectionError(
                        error_message
                        or f"Failed to connect to Proteus API (HTTP {response.status})"
                    )

        return self._session

    async def _get_client(self) -> RetryClient:
        session = await self._get_session()
        retry_options = ExponentialRetry(
            factor=2,
            attempts=10,
            max_timeout=UPDATE_INTERVAL,
            exceptions={ConnectionError, ClientConnectionError, TimeoutError},
        )
        return RetryClient(client_session=session, retry_options=retry_options)

    async def _extract_error_message(
        self, response: aiohttp.ClientResponse
    ) -> str | None:
        """Extract error message from API response body."""
        try:
            data = await response.json()
            return data["error"]["json"]["message"]
        except (JSONDecodeError, KeyError, TypeError):
            return None

    def _parse_response_body(self, response_text: str) -> Any | None:
        """Parse JSON or JSONL response body if possible."""
        if not response_text:
            return None
        try:
            return json.loads(response_text)
        except JSONDecodeError:
            pass

        lines = [line.strip() for line in response_text.splitlines() if line.strip()]
        if not lines:
            return None

        parsed_lines = []
        for line in lines:
            try:
                parsed_lines.append(json.loads(line))
            except JSONDecodeError:
                return None

        if len(parsed_lines) == 1:
            return parsed_lines[0]
        return parsed_lines

    def _iter_trpc_errors(self, payload: Any):
        """Yield embedded tRPC error objects from a response payload."""
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                yield error
            for value in payload.values():
                yield from self._iter_trpc_errors(value)
            return

        if isinstance(payload, list):
            for item in payload:
                yield from self._iter_trpc_errors(item)

    def _format_trpc_error(self, error: dict[str, Any]) -> str:
        """Format a tRPC error payload for logging."""
        error_json = error.get("json")
        message = None
        code = None

        if isinstance(error_json, dict):
            message = error_json.get("message")
            code = error_json.get("code")

        if message is None:
            message = error.get("message")
        if code is None:
            code = error.get("code")

        if message and code is not None:
            return f"{message} (code: {code})"
        if message:
            return str(message)
        if code is not None:
            return f"code: {code}"
        return str(error)

    def _extract_trpc_error_messages(self, payload: Any) -> list[str]:
        """Extract all tRPC error messages from a response payload."""
        return [
            self._format_trpc_error(error) for error in self._iter_trpc_errors(payload)
        ]

    def _is_successful_trpc_response(
        self,
        response: aiohttp.ClientResponse,
        response_text: str,
        *,
        operation: str,
    ) -> bool:
        """Check whether the response succeeded at both HTTP and tRPC layers."""
        payload = self._parse_response_body(response_text)
        error_messages = self._extract_trpc_error_messages(payload)

        if response.status != 200:
            if error_messages:
                _LOGGER.error(
                    "%s failed with status %s: %s",
                    operation,
                    response.status,
                    "; ".join(error_messages),
                )
            else:
                _LOGGER.error(
                    "%s failed with status %s: %s",
                    operation,
                    response.status,
                    response_text or "<empty response>",
                )
            return False

        if error_messages:
            _LOGGER.error(
                "%s returned tRPC error: %s", operation, "; ".join(error_messages)
            )
            return False

        return True

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

    async def fetch_inverters(self) -> list[InverterDict]:
        """Fetch list of inverters available in the API."""
        client = await self._get_client()
        params = {
            "batch": "1",
            "input": json.dumps(
                {"0": {"json": None, "meta": {"values": ["undefined"]}}}
            ),
        }
        async with client.get(
            f"{API_BASE_URL}{API_LIST_ENDPOINT}",
            params=params,
            headers=self.get_headers(),
        ) as response:
            response_text = await response.text()
            if not self._is_successful_trpc_response(
                response,
                response_text,
                operation="Inverter discovery",
            ):
                error_message = await self._extract_error_message(response)
                if response.status in {400, 401}:
                    raise AuthenticationError(
                        error_message
                        or f"Inverter discovery failed (HTTP {response.status})"
                    )
                raise ConnectionError(
                    error_message
                    or f"Failed to fetch inverters (HTTP {response.status})"
                )

            payload = self._parse_response_body(response_text)
            try:
                inverters = cast(
                    list[InverterDict], payload[0]["result"]["data"]["json"]
                )
            except (KeyError, TypeError, IndexError) as exception:
                raise ConnectionError(
                    "Unexpected inverter discovery response"
                ) from exception

            for inverter in inverters:
                _LOGGER.info(
                    "Discovered inverter %s (%s)",
                    inverter["id"],
                    inverter["vendor"],
                )
            return inverters

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
            _LOGGER.debug("Fetching data for %s", self.inverter_id)

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
            # _LOGGER.debug("Parsed data: %s", raw_data)
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
            enabled_capabilities = set(parsed["flexibility_capabilities"])
            all_capabilities = set(FLEXIBILITY_CAPABILITIES)
            if not enabled_capabilities:
                parsed["flexibility_mode"] = "NONE"
            elif enabled_capabilities == all_capabilities:
                parsed["flexibility_mode"] = "FULL"
            else:
                parsed["flexibility_mode"] = "PARTIAL"

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

        _LOGGER.debug("Parsed status %s", parsed)
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
            _LOGGER.debug(
                "Toggling manual control %s for %s to %s: %s",
                control_type,
                self.inverter_id,
                state,
                payload,
            )

            async with client.post(
                f"{API_BASE_URL}{API_CONTROL_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(for_post=True),
            ) as response:
                data = await response.text()
                _LOGGER.debug("Response data: %s", data)
                return self._is_successful_trpc_response(
                    response,
                    data,
                    operation=f"Manual control update for {control_type}",
                )

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
            _LOGGER.debug("Toggling control for %s to %s", self.inverter_id, enabled)

            async with client.post(
                f"{API_BASE_URL}{API_ENABLED_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(for_post=True),
            ) as response:
                data = await response.text()
                _LOGGER.debug("Response data: %s", data)
                return self._is_successful_trpc_response(
                    response,
                    data,
                    operation="Control enabled update",
                )

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
            _LOGGER.debug("Toggling control mode for %s to %s", self.inverter_id, mode)

            async with client.post(
                f"{API_BASE_URL}{API_MODE_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(for_post=True),
            ) as response:
                data = await response.text()
                _LOGGER.debug("Response data: %s", data)
                return self._is_successful_trpc_response(
                    response,
                    data,
                    operation="Control mode update",
                )

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
            _LOGGER.debug(
                "Toggling flexibility mode for %s to %s", self.inverter_id, mode
            )

            async with client.post(
                f"{API_BASE_URL}{API_FLEXIBILITY_ENDPOINT}?batch=1",
                json=payload,
                headers=self.get_headers(for_post=True),
            ) as response:
                data = await response.text()
                _LOGGER.debug("Response data: %s", data)
                return self._is_successful_trpc_response(
                    response,
                    data,
                    operation="Flexibility mode update",
                )

        except Exception:
            _LOGGER.exception("Error updating flexibility mode")
            return False

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            _LOGGER.debug("Closing session for %s", self.inverter_id)
            await self._session.close()
