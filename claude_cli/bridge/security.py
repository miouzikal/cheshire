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
    """Load existing shared secret or generate a new one.

    The secret is stored atomically (write to temp file, then rename)
    with mode 0600 to prevent other processes from reading it.

    Returns:
        The shared secret as a hex string.
    """
    if SECRET_FILE_PATH.exists():
        secret = SECRET_FILE_PATH.read_text().strip()
        if len(secret) >= SECRET_LENGTH_BYTES * 2:
            logger.info("Loaded existing shared secret from %s", SECRET_FILE_PATH)
            return secret
        logger.warning("Existing secret is too short, regenerating")

    secret = generate_shared_secret()

    SECRET_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor = None
    temp_path = None
    try:
        file_descriptor, temp_path = tempfile.mkstemp(
            dir=str(SECRET_FILE_PATH.parent),
            prefix=".secret_",
        )
        os.write(file_descriptor, secret.encode())
        os.fchmod(file_descriptor, stat.S_IRUSR | stat.S_IWUSR)
        os.close(file_descriptor)
        file_descriptor = None
        os.rename(temp_path, str(SECRET_FILE_PATH))
        temp_path = None
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)

    logger.info("Generated new shared secret at %s", SECRET_FILE_PATH)
    logger.info("To view it, run: cat %s", SECRET_FILE_PATH)

    return secret


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
        # Allow unauthenticated access to /health for watchdog probes
        if request.path == "/health":
            return await handler(request)

        authorization = request.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            logger.warning(
                "Request without Bearer token from %s %s",
                request.method,
                request.path,
            )
            return web.json_response(
                {"error": "Missing or invalid Authorization header"},
                status=401,
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
            )

        return await handler(request)

    return middleware
