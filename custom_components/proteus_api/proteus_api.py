"""API client for Proteus."""

from __future__ import annotations

from datetime import datetime
import json
from json import JSONDecodeError
import logging
from math import ceil
import re
from time import monotonic, time
from typing import Any, ClassVar, TypedDict, cast

import aiohttp
from aiohttp.client_exceptions import ClientConnectionError
from aiohttp_retry import ExponentialRetry, RetryClient

from .const import (
    API_BASE_URL,
    API_CONTROL_ENDPOINT,
    API_ENABLED_ENDPOINT,
    API_FLEXIBILITY_ENDPOINT,
    API_LIST_ENDPOINT,
    API_LOGIN_ENDPOINT,
    API_MODE_ENDPOINT,
    API_PRICE_ENDPOINT,
    API_PRICE_ENDPOINTS,
    API_STATUS_ENDPOINT,
    API_STATUS_ENDPOINTS,
    COMMAND_NONE,
    FLEXIBILITY_CAPABILITIES,
    PRICE_UPDATE_DELAY,
    PRICE_UPDATE_INTERVAL,
    TID_DELTA_GREEN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

TRPC_RATE_LIMIT_CODE = -32029
TRPC_RATE_LIMIT_HTTP_STATUS = 429
TRPC_RATE_LIMIT_RETRY_RE = re.compile(
    r"try again in (?P<seconds>\d+) seconds?", re.IGNORECASE
)
RATE_LIMIT_ERROR_INTERVAL = 300


class AuthenticationError(Exception):
    """Exception raised for authentication failures."""


class InverterDict(TypedDict):
    """Inverter definition as retrieved from the API."""

    id: str
    featureFlags: list[str]
    controlMode: str
    controlEnabled: bool
    vendor: str


def get_top_level_trpc_error(payload: Any) -> dict[str, Any] | None:
    """Return a top-level tRPC error object from a response item."""
    if not isinstance(payload, dict):
        return None

    if "error" not in payload or (
        len(payload) != 1 and "result" not in payload and "meta" not in payload
    ):
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        return error

    return None


def iter_trpc_errors(payload: Any):
    """Yield top-level tRPC error objects from a response payload."""
    if isinstance(payload, dict):
        error = get_top_level_trpc_error(payload)
        if error is not None:
            yield error
        return

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield from iter_trpc_errors(item)


def iter_trpc_errors_with_endpoints(payload: Any, endpoints: tuple[str, ...] = ()):
    """Yield tRPC error objects with their batched endpoint name when known."""
    if isinstance(payload, dict):
        error = get_top_level_trpc_error(payload)
        if error is not None:
            yield error, get_trpc_error_path(error)
        return

    if not isinstance(payload, list):
        return

    for index, item in enumerate(payload):
        endpoint = endpoints[index] if index < len(endpoints) else None
        if isinstance(item, dict):
            error = get_top_level_trpc_error(item)
            if error is not None:
                yield error, get_trpc_error_path(error) or endpoint
        elif isinstance(item, list):
            yield from iter_trpc_errors_with_endpoints(item)


def format_trpc_error(error: dict[str, Any], endpoint: str | None = None) -> str:
    """Format a tRPC error payload for logging."""
    message = get_trpc_error_message(error)
    code = get_trpc_error_code(error)

    if message and code is not None:
        formatted = f"{message} (code: {code})"
    elif message:
        formatted = str(message)
    elif code is not None:
        formatted = f"code: {code}"
    else:
        formatted = str(error)

    path = get_trpc_error_path(error) or endpoint
    if path is None:
        return formatted
    return f"{path}: {formatted}"


def extract_trpc_error_messages(
    payload: Any, endpoints: tuple[str, ...] = ()
) -> list[str]:
    """Extract all tRPC error messages from a response payload."""
    if endpoints:
        return [
            format_trpc_error(error, endpoint)
            for error, endpoint in iter_trpc_errors_with_endpoints(payload, endpoints)
        ]

    return [format_trpc_error(error) for error in iter_trpc_errors(payload)]


def get_trpc_error_message(error: dict[str, Any]) -> str | None:
    """Return a tRPC error message if present."""
    error_json = error.get("json")
    if isinstance(error_json, dict):
        message = error_json.get("message")
        if message is not None:
            return str(message)

    message = error.get("message")
    if message is not None:
        return str(message)

    return None


def get_trpc_error_code(error: dict[str, Any]) -> Any | None:
    """Return a tRPC error code if present."""
    error_json = error.get("json")
    if isinstance(error_json, dict) and error_json.get("code") is not None:
        return error_json.get("code")
    return error.get("code")


def _coerce_int(value: Any) -> int | None:
    """Convert an API numeric value to int when possible."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_trpc_error_data(error: dict[str, Any]) -> dict[str, Any]:
    """Return structured tRPC error data if present."""
    error_json = error.get("json")
    if isinstance(error_json, dict):
        data = error_json.get("data")
        if isinstance(data, dict):
            return data

    data = error.get("data")
    if isinstance(data, dict):
        return data

    return {}


def get_trpc_error_path(error: dict[str, Any]) -> str | None:
    """Return the tRPC procedure path for an error if the API provided it."""
    error_data = get_trpc_error_data(error)
    path = error_data.get("path")
    if path is not None:
        return str(path)

    path = error.get("path")
    if path is not None:
        return str(path)

    return None


def is_trpc_rate_limit_error(error: dict[str, Any]) -> bool:
    """Return whether a tRPC error represents API rate limiting."""
    code = _coerce_int(get_trpc_error_code(error))
    if code == TRPC_RATE_LIMIT_CODE:
        return True

    error_data = get_trpc_error_data(error)
    http_status = _coerce_int(error_data.get("httpStatus"))
    if http_status == TRPC_RATE_LIMIT_HTTP_STATUS:
        return True

    if error_data.get("code") == "TOO_MANY_REQUESTS":
        return True

    message = get_trpc_error_message(error)
    return message is not None and "rate limit" in message.casefold()


def get_trpc_rate_limit_retry_after(error: dict[str, Any]) -> int | None:
    """Return the retry delay from a tRPC rate-limit error if present."""
    error_data = get_trpc_error_data(error)
    for key in ("retryAfter", "retryAfterSeconds"):
        retry_after = _coerce_int(error_data.get(key))
        if retry_after is not None:
            return max(0, retry_after)

    message = get_trpc_error_message(error)
    if message is None:
        return None

    match = TRPC_RATE_LIMIT_RETRY_RE.search(message)
    if match is None:
        return None

    return max(0, int(match.group("seconds")))


def extract_trpc_rate_limit_retry_after(payload: Any) -> int | None:
    """Extract the longest retry delay from tRPC rate-limit errors."""
    retry_after_values = []
    has_rate_limit_error = False
    for error in iter_trpc_errors(payload):
        if not is_trpc_rate_limit_error(error):
            continue

        has_rate_limit_error = True
        retry_after = get_trpc_rate_limit_retry_after(error)
        if retry_after is not None:
            retry_after_values.append(retry_after)

    if retry_after_values:
        return max(retry_after_values)

    if has_rate_limit_error:
        return UPDATE_INTERVAL

    return None


def get_trpc_result_json(payload: Any, index: int) -> Any | None:
    """Return one JSON result from a batched tRPC payload."""
    if not isinstance(payload, list) or len(payload) <= index:
        return None

    try:
        return payload[index]["result"]["data"]["json"]
    except (KeyError, TypeError):
        return None


def normalize_price_components(
    price_components: Any, *, price_mwh: Any
) -> dict[str, Any]:
    """Convert raw price components into Home Assistant-friendly attributes."""
    if not isinstance(price_components, dict):
        return {}

    normalized = {
        "price_mwh": price_mwh,
        "distribution_price": price_components.get("distributionPrice"),
        "distribution_tariff_type": price_components.get("distributionTariffType"),
        "fee_electricity_buy": price_components.get("feeElectricityBuy"),
        "fee_electricity_sell": price_components.get("feeElectricitySell"),
        "tax_electricity": price_components.get("taxElectricity"),
        "system_services": price_components.get("systemServices"),
        "poze": price_components.get("poze"),
        "vat_rate": price_components.get("vatRate"),
    }

    return {key: value for key, value in normalized.items() if value is not None}


def parse_price_payload(prices: Any) -> dict[str, Any]:
    """Parse distribution price payload fields."""
    parsed: dict[str, Any] = {}
    if not isinstance(prices, dict):
        return parsed

    consumption_price = prices.get("priceConsumptionMwh")
    if isinstance(consumption_price, int | float):
        parsed["price_consumption_mwh"] = consumption_price
        parsed["price_consumption_kwh"] = round(consumption_price / 1000, 4)

    production_price = prices.get("priceProductionMwh")
    if isinstance(production_price, int | float):
        parsed["price_production_mwh"] = production_price
        parsed["price_production_kwh"] = round(production_price / 1000, 4)

    price_components = prices.get("priceComponents")
    if isinstance(price_components, dict):
        distribution_tariff_type = price_components.get("distributionTariffType")
        if distribution_tariff_type is not None:
            parsed["distribution_tariff_type"] = distribution_tariff_type

        normalized_price_components = normalize_price_components(
            price_components,
            price_mwh=prices.get("priceMwh"),
        )
        if normalized_price_components:
            parsed["price_components"] = normalized_price_components

    return parsed


def parse_price_data(raw_data: Any) -> dict[str, Any]:
    """Parse a standalone distribution price tRPC response."""
    return parse_price_payload(get_trpc_result_json(raw_data, 0))


def get_seconds_until_next_price_update(now: float) -> float:
    """Return seconds until the next quarter-hour price refresh."""
    next_boundary = (int(now // PRICE_UPDATE_INTERVAL) + 1) * PRICE_UPDATE_INTERVAL
    return max(0, next_boundary - now + PRICE_UPDATE_DELAY)


def parse_data(raw_data: Any) -> dict[str, Any]:
    """Parse raw API data into structured format."""
    if not isinstance(raw_data, list) or len(raw_data) < 5:
        _LOGGER.error("Missing data: %s", raw_data)
        return {}

    parsed = {}

    try:
        detail = get_trpc_result_json(raw_data, 0)
        if isinstance(detail, dict):
            parsed["flexibility_state"] = detail["household"]["flexibilityState"]
            parsed["control_mode"] = detail["controlMode"]
            parsed["control_enabled"] = detail["controlEnabled"]

        rewards = get_trpc_result_json(raw_data, 1)
        if isinstance(rewards, dict):
            parsed["flexibility_today"] = round(rewards["todayWithVat"], 2)
            parsed["flexibility_month"] = round(rewards["monthToDateWithVat"], 2)
            parsed["flexibility_total"] = round(rewards["totalWithVat"], 2)

        controls = get_trpc_result_json(raw_data, 2)
        if isinstance(controls, dict):
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

        command_data = get_trpc_result_json(raw_data, 3)
        if isinstance(command_data, dict) and command_data.get("command"):
            parsed["current_command"] = command_data["command"]["type"]
            parsed["command_end"] = datetime.fromisoformat(
                command_data["command"]["endAt"]
            )
        elif command_data is not None:
            parsed["current_command"] = COMMAND_NONE
            parsed["command_end"] = None

        current_step = get_trpc_result_json(raw_data, 4)
        if isinstance(current_step, dict):
            metadata = current_step["metadata"]
            parsed["flexalgo_battery"] = metadata.get("flexalgoBattery")
            parsed["flexalgo_battery_fallback"] = metadata.get(
                "flexalgoBatteryFallback"
            )
            parsed["flexalgo_pv"] = metadata.get("flexalgoPv")
            parsed["target_soc"] = metadata.get("targetSoC")
            parsed["predicted_production"] = metadata.get("predictedProduction")
            parsed["predicted_consumption"] = metadata.get("predictedConsumption")

        prices = get_trpc_result_json(raw_data, 5)
        parsed.update(parse_price_payload(prices))

    except Exception:
        _LOGGER.exception("Error parsing data")
        return {}

    _LOGGER.debug("Parsed status %s", parsed)
    return parsed


class ProteusAPI:
    """Proteus API client."""

    _rate_limited_until_by_scope: ClassVar[dict[tuple[str, str, str], float]] = {}
    _next_rate_limit_error_by_scope: ClassVar[dict[tuple[str, str, str], float]] = {}

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
        self._last_data: dict[str, Any] | None = None
        self._last_price_data: dict[str, Any] | None = None
        self._next_price_update = 0.0
        self._account_key = (self.tenant, self.email.strip().casefold())

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
        """Yield top-level tRPC error objects from a response payload."""
        yield from iter_trpc_errors(payload)

    def _format_trpc_error(
        self, error: dict[str, Any], endpoint: str | None = None
    ) -> str:
        """Format a tRPC error payload for logging."""
        return format_trpc_error(error, endpoint)

    def _extract_trpc_error_messages(
        self, payload: Any, endpoints: tuple[str, ...] = ()
    ) -> list[str]:
        """Extract all tRPC error messages from a response payload."""
        return extract_trpc_error_messages(payload, endpoints)

    def _extract_trpc_rate_limit_retry_after(self, payload: Any) -> int | None:
        """Extract the retry delay from tRPC rate-limit errors."""
        return extract_trpc_rate_limit_retry_after(payload)

    def _get_trpc_result_json(self, payload: Any, index: int) -> Any | None:
        """Return one JSON result from a batched tRPC payload."""
        return get_trpc_result_json(payload, index)

    def _normalize_price_components(
        self, price_components: Any, *, price_mwh: Any
    ) -> dict[str, Any]:
        """Convert raw price components into Home Assistant-friendly attributes."""
        return normalize_price_components(price_components, price_mwh=price_mwh)

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

    def _rate_limit_key(self, scope: str) -> tuple[str, str, str]:
        """Return the shared rate-limit key for an account and endpoint scope."""
        return (*self._account_key, scope)

    def _get_rate_limit_remaining(self, scopes: tuple[str, ...]) -> int:
        """Return seconds until the longest matching cooldown expires."""
        now = monotonic()
        remaining = 0
        for scope in scopes:
            rate_limited_until = self._rate_limited_until_by_scope.get(
                self._rate_limit_key(scope), 0.0
            )
            if rate_limited_until > now:
                remaining = max(remaining, ceil(rate_limited_until - now))
        return remaining

    def _set_rate_limit_cooldown(
        self, retry_after: int, scopes: tuple[str, ...]
    ) -> None:
        """Remember the server-requested rate-limit cooldown."""
        rate_limited_until = monotonic() + retry_after
        for scope in scopes:
            rate_limit_key = self._rate_limit_key(scope)
            self._rate_limited_until_by_scope[rate_limit_key] = max(
                self._rate_limited_until_by_scope.get(rate_limit_key, 0.0),
                rate_limited_until,
            )

    def _log_rate_limit(
        self, retry_after: int, error_messages: list[str], scope: str
    ) -> None:
        """Log rate limiting without the long batched request URL."""
        now = monotonic()
        log_level = logging.DEBUG
        extra = ""
        rate_limit_key = self._rate_limit_key(scope)
        next_error = self._next_rate_limit_error_by_scope.get(rate_limit_key, 0.0)
        if now >= next_error:
            log_level = logging.ERROR
            self._next_rate_limit_error_by_scope[rate_limit_key] = (
                now + RATE_LIMIT_ERROR_INTERVAL
            )
            extra = (
                "; repeated rate-limit messages will be logged at debug "
                f"for {RATE_LIMIT_ERROR_INTERVAL} seconds"
            )

        _LOGGER.log(
            log_level,
            "Proteus API rate-limited %s refresh for inverter %s; "
            "keeping previous values when available and retrying after %s seconds: %s%s",
            scope,
            self.inverter_id,
            retry_after,
            "; ".join(error_messages),
            extra,
        )

    def _build_inverter_batch_params(
        self, endpoints: tuple[str, ...]
    ) -> dict[str, str]:
        """Build batch query params for inverter-scoped tRPC GET requests."""
        return {
            "batch": "1",
            "input": json.dumps(
                {
                    str(index): {"json": {"inverterId": self.inverter_id}}
                    for index in range(len(endpoints))
                }
            ),
        }

    async def _fetch_trpc_batch(
        self,
        client: RetryClient,
        api_endpoint: str,
        endpoints: tuple[str, ...],
        *,
        scope: str,
    ) -> tuple[Any | None, bool]:
        """Fetch one tRPC batch and report whether cached data should be kept."""
        rate_limit_remaining = self._get_rate_limit_remaining(endpoints)
        if rate_limit_remaining:
            _LOGGER.debug(
                "Skipping Proteus API %s refresh for inverter %s; "
                "server rate-limit cooldown has %s seconds remaining",
                scope,
                self.inverter_id,
                rate_limit_remaining,
            )
            return None, True

        async with client.get(
            f"{API_BASE_URL}{api_endpoint}",
            params=self._build_inverter_batch_params(endpoints),
            headers=self.get_headers(),
        ) as response:
            response_text = await response.text()
            payload = self._parse_response_body(response_text)
            retry_after = self._extract_trpc_rate_limit_retry_after(payload)

            if response.status == TRPC_RATE_LIMIT_HTTP_STATUS:
                retry_after = retry_after or UPDATE_INTERVAL
                self._set_rate_limit_cooldown(retry_after, endpoints)
                self._log_rate_limit(
                    retry_after,
                    self._extract_trpc_error_messages(payload, endpoints)
                    or [f"HTTP {response.status}"],
                    scope,
                )
                return None, True

            if response.status not in {200, 207}:
                _LOGGER.error(
                    "API %s request %s failed with status %s (%s)",
                    response.method,
                    response.url,
                    response.status,
                    payload if payload is not None else response_text,
                )
                return None, False

            if payload is None:
                _LOGGER.error(
                    "API %s request %s returned an unparsable response",
                    response.method,
                    response.url,
                )
                return None, False

            keep_cached_data = False
            rate_limit_error_messages = []
            rate_limit_error_endpoints = []
            other_error_messages = []
            for error, endpoint in iter_trpc_errors_with_endpoints(payload, endpoints):
                message = self._format_trpc_error(error, endpoint)
                if is_trpc_rate_limit_error(error):
                    keep_cached_data = True
                    rate_limit_error_messages.append(message)
                    if endpoint is not None:
                        rate_limit_error_endpoints.append(endpoint)
                else:
                    other_error_messages.append(message)

            if rate_limit_error_messages:
                retry_after = retry_after or UPDATE_INTERVAL
                rate_limit_scopes = tuple(rate_limit_error_endpoints) or endpoints
                self._set_rate_limit_cooldown(retry_after, rate_limit_scopes)
                self._log_rate_limit(retry_after, rate_limit_error_messages, scope)

            if other_error_messages:
                _LOGGER.warning(
                    "API %s request for inverter %s returned partial tRPC errors: %s",
                    response.method,
                    self.inverter_id,
                    "; ".join(other_error_messages),
                )

            return payload, keep_cached_data

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

            _LOGGER.debug("Fetching status data for %s", self.inverter_id)
            status_payload, keep_cached_status = await self._fetch_trpc_batch(
                client,
                API_STATUS_ENDPOINT,
                API_STATUS_ENDPOINTS,
                scope="status",
            )
            if status_payload is None and not keep_cached_status:
                return None

            if monotonic() >= self._next_price_update:
                _LOGGER.debug("Fetching price data for %s", self.inverter_id)
                price_payload, _ = await self._fetch_trpc_batch(
                    client,
                    API_PRICE_ENDPOINT,
                    API_PRICE_ENDPOINTS,
                    scope=API_PRICE_ENDPOINT,
                )
                price_data = parse_price_data(price_payload)
                if price_data:
                    self._last_price_data = price_data
                    self._next_price_update = (
                        monotonic() + get_seconds_until_next_price_update(time())
                    )
                else:
                    retry_after = self._get_rate_limit_remaining(API_PRICE_ENDPOINTS)
                    self._next_price_update = monotonic() + (
                        retry_after or UPDATE_INTERVAL
                    )

            data = (
                self._parse_data(status_payload) if status_payload is not None else {}
            )
            if data:
                if keep_cached_status and self._last_data is not None:
                    data = {**self._last_data, **data}
                if self._last_price_data is not None:
                    data = {**data, **self._last_price_data}
                self._last_data = data
                return data

            if keep_cached_status:
                if self._last_data is not None and self._last_price_data is not None:
                    self._last_data = {**self._last_data, **self._last_price_data}
                return self._last_data

        except Exception:
            _LOGGER.exception("Error fetching data")
            return None
        else:
            _LOGGER.error("Proteus API status response did not contain any usable data")
            return None

    def _parse_data(self, raw_data: Any) -> dict[str, Any]:
        """Parse raw API data into structured format."""
        return parse_data(raw_data)

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
