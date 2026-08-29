"""The paid gate: ak_ Bearer key resolution.

The key is read from an explicit argument or, failing that, the
``ARKLEON_API_KEY`` environment variable (contract section 6.2). The client
refuses to operate without an ak_-prefixed key, raising locally before any
network contact so an unauthenticated request is never sent. Keys are
presented, never stored or logged: nothing here writes the key to a file, a
log line, or an exception message.
"""

from __future__ import annotations

import os

from .errors import AuthError

__all__ = ["resolve_api_key", "optional_api_key", "API_KEY_ENV_VAR", "API_KEY_PREFIX"]

API_KEY_ENV_VAR = "ARKLEON_API_KEY"
API_KEY_PREFIX = "ak_"


def resolve_api_key(explicit: str | None) -> str:
    """Return an ak_-prefixed key or raise AuthError locally.

    Resolution order: the explicit argument, then ``ARKLEON_API_KEY``. The key
    is required and validated for the ak_ prefix here, before any request, so
    the client fails closed rather than issuing a silent unauthenticated call
    (contract section 6.2). The raised message never contains the key value.
    """
    key = explicit if explicit is not None else os.environ.get(API_KEY_ENV_VAR)
    if not isinstance(key, str) or not key.strip():
        raise AuthError(
            "An Arkleon /v1 API key is required. Pass api_key=... or set the "
            f"{API_KEY_ENV_VAR} environment variable to an {API_KEY_PREFIX}-prefixed key.",
            error="unauthorized",
        )
    key = key.strip()
    if not key.startswith(API_KEY_PREFIX):
        raise AuthError(
            f"Arkleon /v1 API keys must be {API_KEY_PREFIX}-prefixed. The supplied "
            "value is not a valid key.",
            error="unauthorized",
        )
    return key


def optional_api_key(explicit: str | None) -> str | None:
    """Return a resolvable ak_ key, or None when none is available.

    A soft companion to resolve_api_key for callers that must not raise when no
    key is present, such as the MCP server deciding whether to register the paid
    tools (spec section 7.1). It never raises and never logs the key.
    """
    try:
        return resolve_api_key(explicit)
    except AuthError:
        return None
