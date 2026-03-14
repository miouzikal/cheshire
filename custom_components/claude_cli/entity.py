"""Base entity for Claude CLI."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity

from . import ClaudeCLIConfigEntry
from .const import CONF_MODEL_HINT, DOMAIN


class ClaudeCLIBaseLLMEntity(Entity):
    """Claude CLI base LLM entity.

    Provides common device info, unique ID, and model hint
    for conversation and AI task entities.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, entry: ClaudeCLIConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the entity.

        Args:
            entry: The parent config entry.
            subentry: The subentry providing entity configuration.
        """
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Anthropic",
            model="Claude Code CLI",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def _model_hint(self) -> str:
        """Return the model hint from subentry data."""
        return self.subentry.data.get(CONF_MODEL_HINT, "auto")
