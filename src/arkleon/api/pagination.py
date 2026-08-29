"""Opaque-cursor pagination, as_of-stable.

The /v1 contract paginates by cursor, never by offset (contract section 2.1.3):
offset pagination is incorrect under concurrent writes. Every page of a result
set is evaluated at the same as_of supplied on the first request, so the
iterator here resends that as_of on every page and treats the cursor as opaque:
it never parses, constructs, or modifies it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Page", "paginate"]


@dataclass(frozen=True)
class Page:
    """One page of a /v1 result set.

    ``data`` is the list of records (facts, filings, or companies) exposed in
    the public /v1 vocabulary. ``next_cursor`` is the opaque continuation token,
    or None at the end of the set. ``as_of`` is the date the whole set is
    evaluated at (None on endpoints where as_of is optional and unset).
    ``request`` echoes the non-secret request context for the caller's
    reference; it never contains the API key.
    """

    data: list[Any]
    next_cursor: str | None
    as_of: str | None = None
    request: dict[str, Any] = field(default_factory=dict)


def paginate(fetch_page: Callable[[str | None], Page]) -> Iterator[Any]:
    """Yield every record across pages, following next_cursor to exhaustion.

    ``fetch_page`` takes a cursor (None on the first call) and returns a Page.
    The caller's closure is responsible for resending the same as_of on each
    call so the set stays as_of-stable (contract section 2.1.3); this helper
    only threads the opaque cursor and never inspects it.
    """
    cursor: str | None = None
    while True:
        page = fetch_page(cursor)
        yield from page.data
        cursor = page.next_cursor
        if not cursor:
            return
