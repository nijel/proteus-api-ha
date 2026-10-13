"""Parse daily flexibility volumes from household command records."""

from __future__ import annotations

from math import fsum, isfinite
from typing import Any

VOLUME_FIELDS = {
    "flexibility_volume_up_today": "volumeKwhUp",
    "flexibility_volume_down_today": "volumeKwhDown",
    "flexibility_volume_solar_curtailment_today": "volumeKwhSolarCurtailment",
}


def parse_daily_volumes(payload: Any) -> dict[str, float]:
    """Sum daily flexibility deltas, deduplicating IDs and rejecting invalid data.

    Combined commands can contain multiple volumes. Null volumes represent
    unused directions. A truncated or malformed response must not replace a
    previously known daily total.
    """
    if (
        not isinstance(payload, dict)
        or payload.get("hasMoreRecords") is not False
        or not isinstance(payload.get("records"), list)
    ):
        return {}

    records = {}
    for record in payload["records"]:
        if not isinstance(record, dict):
            return {}
        command_id = record.get("id")
        if not isinstance(command_id, str) or not command_id:
            return {}
        volumes = {}
        for key, field in VOLUME_FIELDS.items():
            if field not in record:
                return {}
            value = record[field]
            if value is None:
                volumes[key] = 0.0
            elif (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isfinite(value)
                and value >= 0
            ):
                volumes[key] = float(value)
            else:
                return {}
        records[command_id] = volumes

    return {
        key: fsum(record[key] for record in records.values()) for key in VOLUME_FIELDS
    }
