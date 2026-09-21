"""Plan editing regressions based on an anonymized portal capture."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.proteus_api import (
    CLEAR_PREDICTIONS_SCHEMA,
    SET_PLAN_STEPS_SCHEMA,
    SET_PREDICTIONS_SCHEMA,
    _async_plan_steps,
)
from custom_components.proteus_api.plan import build_plan_payload, diagnostic_snapshot
from custom_components.proteus_api.proteus_api import (
    ProteusAPI,
    ProteusConnectionError,
    decode_single_result,
    parse_control_plan_payload,
    write_response_diagnostic,
)
from custom_components.proteus_api.sensor import ProteusControlPlanSensor
from homeassistant.core import ServiceCall
from homeassistant.exceptions import ServiceValidationError

CAPABILITIES = [{"battery": "do_not_charge", "photovoltaic": "restricted_to_household"}]


@pytest.fixture
def snapshot():
    """Return a minimized capture retaining the first edited and unedited hours."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "edited_plan.json").read_text()
    )


def hour(value=16):
    """Return an hour within the captured plan."""
    return datetime(2026, 9, 21, value, tzinfo=UTC)


def test_reads_merged_plan(snapshot):
    """The base plan must not hide panel-off edits or manual flags."""
    parsed = parse_control_plan_payload(snapshot)
    assert len(parsed["control_plan_steps"]) == 3
    assert parsed["control_plan_steps"][0]["flexalgo_pv"] == "fully_restricted"
    assert parsed["control_plan_steps"][0]["manually_locked"] is False
    assert parsed["control_plan_steps"][0]["locked"] is True
    assert parsed["control_plan_steps"][0]["predicted_consumption"] == 2906.6363
    assert parsed["control_plan_household_id"] == "household-1"
    assert parsed["grid_overflow_enabled"] is True
    assert parsed["is_recalculating_plan"] is False
    snapshot["activePlan"]["stepsWithFlexibility"] = []
    assert parse_control_plan_payload(snapshot)["control_plan_steps"] == []


def test_merge_preserves_edits_and_soc(snapshot):
    """Changing a later hour preserves earlier edits without turning effective locks into manual locks."""
    before = deepcopy(snapshot)
    payload = build_plan_payload(
        snapshot,
        CAPABILITIES,
        [{"time": hour(), "flexalgo_battery": "charge_from_grid", "target_soc": 80}],
    )["0"]
    steps = payload["json"]["controlPlanSteps"]
    assert len(steps) == 3
    assert steps[0]["flexalgoPv"] == "fully_restricted"
    assert steps[0]["isManuallyLocked"] is False
    assert steps[0]["isManuallyEdited"] is True
    assert steps[0]["targetSoC"] is None
    assert steps[2]["targetSoC"] == 80
    assert steps[2]["isManuallyEdited"] is True
    assert snapshot == before
    assert payload["meta"]["values"] == {
        f"controlPlanSteps.{i}.time": ["Date"] for i in range(3)
    }
    assert set(steps[0]) == {
        "time",
        "flexalgoBattery",
        "flexalgoPv",
        "targetSoC",
        "isManuallyEdited",
        "isManuallyLocked",
    }


def test_reset_preserves_later_edit(snapshot):
    """A reset changes manual flags without silently clearing later edits."""
    steps = build_plan_payload(
        snapshot, CAPABILITIES, [{"time": hour(14)}], clear=True
    )["0"]["json"]["controlPlanSteps"]
    assert steps[0]["isManuallyEdited"] is False
    assert steps[0]["isManuallyLocked"] is False
    assert steps[1]["isManuallyEdited"] is True
    assert steps[2]["targetSoC"] == 67


@pytest.mark.parametrize("locked", [True, False])
def test_explicit_soc_requires_supported_state_or_lock(snapshot, locked):
    """Targets in ordinary battery states must have a lock to persist."""
    changes = [{"time": hour(), "target_soc": 60, "is_manually_locked": locked}]
    if locked:
        step = build_plan_payload(snapshot, [], changes)["0"]["json"][
            "controlPlanSteps"
        ][2]
        assert step["isManuallyLocked"] is True
        assert step["targetSoC"] == 60
    else:
        with pytest.raises(ValueError, match="would not be saved"):
            build_plan_payload(snapshot, [], changes)


@pytest.mark.parametrize(
    "capabilities",
    [
        [{"battery": None, "photovoltaic": "fully_restricted"}],
        [{"battery": "default", "photovoltaic": "fully_restricted"}],
    ],
)
def test_validates_untouched_steps(snapshot, capabilities):
    """The server validates the entire window, so unchanged invalid steps must fail locally."""
    with pytest.raises(ValueError, match="Inverter cannot handle"):
        build_plan_payload(
            snapshot, capabilities, [{"time": hour(), "flexalgo_pv": "unrestricted"}]
        )


@pytest.mark.parametrize("overflow", [False, None])
def test_grid_overflow_validation(snapshot, overflow):
    """Disabled or unavailable export capability cannot authorize a grid discharge."""
    snapshot["inverter"] = {"gridOverflowEnabled": overflow}
    with pytest.raises(ValueError, match="[Gg]rid overflow"):
        build_plan_payload(
            snapshot, [], [{"time": hour(), "flexalgo_battery": "discharge_to_grid"}]
        )


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "recalculating",
        "outside",
        "flags",
        "malformed_step",
        "duplicate",
        "invalid_soc",
        "unknown",
        "duration",
    ],
)
def test_invalid_plan_edits(snapshot, case):
    """Incomplete snapshots and invalid requests must fail before any POST."""
    changes = [{"time": hour(), "flexalgo_pv": "unrestricted"}]
    if case == "missing":
        del snapshot["activePlan"]["stepsWithFlexibility"]
    elif case == "recalculating":
        snapshot["isRecalculatingPlan"] = True
    elif case == "outside":
        changes[0]["time"] = hour(17)
    elif case == "flags":
        del snapshot["activePlan"]["stepsWithFlexibility"][0]["metadata"][
            "manuallyLocked"
        ]
    elif case == "duplicate":
        changes *= 2
    elif case == "malformed_step":
        snapshot["activePlan"]["stepsWithFlexibility"].append({})
    elif case == "invalid_soc":
        changes[0]["target_soc"] = float("nan")
    elif case == "unknown":
        changes[0]["flexalgo_pv"] = "invalid"
    else:
        snapshot["activePlan"]["stepsWithFlexibility"][0]["durationMinutes"] = 30
    with pytest.raises(ValueError):
        build_plan_payload(snapshot, [], changes)


@pytest.mark.parametrize("count", [96, 97])
@pytest.mark.parametrize("clear", [True, False])
def test_prediction_limits(count, clear):
    """Both prediction services enforce the API's maximum payload size."""
    times = [hour() + timedelta(hours=i) for i in range(count)]
    schema = CLEAR_PREDICTIONS_SCHEMA if clear else SET_PREDICTIONS_SCHEMA
    data = (
        {"times": times}
        if clear
        else {"predictions": [{"time": time, "production_kwh": 1} for time in times]}
    )
    if count == 97:
        with pytest.raises(vol.Invalid):
            schema(data)
    else:
        schema(data)


@pytest.mark.parametrize(
    "times",
    [
        ["2026-09-21T16:01:00Z"],
        ["2026-09-21T16:00:00Z", "2026-09-21T18:00:00+02:00"],
    ],
)
def test_rejects_off_hour_and_duplicate_times(times):
    """Compare instants after offset normalization."""
    with pytest.raises(vol.Invalid):
        CLEAR_PREDICTIONS_SCHEMA({"times": times})


def test_plan_schema_requires_change():
    """An hour without fields is not an edit."""
    with pytest.raises(vol.Invalid, match="at least one"):
        SET_PLAN_STEPS_SCHEMA({"steps": [{"time": hour()}]})


def test_diagnostics_are_allowlisted(snapshot):
    """New server metadata must not accidentally expose personal or credential fields."""
    snapshot["inverter"].update(address="private", accessToken="secret")
    snapshot["activePlan"]["stepsWithFlexibility"][0]["metadata"]["credentials"] = (
        "secret"
    )
    result = diagnostic_snapshot(snapshot)
    encoded = json.dumps(result)
    assert "secret" not in encoded
    assert "private" not in encoded
    assert "household-1" not in encoded
    assert (
        result["activePlan"]["stepsWithFlexibility"][0]["metadata"]["manuallyLocked"]
        is False
    )


def response_client(data, *, status=200):
    """Build a mocked retry client with independently controlled response bodies."""
    response = AsyncMock(status=status)
    response.text.return_value = data
    client = MagicMock()
    client.get.return_value.__aenter__.return_value = response
    client.post.return_value.__aenter__.return_value = response
    return client


def plain(data):
    """Wrap response data in a regular tRPC batch."""
    return json.dumps([{"result": {"data": {"json": data}}}])


async def test_write_success_marks_pending_and_disables_retry():
    """A write accepts a null result but never uses the client's normal ten attempts."""
    api = ProteusAPI("inv", "writer@example.com", "secret")
    client = response_client(plain(None))
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert await api.upsert_prediction_overrides(
            [{"time": hour(), "production_kwh": 1}]
        )
    assert api.plan_refresh_pending
    assert client.post.call_args.kwargs["retry_options"].attempts == 1


@pytest.mark.parametrize(
    "body", ["broken", '[{"error":{"json":{"message":"unsupported combination"}}}]']
)
async def test_write_errors_and_uncertain_outcome(body):
    """HTTP 200 alone must not count as a successful mutation."""
    api = ProteusAPI("inv", "errors@example.com", "secret")
    client = response_client(body)
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert not await api.clear_prediction_overrides([hour()])
    assert api.last_write_error
    assert api.plan_refresh_pending
    client.post.assert_called_once()


async def test_stale_read_cannot_complete_new_write(snapshot):
    """Only reads started after the latest write can clear its pending flag."""
    api = ProteusAPI("inv", "stale@example.com", "secret")
    client = response_client(plain(snapshot))

    async def writing_response():
        api.invalidate_plan()
        return plain(snapshot)

    client.get.return_value.__aenter__.return_value.text.side_effect = writing_response
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        await api.fetch_control_plan()
    assert api.plan_refresh_pending
    client.get.return_value.__aenter__.return_value.text.side_effect = None
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        await api.fetch_control_plan()
    assert not api.plan_refresh_pending


async def test_household_clients_share_pending_state(snapshot):
    """Two inverters in one account/household must not race plan writes."""
    first = ProteusAPI("inv-1", "shared@example.com", "secret")
    second = ProteusAPI("inv-2", "shared@example.com", "secret")
    client = response_client(plain(snapshot))
    for api in (first, second):
        with patch.object(api, "_get_client", AsyncMock(return_value=client)):
            await api.fetch_control_plan()
    assert first.shares_household(second)
    first.invalidate_plan()
    assert second.plan_refresh_pending
    with pytest.raises(ValueError, match="previous write"):
        await second.update_plan_steps(
            [{"time": hour(), "flexalgo_pv": "unrestricted"}]
        )


async def test_capabilities_stream_and_rate_limit():
    """Read the captured streamed forbidden combination and honor server cooldowns."""
    api = ProteusAPI("inv", "capabilities@example.com", "secret")
    body = "\n".join(
        json.dumps({"json": value})
        for value in [
            {"0": [[0], [None, 0, 1]]},
            [1, 0, [[{"result": {"data": CAPABILITIES}}]]],
        ]
    )
    client = response_client(body)
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert await api.fetch_plan_capabilities() == CAPABILITIES
    client = response_client(
        '[{"error":{"json":{"message":"rate limit","code":-32029}}}]', status=429
    )
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        with pytest.raises(ProteusConnectionError, match="rate limited"):
            await api.fetch_plan_capabilities()
        with pytest.raises(ProteusConnectionError, match="rate limited"):
            await api.fetch_plan_capabilities()
    client.get.assert_called_once()


def test_streamed_undefined_soc(snapshot):
    """A superjson undefined target stays absent, never falling back to original SoC."""
    body = "\n".join(
        json.dumps(value)
        for value in [
            {"json": {"0": [[0], [None, 0, 1]]}},
            {
                "json": [1, 0, [[{"result": {"data": snapshot}}]]],
                "meta": {
                    "values": {
                        "2.0.0.result.data.activePlan.stepsWithFlexibility.0.metadata.targetSoC": [
                            "undefined"
                        ]
                    }
                },
            },
        ]
    )
    result = decode_single_result(body)
    assert (
        result["activePlan"]["stepsWithFlexibility"][0]["metadata"]["targetSoC"] is None
    )


async def test_update_posts_full_window_and_fetches_fresh(snapshot):
    """Exercise the complete read/validate/write flow rather than only its builder."""
    api = ProteusAPI("inv", "edit-flow@example.com", "secret")
    client = response_client(plain(snapshot))
    client.get.return_value.__aenter__.return_value.text.side_effect = [
        plain(snapshot),
        plain(snapshot),
        plain(CAPABILITIES),
    ]
    posted = AsyncMock(status=200)
    posted.text.return_value = plain("calculation-id")
    client.post.return_value.__aenter__.return_value = posted
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        await api.update_plan_steps(
            [{"time": hour(), "flexalgo_pv": "fully_restricted"}]
        )
    assert client.get.call_count == 3
    client.post.assert_called_once()
    assert "controlPlans.updateSteps" in client.post.call_args.args[0]
    sent = client.post.call_args.kwargs["json"]["0"]["json"]
    assert sent["householdId"] == "household-1"
    assert len(sent["controlPlanSteps"]) == 3
    assert sent["controlPlanSteps"][2]["targetSoC"] == 67
    assert api.plan_refresh_pending


async def test_invalid_capability_prevents_post(snapshot):
    """An unavailable capabilities response must never be treated as no restrictions."""
    api = ProteusAPI("inv", "bad-capabilities@example.com", "secret")
    client = response_client(plain(snapshot))
    client.get.return_value.__aenter__.return_value.text.side_effect = [
        plain(snapshot),
        plain(snapshot),
        plain(None),
    ]
    with (
        patch.object(api, "_get_client", AsyncMock(return_value=client)),
        pytest.raises(ValueError, match="capabilities"),
    ):
        await api.update_plan_steps(
            [{"time": hour(), "flexalgo_pv": "fully_restricted"}]
        )
    client.post.assert_not_called()


async def test_write_transport_failure_is_not_retried():
    """A dropped connection after sending is ambiguous and must force a read."""
    api = ProteusAPI("inv", "connection@example.com", "secret")
    client = response_client(plain(None))
    client.post.return_value.__aenter__.side_effect = TimeoutError("lost response")
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert not await api.clear_prediction_overrides([hour()])
    assert "uncertain" in api.last_write_error
    assert api.plan_refresh_pending
    client.post.assert_called_once()


async def test_diagnostic_capture_suppresses_duplicates(snapshot, caplog):
    """Explicit diagnostics retain changed manual metadata but omit repeated windows."""
    api = ProteusAPI("inv", "diagnostics@example.com", "secret")
    client = response_client(plain(snapshot))
    with (
        caplog.at_level(
            logging.DEBUG, logger="custom_components.proteus_api.plan_diagnostics"
        ),
        patch.object(api, "_get_client", AsyncMock(return_value=client)),
    ):
        await api.fetch_control_plan()
        await api.fetch_control_plan()
        snapshot["activePlan"]["stepsWithFlexibility"][0]["metadata"][
            "manuallyLocked"
        ] = True
        client.get.return_value.__aenter__.return_value.text.return_value = plain(
            snapshot
        )
        await api.fetch_control_plan()
    assert sum("Plan snapshot" in record.message for record in caplog.records) == 2
    assert "diagnostics@example.com" not in caplog.text
    assert "household-1" not in caplog.text


@pytest.mark.parametrize("count", [0, 2])
async def test_plan_service_requires_exact_target(hass, count):
    """Missing and multi-inverter targets cannot silently change multiple households."""

    call = ServiceCall(
        hass,
        "proteus_api",
        "set_plan_steps",
        {
            "device_id": ["device"] if count else [],
            "steps": [{"time": hour(), "flexalgo_pv": "unrestricted"}],
        },
    )
    with (
        patch(
            "custom_components.proteus_api._async_get_target_apis",
            return_value=[("inv", MagicMock())] * count,
        ),
        pytest.raises(ServiceValidationError, match="exactly one"),
    ):
        await _async_plan_steps(hass, call)


async def test_plan_service_refreshes_known_household_peers(hass, snapshot):
    """After an accepted service write all known peers receive fresh plan data."""

    api = ProteusAPI("inv", "service@example.com", "secret")
    peer = ProteusAPI("peer", "service@example.com", "secret")
    client = response_client(plain(snapshot))
    for item in (api, peer):
        with patch.object(item, "_get_client", AsyncMock(return_value=client)):
            await item.fetch_control_plan()
    coordinators = [MagicMock(async_request_refresh=AsyncMock()) for _ in range(2)]
    hass.data["proteus_api"] = {
        "entry": {
            "inverters": {
                "inv": {"api": api, "coordinator": coordinators[0]},
                "peer": {"api": peer, "coordinator": coordinators[1]},
            }
        }
    }

    async def accept(*args, **kwargs):
        api.invalidate_plan()

    call = ServiceCall(
        hass,
        "proteus_api",
        "set_plan_steps",
        {
            "device_id": ["device"],
            "steps": [{"time": hour(), "flexalgo_pv": "fully_restricted"}],
        },
    )
    with (
        patch(
            "custom_components.proteus_api._async_get_target_apis",
            return_value=[("inv", api)],
        ),
        patch.object(api, "update_plan_steps", AsyncMock(side_effect=accept)),
    ):
        await _async_plan_steps(hass, call)
    for coordinator in coordinators:
        coordinator.async_request_refresh.assert_awaited_once()


def test_full_48_hour_window(snapshot):
    """Use the captured action fields over the portal's full visible window length."""
    steps = snapshot["activePlan"]["stepsWithFlexibility"]
    original = deepcopy(steps[2])
    for offset in range(3, 48):
        step = deepcopy(original)
        step["startAt"] = (hour(14) + timedelta(hours=offset)).isoformat()
        step["metadata"]["targetSoC"] = offset
        steps.append(step)
    payload = build_plan_payload(
        snapshot,
        CAPABILITIES,
        [
            {
                "time": hour(14) + timedelta(hours=47),
                "flexalgo_battery": "charge_from_grid",
                "target_soc": 80,
            }
        ],
    )["0"]
    sent = payload["json"]["controlPlanSteps"]
    assert len(sent) == len(payload["meta"]["values"]) == 48
    assert [step["targetSoC"] for step in sent[3:47]] == list(range(3, 47))
    assert sent[0]["flexalgoPv"] == "fully_restricted"
    assert sent[-1]["targetSoC"] == 80


async def test_concurrent_edits_are_serialized(snapshot):
    """An edit queued during another edit's preflight must not overwrite its result."""
    first = ProteusAPI("inv-1", "concurrent@example.com", "secret")
    second = ProteusAPI("inv-2", "concurrent@example.com", "secret")
    client = response_client(plain(snapshot))
    for api in (first, second):
        with patch.object(api, "_get_client", AsyncMock(return_value=client)):
            await api.fetch_control_plan()
    entered = asyncio.Event()
    release = asyncio.Event()
    second_read = asyncio.Event()

    async def capabilities():
        entered.set()
        await release.wait()
        return CAPABILITIES

    async def refresh_second():
        second_read.set()
        return parse_control_plan_payload(snapshot)

    async def write(*args):
        first.invalidate_plan()
        return True

    changes = [{"time": hour(), "flexalgo_pv": "unrestricted"}]
    with (
        patch.object(
            first,
            "_fetch_control_plan_safely",
            AsyncMock(return_value=parse_control_plan_payload(snapshot)),
        ),
        patch.object(
            second, "_fetch_control_plan_safely", AsyncMock(side_effect=refresh_second)
        ),
        patch.object(
            first, "fetch_plan_capabilities", AsyncMock(side_effect=capabilities)
        ),
        patch.object(first, "_post_plan_write", AsyncMock(side_effect=write)) as post,
        patch.object(second, "_post_plan_write", AsyncMock()) as other_post,
    ):
        first_task = asyncio.create_task(first.update_plan_steps(changes))
        await entered.wait()
        second_task = asyncio.create_task(second.update_plan_steps(changes))
        await second_read.wait()
        release.set()
        await first_task
        with pytest.raises(ValueError, match="previous write"):
            await second_task
    post.assert_awaited_once()
    other_post.assert_not_awaited()


async def test_manual_sensor_refresh_forces_plan_fetch(hass):
    """An explicit entity refresh bypasses only the plan's normal scheduling deadline."""
    entry = SimpleNamespace(entry_id="entry")
    api = MagicMock()
    coordinator = MagicMock(async_request_refresh=AsyncMock(), data={})
    hass.data["proteus_api"] = {"entry": {"inverters": {"inv": {"api": api}}}}
    sensor = ProteusControlPlanSensor(coordinator, entry, "inv", {})
    sensor.hass = hass
    await sensor.async_update()
    api.request_plan_refresh.assert_called_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("wrapped", [False, True])
async def test_void_stream_write_succeeds(wrapped):
    """A fulfilled undefined value is a successful write, not malformed JSONL."""
    api = ProteusAPI("inv", "void@example.com", "secret")
    body = "\n".join(
        json.dumps({"json": value})
        for value in [
            {"0": [[0], [None, 0, 1]]},
            [1, 0, [[{"result": 0}], ["result", 0, 2]]],
            [2, 0, [[{"data": 0}], ["data", 0, 3]]],
            [
                3,
                0,
                [[{"json": None, "meta": {"values": ["undefined"]}}]]
                if wrapped
                else [[]],
            ],
        ]
    )
    client = response_client(body)
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert await api.clear_prediction_overrides([hour()])
    assert api.last_write_error is None
    assert api.plan_refresh_pending
    client.post.assert_called_once()


@pytest.mark.parametrize("tail", [None, [3, 0, []], [3, 1, {"message": "rejected"}]])
async def test_incomplete_or_rejected_stream_write_still_fails(tail):
    """Supporting void must not turn absent chunks or rejected results into success."""
    chunks = [
        {"0": [[0], [None, 0, 1]]},
        [1, 0, [[{"result": 0}], ["result", 0, 2]]],
        [2, 0, [[{"data": 0}], ["data", 0, 3]]],
    ]
    if tail is not None:
        chunks.append(tail)
    body = "\n".join(json.dumps({"json": value}) for value in chunks)
    api = ProteusAPI("inv", "incomplete@example.com", "secret")
    client = response_client(body)
    with patch.object(api, "_get_client", AsyncMock(return_value=client)):
        assert not await api.clear_prediction_overrides([hour()])
    assert api.plan_refresh_pending


def test_write_response_diagnostics_redact_values():
    """Debug output retains the undefined marker and references, without returned identifiers."""
    body = json.dumps(
        {
            "json": [
                3,
                0,
                [
                    [
                        {
                            "id": "private-id",
                            "json": None,
                            "meta": {"values": ["undefined"]},
                        }
                    ]
                ],
            ]
        }
    )
    result = write_response_diagnostic(body)
    encoded = json.dumps(result)
    assert "private-id" not in encoded
    assert "undefined" in encoded
    assert result[0]["json"][:2] == [3, 0]


def test_explicit_lock_capture_preserves_manual_flags(snapshot):
    """Observed server state separates cascade locks from explicit locks and edits."""
    steps = snapshot["activePlan"]["stepsWithFlexibility"]
    # First three hours from the user's 14:16:38Z diagnostic capture.
    for index, step in enumerate(steps):
        metadata = step["metadata"]
        metadata.update(
            flexalgoBattery="charge_from_grid"
            if index == 0
            else "discharge_to_household",
            flexalgoPv="unrestricted",
            targetSoC=[76, 71, 65][index],
            manuallyEdited=False,
            manuallyLocked=index == 2,
            locked=True,
        )
    payload = build_plan_payload(
        snapshot, CAPABILITIES, [{"time": hour(), "is_manually_locked": True}]
    )["0"]["json"]["controlPlanSteps"]
    assert [step["isManuallyLocked"] for step in payload] == [False, False, True]
    assert [step["targetSoC"] for step in payload] == [76, 71, 65]
    cleared = build_plan_payload(
        snapshot, CAPABILITIES, [{"time": hour()}], clear=True
    )["0"]["json"]["controlPlanSteps"]
    assert all(
        not step["isManuallyLocked"] and not step["isManuallyEdited"]
        for step in cleared
    )
