"""Tests for prediction override payload building."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.proteus_api.const import API_PREDICTIONS_OVERRIDE_ENDPOINT
from custom_components.proteus_api.proteus_api import (
    ProteusAPI,
    build_prediction_overrides_payload,
    format_prediction_time,
)

PRAGUE_SUMMER = timezone(timedelta(hours=2))


def test_format_prediction_time_converts_to_utc_with_milliseconds() -> None:
    """A local timestamp should be serialized the way superjson encodes a Date."""
    local_time = datetime(2026, 8, 9, 19, 0, tzinfo=PRAGUE_SUMMER)

    assert format_prediction_time(local_time) == "2026-08-09T17:00:00.000Z"


def test_format_prediction_time_treats_naive_values_as_utc() -> None:
    """A naive timestamp should not be shifted by the local machine timezone."""
    assert (
        format_prediction_time(datetime(2026, 8, 9, 17, 0))
        == "2026-08-09T17:00:00.000Z"
    )


def test_build_prediction_overrides_payload_matches_web_ui_request() -> None:
    """The payload should mirror what the Proteus web UI sends."""
    payload = build_prediction_overrides_payload(
        "inverter-1",
        [
            {
                "time": datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
                "consumption_kwh": 0.7,
                "production_kwh": 0.3,
            }
        ],
    )

    assert payload == {
        "0": {
            "json": {
                "inverterId": "inverter-1",
                "predictions": [
                    {
                        "time": "2026-08-09T17:00:00.000Z",
                        "consumptionEnergyKwh": 0.7,
                        "photovoltaicEnergyKwh": 0.3,
                    }
                ],
            },
            "meta": {"values": {"predictions.0.time": ["Date"]}},
        }
    }


def test_build_prediction_overrides_payload_annotates_every_timestamp() -> None:
    """Each prediction needs its own Date entry, otherwise the API sees strings."""
    payload = build_prediction_overrides_payload(
        "inverter-1",
        [
            {
                "time": datetime(2026, 8, 9, hour, 0, tzinfo=UTC),
                "consumption_kwh": 1.0,
                "production_kwh": 2.0,
            }
            for hour in range(3)
        ],
    )

    assert payload["0"]["meta"]["values"] == {
        "predictions.0.time": ["Date"],
        "predictions.1.time": ["Date"],
        "predictions.2.time": ["Date"],
    }


@pytest.mark.asyncio
async def test_upsert_prediction_overrides_posts_batched_request() -> None:
    """The override request should be posted as a CSRF-protected tRPC batch."""
    api = ProteusAPI("inverter-1", "user@example.com", "secret")
    response = AsyncMock()
    response.text = AsyncMock(return_value='[{"result":{"data":{"json":null}}}]')
    response.status = 200
    client = MagicMock()
    client.post.return_value.__aenter__ = AsyncMock(return_value=response)
    client.post.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(ProteusAPI, "_get_client", AsyncMock(return_value=client)),
        patch.object(
            ProteusAPI, "get_headers", return_value={"x-proteus-csrf": "token"}
        ),
    ):
        result = await api.upsert_prediction_overrides(
            [
                {
                    "time": datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
                    "consumption_kwh": 0.7,
                    "production_kwh": 0.3,
                }
            ]
        )

    assert result is True
    url = client.post.call_args.args[0]
    assert url.endswith(f"{API_PREDICTIONS_OVERRIDE_ENDPOINT}?batch=1")
    assert client.post.call_args.kwargs["json"]["0"]["json"]["predictions"] == [
        {
            "time": "2026-08-09T17:00:00.000Z",
            "consumptionEnergyKwh": 0.7,
            "photovoltaicEnergyKwh": 0.3,
        }
    ]


@pytest.mark.asyncio
async def test_upsert_prediction_overrides_reports_trpc_errors() -> None:
    """A tRPC error response should surface as a failed update."""
    api = ProteusAPI("inverter-1", "user@example.com", "secret")
    response = AsyncMock()
    response.text = AsyncMock(
        return_value='[{"error":{"json":{"message":"nope","code":-32600}}}]'
    )
    response.status = 200
    client = MagicMock()
    client.post.return_value.__aenter__ = AsyncMock(return_value=response)
    client.post.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(ProteusAPI, "_get_client", AsyncMock(return_value=client)),
        patch.object(ProteusAPI, "get_headers", return_value={}),
    ):
        result = await api.upsert_prediction_overrides(
            [
                {
                    "time": datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
                    "consumption_kwh": 0.7,
                    "production_kwh": 0.3,
                }
            ]
        )

    assert result is False


def test_build_prediction_overrides_payload_sends_missing_values_as_null() -> None:
    """A quantity that is not given should be sent as null to keep Proteus' own prediction."""
    payload = build_prediction_overrides_payload(
        "inverter-1",
        [
            {
                "time": datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
                "consumption_kwh": 0.5,
                "production_kwh": None,
            },
            {
                "time": datetime(2026, 8, 9, 18, 0, tzinfo=UTC),
                "production_kwh": 1.2,
            },
        ],
    )

    assert payload["0"]["json"]["predictions"] == [
        {
            "time": "2026-08-09T17:00:00.000Z",
            "consumptionEnergyKwh": 0.5,
            "photovoltaicEnergyKwh": None,
        },
        {
            "time": "2026-08-09T18:00:00.000Z",
            "consumptionEnergyKwh": None,
            "photovoltaicEnergyKwh": 1.2,
        },
    ]


@pytest.mark.asyncio
async def test_clear_prediction_overrides_posts_null_values() -> None:
    """Clearing an override should mirror the web UI reset: both values null."""
    api = ProteusAPI("inverter-1", "user@example.com", "secret")
    response = AsyncMock()
    response.text = AsyncMock(return_value='[{"result":{"data":{"json":null}}}]')
    response.status = 200
    client = MagicMock()
    client.post.return_value.__aenter__ = AsyncMock(return_value=response)
    client.post.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(ProteusAPI, "_get_client", AsyncMock(return_value=client)),
        patch.object(ProteusAPI, "get_headers", return_value={}),
    ):
        result = await api.clear_prediction_overrides(
            [
                datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
                datetime(2026, 8, 9, 18, 0, tzinfo=UTC),
            ]
        )

    assert result is True
    sent = client.post.call_args.kwargs["json"]["0"]
    assert sent["json"]["predictions"] == [
        {
            "time": "2026-08-09T17:00:00.000Z",
            "consumptionEnergyKwh": None,
            "photovoltaicEnergyKwh": None,
        },
        {
            "time": "2026-08-09T18:00:00.000Z",
            "consumptionEnergyKwh": None,
            "photovoltaicEnergyKwh": None,
        },
    ]
    assert sent["meta"]["values"] == {
        "predictions.0.time": ["Date"],
        "predictions.1.time": ["Date"],
    }
