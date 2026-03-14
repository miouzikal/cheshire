"""Diagnostics support for Claude CLI."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from . import ClaudeCLIConfigEntry
from .const import CONF_PROMPT

REDACTED_SUBENTRY_KEYS = {CONF_PROMPT}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClaudeCLIConfigEntry
) -> dict[
    str,
    str
    | list[dict[str, str | dict[str, str]]]
    | dict[str, str | int | bool | list[str]]
    | None,
]:
    """Return diagnostics for a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to generate diagnostics for.

    Returns:
        Dictionary with redacted config entry diagnostics.
    """
    coordinator_data = None
    if hasattr(entry, "runtime_data") and entry.runtime_data:
        coordinator_data = entry.runtime_data.coordinator.data

    subentries = []
    for subentry in entry.subentries.values():
        subentry_data = {
            field_key: REDACTED if field_key in REDACTED_SUBENTRY_KEYS else field_value
            for field_key, field_value in subentry.data.items()
        }
        subentries.append(
            {
                "subentry_id": subentry.subentry_id,
                "subentry_type": subentry.subentry_type,
                "title": subentry.title,
                "data": subentry_data,
            }
        )

    return {
        "bridge_url": entry.data.get("bridge_url"),
        "shared_secret": REDACTED,
        "health": coordinator_data,
        "subentries": subentries,
    }
