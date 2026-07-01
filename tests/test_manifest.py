"""Tests for Home Assistant manifest metadata."""

from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

MANIFEST_PATH = (
    Path(__file__).parents[1] / "custom_components" / "proteus_api" / "manifest.json"
)


def test_manifest_accepts_installed_aiohttp_version() -> None:
    """Manifest requirements should not reject Home Assistant's aiohttp pin."""
    requirements = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["requirements"]
    aiohttp_requirement = next(
        Requirement(requirement)
        for requirement in requirements
        if Requirement(requirement).name == "aiohttp"
    )

    assert Version(version("aiohttp")) in aiohttp_requirement.specifier
