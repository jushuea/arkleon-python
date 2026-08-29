"""Optional paid /v1 client for the Arkleon Data API.

Component (b) of the arkleon package (spec section 6). This subpackage is
always importable because its HTTP dependency (httpx) is a base dependency;
there is no import gate. The paid gate is a RUNTIME requirement instead: the
client refuses to construct without an ak_-prefixed key (contract section 6.2),
resolved from the constructor argument or the ARKLEON_API_KEY environment
variable.

Nothing here activates without a key. Installing the client does not activate
the paid path; a key must still be supplied at runtime.
"""

from __future__ import annotations

from .client import DataClient
from .errors import (
    ArkleonAPIError,
    AuthError,
    ConflictError,
    NotFoundError,
    NotServedError,
    RateLimitError,
    RequestError,
    ScopeError,
    ServerError,
    UnprocessableError,
    error_from_envelope,
)
from .errors import NotImplementedError  # noqa: A004  (contract alias, spec section 6.5)
from .pagination import Page

__all__ = [
    "DataClient",
    "Page",
    "error_from_envelope",
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
    # Alias exported per spec section 6.5; primary name is NotServedError.
    "NotImplementedError",
]
