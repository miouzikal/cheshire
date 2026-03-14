"""The Claude CLI integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import ConfigType

from .const import CONF_BRIDGE_URL, CONF_SHARED_SECRET, DOMAIN, LOGGER
from .coordinator import ClaudeCLICoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry

PLATFORMS = (
    Platform.AI_TASK,
    Platform.BINARY_SENSOR,
    Platform.CONVERSATION,
    Platform.SENSOR,
)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class ClaudeCLIRuntimeData:
    """Runtime data for the Claude CLI integration."""

    bridge_url: str
    session: aiohttp.ClientSession
    shared_secret: str
    coordinator: ClaudeCLICoordinator
    request_timeout_seconds: int


type ClaudeCLIConfigEntry = ConfigEntry[ClaudeCLIRuntimeData]


async def _validate_bridge(
    session: aiohttp.ClientSession,
    bridge_url: str,
    shared_secret: str,
) -> dict[str, str | int | bool]:
    """Validate bridge connectivity and return health data.

    Args:
        session: The aiohttp session to use for the request.
        bridge_url: URL of the bridge server.
        shared_secret: Bearer token for authentication.

    Returns:
        Health response data from the bridge.
    """
    async with session.get(
        f"{bridge_url}/health",
        headers={"Authorization": f"Bearer {shared_secret}"},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as response:
        response.raise_for_status()
        return await response.json()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Claude CLI."""
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ClaudeCLIConfigEntry
) -> bool:
    """Set up Claude CLI from a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.
    """
    bridge_url = entry.data[CONF_BRIDGE_URL]
    shared_secret = entry.data[CONF_SHARED_SECRET]

    session = aiohttp.ClientSession()

    try:
        health_data = await _validate_bridge(session, bridge_url, shared_secret)
    except (aiohttp.ClientError, TimeoutError) as error:
        await session.close()
        raise ConfigEntryNotReady(
            f"Cannot connect to Claude CLI bridge at {bridge_url}"
        ) from error

    coordinator = ClaudeCLICoordinator(hass, session, bridge_url, shared_secret)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = ClaudeCLIRuntimeData(
        bridge_url=bridge_url,
        session=session,
        shared_secret=shared_secret,
        coordinator=coordinator,
        request_timeout_seconds=int(
            health_data.get("request_timeout_seconds", 120)
        ),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register subentry lifecycle callbacks
    entry.async_on_unload(
        entry.async_setup_on_subentry_change(_async_on_subentry_change)
    )

    # Register reload_environment service
    async def handle_reload_environment(call: ServiceCall) -> None:
        """Handle the reload_environment service call."""
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(config_entry, "runtime_data"):
                continue
            runtime: ClaudeCLIRuntimeData = config_entry.runtime_data
            try:
                async with runtime.session.post(
                    f"{runtime.bridge_url}/reload",
                    headers={
                        "Authorization": f"Bearer {runtime.shared_secret}"
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    if not result.get("success"):
                        LOGGER.warning(
                            "Reload returned errors: %s",
                            result.get("error_messages"),
                        )
            except (aiohttp.ClientError, TimeoutError):
                LOGGER.exception("Failed to reload environment")

    if not hass.services.has_service(DOMAIN, "reload_environment"):
        hass.services.async_register(
            DOMAIN, "reload_environment", handle_reload_environment
        )

    return True


async def _async_on_subentry_change(
    hass: HomeAssistant,
    entry: ClaudeCLIConfigEntry,
    subentry: ConfigSubentry,
    change: str,
    async_add_entities: AddConfigEntryEntitiesCallback | None = None,
) -> None:
    """Handle subentry add/remove for dynamic entity management.

    Args:
        hass: The Home Assistant instance.
        entry: The parent config entry.
        subentry: The subentry being added or removed.
        change: Either 'added' or 'removed'.
        async_add_entities: Callback to add entities (provided for 'added').
    """
    if change == "added" and async_add_entities is not None:
        if subentry.subentry_type == "conversation":
            from .conversation import ClaudeCLIConversationEntity

            async_add_entities(
                [ClaudeCLIConversationEntity(entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )
        elif subentry.subentry_type == "ai_task_data":
            from .ai_task import ClaudeCLITaskEntity

            async_add_entities(
                [ClaudeCLITaskEntity(entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )


async def async_unload_entry(
    hass: HomeAssistant, entry: ClaudeCLIConfigEntry
) -> bool:
    """Unload Claude CLI.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        True if unload was successful.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.session.close()

        # Remove service if no other entries remain
        remaining_entries = hass.config_entries.async_entries(DOMAIN)
        if not any(
            existing_entry.entry_id != entry.entry_id
            for existing_entry in remaining_entries
        ):
            hass.services.async_remove(DOMAIN, "reload_environment")

    return unload_ok
