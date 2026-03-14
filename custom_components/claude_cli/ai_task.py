"""AI Task platform for Claude CLI."""

from __future__ import annotations

from json import JSONDecodeError
from typing import TYPE_CHECKING

import aiohttp

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from .const import DOMAIN, LOGGER
from .entity import ClaudeCLIBaseLLMEntity

if TYPE_CHECKING:
    from . import ClaudeCLIConfigEntry, ClaudeCLIRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ClaudeCLIConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI task entities from subentries.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [ClaudeCLITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class ClaudeCLITaskEntity(
    ai_task.AITaskEntity,
    ClaudeCLIBaseLLMEntity,
):
    """Claude CLI AI Task entity."""

    _attr_supported_features = ai_task.AITaskEntityFeature.GENERATE_DATA
    _attr_translation_key = "ai_task_data"

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task via the bridge API.

        Args:
            task: The generation task with instructions and optional schema.
            chat_log: The conversation chat log for context.

        Returns:
            GenDataTaskResult with the generated content.
        """
        runtime: ClaudeCLIRuntimeData = self.entry.runtime_data

        try:
            async with runtime.session.post(
                f"{runtime.bridge_url}/task",
                headers={
                    "Authorization": f"Bearer {runtime.shared_secret}"
                },
                json={
                    "task_prompt": task.instructions,
                    "model_hint": self._model_hint,
                },
                timeout=aiohttp.ClientTimeout(
                    total=runtime.request_timeout_seconds + 30
                ),
            ) as response:
                if response.status != 200:
                    error_body = await response.text()
                    LOGGER.error(
                        "Bridge task error (%d): %s",
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

        generated_text = result.get("generated_content", "")

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=generated_text,
            )

        try:
            parsed_data = json_loads(generated_text)
        except JSONDecodeError as parse_error:
            LOGGER.error(
                "Failed to parse JSON response: %s. Response: %s",
                parse_error,
                generated_text,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="structured_response_parse_error",
            ) from parse_error

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=parsed_data,
        )
