"""Binary sensor platform for Claude CLI."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClaudeCLIConfigEntry
from .const import DOMAIN
from .coordinator import ClaudeCLICoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeCLIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Claude CLI binary sensors.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    coordinator = entry.runtime_data.coordinator
    async_add_entities([ClaudeCLIHealthSensor(coordinator, entry)])


class ClaudeCLIHealthSensor(
    CoordinatorEntity[ClaudeCLICoordinator], BinarySensorEntity
):
    """Binary sensor indicating whether the Claude CLI addon is healthy."""

    _attr_has_entity_name = True
    _attr_translation_key = "addon_healthy"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: ClaudeCLICoordinator,
        entry: ClaudeCLIConfigEntry,
    ) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The data update coordinator.
            entry: The config entry this sensor belongs to.
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_addon_healthy"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Claude CLI",
            manufacturer="Anthropic",
            model="Claude Code CLI",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the addon is healthy (coordinator has data)."""
        return self.coordinator.last_update_success

    @property
    def available(self) -> bool:
        """Always available — is_on reflects connectivity status."""
        return True
