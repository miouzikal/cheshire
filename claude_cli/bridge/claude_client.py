"""Claude Code SDK wrapper with session pool for low-latency conversations.

Provides two interaction modes:
- SessionPool: warm ClaudeSDKClient instances for multi-turn conversations
- one_shot_query(): stateless query() calls for ai_task generation
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from models import ToolCallRecord

logger = logging.getLogger(__name__)

DEFAULT_IDLE_TIMEOUT = 300  # 5 minutes
DEFAULT_MAX_SESSIONS = 50


@dataclass
class SessionResult:
    """Result from a conversation turn or one-shot query."""

    response_text: str
    session_id: str
    model_used: str
    tool_calls: list[ToolCallRecord]
    latency_ms: int
    is_error: bool = False


@dataclass
class _ManagedSession:
    """Internal wrapper around a ClaudeSDKClient with lifecycle tracking."""

    client: ClaudeSDKClient
    session_id: str
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    turn_count: int = 0
    in_use: bool = False

    def touch(self) -> None:
        """Update last-used timestamp."""
        self.last_used = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        """Seconds since last use."""
        return time.monotonic() - self.last_used


def _build_options(
    default_options: dict[str, str | int | bool],
    *,
    model: str | None = None,
    system_prompt: str | None = None,
) -> ClaudeCodeOptions:
    """Build ClaudeCodeOptions from defaults plus per-request overrides.

    Args:
        default_options: Base options from addon configuration.
        model: Model identifier override for this request.
        system_prompt: System prompt to append for this request.

    Returns:
        Configured ClaudeCodeOptions instance.
    """
    option_arguments: dict[str, str | int | bool | dict[str, str]] = {
        "permission_mode": "allowEdits",
    }

    if default_options.get("cwd"):
        option_arguments["cwd"] = default_options["cwd"]
    if default_options.get("env"):
        option_arguments["env"] = default_options["env"]
    if default_options.get("max_turns"):
        option_arguments["max_turns"] = default_options["max_turns"]

    # MCP servers config file
    mcp_config_path = default_options.get("mcp_config")
    if mcp_config_path and Path(str(mcp_config_path)).exists():
        option_arguments["mcp_servers"] = mcp_config_path

    if model:
        option_arguments["model"] = model
    elif default_options.get("model"):
        option_arguments["model"] = default_options["model"]

    if system_prompt:
        option_arguments["append_system_prompt"] = system_prompt

    return ClaudeCodeOptions(**option_arguments)


def _collect_content(
    message: AssistantMessage,
    text_parts: list[str],
    tool_calls: list[ToolCallRecord],
) -> str:
    """Extract text and tool calls from an AssistantMessage.

    Args:
        message: The assistant message to extract content from.
        text_parts: Accumulator list for text content blocks.
        tool_calls: Accumulator list for tool call records.

    Returns:
        The model identifier string from the message.
    """
    model_used = message.model or ""
    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                ToolCallRecord(id=block.id, name=block.name, input=block.input)
            )
    return model_used


class SessionPool:
    """Manages warm ClaudeSDKClient instances for low-latency conversation.

    Each conversation session keeps a persistent CLI subprocess alive,
    eliminating the ~37ms cold-start on subsequent turns.

    Concurrency model:
    - self._lock protects dict mutations only (short critical sections)
    - connect()/disconnect() happen OUTSIDE the lock to avoid blocking
    - in_use flag prevents cleanup from evicting active sessions
    """

    def __init__(
        self,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        default_options: dict[str, str | int | bool] | None = None,
    ) -> None:
        """Initialize the session pool.

        Args:
            max_sessions: Maximum number of concurrent sessions.
            idle_timeout: Seconds before an idle session is closed.
            default_options: Default SDK options for new sessions.
        """
        self._sessions: dict[str, _ManagedSession] = {}
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout
        self._default_options: dict[str, str | int | bool] = default_options or {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(
                "Session pool started (max=%d, idle_timeout=%ds)",
                self._max_sessions,
                self._idle_timeout,
            )

    async def stop(self) -> None:
        """Stop cleanup and disconnect all sessions."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Collect all clients to disconnect, then disconnect outside lock
        async with self._lock:
            sessions_to_disconnect = list(self._sessions.values())
            self._sessions.clear()

        for managed_session in sessions_to_disconnect:
            await self._safe_disconnect(managed_session)

        logger.info("Session pool stopped, all sessions closed")

    async def converse(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        timeout: int = 120,
    ) -> SessionResult:
        """Send a message in a conversation session.

        If session_id is provided and a warm session exists, reuses it.
        Otherwise creates a new session. Returns the full response.

        Args:
            prompt: The user message text.
            session_id: Existing session to continue, or None for new.
            model: Model identifier override.
            system_prompt: System prompt to append.
            timeout: Maximum seconds to wait for response.

        Returns:
            SessionResult with response text, model info, and tool calls.
        """
        start_time = time.monotonic()

        if session_id is None:
            session_id = str(uuid.uuid4())

        # Try to get existing session under lock
        evicted_session: _ManagedSession | None = None
        need_new = False

        async with self._lock:
            managed_session = self._sessions.get(session_id)
            if managed_session is not None:
                managed_session.touch()
                managed_session.turn_count += 1
                managed_session.in_use = True
                logger.debug(
                    "Reusing warm session %s (turn %d)",
                    session_id,
                    managed_session.turn_count,
                )
            else:
                need_new = True
                # Check capacity and evict LRU if needed
                if len(self._sessions) >= self._max_sessions:
                    evicted_session = self._pop_least_recently_used()
                    if evicted_session is None and len(self._sessions) >= self._max_sessions:
                        raise RuntimeError("Session pool exhausted — all sessions in use")

        # Disconnect evicted client OUTSIDE lock
        if evicted_session is not None:
            await self._safe_disconnect(evicted_session)

        if need_new:
            # Create and connect new client OUTSIDE lock
            options = _build_options(
                self._default_options, model=model, system_prompt=system_prompt
            )
            client = ClaudeSDKClient(options)
            await client.connect()

            new_managed_session = _ManagedSession(
                client=client, session_id=session_id, in_use=True
            )

            async with self._lock:
                # Check if another request created this session while we were connecting
                existing_session = self._sessions.get(session_id)
                if existing_session is not None:
                    # Another request won the race — discard our new client
                    existing_session.touch()
                    existing_session.turn_count += 1
                    existing_session.in_use = True
                    managed_session = existing_session
                    # Disconnect the duplicate outside lock
                    task = asyncio.create_task(self._safe_disconnect(new_managed_session))
                    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    logger.debug(
                        "Session %s created by concurrent request, reusing",
                        session_id,
                    )
                else:
                    managed_session = new_managed_session
                    self._sessions[session_id] = managed_session
                    logger.info("Created new session %s", session_id)

        try:
            return await self._send_and_collect(
                managed_session, prompt, timeout=timeout, start_time=start_time
            )
        finally:
            async with self._lock:
                if session_id in self._sessions:
                    self._sessions[session_id].in_use = False
                    self._sessions[session_id].touch()

    async def close_session(self, session_id: str) -> bool:
        """Explicitly close a session.

        Args:
            session_id: The session identifier to close.

        Returns:
            True if the session existed and was closed.
        """
        async with self._lock:
            managed_session = self._sessions.pop(session_id, None)

        if managed_session is not None:
            await self._safe_disconnect(managed_session)
            return True
        return False

    def update_default_options(self, options: dict[str, str | int | bool]) -> None:
        """Update default options (e.g., after config reload).

        Args:
            options: New default options to apply to future sessions.
        """
        self._default_options = options

    @property
    def active_session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)

    async def _send_and_collect(
        self,
        managed_session: _ManagedSession,
        prompt: str,
        *,
        timeout: int,
        start_time: float,
    ) -> SessionResult:
        """Send prompt and collect the full response.

        Args:
            managed_session: The session to send the prompt to.
            prompt: The user message text.
            timeout: Maximum seconds to wait.
            start_time: Monotonic timestamp when the request started.

        Returns:
            SessionResult with the collected response.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCallRecord] = []
        model_used = ""
        cli_session_id = managed_session.session_id
        is_error = False

        try:
            async with asyncio.timeout(timeout):
                await managed_session.client.query(prompt)
                async for message in managed_session.client.receive_response():
                    if isinstance(message, AssistantMessage):
                        model_used = (
                            _collect_content(message, text_parts, tool_calls)
                            or model_used
                        )
                    elif isinstance(message, ResultMessage):
                        cli_session_id = message.session_id or cli_session_id
                        is_error = message.is_error

        except TimeoutError:
            logger.warning(
                "Session %s timed out after %ds",
                managed_session.session_id,
                timeout,
            )
            await self._remove_and_disconnect(managed_session.session_id)
            return SessionResult(
                response_text="Request timed out.",
                session_id=managed_session.session_id,
                model_used=model_used,
                tool_calls=[],
                latency_ms=int((time.monotonic() - start_time) * 1000),
                is_error=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error in session %s", managed_session.session_id)
            await self._remove_and_disconnect(managed_session.session_id)
            raise

        return SessionResult(
            response_text="\n".join(text_parts),
            session_id=cli_session_id,
            model_used=model_used,
            tool_calls=tool_calls,
            latency_ms=int((time.monotonic() - start_time) * 1000),
            is_error=is_error,
        )

    def _pop_least_recently_used(self) -> _ManagedSession | None:
        """Pop the least-recently-used non-in-use session. Must hold lock.

        Returns:
            The evicted session, or None if all sessions are in use.
        """
        candidates = [
            (session_identifier, session)
            for session_identifier, session in self._sessions.items()
            if not session.in_use
        ]
        if not candidates:
            return None
        oldest_identifier = min(
            candidates, key=lambda candidate: candidate[1].last_used
        )[0]
        logger.info("Evicting idle session %s (LRU)", oldest_identifier)
        return self._sessions.pop(oldest_identifier)

    async def _remove_and_disconnect(self, session_id: str) -> None:
        """Remove session from pool under lock, then disconnect outside lock.

        Args:
            session_id: The session identifier to remove and disconnect.
        """
        async with self._lock:
            managed_session = self._sessions.pop(session_id, None)
        if managed_session is not None:
            await self._safe_disconnect(managed_session)

    @staticmethod
    async def _safe_disconnect(managed_session: _ManagedSession) -> None:
        """Disconnect a client, swallowing errors.

        Args:
            managed_session: The session to disconnect.
        """
        try:
            await asyncio.wait_for(managed_session.client.disconnect(), timeout=5.0)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Error disconnecting session %s",
                managed_session.session_id,
                exc_info=True,
            )

    async def _cleanup_loop(self) -> None:
        """Periodically close idle sessions."""
        while True:
            await asyncio.sleep(30)
            sessions_to_disconnect: list[_ManagedSession] = []

            async with self._lock:
                expired_identifiers = [
                    session_identifier
                    for session_identifier, session in self._sessions.items()
                    if not session.in_use
                    and session.idle_seconds > self._idle_timeout
                ]
                for session_identifier in expired_identifiers:
                    managed_session = self._sessions.pop(session_identifier)
                    sessions_to_disconnect.append(managed_session)
                    logger.info(
                        "Closing idle session %s (%.0fs idle)",
                        session_identifier,
                        managed_session.idle_seconds,
                    )

            # Disconnect outside lock
            for managed_session in sessions_to_disconnect:
                await self._safe_disconnect(managed_session)


async def one_shot_query(
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    max_turns: int | None = None,
    mcp_config: str | None = None,
    timeout: int = 120,
) -> SessionResult:
    """Execute a one-shot query (no session persistence).

    Used for ai_task structured generation where no multi-turn
    conversation is needed.

    Args:
        prompt: The task prompt text.
        model: Model identifier to use.
        system_prompt: System prompt to append.
        cwd: Working directory for the CLI process.
        env: Environment variables for the CLI process.
        max_turns: Maximum tool-use turns.
        mcp_config: Path to MCP server configuration file.
        timeout: Maximum seconds to wait for response.

    Returns:
        SessionResult with the generated content.
    """
    start_time = time.monotonic()

    option_arguments: dict[str, str | int | bool | dict[str, str]] = {
        "permission_mode": "allowEdits",
    }
    if model:
        option_arguments["model"] = model
    if system_prompt:
        option_arguments["append_system_prompt"] = system_prompt
    if cwd:
        option_arguments["cwd"] = cwd
    if env:
        option_arguments["env"] = env
    if max_turns:
        option_arguments["max_turns"] = max_turns
    if mcp_config and Path(mcp_config).exists():
        option_arguments["mcp_servers"] = mcp_config

    options = ClaudeCodeOptions(**option_arguments)

    text_parts: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    model_used = ""
    session_id = ""
    is_error = False

    try:
        async with asyncio.timeout(timeout):
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    model_used = (
                        _collect_content(message, text_parts, tool_calls) or model_used
                    )
                elif isinstance(message, ResultMessage):
                    session_id = message.session_id or session_id
                    is_error = message.is_error
    except TimeoutError:
        logger.warning("One-shot query timed out after %ds", timeout)
        return SessionResult(
            response_text="Request timed out.",
            session_id="",
            model_used=model_used,
            tool_calls=[],
            latency_ms=int((time.monotonic() - start_time) * 1000),
            is_error=True,
        )

    return SessionResult(
        response_text="\n".join(text_parts),
        session_id=session_id,
        model_used=model_used,
        tool_calls=tool_calls,
        latency_ms=int((time.monotonic() - start_time) * 1000),
        is_error=is_error,
    )
