"""DataUpdateCoordinator for Claude CLI health polling."""

from __future__ import annotations

from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER

POLL_INTERVAL = timedelta(seconds=60)

REPAIR_ADDON_UNREACHABLE = "addon_unreachable"
REPAIR_CLI_NOT_AUTHENTICATED = "cli_not_authenticated"


class ClaudeCLICoordinator(
    DataUpdateCoordinator[dict[str, str | int | bool | list[str]]],
):
    """Polls the bridge /health endpoint and exposes data to sensors.

    Creates and clears repair issues based on bridge connectivity
    and CLI authentication status.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        bridge_url: str,
        shared_secret: str,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            session: The aiohttp session for bridge requests.
            bridge_url: URL of the bridge server.
            shared_secret: Bearer token for authentication.
        """
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self._session = session
        self._bridge_url = bridge_url
        self._shared_secret = shared_secret

    async def _async_update_data(
        self,
    ) -> dict[str, str | int | bool | list[str]]:
        """Fetch health data from the bridge.

        Returns:
            Health response data from the bridge.

        Raises:
            UpdateFailed: If the bridge is unreachable.
        """
        try:
            async with self._session.get(
                f"{self._bridge_url}/health",
                headers={
                    "Authorization": f"Bearer {self._shared_secret}"
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                health_data: dict[str, str | int | bool | list[str]] = (
                    await response.json()
                )
        except (aiohttp.ClientError, TimeoutError) as error:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                REPAIR_ADDON_UNREACHABLE,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=REPAIR_ADDON_UNREACHABLE,
            )
            raise UpdateFailed(f"Bridge unreachable: {error}") from error

        # Clear unreachable repair on success
        ir.async_delete_issue(self.hass, DOMAIN, REPAIR_ADDON_UNREACHABLE)

        # Check authentication status
        if not health_data.get("authenticated"):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                REPAIR_CLI_NOT_AUTHENTICATED,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=REPAIR_CLI_NOT_AUTHENTICATED,
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, REPAIR_CLI_NOT_AUTHENTICATED
            )

        return health_data
