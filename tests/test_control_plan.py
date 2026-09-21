"""Tests for control plan parsing and the tRPC jsonl streaming decoder."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.proteus_api.const import (
    CONTROL_PLAN_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from custom_components.proteus_api.proteus_api import (
    ProteusAPI,
    decode_trpc_stream_response,
    get_trpc_stream_result_json,
    parse_control_plan_payload,
    parse_control_plan_response,
    parse_control_plan_step,
)


def _jsonl(*lines: object) -> str:
    """Build a jsonl response body from a sequence of json-able line payloads."""
    return "\n".join(json.dumps({"json": line}) for line in lines)


def test_decode_trpc_stream_response_resolves_chained_references() -> None:
    """A value nested behind several deferred chunks should resolve fully."""
    response_text = _jsonl(
        {"0": [[0], [None, 0, 3]]},
        [3, 0, [[{"result": 0}], ["result", 0, 4]]],
        [4, 0, [[{"data": 0}], ["data", 0, 5]]],
        [5, 0, [[[]]]],
    )

    resolved = decode_trpc_stream_response(response_text)

    assert resolved == {"0": {"result": {"data": []}}}


def test_decode_trpc_stream_response_ignores_superjson_type_meta() -> None:
    """A dict meta (superjson type info) should not be treated as a chunk ref."""
    response_text = _jsonl(
        {"0": [[0], [None, 0, 1]]},
        [1, 0, [[{"value": "2026-07-02T21:56:59.083Z"}], {"values": {}}]],
    )

    resolved = decode_trpc_stream_response(response_text)

    assert resolved == {"0": {"value": "2026-07-02T21:56:59.083Z"}}


@pytest.mark.parametrize("wrapped", [False, True])
def test_get_trpc_stream_result_json_extracts_result_data(wrapped) -> None:
    """The result.data payload should be extracted for a given batch position."""
    data = {"activePlan": {"id": "plan-1"}}
    if wrapped:
        data = {"json": data, "meta": {"values": {}}}
    resolved_roots = {"2": {"result": {"data": data}}}

    assert get_trpc_stream_result_json(resolved_roots, 2) == {
        "activePlan": {"id": "plan-1"}
    }


def test_get_trpc_stream_result_json_returns_none_for_missing_position() -> None:
    """A missing root position should return None instead of raising."""
    assert get_trpc_stream_result_json({}, 0) is None


def test_parse_control_plan_step_extracts_expected_fields() -> None:
    """A raw plan step should be converted into HA-friendly fields."""
    step = {
        "id": "step-1",
        "startAt": "2026-07-02T16:00:00.000Z",
        "durationMinutes": 60,
        "metadata": {
            "flexalgoBattery": "default",
            "flexalgoPv": "unrestricted",
            "targetSoC": 100,
            "priceMwhConsumption": 6594.077831,
            "priceMwhProduction": 2213.2311,
            "priceComponents": {"distributionTariffType": "HT"},
            "isPrediction": False,
        },
    }

    parsed = parse_control_plan_step(step)

    assert parsed == {
        "start": "2026-07-02T16:00:00.000Z",
        "duration_minutes": 60,
        "flexalgo_battery": "default",
        "flexalgo_pv": "unrestricted",
        "target_soc": 100,
        "is_prediction": False,
        "price_consumption_kwh": 6.5941,
        "price_production_kwh": 2.2132,
        "distribution_tariff_type": "HT",
    }


def test_parse_control_plan_step_returns_none_without_metadata() -> None:
    """A step without metadata should be dropped."""
    assert parse_control_plan_step({"id": "step-1"}) is None
    assert parse_control_plan_step("not-a-dict") is None


def test_parse_control_plan_payload_builds_steps_and_plan_metadata() -> None:
    """A controlPlans.active payload should yield a step list and plan metadata."""
    control_plan_data = {
        "activePlan": {
            "id": "plan-1",
            "createdAt": "2026-07-02T21:56:59.083Z",
            "payload": {
                "steps": [
                    {
                        "startAt": "2026-07-02T16:00:00.000Z",
                        "durationMinutes": 60,
                        "metadata": {
                            "flexalgoBattery": "default",
                            "flexalgoPv": "unrestricted",
                            "targetSoC": 100,
                            "priceMwhConsumption": 6594.077831,
                            "priceMwhProduction": 2213.2311,
                            "isPrediction": False,
                        },
                    },
                    {
                        "startAt": "2026-07-02T17:00:00.000Z",
                        "durationMinutes": 60,
                        "metadata": {
                            "flexalgoBattery": "discharge_to_grid",
                            "flexalgoPv": "unrestricted",
                            "targetSoC": 87,
                            "priceMwhConsumption": 7440.441008,
                            "priceMwhProduction": 2912.7048,
                            "isPrediction": True,
                        },
                    },
                ]
            },
        }
    }

    parsed = parse_control_plan_payload(control_plan_data)

    assert parsed["control_plan_id"] == "plan-1"
    assert len(parsed["control_plan_steps"]) == 2
    assert parsed["control_plan_steps"][0]["price_consumption_kwh"] == 6.5941
    assert parsed["control_plan_steps"][1]["flexalgo_battery"] == "discharge_to_grid"


def test_parse_control_plan_payload_handles_missing_plan() -> None:
    """A response without an active plan should parse to an empty dict."""
    assert parse_control_plan_payload({}) == {}
    assert parse_control_plan_payload("not-a-dict") == {}


@pytest.mark.parametrize("wrapped", [False, True])
def test_parse_control_plan_response_decodes_streamed_format(wrapped) -> None:
    """The jsonl streaming wire format should decode into control plan fields."""
    active_plan = {
        "id": "plan-1",
        "createdAt": "2026-07-02T21:56:59.083Z",
        "payload": {
            "steps": [
                {
                    "startAt": "2026-07-02T16:00:00.000Z",
                    "durationMinutes": 60,
                    "metadata": {
                        "flexalgoBattery": "default",
                        "flexalgoPv": "unrestricted",
                        "targetSoC": 100,
                        "priceMwhConsumption": 6594.077831,
                        "priceMwhProduction": 2213.2311,
                        "isPrediction": False,
                    },
                }
            ]
        },
    }
    data = {"activePlan": active_plan}
    if wrapped:
        data = {"json": data, "meta": {"values": {}}}
    response_text = _jsonl(
        {"0": [[0], [None, 0, 1]]},
        [1, 0, [[{"result": 0}], ["result", 0, 2]]],
        [2, 0, [[{"data": 0}], ["data", 0, 3]]],
        [3, 0, [[data], [{"values": {}}]]],
    )

    parsed = parse_control_plan_response(response_text)

    assert parsed["control_plan_id"] == "plan-1"
    assert len(parsed["control_plan_steps"]) == 1


def test_parse_control_plan_response_decodes_plain_batch_format() -> None:
    """The classic non-streamed batch array format should also be supported."""
    response_text = json.dumps(
        [
            {
                "result": {
                    "data": {
                        "json": {
                            "activePlan": {
                                "id": "plan-2",
                                "payload": {
                                    "steps": [
                                        {
                                            "startAt": "2026-07-02T16:00:00.000Z",
                                            "durationMinutes": 60,
                                            "metadata": {
                                                "flexalgoBattery": "default",
                                                "flexalgoPv": "unrestricted",
                                                "targetSoC": 100,
                                            },
                                        }
                                    ]
                                },
                            }
                        }
                    }
                }
            }
        ]
    )

    parsed = parse_control_plan_response(response_text)

    assert parsed["control_plan_id"] == "plan-2"
    assert len(parsed["control_plan_steps"]) == 1


def test_parse_control_plan_response_handles_empty_or_invalid_text() -> None:
    """Empty or unparsable responses should not raise."""
    assert parse_control_plan_response("") == {}
    assert parse_control_plan_response("not json") == {}


class RefreshProteusAPI(ProteusAPI):
    """Client exposing refresh state with mocked status and HTTP transport."""

    def __init__(self, response_text: str, status: int) -> None:
        """Seed a previously active plan and a response for its next refresh."""
        super().__init__("inverter-1", "plan@example.com", "secret")
        self._rate_limited_until_by_scope = {}
        self._next_rate_limit_error_by_scope = {}
        self._next_price_update = float("inf")
        self._last_control_plan_data = {
            "control_plan_id": "old-plan",
            "control_plan_created_at": "old-date",
            "control_plan_steps": [{"start": "old-step"}],
        }
        self._last_data = {"power": 1, **self._last_control_plan_data}
        response = AsyncMock(status=status, method="GET", url="https://example.com")
        response.text.return_value = response_text
        self.client = MagicMock()
        self.client.get.return_value.__aenter__.return_value = response
        self.cached_status = False

    async def _get_client(self):
        """Return the fake HTTP client."""
        return self.client

    async def _fetch_trpc_batch(self, *args, **kwargs):
        """Return either fresh status or a cached status fallback."""
        return (None, True) if self.cached_status else ([], False)

    def _parse_data(self, raw_data):
        """Provide usable status data."""
        return {"power": 2}

    @property
    def next_refresh(self):
        """Expose the scheduled control-plan refresh."""
        return self._next_control_plan_update

    def share_cooldown(self, other: RefreshProteusAPI) -> None:
        """Use the same account cooldown store as another client."""
        self._rate_limited_until_by_scope = other._rate_limited_until_by_scope


def _plan_response(data, wire_format):
    """Encode control-plan result data in either supported wire format."""
    if wire_format == "plain":
        return json.dumps([{"result": {"data": {"json": data}}}])
    if wire_format == "wrapped_stream":
        data = {"json": data, "meta": {"values": {}}}
    return _jsonl(
        {"0": [[0], [None, 0, 1]]},
        [1, 0, [[{"result": {"data": data}}]]],
    )


@pytest.mark.parametrize("wire_format", ["plain", "stream", "wrapped_stream"])
@pytest.mark.parametrize("cached_status", [False, True])
async def test_refresh_clears_disappeared_plan(monkeypatch, wire_format, cached_status):
    """An absent active plan clears every field, even with cached status."""
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: 100
    )
    api = RefreshProteusAPI(_plan_response({"activePlan": None}, wire_format), 200)
    api.cached_status = cached_status

    data = await api.get_data()

    assert data["control_plan_steps"] == []
    assert data["control_plan_id"] is None
    assert data["control_plan_created_at"] is None
    assert api.next_refresh == 100 + CONTROL_PLAN_UPDATE_INTERVAL
    await api.get_data()
    api.client.get.assert_called_once()


@pytest.mark.parametrize("wire_format", ["plain", "stream", "wrapped_stream"])
@pytest.mark.parametrize("cached_status", [False, True])
@pytest.mark.parametrize("steps", [[], [{}]])
async def test_refresh_preserves_empty_plan_steps(
    monkeypatch, wire_format, cached_status, steps
):
    """An active plan with no usable steps replaces the previous schedule."""
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: 100
    )
    plan = {"activePlan": {"id": "new-plan", "payload": {"steps": steps}}}
    api = RefreshProteusAPI(_plan_response(plan, wire_format), 200)
    api.cached_status = cached_status

    data = await api.get_data()

    assert data["control_plan_steps"] == []
    assert data["control_plan_id"] == "new-plan"
    assert api.next_refresh == 100 + CONTROL_PLAN_UPDATE_INTERVAL
    assert (await api.get_data())["control_plan_steps"] == []
    api.client.get.assert_called_once()


@pytest.mark.parametrize("status", [200, 207, 429])
@pytest.mark.parametrize("wire_format", ["plain", "stream", "rejected"])
@pytest.mark.parametrize("delay", [None, 120])
async def test_control_plan_rate_limit(monkeypatch, status, wire_format, delay):
    """Rate limits preserve cached plans and defer all clients on the account."""
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: 100
    )
    error = {"message": "Rate limit exceeded", "code": -32029}
    if delay is not None:
        error["data"] = {"retryAfter": delay}
    if wire_format == "plain":
        response = json.dumps([{"error": {"json": error}}])
    elif wire_format == "stream":
        response = _jsonl(
            {"0": [[0], [None, 0, 1]]},
            [1, 0, [[{"error": error}]]],
        )
    else:
        response = _jsonl(
            {"0": [[0], [None, 0, 1]]},
            [1, 1, error],
        )
    api = RefreshProteusAPI(response, status)

    data = await api.get_data()

    assert data["control_plan_id"] == "old-plan"
    assert data["control_plan_steps"] == [{"start": "old-step"}]
    assert api.next_refresh == 100 + (delay or UPDATE_INTERVAL)
    other = RefreshProteusAPI(response, status)
    other.share_cooldown(api)
    await other.get_data()
    other.client.get.assert_not_called()
    await api.get_data()
    api.client.get.assert_called_once()


@pytest.mark.parametrize(
    ("status", "response"),
    [
        (500, "failure"),
        (200, "invalid json"),
        (200, '[{"error":{"message":"failed"}}]'),
    ],
)
async def test_failed_control_plan_refresh_preserves_cache(
    monkeypatch, status, response
):
    """Failed or malformed responses must not clear the active schedule."""
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: 100
    )
    api = RefreshProteusAPI(response, status)

    data = await api.get_data()

    assert data["control_plan_id"] == "old-plan"
    assert api.next_refresh == 100 + UPDATE_INTERVAL


async def test_pending_polling_and_completion(monkeypatch):
    """Fast plan polling ends only on an explicit complete response, including after errors."""
    snapshot = {
        "activePlan": {"id": "plan-1", "payload": {"steps": []}},
        "isRecalculatingPlan": False,
    }
    now = 100
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: now
    )
    api = RefreshProteusAPI(_plan_response(snapshot, "plain"), 200)
    api.invalidate_plan()
    snapshot["isRecalculatingPlan"] = True
    response = api.client.get.return_value.__aenter__.return_value
    response.text.return_value = _plan_response(snapshot, "plain")
    data = await api.get_data()
    assert data["plan_refresh_pending"] is True
    assert data["is_recalculating_plan"] is True
    assert api.next_refresh == now + UPDATE_INTERVAL
    now += UPDATE_INTERVAL
    response.text.return_value = "malformed"
    data = await api.get_data()
    assert data["control_plan_id"] == "plan-1"
    assert data["plan_refresh_pending"] is True
    now += UPDATE_INTERVAL
    snapshot["isRecalculatingPlan"] = False
    response.text.return_value = _plan_response(snapshot, "plain")
    data = await api.get_data()
    assert data["plan_refresh_pending"] is False
    assert data["is_recalculating_plan"] is False
    assert api.next_refresh == now + CONTROL_PLAN_UPDATE_INTERVAL
