"""Closed-alphabet error envelope to typed exceptions.

Maps the /v1 contract's closed error alphabet (contract section 4.2) to a small
typed exception hierarchy, one class per meaning. Each exception preserves the
server's ``error`` code, ``message``, and ``error_id`` (the support correlation
handle, contract section 4.4). The alphabet is closed: a handler MAY select a
code from the table below but MUST NOT introduce one, so an unknown code
collapses to a status-mapped default rather than leaking an upstream string.
"""

from __future__ import annotations

import builtins
from typing import Any

__all__ = [
    "ArkleonAPIError",
    "AuthError",
    "ScopeError",
    "RequestError",
    "NotFoundError",
    "ConflictError",
    "UnprocessableError",
    "RateLimitError",
    "NotServedError",
    "ServerError",
    "error_from_envelope",
    # Alias exported per spec section 6.5; the primary class name is
    # NotServedError to avoid shadowing the builtin at call sites.
    "NotImplementedError",
]


class ArkleonAPIError(Exception):
    """Base class for every /v1 client error.

    Carries the three envelope fields the contract guarantees on a >= 400
    response: ``error`` (the closed-alphabet code), ``message`` (a fixed
    literal selected by the server), and ``error_id`` (the UUID a customer
    quotes to support). ``status_code`` is the HTTP status the envelope
    arrived with, retained for callers that branch on it.
    """

    def __init__(
        self,
        message: str,
        *,
        error: str | None = None,
        error_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.error_id = error_id
        self.status_code = status_code


class AuthError(ArkleonAPIError):
    """401 unauthorized or invalid_api_key.

    Also raised locally, before any request, when no ak_-prefixed key is
    resolvable (the paid gate, contract section 6.2).
    """


class ScopeError(ArkleonAPIError):
    """403 scope_insufficient: the key is valid but lacks the endpoint scope."""


class RequestError(ArkleonAPIError):
    """400 invalid_request.

    Also raised locally for caller errors the client can catch before a
    request: a missing as_of on facts(), or cik and ticker supplied together.
    """


class NotFoundError(ArkleonAPIError):
    """404 not_found: the route or named entity does not exist.

    Never returned for a query that merely matched zero rows; an empty match
    is a 200 with an empty data array (contract section 4.3).
    """


class ConflictError(ArkleonAPIError):
    """409 conflict: an ambiguous identifier."""


class UnprocessableError(ArkleonAPIError):
    """422 unprocessable: understood but cannot be processed."""


class RateLimitError(ArkleonAPIError):
    """429 rate_limited.

    Carries ``retry_after`` (seconds). Per contract section 1.3 a 429 without a
    Retry-After is itself a contract violation; the client honors the value
    rather than retrying on a fixed schedule.
    """

    def __init__(
        self,
        message: str,
        *,
        error: str | None = None,
        error_id: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, error=error, error_id=error_id, status_code=status_code)
        self.retry_after = retry_after


class NotServedError(ArkleonAPIError, builtins.NotImplementedError):
    """501 not_implemented: specified by the contract but not served today.

    Subclasses both ArkleonAPIError and the builtin NotImplementedError so a
    caller can catch it either way. The most common cause in v1 is a ticker
    filter, which the contract rejects with 501 on every endpoint until a
    persisted point-in-time ticker to CIK mapping exists (contract section
    2.3.1). Exported under the alias name NotImplementedError per spec section
    6.5, but the primary class name is NotServedError so the builtin is not
    shadowed at call sites.
    """


class ServerError(ArkleonAPIError):
    """5xx server-side failure.

    Covers internal_error, dependency_unavailable, and upstream_timeout, plus
    the status-mapped default for any unknown 5xx code.
    """


# error code (closed alphabet, contract section 4.2) -> exception class.
_ERROR_MAP: dict[str, type[ArkleonAPIError]] = {
    "unauthorized": AuthError,
    "invalid_api_key": AuthError,
    "scope_insufficient": ScopeError,
    "invalid_request": RequestError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "unprocessable": UnprocessableError,
    "rate_limited": RateLimitError,
    "not_implemented": NotServedError,
    "dependency_unavailable": ServerError,
    "upstream_timeout": ServerError,
    "internal_error": ServerError,
}


def error_from_envelope(status_code: int, body: dict[str, Any]) -> ArkleonAPIError:
    """Build the typed exception for a >= 400 /v1 response.

    ``body`` is the parsed error envelope. A recognized ``error`` code maps to
    its class; an unknown or absent code collapses to the status-mapped default
    (ServerError for 5xx, RequestError for 4xx) so no handler-authored or
    upstream string can reach the caller as a code.
    """
    code = body.get("error")
    message = body.get("message")
    if not isinstance(message, str) or not message:
        message = f"HTTP {status_code}"
    error_id = body.get("error_id")
    error_id = error_id if isinstance(error_id, str) else None

    mapped_class = _ERROR_MAP.get(code) if isinstance(code, str) else None
    recognized = mapped_class is not None
    exception_class = mapped_class
    if exception_class is None:
        exception_class = ServerError if status_code >= 500 else RequestError

    # The alphabet is closed: only a recognized code travels as ``error``. An
    # unknown or absent code collapsed to the status-mapped default carries
    # error=None, so no handler-authored or upstream string leaks as a code.
    resolved_error = code if recognized else None

    if exception_class is RateLimitError:
        retry_after = body.get("retry_after")
        retry_after = retry_after if isinstance(retry_after, int | float) else None
        return RateLimitError(
            message,
            error=resolved_error,
            error_id=error_id,
            status_code=status_code,
            retry_after=retry_after,
        )

    return exception_class(
        message,
        error=resolved_error,
        error_id=error_id,
        status_code=status_code,
    )


# Spec section 6.5: export NotServedError under the contract's alias name too.
# Deliberately shadows builtins.NotImplementedError inside this module's
# namespace only; call sites import the primary name NotServedError.
NotImplementedError = NotServedError  # noqa: A001
