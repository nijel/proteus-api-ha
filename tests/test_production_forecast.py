"""Tests for Proteus production forecasts and their refresh schedule."""

from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.proteus_api.const import (
    API_PRODUCTION_PREDICTIONS_ENDPOINT,
    PRODUCTION_FORECAST_UPDATE_INTERVAL,
)
from custom_components.proteus_api.proteus_api import (
    ProteusAPI,
    ProteusConnectionError,
    decode_single_result,
    parse_production_forecast,
)

DAY = datetime(2026, 11, 10, tzinfo=ZoneInfo("Europe/Prague"))
STREAM = (
    Path(__file__).parent / "fixtures" / "production_predictions.jsonl"
).read_text()


@pytest.mark.parametrize("stream", [False, True])
async def test_fetch_forecast_matches_proteus_response(monkeypatch, stream):
    """Plain and real streamed responses retain interval starts and Wh units."""
    api = ProteusAPI("inverter", "forecast@example.com", "secret")
    body = (
        STREAM
        if stream
        else json.dumps([{"result": {"data": {"json": decode_single_result(STREAM)}}}])
    )
    response = AsyncMock(status=200)
    response.text.return_value = body
    client = MagicMock()
    client.get.return_value.__aenter__.return_value = response
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))

    forecast = await api.fetch_production_forecast(DAY)

    assert len(forecast) == 24
    assert forecast["2026-11-09T23:00:00+00:00"] == 0
    assert forecast["2026-11-10T08:00:00+00:00"] == 878.5
    assert forecast["2026-11-10T12:00:00+00:00"] == 5878
    assert sum(forecast.values()) == 23428.0
    call = client.get.call_args
    assert call.args[0].endswith(API_PRODUCTION_PREDICTIONS_ENDPOINT)
    assert call.kwargs["params"]["batch"] == "1"
    assert json.loads(call.kwargs["params"]["input"]) == {
        "0": {
            "json": {
                "inverterId": "inverter",
                "from": "2026-11-09T23:00:00.000Z",
                "to": "2026-11-11T22:59:59.999Z",
            },
            "meta": {"values": {"from": ["Date"], "to": ["Date"]}},
        }
    }


@pytest.mark.parametrize(
    ("day", "end"),
    [
        (datetime(2026, 3, 28), "2026-03-29T21:59:59.999Z"),
        (datetime(2026, 10, 24), "2026-10-25T22:59:59.999Z"),
    ],
)
async def test_forecast_range_covers_local_days_across_dst(monkeypatch, day, end):
    """Two local days may span 47 or 49 hours when the UTC offset changes."""
    api = ProteusAPI("inverter", "forecast@example.com", "secret")
    response = AsyncMock(status=200)
    response.text.return_value = '[{"result":{"data":{"json":[]}}}]'
    client = MagicMock()
    client.get.return_value.__aenter__.return_value = response
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert (
        await api.fetch_production_forecast(
            day.replace(tzinfo=ZoneInfo("Europe/Prague"))
        )
        == {}
    )
    payload = json.loads(client.get.call_args.kwargs["params"]["input"])
    assert payload["0"]["json"]["to"] == end


def test_parse_forecast_rejects_invalid_values():
    """Reject unknown, negative, nonfinite or ambiguous points while keeping zero."""
    payload = [
        {"startAt": "2026-11-10T09:00:00+01:00", "energyWh": 1.5},
        {"startAt": "2026-11-10T10:00:00+01:00", "energyWh": 0},
        None,
        {"startAt": "invalid", "energyWh": 10},
        {"startAt": "2026-11-10T12:00:00", "energyWh": 10},
    ]
    payload.extend(
        {"startAt": "2026-11-10T12:00:00Z", "energyWh": value}
        for value in (None, True, "10", -1, float("nan"), float("inf"))
    )
    assert parse_production_forecast(payload) == {
        "2026-11-10T08:00:00+00:00": 1.5,
        "2026-11-10T09:00:00+00:00": 0,
    }
    assert parse_production_forecast({}) is None
    assert parse_production_forecast([{}]) is None
    assert parse_production_forecast([]) == {}


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, "error"),
        (200, "not json"),
        (200, '[{"error":{"json":{"message":"no forecast","code":-32600}}}]'),
    ],
)
async def test_failed_forecast_is_not_an_empty_success(monkeypatch, status, body):
    """Errors must preserve the last valid forecast rather than clear it."""
    api = ProteusAPI("inverter", "forecast@example.com", "secret")
    response = AsyncMock(status=status)
    response.text.return_value = body
    client = MagicMock()
    client.get.return_value.__aenter__.return_value = response
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert await api.fetch_production_forecast(DAY) is None


async def test_forecast_rate_limit_skips_subsequent_requests(monkeypatch):
    """The forecast has its own endpoint cooldown."""
    api = ProteusAPI("inverter", "forecast-rate@example.com", "secret")
    monkeypatch.setattr(api, "_rate_limited_until_by_scope", {})
    monkeypatch.setattr(api, "_next_rate_limit_error_by_scope", {})
    response = AsyncMock(status=429)
    response.text.return_value = "{}"
    client = MagicMock()
    client.get.return_value.__aenter__.return_value = response
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert await api.fetch_production_forecast(DAY) is None
    assert await api.fetch_production_forecast(DAY) is None
    client.get.assert_called_once()


@pytest.mark.parametrize("cached_status", [False, True])
async def test_forecast_cache_refresh_and_expiration(monkeypatch, cached_status):
    """Cache for 15 minutes, retain on errors, expire old days even in cooldown."""
    api = ProteusAPI("inverter", "forecast@example.com", "secret")
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(api, "_fetch_trpc_batch", AsyncMock(return_value=([], False)))
    monkeypatch.setattr(api, "_parse_data", lambda _: {"state": "ok"})
    monkeypatch.setattr(api, "_next_price_update", float("inf"))
    monkeypatch.setattr(api, "_next_control_plan_update", float("inf"))
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic", lambda: 100
    )
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.dt_util.start_of_local_day",
        lambda: DAY,
    )
    today = "2026-11-10T08:00:00+00:00"
    tomorrow = "2026-11-11T08:00:00+00:00"
    fetch = AsyncMock(return_value={today: 500.0, tomorrow: 250.0})
    monkeypatch.setattr(api, "fetch_production_forecast", fetch)

    assert (await api.get_data())["production_forecast"] == {today: 500, tomorrow: 250}
    await api.get_data()
    fetch.assert_awaited_once_with(DAY)
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic",
        lambda: 100 + PRODUCTION_FORECAST_UPDATE_INTERVAL - 1,
    )
    await api.get_data()
    fetch.assert_awaited_once()
    if cached_status:
        monkeypatch.setattr(
            api, "_fetch_trpc_batch", AsyncMock(return_value=(None, True))
        )

    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.monotonic",
        lambda: 100 + PRODUCTION_FORECAST_UPDATE_INTERVAL,
    )
    fetch.side_effect = ProteusConnectionError("offline")
    assert (await api.get_data())["production_forecast"] == {today: 500, tomorrow: 250}
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.dt_util.start_of_local_day",
        lambda: DAY + timedelta(days=1),
    )
    assert (await api.get_data())["production_forecast"] == {tomorrow: 250}
    assert fetch.await_count == 3
    await api.get_data()
    assert fetch.await_count == 3

    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.dt_util.start_of_local_day",
        lambda: DAY + timedelta(days=2),
    )
    assert "production_forecast" not in await api.get_data()


async def test_empty_forecast_clears_cached_values(monkeypatch):
    """A successful empty forecast must clear values instead of preserving them."""
    api = ProteusAPI("inverter", "forecast@example.com", "secret")
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(api, "_fetch_trpc_batch", AsyncMock(return_value=([], False)))
    monkeypatch.setattr(api, "_parse_data", lambda _: {"state": "ok"})
    monkeypatch.setattr(api, "_next_price_update", float("inf"))
    monkeypatch.setattr(api, "_next_control_plan_update", float("inf"))
    monkeypatch.setattr(api, "_production_forecast", {"2026-11-10T08:00:00+00:00": 100})
    monkeypatch.setattr(
        api, "_last_data", {"production_forecast": {"2026-11-10T08:00:00+00:00": 100}}
    )
    monkeypatch.setattr(api, "fetch_production_forecast", AsyncMock(return_value={}))
    assert "production_forecast" not in await api.get_data()
