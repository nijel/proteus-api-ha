"""Tests for tRPC error parsing."""

from custom_components.proteus_api.const import UPDATE_INTERVAL
from custom_components.proteus_api.proteus_api import (
    extract_trpc_error_messages,
    extract_trpc_rate_limit_retry_after,
)


def test_ignores_domain_error_fields() -> None:
    """Nested business data named error must not be treated as a tRPC error."""
    payload = [
        {
            "result": {
                "data": {
                    "json": {
                        "status": {
                            "error": {
                                "DEFAULT": "#CD3537",
                                "contrast": "#CD3537",
                                "background": "#FFEEF0",
                            }
                        }
                    }
                }
            }
        }
    ]

    assert extract_trpc_error_messages(payload) == []


def test_reads_top_level_batch_errors() -> None:
    """Top-level tRPC batch errors should still be reported."""
    payload = [
        {"result": {"data": {"json": {"ok": True}}}},
        {
            "error": {
                "json": {
                    "message": "Not found",
                    "code": -32004,
                }
            }
        },
    ]

    assert extract_trpc_error_messages(payload) == ["Not found (code: -32004)"]


def test_reads_endpoint_from_batch_position() -> None:
    """Batch error messages should identify the affected endpoint when known."""
    payload = [
        {"result": {"data": {"json": {"ok": True}}}},
        {
            "error": {
                "json": {
                    "message": "Not found",
                    "code": -32004,
                }
            }
        },
    ]

    assert extract_trpc_error_messages(
        payload, ("inverters.detail", "commands.current")
    ) == ["commands.current: Not found (code: -32004)"]


def test_prefers_endpoint_from_error_data() -> None:
    """API-provided tRPC path should override the fallback batch position."""
    payload = [
        {
            "error": {
                "json": {
                    "message": "Rate limit exceeded. Try again in 9 seconds.",
                    "code": -32029,
                    "data": {
                        "code": "TOO_MANY_REQUESTS",
                        "httpStatus": 429,
                        "path": "prices.currentDistributionPrices",
                    },
                }
            }
        }
    ]

    assert extract_trpc_error_messages(payload, ("inverters.detail",)) == [
        "prices.currentDistributionPrices: Rate limit exceeded. "
        "Try again in 9 seconds. (code: -32029)"
    ]


def test_reads_rate_limit_retry_delay() -> None:
    """Rate-limit retry delay should be parsed from the API message."""
    payload = [
        {
            "error": {
                "json": {
                    "message": "Rate limit exceeded. Try again in 9 seconds.",
                    "code": -32029,
                }
            }
        }
    ]

    assert extract_trpc_rate_limit_retry_after(payload) == 9


def test_uses_default_retry_delay_for_rate_limit_without_delay() -> None:
    """Rate-limit errors without a delay should still produce a cooldown."""
    payload = [
        {
            "error": {
                "json": {
                    "message": "Rate limit exceeded.",
                    "code": -32029,
                }
            }
        }
    ]

    assert extract_trpc_rate_limit_retry_after(payload) == UPDATE_INTERVAL
