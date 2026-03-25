"""Tests for tRPC error parsing."""

from custom_components.proteus_api.proteus_api import ProteusAPI


def test_ignores_domain_error_fields() -> None:
    """Nested business data named error must not be treated as a tRPC error."""
    api = ProteusAPI("inverter-id", "user@example.com", "secret")
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

    assert api._extract_trpc_error_messages(payload) == []  # noqa: SLF001


def test_reads_top_level_batch_errors() -> None:
    """Top-level tRPC batch errors should still be reported."""
    api = ProteusAPI("inverter-id", "user@example.com", "secret")
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

    assert api._extract_trpc_error_messages(payload) == [  # noqa: SLF001
        "Not found (code: -32004)"
    ]
