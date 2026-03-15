"""HTTP bridge server for the Claude CLI addon.

Exposes the Claude Code CLI via a REST API for consumption by
the Home Assistant custom component.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict

# Ensure sibling modules are importable when run as `python3 /opt/bridge/server.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiohttp import web

from claude_client import SessionPool, one_shot_query
from models import (
    ConfiguredModels,
    ConverseRequest,
    ConverseResponse,
    EnvironmentResponse,
    HealthResponse,
    McpServerInfo,
    PermissionsSummary,
    ReloadResponse,
    TaskRequest,
    TaskResponse,
)
from security import auth_middleware, load_shared_secret, rate_limit_middleware

logger = logging.getLogger(__name__)

ADDON_VERSION = os.environ.get("ADDON_VERSION", "unknown")
MAX_REQUEST_SIZE = 512 * 1024  # 512KB
ENVIRONMENT_DIR = Path("/data/claude_environment")
OPTIONS_PATH = Path("/data/options.json")

SAFE_OPTION_KEYS = frozenset({
    "fast_model",
    "default_model",
    "smart_model",
    "max_output_tokens",
    "max_thinking_tokens",
    "disable_telemetry",
    "request_timeout_seconds",
    "max_tool_iterations",
    "log_level",
})

VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})

# UUID v4 pattern for session ID validation
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Model name validation: alphanumeric, dots, hyphens, underscores
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")

_CLI_ENV: dict[str, str] = {
    "HOME": os.environ.get("HOME", "/data"),
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "DISABLE_AUTOUPDATER": "1",
}

# Pass through API key if set (needed for `claude auth status` to detect API key auth)
_api_key = os.environ.get("ANTHROPIC_API_KEY")
if _api_key:
    _CLI_ENV["ANTHROPIC_API_KEY"] = _api_key


class CliAuthStatus(TypedDict):
    """Authentication status returned by `claude auth status --json`."""

    loggedIn: bool
    authMethod: str
    email: str
    subscriptionType: str


def _load_options() -> dict[str, str | int | bool]:
    """Load addon options from /data/options.json.

    Returns:
        Dictionary of addon configuration options.
    """
    if OPTIONS_PATH.exists():
        try:
            return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error("Failed to parse %s: %s", OPTIONS_PATH, e)
    return {}


def _get_configured_models(
    options: dict[str, str | int | bool],
) -> ConfiguredModels:
    """Extract configured model names from addon options.

    Args:
        options: The addon configuration options.

    Returns:
        Mapping of model tier names to model identifiers.
    """
    return ConfiguredModels(
        fast=str(options.get("fast_model", "claude-haiku-4-5")),
        default=str(options.get("default_model", "claude-sonnet-4-6")),
        smart=str(options.get("smart_model", "claude-opus-4-6")),
    )


def _get_cli_auth_status() -> CliAuthStatus:
    """Get Claude CLI authentication status via `claude auth status --json`.

    Returns:
        Authentication status with login state, method, email, and subscription.
    """
    try:
        result = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            env=_CLI_ENV,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as error:
        logger.warning("Failed to get CLI auth status: %s", error)
    return CliAuthStatus(
        loggedIn=False,
        authMethod="unknown",
        email="",
        subscriptionType="",
    )


def _get_cli_version() -> str:
    """Get Claude CLI version string.

    Returns:
        Version string, or 'unknown' if not available.
    """
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            env=_CLI_ENV,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        logger.debug("Failed to get CLI version: %s", error)
    return "unknown"


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file, or return empty string if not found.

    Reads in chunks to avoid unbounded memory allocation.

    Args:
        file_path: Path to the file to hash.

    Returns:
        First 16 characters of the SHA-256 hex digest, or empty string.
    """
    if not file_path.exists():
        return ""
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _list_commands() -> list[str]:
    """List command files in the .claude/commands/ directory.

    Returns:
        Sorted list of command names (file stems).
    """
    commands_dir = ENVIRONMENT_DIR / ".claude" / "commands"
    if not commands_dir.exists():
        return []
    return [
        command_path.stem
        for command_path in sorted(commands_dir.glob("*.md"))
        if command_path.is_file()
    ]


def _read_mcp_config() -> list[McpServerInfo]:
    """Read MCP server configuration from mcp.json.

    Returns:
        List of MCP server info records.
    """
    mcp_path = ENVIRONMENT_DIR / "mcp.json"
    if not mcp_path.exists():
        return []
    try:
        config = json.loads(mcp_path.read_text(encoding="utf-8"))
        servers = config.get("mcpServers", {})
        return [
            McpServerInfo(name=server_name, status="configured")
            for server_name in servers
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def _read_permissions() -> PermissionsSummary:
    """Read permissions from .claude/settings.json.

    Returns:
        Permissions summary with allow and deny lists.
    """
    settings_path = ENVIRONMENT_DIR / ".claude" / "settings.json"
    if not settings_path.exists():
        return PermissionsSummary(allow=[], deny=[])
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8")).get("permissions", {})
        return PermissionsSummary(
            allow=raw.get("allow", []),
            deny=raw.get("deny", []),
        )
    except (json.JSONDecodeError, AttributeError):
        return PermissionsSummary(allow=[], deny=[])


def _check_sshd() -> bool:
    """Check if sshd is reachable by probing TCP port 22.

    Returns:
        True if sshd accepts connections, False otherwise.
    """
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=2):
            return True
    except (OSError, TimeoutError):
        return False


VALID_MODEL_HINTS = frozenset({"auto", "fast", "default", "smart"})

_MODEL_TIER_MAP = {"fast": "fast_model", "default": "default_model", "smart": "smart_model"}


def _resolve_model(
    model_hint: str | None,
    options: dict[str, str | int | bool],
) -> str:
    """Resolve a model hint (fast/default/smart) to a model name.

    Only accepts known tier hints. Unknown hints fall back to the
    default model to prevent arbitrary strings reaching the SDK.

    Args:
        model_hint: The model tier hint from the request.
        options: Addon configuration options.

    Returns:
        Resolved model identifier string.
    """
    default_model = str(options.get("default_model", "claude-sonnet-4-6"))
    if not model_hint or model_hint == "auto":
        return default_model
    if model_hint not in VALID_MODEL_HINTS:
        logger.warning(
            "Unknown model hint '%s', falling back to default", model_hint
        )
        return default_model
    option_key = _MODEL_TIER_MAP.get(model_hint)
    if option_key:
        resolved = str(options.get(option_key, default_model))
        if not _MODEL_NAME_RE.match(resolved):
            logger.warning("Invalid model name '%s', falling back to default", resolved)
            return default_model
        return resolved
    return default_model


def _build_pool_options(
    options: dict[str, str | int | bool],
) -> dict[str, str | int | bool]:
    """Build default options dict for the session pool.

    Args:
        options: Addon configuration options.

    Returns:
        Options dict suitable for SessionPool default_options.
    """
    mcp_path = ENVIRONMENT_DIR / "mcp.json"
    pool_options: dict[str, str | int | bool] = {
        "cwd": str(ENVIRONMENT_DIR),
        "max_turns": int(options.get("max_tool_iterations", 10)),
    }
    if mcp_path.exists():
        pool_options["mcp_config"] = str(mcp_path)
    return pool_options


def _validate_session_id(session_id: str | None) -> str | None:
    """Validate that a session ID matches UUID v4 format.

    Args:
        session_id: The session ID from the request, or None.

    Returns:
        The validated session ID, or None if invalid/missing.
    """
    if session_id is None:
        return None
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        logger.warning("Invalid session_id format, ignoring: %s", session_id[:50])
        return None
    return session_id


class BridgeServer:
    """HTTP bridge server managing Claude Code CLI interactions."""

    def __init__(self) -> None:
        """Initialize the bridge server."""
        self._options: dict[str, str | int | bool] = _load_options()
        self._session_pool = SessionPool(
            max_sessions=50,
            idle_timeout=300,
            default_options=_build_pool_options(self._options),
        )

    async def startup(self, application: web.Application) -> None:
        """Start session pool on app startup.

        Args:
            application: The aiohttp application instance.
        """
        await self._session_pool.start()

    async def shutdown(self, application: web.Application) -> None:
        """Stop session pool on app shutdown.

        Args:
            application: The aiohttp application instance.
        """
        await self._session_pool.stop(drain_timeout=10)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health — return addon and CLI status.

        When accessed without authentication (watchdog), returns only
        non-sensitive status. When authenticated, returns full details.

        Args:
            request: The incoming HTTP request.

        Returns:
            JSON response with health status.
        """
        # Check if request is authenticated (set by security middleware)
        is_authenticated = request.get("authenticated_request", False)

        sshd_alive = await asyncio.to_thread(_check_sshd)

        if not is_authenticated:
            # Only report degraded if SSH keys were configured (sshd expected)
            ssh_keys = self._options.get("ssh_authorized_keys", [])
            sshd_expected = isinstance(ssh_keys, list) and len(ssh_keys) > 0
            if sshd_expected and not sshd_alive:
                return web.json_response(
                    {"status": "degraded", "sshd": "dead"},
                    status=503,
                )
            return web.json_response({"status": "ok"})

        auth_status, cli_version = await asyncio.gather(
            asyncio.to_thread(_get_cli_auth_status),
            asyncio.to_thread(_get_cli_version),
        )

        response = HealthResponse(
            addon_version=ADDON_VERSION,
            cli_version=cli_version,
            authenticated=auth_status.get("loggedIn", False),
            auth_method=auth_status.get("authMethod", "unknown"),
            email=auth_status.get("email", ""),
            subscription_type=auth_status.get("subscriptionType", ""),
            active_sessions=self._session_pool.active_session_count,
            configured_models=_get_configured_models(self._options),
            mcp_servers=_read_mcp_config(),
            request_timeout_seconds=int(
                self._options.get("request_timeout_seconds", 120)
            ),
            sshd=("running" if sshd_alive else "dead"),
        )
        return web.json_response(asdict(response))

    async def handle_converse(self, request: web.Request) -> web.Response:
        """Handle POST /converse — multi-turn conversation with Claude.

        Args:
            request: The incoming HTTP request with conversation data.

        Returns:
            JSON response with conversation result.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        system_prompt = body.get("system_prompt")
        if system_prompt is not None:
            if not isinstance(system_prompt, str) or len(system_prompt) > 10_000:
                return web.json_response(
                    {"error": "system_prompt must be a string under 10KB"},
                    status=400,
                )

        converse_request = ConverseRequest(
            message_text=body.get("message_text", ""),
            conversation_session_id=_validate_session_id(
                body.get("conversation_session_id")
            ),
            model_hint=body.get("model_hint"),
            system_prompt=system_prompt,
        )

        if not converse_request.message_text.strip():
            return web.json_response(
                {"error": "message_text is required"}, status=400
            )

        if len(converse_request.message_text) > 100_000:
            return web.json_response(
                {"error": "message_text too long"}, status=413
            )

        model = _resolve_model(converse_request.model_hint, self._options)
        request_timeout = int(
            self._options.get("request_timeout_seconds", 120)
        )

        try:
            result = await self._session_pool.converse(
                prompt=converse_request.message_text,
                session_id=converse_request.conversation_session_id,
                model=model,
                system_prompt=converse_request.system_prompt,
                timeout=request_timeout,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Converse request failed")
            return web.json_response({"error": "Internal error"}, status=500)

        response = ConverseResponse(
            response_text=result.response_text,
            conversation_session_id=result.session_id,
            model_used=result.model_used,
            tool_calls_requested=result.tool_calls,
            latency_milliseconds=result.latency_ms,
        )
        return web.json_response(asdict(response))

    async def handle_task(self, request: web.Request) -> web.Response:
        """Handle POST /task — one-shot structured generation.

        Args:
            request: The incoming HTTP request with task data.

        Returns:
            JSON response with generated content.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        task_request = TaskRequest(
            task_prompt=body.get("task_prompt", ""),
            model_hint=body.get("model_hint"),
        )

        if not task_request.task_prompt.strip():
            return web.json_response(
                {"error": "task_prompt is required"}, status=400
            )

        if len(task_request.task_prompt) > 100_000:
            return web.json_response(
                {"error": "task_prompt too long"}, status=413
            )

        model = _resolve_model(task_request.model_hint, self._options)
        request_timeout = int(
            self._options.get("request_timeout_seconds", 120)
        )

        try:
            mcp_path = ENVIRONMENT_DIR / "mcp.json"
            result = await one_shot_query(
                prompt=task_request.task_prompt,
                model=model,
                cwd=str(ENVIRONMENT_DIR),
                max_turns=int(self._options.get("max_tool_iterations", 10)),
                mcp_config=str(mcp_path) if mcp_path.exists() else None,
                timeout=request_timeout,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Task request failed")
            return web.json_response({"error": "Internal error"}, status=500)

        response = TaskResponse(
            generated_content=result.response_text,
            model_used=result.model_used,
            latency_milliseconds=result.latency_ms,
        )
        return web.json_response(asdict(response))

    async def handle_environment(self, request: web.Request) -> web.Response:
        """Handle GET /environment — current environment state.

        Args:
            request: The incoming HTTP request.

        Returns:
            JSON response with environment configuration details.
        """
        claude_md_path = ENVIRONMENT_DIR / "CLAUDE.md"
        claude_md_preview = ""
        if claude_md_path.exists():
            with claude_md_path.open(encoding="utf-8") as f:
                claude_md_preview = f.read(200)

        response = EnvironmentResponse(
            claude_md_hash=_compute_file_hash(claude_md_path),
            claude_md_preview=claude_md_preview,
            loaded_commands=_list_commands(),
            permissions_summary=_read_permissions(),
            mcp_servers=_read_mcp_config(),
            effective_options={
                option_key: option_value
                for option_key, option_value in self._options.items()
                if option_key in SAFE_OPTION_KEYS
            },
        )
        return web.json_response(asdict(response))

    async def handle_reload(self, request: web.Request) -> web.Response:
        """Handle POST /reload — reload config files from disk.

        Args:
            request: The incoming HTTP request.

        Returns:
            JSON response with reload status and any errors.
        """
        error_messages: list[str] = []

        claude_md_path = ENVIRONMENT_DIR / "CLAUDE.md"
        if not claude_md_path.exists():
            error_messages.append("CLAUDE.md not found")

        settings_path = ENVIRONMENT_DIR / ".claude" / "settings.json"
        if settings_path.exists():
            try:
                json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as parse_error:
                error_messages.append(f"settings.json parse error: {parse_error}")

        mcp_path = ENVIRONMENT_DIR / "mcp.json"
        if mcp_path.exists():
            try:
                json.loads(mcp_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as parse_error:
                error_messages.append(f"mcp.json parse error: {parse_error}")

        self._options = _load_options()
        self._session_pool.update_default_options(
            _build_pool_options(self._options)
        )

        response = ReloadResponse(
            success=len(error_messages) == 0,
            claude_md_hash=_compute_file_hash(claude_md_path),
            command_count=len(_list_commands()),
            mcp_server_count=len(_read_mcp_config()),
            error_messages=error_messages,
        )
        return web.json_response(asdict(response))


def create_application(shared_secret: str) -> web.Application:
    """Create and configure the aiohttp application.

    Args:
        shared_secret: The shared secret for Bearer token auth.

    Returns:
        Configured aiohttp Application.
    """
    application = web.Application(
        middlewares=[rate_limit_middleware(), auth_middleware(shared_secret)],
        client_max_size=MAX_REQUEST_SIZE,
    )

    bridge = BridgeServer()

    application.on_startup.append(bridge.startup)
    application.on_shutdown.append(bridge.shutdown)

    application.router.add_get("/health", bridge.handle_health)
    application.router.add_post("/converse", bridge.handle_converse)
    application.router.add_post("/task", bridge.handle_task)
    application.router.add_get("/environment", bridge.handle_environment)
    application.router.add_post("/reload", bridge.handle_reload)

    return application


def main() -> None:
    """Entry point for the bridge server."""
    options = _load_options()
    log_level_name = str(options.get("log_level", "info")).upper()
    if log_level_name not in VALID_LOG_LEVELS:
        log_level_name = "INFO"

    logging.basicConfig(
        level=getattr(logging, log_level_name, logging.INFO),
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    shared_secret = load_shared_secret()
    application = create_application(shared_secret)

    port = 8099
    logger.info("Starting bridge server on port %d", port)
    web.run_app(application, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
