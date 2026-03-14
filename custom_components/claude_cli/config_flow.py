"""Config flow for Claude CLI integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_LLM_HASS_API, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)
from homeassistant.helpers.typing import VolDictType

from .const import (
    CONF_BRIDGE_URL,
    CONF_MODEL_HINT,
    CONF_PROMPT,
    CONF_RECOMMENDED,
    CONF_SHARED_SECRET,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_BRIDGE_URL,
    DEFAULT_CONVERSATION_NAME,
    DOMAIN,
    MODEL_HINTS,
)

if TYPE_CHECKING:
    from . import ClaudeCLIConfigEntry

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BRIDGE_URL, default=DEFAULT_BRIDGE_URL): str,
        vol.Required(CONF_SHARED_SECRET): str,
    }
)

DEFAULT_CONVERSATION_OPTIONS: dict[str, str | bool | list[str]] = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}

DEFAULT_AI_TASK_OPTIONS: dict[str, bool] = {
    CONF_RECOMMENDED: True,
}


async def _validate_bridge(
    bridge_url: str, shared_secret: str
) -> dict[str, str | int | bool]:
    """Validate the bridge connection.

    Args:
        bridge_url: URL of the bridge server to validate.
        shared_secret: Bearer token for authentication.

    Returns:
        Health response data from the bridge.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{bridge_url}/health",
            headers={"Authorization": f"Bearer {shared_secret}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return await response.json()


class ClaudeCLIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Claude CLI."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_hassio(
        self, discovery_info: dict[str, str | int]
    ) -> ConfigFlowResult:
        """Handle Supervisor addon discovery.

        Args:
            discovery_info: Discovery data from the Supervisor.

        Returns:
            Config flow result directing to the confirmation step.
        """
        # HA passes slug as hostname for internal addon networking
        port = discovery_info.get("port", 8099)
        bridge_url = f"http://local-claude-cli:{port}"
        self._async_abort_entries_match({CONF_BRIDGE_URL: bridge_url})
        self.context["bridge_url"] = bridge_url
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Confirm Supervisor addon discovery.

        Args:
            user_input: User-provided shared secret, or None for initial form.

        Returns:
            Config flow result with entry creation or form.
        """
        errors: dict[str, str] = {}
        bridge_url = self.context["bridge_url"]

        if user_input is not None:
            shared_secret = user_input[CONF_SHARED_SECRET]
            try:
                await _validate_bridge(bridge_url, shared_secret)
            except aiohttp.ClientResponseError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Claude CLI",
                    data={
                        CONF_BRIDGE_URL: bridge_url,
                        CONF_SHARED_SECRET: shared_secret,
                    },
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "data": DEFAULT_CONVERSATION_OPTIONS,
                            "title": DEFAULT_CONVERSATION_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "ai_task_data",
                            "data": DEFAULT_AI_TASK_OPTIONS,
                            "title": DEFAULT_AI_TASK_NAME,
                            "unique_id": None,
                        },
                    ],
                )

        return self.async_show_form(
            step_id="hassio_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_SHARED_SECRET): str}
            ),
            errors=errors or None,
            description_placeholders={"addon": "Claude CLI"},
        )

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup.

        Args:
            user_input: User-provided bridge URL and secret, or None.

        Returns:
            Config flow result with entry creation or form.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            bridge_url = user_input[CONF_BRIDGE_URL].rstrip("/")
            shared_secret = user_input[CONF_SHARED_SECRET]

            if not bridge_url.startswith(("http://", "https://")):
                errors["base"] = "invalid_url"
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors=errors,
                )

            self._async_abort_entries_match({CONF_BRIDGE_URL: bridge_url})

            try:
                await _validate_bridge(bridge_url, shared_secret)
            except aiohttp.ClientResponseError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Claude CLI",
                    data={
                        CONF_BRIDGE_URL: bridge_url,
                        CONF_SHARED_SECRET: shared_secret,
                    },
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "data": DEFAULT_CONVERSATION_OPTIONS,
                            "title": DEFAULT_CONVERSATION_NAME,
                            "unique_id": None,
                        },
                        {
                            "subentry_type": "ai_task_data",
                            "data": DEFAULT_AI_TASK_OPTIONS,
                            "title": DEFAULT_AI_TASK_NAME,
                            "unique_id": None,
                        },
                    ],
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors or None,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ClaudeCLIConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types.

        Args:
            config_entry: The config entry to get subentry types for.

        Returns:
            Mapping of subentry type names to flow classes.
        """
        return {
            "conversation": ClaudeCLISubentryFlow,
            "ai_task_data": ClaudeCLISubentryFlow,
        }


class ClaudeCLISubentryFlow(ConfigSubentryFlow):
    """Flow for managing Claude CLI subentries."""

    options: dict[str, str | bool | list[str]]

    @property
    def _is_new(self) -> bool:
        """Return True if this is a new subentry (not reconfigure)."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, str | bool | list[str]] | None = None
    ) -> SubentryFlowResult:
        """Add a subentry.

        Args:
            user_input: User-provided data, or None.

        Returns:
            Subentry flow result directing to init step.
        """
        if self._subentry_type == "ai_task_data":
            self.options = dict(DEFAULT_AI_TASK_OPTIONS)
        else:
            self.options = dict(DEFAULT_CONVERSATION_OPTIONS)
        return await self.async_step_init()

    async def async_step_reconfigure(
        self, user_input: dict[str, str | bool | list[str]] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure a subentry.

        Args:
            user_input: User-provided data, or None.

        Returns:
            Subentry flow result directing to init step.
        """
        self.options = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_init()

    async def async_step_init(
        self, user_input: dict[str, str | bool | list[str]] | None = None
    ) -> SubentryFlowResult:
        """Set initial options.

        Args:
            user_input: User-provided configuration, or None for form display.

        Returns:
            Subentry flow result with form or next step.
        """
        if self._get_entry().state != ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        hass_apis: list[SelectOptionDict] = [
            SelectOptionDict(label=api.name, value=api.id)
            for api in llm.async_get_apis(self.hass)
        ]
        if suggested_llm_apis := self.options.get(CONF_LLM_HASS_API):
            if isinstance(suggested_llm_apis, str):
                suggested_llm_apis = [suggested_llm_apis]
            known_api_ids = {
                api.id for api in llm.async_get_apis(self.hass)
            }
            self.options[CONF_LLM_HASS_API] = [
                api_id
                for api_id in suggested_llm_apis
                if api_id in known_api_ids
            ]

        step_schema: VolDictType = {}

        if self._is_new:
            default_name = (
                DEFAULT_AI_TASK_NAME
                if self._subentry_type == "ai_task_data"
                else DEFAULT_CONVERSATION_NAME
            )
            step_schema[vol.Required(CONF_NAME, default=default_name)] = str

        if self._subentry_type == "conversation":
            step_schema.update(
                {
                    vol.Optional(CONF_PROMPT): TemplateSelector(),
                    vol.Optional(CONF_LLM_HASS_API): SelectSelector(
                        SelectSelectorConfig(
                            options=hass_apis, multiple=True
                        )
                    ),
                }
            )

        step_schema[
            vol.Required(
                CONF_RECOMMENDED,
                default=self.options.get(CONF_RECOMMENDED, False),
            )
        ] = bool

        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)

            if user_input[CONF_RECOMMENDED]:
                if self._is_new:
                    return self.async_create_entry(
                        title=user_input.pop(CONF_NAME),
                        data=user_input,
                    )
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    data=user_input,
                )

            self.options.update(user_input)
            if (
                CONF_LLM_HASS_API in self.options
                and CONF_LLM_HASS_API not in user_input
            ):
                self.options.pop(CONF_LLM_HASS_API)
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(step_schema), self.options
            ),
        )

    async def async_step_advanced(
        self, user_input: dict[str, str] | None = None
    ) -> SubentryFlowResult:
        """Manage advanced options.

        Args:
            user_input: User-provided advanced settings, or None for form.

        Returns:
            Subentry flow result with entry creation or form.
        """
        model_options = [
            SelectOptionDict(label=hint.capitalize(), value=hint)
            for hint in MODEL_HINTS
        ]

        step_schema: VolDictType = {
            vol.Optional(
                CONF_MODEL_HINT,
                default=self.options.get(CONF_MODEL_HINT, "auto"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=model_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        if user_input is not None:
            self.options.update(user_input)
            if self._is_new:
                return self.async_create_entry(
                    title=self.options.pop(CONF_NAME),
                    data=self.options,
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self.options,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(step_schema), self.options
            ),
            last_step=True,
        )
