"""Sensor platform for Claude CLI."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ClaudeCLIConfigEntry
from .const import DOMAIN
from .coordinator import ClaudeCLICoordinator

SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(
        key="auth_status",
        translation_key="auth_status",
        icon="mdi:shield-key",
    ),
    SensorEntityDescription(
        key="active_model",
        translation_key="active_model",
        icon="mdi:brain",
    ),
    SensorEntityDescription(
        key="cli_version",
        translation_key="cli_version",
        icon="mdi:file-document-check",
    ),
    SensorEntityDescription(
        key="active_sessions",
        translation_key="active_sessions",
        icon="mdi:chat-processing",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeCLIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Claude CLI sensors.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        ClaudeCLISensor(coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    )


class ClaudeCLISensor(CoordinatorEntity[ClaudeCLICoordinator], SensorEntity):
    """Sensor entity for Claude CLI bridge status."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClaudeCLICoordinator,
        description: SensorEntityDescription,
        entry: ClaudeCLIConfigEntry,
    ) -> None:
        """Initialize the sensor.

        Args:
            coordinator: The data update coordinator.
            description: The sensor entity description.
            entry: The config entry this sensor belongs to.
        """
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Claude CLI",
            manufacturer="Anthropic",
            model="Claude Code CLI",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None

        coordinator_data = self.coordinator.data
        sensor_key = self.entity_description.key

        if sensor_key == "auth_status":
            if coordinator_data.get("authenticated"):
                auth_method = str(
                    coordinator_data.get("auth_method", "unknown")
                )
                email_address = str(coordinator_data.get("email", ""))
                if email_address:
                    return f"{auth_method} ({email_address})"
                return auth_method
            return "not authenticated"

        if sensor_key == "active_model":
            configured_models = coordinator_data.get("configured_models", {})
            if isinstance(configured_models, dict):
                return str(configured_models.get("default", "unknown"))
            return "unknown"

        if sensor_key == "cli_version":
            return str(coordinator_data.get("cli_version", "unknown"))

        if sensor_key == "active_sessions":
            return int(coordinator_data.get("active_sessions", 0))

        return None
