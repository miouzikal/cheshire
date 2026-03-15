"""Request and response dataclasses for the bridge API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


class McpServerInfo(TypedDict):
    """Information about a configured MCP server."""

    name: str
    status: str


class ToolCallRecord(TypedDict):
    """Record of a tool call made during a conversation turn."""

    id: str
    name: str
    input: dict[str, object]


class ConfiguredModels(TypedDict):
    """Mapping of model tier names to model identifiers."""

    fast: str
    default: str
    smart: str


class PermissionsSummary(TypedDict):
    """Summary of tool permissions from settings.json."""

    allow: list[str]
    deny: list[str]


@dataclass
class HealthResponse:
    """Response from GET /health."""

    addon_version: str
    cli_version: str
    authenticated: bool
    auth_method: str
    email: str
    subscription_type: str
    active_sessions: int
    configured_models: ConfiguredModels
    mcp_servers: list[McpServerInfo]
    request_timeout_seconds: int
    sshd: str = "unknown"


@dataclass
class ConverseRequest:
    """Request body for POST /converse."""

    message_text: str
    conversation_session_id: str | None = None
    model_hint: str | None = None
    system_prompt: str | None = None


@dataclass
class ConverseResponse:
    """Response from POST /converse."""

    response_text: str
    conversation_session_id: str
    model_used: str
    tool_calls_requested: list[ToolCallRecord]
    latency_milliseconds: int


@dataclass
class TaskRequest:
    """Request body for POST /task."""

    task_prompt: str
    model_hint: str | None = None


@dataclass
class TaskResponse:
    """Response from POST /task."""

    generated_content: str
    model_used: str
    latency_milliseconds: int


@dataclass
class EnvironmentResponse:
    """Response from GET /environment."""

    claude_md_hash: str
    claude_md_preview: str
    loaded_commands: list[str]
    permissions_summary: PermissionsSummary
    mcp_servers: list[McpServerInfo]
    effective_options: dict[str, str | int | bool]


@dataclass
class ReloadResponse:
    """Response from POST /reload."""

    success: bool
    claude_md_hash: str
    command_count: int
    mcp_server_count: int
    error_messages: list[str] = field(default_factory=list)
