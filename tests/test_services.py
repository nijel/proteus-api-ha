"""Tests for the prediction service schemas."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.proteus_api import (
    CLEAR_PREDICTIONS_SCHEMA,
    SET_PREDICTIONS_SCHEMA,
)


def test_set_predictions_accepts_partial_override() -> None:
    """Either quantity may be left out; the other is still coerced to float."""
    data = SET_PREDICTIONS_SCHEMA(
        {
            "predictions": [
                {"time": "2026-08-09T19:00:00", "consumption_kwh": "0.5"},
                {"time": "2026-08-09T20:00:00", "production_kwh": 0},
            ]
        }
    )

    assert data["predictions"][0]["consumption_kwh"] == 0.5
    assert "production_kwh" not in data["predictions"][0]
    assert data["predictions"][1]["production_kwh"] == 0.0


def test_set_predictions_accepts_explicit_null_for_one_quantity() -> None:
    """An explicit null is allowed as long as the other quantity has a value."""
    data = SET_PREDICTIONS_SCHEMA(
        {
            "predictions": [
                {
                    "time": "2026-08-09T19:00:00",
                    "consumption_kwh": 0.5,
                    "production_kwh": None,
                }
            ]
        }
    )

    assert data["predictions"][0]["production_kwh"] is None


@pytest.mark.parametrize(
    "prediction",
    [
        {"time": "2026-08-09T19:00:00"},
        {"time": "2026-08-09T19:00:00", "consumption_kwh": None},
        {
            "time": "2026-08-09T19:00:00",
            "consumption_kwh": None,
            "production_kwh": None,
        },
    ],
)
def test_set_predictions_requires_at_least_one_value(prediction: dict) -> None:
    """An item without any value is rejected; clearing has its own service."""
    with pytest.raises(vol.Invalid, match="clear_predictions"):
        SET_PREDICTIONS_SCHEMA({"predictions": [prediction]})


def test_set_predictions_requires_time() -> None:
    """Every item needs a timestamp."""
    with pytest.raises(vol.Invalid):
        SET_PREDICTIONS_SCHEMA({"predictions": [{"consumption_kwh": 0.5}]})


def test_clear_predictions_accepts_single_time() -> None:
    """A single timestamp is wrapped into a list and parsed."""
    data = CLEAR_PREDICTIONS_SCHEMA({"times": "2026-08-09T19:00:00"})

    assert len(data["times"]) == 1
    assert data["times"][0].hour == 19


def test_clear_predictions_rejects_empty_list() -> None:
    """Clearing nothing is a caller mistake."""
    with pytest.raises(vol.Invalid):
        CLEAR_PREDICTIONS_SCHEMA({"times": []})
