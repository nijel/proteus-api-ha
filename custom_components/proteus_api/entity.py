"""Shared entity helpers for Proteus API platforms."""

from __future__ import annotations

from .const import DOMAIN, format_vendor_name

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
