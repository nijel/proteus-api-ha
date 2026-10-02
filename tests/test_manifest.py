"""Tests for Home Assistant manifest metadata."""

from __future__ import annotations

import json
from pathlib import Path

from packaging.requirements import Requirement

MANIFEST_PATH = (
    Path(__file__).parents[1] / "custom_components" / "proteus_api" / "manifest.json"
)


def test_manifest_does_not_require_aiohttp() -> None:
    """Home Assistant provides aiohttp, so the manifest must not require it."""
    requirements = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["requirements"]
    assert all(
        Requirement(requirement).name != "aiohttp" for requirement in requirements
    )
