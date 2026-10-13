"""Tests for daily command volumes, complete reads, and daily statistics."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.proteus_api.const import API_COMMAND_LIST_ENDPOINT
from custom_components.proteus_api.proteus_api import ProteusAPI, parse_detail_payload
from custom_components.proteus_api.volume import VOLUME_FIELDS, parse_daily_volumes

DAY = datetime(2026, 10, 12, tzinfo=ZoneInfo("Europe/Prague"))


class StubProteusAPI(ProteusAPI):
    """Serve status data while leaving the optional volume refresh active."""

    def __init__(self):
        """Initialize an API client without status-network polling."""
        super().__init__("inverter", "daily-volumes@example.com", "secret")
        self.parsed_data = {}
        self.status_result = ([], False)
        self._next_price_update = float("inf")
        self._next_control_plan_update = float("inf")

    async def _get_client(self):
        return None

    async def _fetch_trpc_batch(self, *args, **kwargs):
        return self.status_result

    def _parse_data(self, payload):
        return dict(self.parsed_data)


def _payload(volume=1.0):
    return {
        "hasMoreRecords": False,
        "records": [
            {
                "id": "command",
                "volumeKwhUp": volume,
                "volumeKwhDown": None,
                "volumeKwhSolarCurtailment": None,
            }
        ],
    }


def test_sample_volumes():
    """All directions in the supplied samples should retain their precision."""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/flexibility_volumes.json").read_text()
    )
    assert parse_daily_volumes(payload) == pytest.approx(
        {
            "flexibility_volume_up_today": 3.9617180555555555,
            "flexibility_volume_down_today": 0.7770861111111111,
            "flexibility_volume_solar_curtailment_today": 0.077425,
        }
    )


def test_combined_command_and_duplicate_ids():
    """Use volume fields rather than command type and count each ID once."""
    payload = _payload()
    record = payload["records"][0]
    record.update(
        type="DOWN_BATTERY_SOLAR_CURTAILMENT_POWER",
        volumeKwhDown=2.0,
        volumeKwhSolarCurtailment=3.0,
    )
    payload["records"].append(dict(record))
    assert list(parse_daily_volumes(payload).values()) == [1.0, 2.0, 3.0]
    record["volumeKwhUp"] = 0.25
    payload["records"] = [record]
    assert parse_daily_volumes(payload)["flexibility_volume_up_today"] == 0.25


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "1"])
def test_invalid_measurements(value):
    """Bad measurements must not turn a cached total into zero."""
    assert parse_daily_volumes(_payload(value)) == {}


def test_incomplete_responses():
    """Truncation, summaries, and absent fields are not valid daily totals."""
    payload = _payload()
    payload["hasMoreRecords"] = True
    assert parse_daily_volumes(payload) == {}
    assert parse_daily_volumes({"records": []}) == {}
    payload = _payload()
    del payload["records"][0]["volumeKwhDown"]
    assert parse_daily_volumes(payload) == {}
    assert parse_daily_volumes(
        {"hasMoreRecords": False, "records": []}
    ) == dict.fromkeys(VOLUME_FIELDS, 0.0)


class _Response:
    """Minimal response context supporting plain and streamed tRPC responses."""

    def __init__(self, payload, status=200, stream=False):
        self.status = status
        if stream:
            self.body = "\n".join(
                json.dumps({"json": line})
                for line in (
                    {"0": [[0], [None, 0, 0]]},
                    [0, 0, [[{"result": 0}], ["result", 0, 1]]],
                    [1, 0, [[{"data": 0}], ["data", 0, 2]]],
                    [2, 0, [[payload]]],
                )
            )
        else:
            self.body = json.dumps([{"result": {"data": {"json": payload}}}])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self.body


class _Client:
    """Record inputs and serve sequential responses."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.inputs = []

    def get(self, url, *, params, headers):
        assert url.endswith(API_COMMAND_LIST_ENDPOINT)
        self.inputs.append(json.loads(params["input"])["0"])
        return next(self.responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_fetch_uses_one_request_per_refresh(monkeypatch, stream):
    """Repeated daily reads should use the full limit without smaller prefixes."""
    client = _Client(
        [
            _Response(_payload(3.0), stream=stream),
            _Response(_payload(4.0), stream=stream),
        ]
    )
    api = ProteusAPI("inverter", "volume-tests@example.com", "secret")
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert (await api.fetch_daily_volumes("household", DAY))[
        "flexibility_volume_up_today"
    ] == 3.0
    assert len(client.inputs) == 1
    assert (await api.fetch_daily_volumes("household", DAY))[
        "flexibility_volume_up_today"
    ] == 4.0
    assert [item["json"]["limit"] for item in client.inputs] == [1280, 1280]
    assert client.inputs[0] == {
        "json": {
            "householdId": "household",
            "date": "2026-10-12T00:00:00.000+02:00",
            "limit": 1280,
            "timezone": "Europe/Prague",
            "allowedCommandTypes": None,
        },
        "meta": {"values": {"date": ["Date"], "allowedCommandTypes": ["undefined"]}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_truncated_daily_read_does_not_retry(monkeypatch, caplog, stream):
    """Truncated responses must not publish partial totals or trigger more GETs."""
    payload = _payload(3.0)
    payload["hasMoreRecords"] = True
    client = _Client([_Response(payload, stream=stream)])
    api = ProteusAPI("inverter", "volume-tests@example.com", "secret")
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert await api.fetch_daily_volumes("household", DAY) == {}
    assert len(client.inputs) == 1
    assert "remains truncated at the maximum limit" in caplog.text


@pytest.mark.asyncio
async def test_volume_rate_limit_preserves_optional_update(monkeypatch):
    """Rate limits prevent further calls for the endpoint."""
    api = ProteusAPI("inverter", "volume-rate-limit@example.com", "secret")
    monkeypatch.setattr(api, "_rate_limited_until_by_scope", {})
    monkeypatch.setattr(api, "_next_rate_limit_error_by_scope", {})
    client = _Client([_Response({}, status=429)])
    monkeypatch.setattr(api, "_get_client", AsyncMock(return_value=client))
    assert await api.fetch_daily_volumes("household", DAY) == {}
    assert await api.fetch_daily_volumes("household", DAY) == {}
    assert len(client.inputs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cached_status", [False, True])
async def test_midnight_expiration_and_failed_refresh(monkeypatch, cached_status):
    """Yesterday's values disappear on a failed new-day read, without polling rapidly."""
    api = StubProteusAPI()
    api.parsed_data = {"household_id": "household", "flexibility_today": 2.0}
    fetch = AsyncMock(return_value=parse_daily_volumes(_payload(4.0)))
    monkeypatch.setattr(api, "fetch_daily_volumes", fetch)
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.dt_util.start_of_local_day",
        lambda: DAY,
    )
    assert (await api.get_data())["flexibility_volume_up_today"] == 4.0
    assert (await api.get_data())["flexibility_volume_up_today"] == 4.0
    assert fetch.await_count == 1
    monkeypatch.setattr(api, "_next_volume_update", 0)
    fetch.return_value = {}
    assert (await api.get_data())["flexibility_volume_up_today"] == 4.0
    monkeypatch.setattr(
        "custom_components.proteus_api.proteus_api.dt_util.start_of_local_day",
        lambda: DAY + timedelta(days=1),
    )
    if cached_status:
        api.status_result = (None, True)
    data = await api.get_data()
    assert "flexibility_volume_up_today" not in data
    assert "flexibility_volume_last_reset" not in data
    await api.get_data()
    assert fetch.await_count == 3


def test_detail_resolves_household():
    """Use the household from detail without depending on an active plan."""
    assert (
        parse_detail_payload({"household": {"id": "household"}})["household_id"]
        == "household"
    )
