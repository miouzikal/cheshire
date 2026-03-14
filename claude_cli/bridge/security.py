"""Security utilities for the bridge server.

Handles shared secret generation, storage, and request authentication.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
import tempfile
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)

SECRET_FILE_PATH = Path("/data/shared_secret")
SECRET_LENGTH_BYTES = 32


def generate_shared_secret() -> str:
    """Generate a cryptographically random shared secret.

    Returns:
        Hex-encoded string of SECRET_LENGTH_BYTES random bytes.
    """
    return secrets.token_hex(SECRET_LENGTH_BYTES)


def load_or_create_secret() -> str:
    """Load the shared secret created by run.sh at startup.

    The secret file is created by the entrypoint script (as root) before
    the bridge starts as the claude user. This function only reads it.

    Returns:
        The shared secret as a hex string.

    Raises:
        FileNotFoundError: If the secret file does not exist.
    """
    if SECRET_FILE_PATH.exists():
        secret = SECRET_FILE_PATH.read_text().strip()
        if len(secret) >= SECRET_LENGTH_BYTES * 2:
            logger.info("Loaded shared secret")
            return secret

    # Secret should have been created by run.sh — fatal if missing
    raise FileNotFoundError(
        f"Shared secret not found at {SECRET_FILE_PATH}. "
        "The entrypoint script (run.sh) should create it before starting the bridge."
    )


def verify_token(provided_token: str, expected_secret: str) -> bool:
    """Compare tokens using constant-time comparison to prevent timing attacks.

    Args:
        provided_token: The token from the Authorization header.
        expected_secret: The stored shared secret.

    Returns:
        True if the tokens match.
    """
    return hmac.compare_digest(provided_token.encode(), expected_secret.encode())


def auth_middleware(shared_secret: str) -> web.middleware:
    """Create aiohttp middleware that enforces Bearer token authentication.

    Args:
        shared_secret: The expected shared secret.

    Returns:
        An aiohttp middleware function.
    """

    @web.middleware
    async def middleware(
        request: web.Request,
        handler: web.RequestHandler,
    ) -> web.StreamResponse:
        authorization = request.headers.get("Authorization", "")

        # For /health, skip auth enforcement but flag whether authenticated
        if request.path == "/health":
            authenticated = False
            if authorization.startswith("Bearer "):
                token = authorization[7:]
                authenticated = verify_token(token, shared_secret)
            request["authenticated_request"] = authenticated
            return await handler(request)

        if not authorization.startswith("Bearer "):
            logger.warning(
                "Request without Bearer token from %s %s",
                request.method,
                request.path,
            )
            return web.json_response(
                {"error": "Missing or invalid Authorization header"},
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = authorization[7:]

        if not verify_token(token, shared_secret):
            logger.warning(
                "Invalid token in request from %s %s",
                request.method,
                request.path,
            )
            return web.json_response(
                {"error": "Invalid authentication token"},
                status=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        request["authenticated_request"] = True
        return await handler(request)

    return middleware
