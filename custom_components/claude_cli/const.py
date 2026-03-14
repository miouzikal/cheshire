"""Constants for the Claude CLI integration."""

import logging

DOMAIN = "claude_cli"
LOGGER = logging.getLogger(__package__)

DEFAULT_CONVERSATION_NAME = "Claude CLI conversation"
DEFAULT_AI_TASK_NAME = "Claude CLI AI Task"

CONF_BRIDGE_URL = "bridge_url"
CONF_SHARED_SECRET = "shared_secret"
CONF_MODEL_HINT = "model_hint"
CONF_PROMPT = "prompt"
CONF_RECOMMENDED = "recommended"

DEFAULT_BRIDGE_URL = "http://localhost:8099"

MODEL_HINTS = ["auto", "fast", "default", "smart"]
