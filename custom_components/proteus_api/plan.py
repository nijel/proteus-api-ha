"""Validation and payload construction for hourly Proteus writes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from typing import Any

BATTERY_STATES = (
    "charge_from_grid",
    "charge_from_pv",
    "default",
    "do_not_charge",
    "do_not_discharge",
    "discharge_to_household",
    "discharge_to_grid",
    "unknown",
)
PV_STATES = ("unrestricted", "fully_restricted", "restricted_to_household", "unknown")
GRID_SOC_STATES = ("charge_from_grid", "discharge_to_grid")


@dataclass
class PlanWriteState:
    """Coordinate clients sharing a household without retaining unloaded clients."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: bool = False
    writing: int = 0
    revision: int = 0


def validate_times(times: list[datetime], *, maximum: int | None = None) -> None:
    """Validate normalized hourly instants before any requests are made."""
    if not times or (maximum is not None and len(times) > maximum):
        raise ValueError(
            f"Expected 1 to {maximum} hours" if maximum else "Hours cannot be empty"
        )
    normalized = []
    for value in times:
        if not isinstance(value, datetime):
            raise ValueError("Each time must be a datetime")  # noqa: TRY004 - public validation error
        value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        if value.minute or value.second or value.microsecond:
            raise ValueError("Times must fall on an hourly UTC boundary")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("Duplicate hours are not allowed")


def format_time(value: datetime) -> str:
    """Serialize a timestamp as a superjson Date string."""
    value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_capabilities(value: Any) -> list[dict[str, Any]]:
    """Require a complete list of forbidden combinations, including wildcards."""
    if not isinstance(value, list) or any(
        not isinstance(item, dict)
        or "battery" not in item
        or item["battery"] not in (*BATTERY_STATES, None)
        or item.get("photovoltaic") not in PV_STATES
        for item in value
    ):
        raise ValueError("Invalid or missing inverter capabilities")
    return value


def grid_overflow_enabled(inverter: Any) -> bool | None:
    """Read the installation setting without inferring it from manual controls."""
    if not isinstance(inverter, dict):
        return None
    enabled = inverter.get("gridOverflowEnabled")
    if not isinstance(enabled, bool):
        return None
    setting = inverter.get("gridOverflow")
    if setting is not None and setting != ("ENABLED" if enabled else "DISABLED"):
        return None
    return enabled


def validate_soc(value: Any) -> None:
    """Accept an absent target or a finite percentage."""
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or not 0 <= value <= 100
    ):
        raise ValueError("target_soc must be null or a finite number from 0 to 100")


def build_plan_payload(
    snapshot: dict[str, Any],
    capabilities: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    *,
    clear: bool = False,
) -> dict[str, Any]:
    """Merge requested hours into the full current window without losing edits."""
    validate_times([item["time"] for item in changes])
    validate_capabilities(capabilities)
    if snapshot.get("isRecalculatingPlan") is not False:
        raise ValueError("The plan is recalculating or its status is unavailable")
    plan = snapshot.get("activePlan")
    if not isinstance(plan, dict) or not plan.get("householdId"):
        raise ValueError("No active household plan is available")
    raw_steps = plan.get("stepsWithFlexibility")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("The merged plan window is unavailable")
    overflow = grid_overflow_enabled(snapshot.get("inverter"))
    if overflow is None:
        raise ValueError("Grid overflow capability is unavailable or contradictory")
    steps = {}
    for raw in raw_steps:
        if not isinstance(raw, dict) or not isinstance(raw.get("metadata"), dict):
            raise ValueError("Invalid step in the active plan")  # noqa: TRY004 - malformed server data
        metadata = raw["metadata"]
        try:
            instant = datetime.fromisoformat(raw["startAt"])
            validate_times([instant])
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError("Invalid step time in the active plan") from err
        timestamp = format_time(instant)
        if timestamp in steps or raw.get("durationMinutes") != 60:
            raise ValueError("The plan must contain unique hourly steps")
        if any(
            not isinstance(metadata.get(key), bool)
            for key in ("manuallyEdited", "manuallyLocked")
        ):
            raise ValueError("Manual edit/lock flags are missing from the active plan")
        steps[timestamp] = {
            "time": timestamp,
            "flexalgoBattery": metadata.get("flexalgoBattery"),
            "flexalgoPv": metadata.get("flexalgoPv"),
            "targetSoC": metadata.get("targetSoC"),
            "isManuallyEdited": metadata["manuallyEdited"],
            "isManuallyLocked": metadata["manuallyLocked"],
        }
    explicit_soc = set()
    for change in changes:
        timestamp = format_time(change["time"])
        if timestamp not in steps:
            raise ValueError(f"Hour {timestamp} is outside the active plan window")
        step = steps[timestamp]
        if clear:
            step.update(isManuallyEdited=False, isManuallyLocked=False)
            continue
        fields = {
            "flexalgo_battery": "flexalgoBattery",
            "flexalgo_pv": "flexalgoPv",
            "target_soc": "targetSoC",
            "is_manually_locked": "isManuallyLocked",
        }
        if not fields.keys() & change.keys():
            raise ValueError("Each step requires at least one change")
        for source, target in fields.items():
            if source in change:
                step[target] = change[source]
        step["isManuallyEdited"] = True
        if "target_soc" in change and change["target_soc"] is not None:
            explicit_soc.add(timestamp)
    cascade = False
    for timestamp, step in sorted(steps.items(), reverse=True):
        battery, pv = step["flexalgoBattery"], step["flexalgoPv"]
        if battery not in BATTERY_STATES or pv not in PV_STATES:
            raise ValueError(f"Unknown battery or photovoltaic state at {timestamp}")
        if not isinstance(step["isManuallyLocked"], bool):
            raise ValueError("is_manually_locked must be a boolean")  # noqa: TRY004 - public validation error
        validate_soc(step["targetSoC"])
        if not overflow and battery in ("discharge_to_grid", "do_not_charge"):
            raise ValueError(f"Grid overflow is disabled: {battery} at {timestamp}")
        if any(
            item["photovoltaic"] == pv and item["battery"] in (None, battery)
            for item in capabilities
        ):
            raise ValueError(f"Inverter cannot handle {battery} / {pv} at {timestamp}")
        if (
            timestamp in explicit_soc
            and battery not in GRID_SOC_STATES
            and not (step["isManuallyLocked"] or cascade)
        ):
            raise ValueError(
                f"target_soc would not be saved at {timestamp}; use a grid charge/discharge state or lock the hour"
            )
        cascade |= step["isManuallyEdited"] or step["isManuallyLocked"]
    entries = [step for _, step in sorted(steps.items())]
    return {
        "0": {
            "json": {"householdId": plan["householdId"], "controlPlanSteps": entries},
            "meta": {
                "values": {
                    f"controlPlanSteps.{index}.time": ["Date"]
                    for index in range(len(entries))
                }
            },
        }
    }


def diagnostic_snapshot(
    snapshot: dict[str, Any], identifiers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Allowlist plan diagnostics without household, credential, or address data."""
    if identifiers is None:
        identifiers = {}
    result = {"isRecalculatingPlan": snapshot.get("isRecalculatingPlan")}
    inverter = snapshot.get("inverter") or {}
    result["inverter"] = {
        key: inverter[key]
        for key in ("gridOverflowEnabled", "gridOverflow")
        if key in inverter
    }
    plan = snapshot.get("activePlan")
    if isinstance(plan, dict):
        result["activePlan"] = {
            key: deepcopy(plan[key])
            for key in ("createdAt", "updatedAt", "stepsWithFlexibility")
            if key in plan
        }
        for step in result["activePlan"].get("stepsWithFlexibility", []):
            key = str(step.get("id", step.get("startAt")))
            step["id"] = identifiers.setdefault(key, f"step-{len(identifiers)}")
            # Metadata is also allowlisted: future API additions must not leak.
            step["metadata"] = {
                key: value
                for key, value in step.get("metadata", {}).items()
                if key
                in (
                    "flexalgoBattery",
                    "flexalgoPv",
                    "targetSoC",
                    "manuallyEdited",
                    "manuallyLocked",
                    "locked",
                    "originalFlexalgoBattery",
                    "originalFlexalgoPv",
                    "originalTargetSoC",
                    "predictedProduction",
                    "predictedConsumption",
                    "predictedProductionFromOverride",
                    "predictedConsumptionFromOverride",
                    "hasEditedPredictions",
                )
            }
            for key in list(step):
                if key not in (
                    "id",
                    "startAt",
                    "durationMinutes",
                    "metadata",
                    "hasFlexibility",
                ):
                    del step[key]
    else:
        result["activePlan"] = None
    return result
