"""Shared entity helpers for Proteus API platforms."""

from __future__ import annotations

from .const import DOMAIN, FLEXIBILITY_CAPABILITY_LOCALIZED_NAMES, format_vendor_name

CONTROL_TYPE_ICONS = {
    "SELLING_INSTEAD_OF_BATTERY_CHARGE": "mdi:transmission-tower-export",
    "SELLING_FROM_BATTERY": "mdi:battery-arrow-up",
    "USING_FROM_GRID_INSTEAD_OF_BATTERY": "mdi:battery-lock",
    "SAVING_TO_BATTERY": "mdi:battery-arrow-down",
    "BLOCKING_GRID_OVERFLOW": "mdi:transmission-tower-off",
}


def build_device_info(inverter_id: str, inverter: dict) -> dict:
    """Build device info for an inverter-backed entity."""
    vendor_name = format_vendor_name(inverter.get("vendor", "Unknown"))
    return {
        "identifiers": {(DOMAIN, inverter_id)},
        "name": f"{vendor_name} Inverter",
        "manufacturer": vendor_name,
        "model": "Proteus",
    }


def get_control_type_icon(control_type: str) -> str:
    """Return the icon for a control type."""
    return CONTROL_TYPE_ICONS.get(control_type, "mdi:toggle-switch")


def get_flexibility_capability_name(language: str, capability: str) -> str:
    """Return the localized display name for a flexibility capability."""
    language_variants = [language, language.split("-", 1)[0], "en"]
    for variant in language_variants:
        if variant in FLEXIBILITY_CAPABILITY_LOCALIZED_NAMES:
            return FLEXIBILITY_CAPABILITY_LOCALIZED_NAMES[variant].get(
                capability, capability
            )
    return capability
