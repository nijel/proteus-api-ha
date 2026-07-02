"""Tests for control plan parsing and the tRPC jsonl streaming decoder."""

from __future__ import annotations

import json

from custom_components.proteus_api.proteus_api import (
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


def test_get_trpc_stream_result_json_extracts_result_data() -> None:
    """The result.data payload should be extracted for a given batch position."""
    resolved_roots = {"2": {"result": {"data": {"activePlan": {"id": "plan-1"}}}}}

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


def test_parse_control_plan_response_decodes_streamed_format() -> None:
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
    response_text = _jsonl(
        {"0": [[0], [None, 0, 1]]},
        [1, 0, [[{"result": 0}], ["result", 0, 2]]],
        [2, 0, [[{"data": 0}], ["data", 0, 3]]],
        [3, 0, [[{"activePlan": active_plan}], [{"values": {}}]]],
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
