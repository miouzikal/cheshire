"""Conversation platform for Claude CLI."""

from __future__ import annotations

from typing import Literal

import aiohttp

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ClaudeCLIConfigEntry, ClaudeCLIRuntimeData
from .const import CONF_PROMPT, DOMAIN, LOGGER
from .entity import ClaudeCLIBaseLLMEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ClaudeCLIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities from subentries.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "conversation":
            continue
        async_add_entities(
            [ClaudeCLIConversationEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class ClaudeCLIConversationEntity(
    conversation.ConversationEntity,
    ClaudeCLIBaseLLMEntity,
):
    """Claude CLI conversation agent."""

    _attr_supports_streaming = False
    _attr_translation_key = "conversation"

    def __init__(
        self, entry: ClaudeCLIConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the agent.

        Args:
            entry: The parent config entry.
            subentry: The conversation subentry configuration.
        """
        super().__init__(entry, subentry)
        if self.subentry.data.get(CONF_LLM_HASS_API):
            self._attr_supported_features = (
                conversation.ConversationEntityFeature.CONTROL
            )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Process a conversation message via the bridge API.

        Args:
            user_input: The user's conversation input.
            chat_log: The conversation chat log for context.

        Returns:
            ConversationResult with the assistant's response.
        """
        options = self.subentry.data

        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                options.get(CONF_LLM_HASS_API),
                options.get(CONF_PROMPT),
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as converse_error:
            return converse_error.as_conversation_result()

        # Build system prompt from chat log
        system_prompt = None
        if chat_log.content and isinstance(
            chat_log.content[0], conversation.SystemContent
        ):
            system_prompt = chat_log.content[0].content

        runtime: ClaudeCLIRuntimeData = self.entry.runtime_data

        try:
            async with runtime.session.post(
                f"{runtime.bridge_url}/converse",
                headers={
                    "Authorization": f"Bearer {runtime.shared_secret}"
                },
                json={
                    "message_text": user_input.text,
                    "conversation_session_id": chat_log.conversation_id,
                    "model_hint": self._model_hint,
                    "system_prompt": system_prompt,
                },
                timeout=aiohttp.ClientTimeout(
                    total=runtime.request_timeout_seconds + 30
                ),
            ) as response:
                if response.status != 200:
                    error_body = await response.text()
                    LOGGER.error(
                        "Bridge converse error (%d): %s",
                        response.status,
                        error_body,
                    )
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="bridge_error",
                        translation_placeholders={"status": str(response.status)},
                    )
                result = await response.json()
        except (aiohttp.ClientError, TimeoutError) as error:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_unreachable",
            ) from error

        response_text = result.get("response_text", "")

        # Add assistant response to chat log
        chat_log.async_add_assistant_content(
            conversation.AssistantContent(
                agent_id=self.entity_id,
                content=response_text,
            )
        )

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
