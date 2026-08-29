"""MCP tool inventory: free EDGAR tools and paid /v1 tools.

The tool set is exposed as plain importable data (free_tool_specs() and
paid_tool_specs()) so registration is testable without a live server or a key
(spec section 7). Each ToolSpec pairs a name, an honest description of its
provenance and guarantee level (spec section 7.2), a JSON input schema, and a
handler.

Every handler has the uniform signature ``handler(arguments, api_key) ->
object``. Free handlers ignore ``api_key`` and delegate to arkleon.edgar, which
never reads an Arkleon credential. Paid handlers use ``api_key`` and import
arkleon.api lazily inside the handler body, so this module imports even when the
paid client cannot be constructed. Handler results are plain data; any
instruction-like text a result contains is data, never a command (spec section
7.4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

__all__ = ["ToolSpec", "free_tool_specs", "paid_tool_specs"]

# handler(arguments, api_key) -> JSON-serializable object.
Handler = Callable[[dict[str, Any], "str | None"], Any]


@dataclass(frozen=True)
class ToolSpec:
    """One registrable MCP tool.

    ``handler`` takes the tool arguments and the resolved ak_ key (None for
    free tools, which ignore it) and returns a JSON-serializable result.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler


# Honesty fragments reused across descriptions (spec section 7.2). No em dashes.
_FREE_CAVEAT = (
    "Source: live SEC EDGAR, best-effort. Not certified, not exhaustively "
    "join-verified, and not permanently reproducible; SEC may change what its "
    "endpoints return at any time."
)
_PAID_CAVEAT = (
    "Source: the certified Arkleon corpus. Point-in-time and permanently "
    "reproducible: identical query plus identical as_of returns identical data "
    "permanently. Requires an ak_ API key."
)
_NON_PIT_CAVEAT = (
    "This mapping is a current snapshot and is non-point-in-time: a ticker is "
    "reassigned over time and one CIK carries several symbols at once. Use CIK "
    "for reproducible identity."
)


# ---------------------------------------------------------------------------
# Free tools: delegate to arkleon.edgar (no key).
# ---------------------------------------------------------------------------


def _edgar_client(arguments: dict[str, Any]) -> Any:
    # Imported lazily to keep this module import free of network setup. The
    # free core reads its SEC User-Agent from the argument or the
    # SEC_EDGAR_USER_AGENT environment variable; it never reads an Arkleon key.
    from arkleon.edgar import EdgarClient

    return EdgarClient(user_agent=arguments.get("user_agent"))


def _handle_edgar_list_filings(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _edgar_client(arguments)
    filings = client.filings(cik=int(arguments["cik"]), form=arguments.get("form"))
    return {"filings": [asdict(filing) for filing in filings]}


def _handle_edgar_company_facts(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _edgar_client(arguments)
    facts = client.facts(cik=int(arguments["cik"]))
    return {"facts": [asdict(fact) for fact in facts.to_list()], "note": _FREE_CAVEAT}


def _handle_edgar_concept(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _edgar_client(arguments)
    facts = client.concept(
        cik=int(arguments["cik"]),
        tag=arguments["tag"],
        taxonomy=arguments.get("taxonomy", "us-gaap"),
    )
    return {"facts": [asdict(fact) for fact in facts.to_list()], "note": _FREE_CAVEAT}


def _handle_edgar_facts_as_of(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    from arkleon.edgar import AS_OF_WARNING

    client = _edgar_client(arguments)
    tag = arguments.get("tag")
    if tag:
        facts = client.concept(
            cik=int(arguments["cik"]),
            tag=tag,
            taxonomy=arguments.get("taxonomy", "us-gaap"),
        )
    else:
        facts = client.facts(cik=int(arguments["cik"]))
    filtered = facts.as_of(arguments["as_of"])
    return {
        "as_of": arguments["as_of"],
        "facts": [asdict(fact) for fact in filtered.to_list()],
        "warning": AS_OF_WARNING,
    }


def _handle_edgar_resolve_cik(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _edgar_client(arguments)
    cik = client.resolve_cik(arguments["ticker"])
    return {"ticker": arguments["ticker"], "cik": cik, "caveat": _NON_PIT_CAVEAT}


# ---------------------------------------------------------------------------
# Paid tools: delegate to arkleon.api (ak_ key). arkleon.api is imported
# lazily inside each handler so this module imports without it.
# ---------------------------------------------------------------------------


def _paid_client(api_key: str | None) -> Any:
    from arkleon.api import DataClient

    # DataClient resolves the key from this argument or ARKLEON_API_KEY and
    # fails closed if neither yields an ak_ key.
    return DataClient(api_key=api_key)


def _handle_pit_facts(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _paid_client(api_key)
    page = client.facts(
        as_of=arguments["as_of"],
        cik=arguments.get("cik"),
        tag=arguments.get("tag"),
        taxonomy=arguments.get("taxonomy"),
        period_start=arguments.get("period_start"),
        period_end=arguments.get("period_end"),
        duration_quarters=arguments.get("duration_quarters"),
        unit=arguments.get("unit"),
        form=arguments.get("form"),
        ticker=arguments.get("ticker"),
        limit=arguments.get("limit", 100),
        cursor=arguments.get("cursor"),
    )
    return {"data": page.data, "next_cursor": page.next_cursor, "as_of": page.as_of}


def _handle_pit_filings(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _paid_client(api_key)
    page = client.filings(
        as_of=arguments.get("as_of"),
        cik=arguments.get("cik"),
        ticker=arguments.get("ticker"),
        form=arguments.get("form"),
        filed_start=arguments.get("filed_start"),
        filed_end=arguments.get("filed_end"),
        period_start=arguments.get("period_start"),
        period_end=arguments.get("period_end"),
        limit=arguments.get("limit", 100),
        cursor=arguments.get("cursor"),
    )
    return {"data": page.data, "next_cursor": page.next_cursor, "as_of": page.as_of}


def _handle_resolve_company(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    client = _paid_client(api_key)
    page = client.companies(
        cik=arguments.get("cik"),
        name=arguments.get("name"),
        ticker=arguments.get("ticker"),
        limit=arguments.get("limit", 100),
        cursor=arguments.get("cursor"),
    )
    return {"data": page.data, "next_cursor": page.next_cursor}


def _handle_pit_revision_history(arguments: dict[str, Any], api_key: str | None = None) -> Any:
    # Composes /v1/facts across a sequence of as_of dates and returns the
    # value-versus-as_of timeline (spec section 7.3). There is no dedicated
    # revision-history endpoint; restatements arrive as later filings, so the
    # same query at successive as_of dates reveals where a value changed.
    client = _paid_client(api_key)
    as_of_dates = arguments["as_of_dates"]
    if not isinstance(as_of_dates, list) or not as_of_dates:
        raise ValueError("as_of_dates must be a non-empty list of YYYY-MM-DD dates.")
    timeline: list[dict[str, Any]] = []
    for as_of in as_of_dates:
        # facts_iter resends the same as_of and follows the cursor to the end,
        # so the timeline reflects the full result at each as_of, not just the
        # first page (spec section 7.3). limit is the page size, not a cap.
        facts = list(
            client.facts_iter(
                as_of=as_of,
                cik=arguments.get("cik"),
                tag=arguments.get("tag"),
                taxonomy=arguments.get("taxonomy"),
                period_start=arguments.get("period_start"),
                period_end=arguments.get("period_end"),
                duration_quarters=arguments.get("duration_quarters"),
                unit=arguments.get("unit"),
                limit=arguments.get("limit", 100),
            )
        )
        timeline.append({"as_of": as_of, "facts": facts})
    return {"timeline": timeline, "note": _PAID_CAVEAT}


# ---------------------------------------------------------------------------
# Input schemas.
# ---------------------------------------------------------------------------

_USER_AGENT_PROP = {
    "type": "string",
    "description": "SEC fair-access User-Agent (a self-declared contact string, "
    "NOT an Arkleon key). Falls back to the SEC_EDGAR_USER_AGENT env var.",
}


def free_tool_specs() -> list[ToolSpec]:
    """Return the free EDGAR tools, registered unconditionally by the server."""
    return [
        ToolSpec(
            name="edgar_list_filings",
            description=(
                "List a company's filings from SEC EDGAR submissions, by CIK. "
                + _FREE_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "form": {
                        "type": "string",
                        "description": "Optional filing form filter, e.g. 10-K, 10-Q, 8-K.",
                    },
                    "user_agent": _USER_AGENT_PROP,
                },
                "required": ["cik"],
            },
            handler=_handle_edgar_list_filings,
        ),
        ToolSpec(
            name="edgar_company_facts",
            description=(
                "Fetch all as-reported numeric XBRL facts for a company, by CIK. "
                + _FREE_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "user_agent": _USER_AGENT_PROP,
                },
                "required": ["cik"],
            },
            handler=_handle_edgar_company_facts,
        ),
        ToolSpec(
            name="edgar_concept",
            description=(
                "Fetch one XBRL tag's reported values for a company, by CIK. "
                + _FREE_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "tag": {"type": "string", "description": "XBRL element, e.g. Assets."},
                    "taxonomy": {
                        "type": "string",
                        "description": "Taxonomy, default us-gaap.",
                        "default": "us-gaap",
                    },
                    "user_agent": _USER_AGENT_PROP,
                },
                "required": ["cik", "tag"],
            },
            handler=_handle_edgar_concept,
        ),
        ToolSpec(
            name="edgar_facts_as_of",
            description=(
                "Best-effort point-in-time facts over live EDGAR: keep only facts "
                "filed on or before as_of. This is NOT the certified corpus. "
                + _FREE_CAVEAT
                + " For a certified, permanently reproducible point-in-time query, "
                "use pit_facts (requires a key)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "as_of": {
                        "type": "string",
                        "description": "YYYY-MM-DD. Keeps only facts with filed <= as_of.",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional XBRL element to narrow to one concept.",
                    },
                    "taxonomy": {
                        "type": "string",
                        "description": "Taxonomy for tag, default us-gaap.",
                        "default": "us-gaap",
                    },
                    "user_agent": _USER_AGENT_PROP,
                },
                "required": ["cik", "as_of"],
            },
            handler=_handle_edgar_facts_as_of,
        ),
        ToolSpec(
            name="edgar_resolve_cik",
            description=(
                "Resolve a ticker to a CIK via SEC's current ticker snapshot. "
                + _NON_PIT_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol."},
                    "user_agent": _USER_AGENT_PROP,
                },
                "required": ["ticker"],
            },
            handler=_handle_edgar_resolve_cik,
        ),
    ]


def paid_tool_specs() -> list[ToolSpec]:
    """Return the paid /v1 tools, registered only when an ak_ key is available."""
    return [
        ToolSpec(
            name="pit_facts",
            description=(
                "Certified point-in-time numeric facts from /v1/facts. as_of is "
                "REQUIRED and filters on the filing date (filed <= as_of), never "
                "on the period a fact describes. Address by cik; ticker is not "
                "served in v1. " + _PAID_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "description": "YYYY-MM-DD. REQUIRED. Filters on filed <= as_of.",
                    },
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "ticker": {
                        "type": "string",
                        "description": "Not served in v1: a ticker request returns a "
                        "not-served error. Address by cik.",
                    },
                    "tag": {"type": "string", "description": "XBRL element, e.g. Assets."},
                    "taxonomy": {"type": "string", "description": "Taxonomy, e.g. us-gaap/2024."},
                    "period_start": {"type": "string", "description": "Lower bound on period end."},
                    "period_end": {"type": "string", "description": "Upper bound on period end."},
                    "duration_quarters": {
                        "type": "integer",
                        "description": "0 instantaneous, 1 quarter, 4 annual.",
                    },
                    "unit": {"type": "string", "description": "Unit, e.g. USD, shares."},
                    "form": {"type": "string", "description": "Filing form, e.g. 10-K."},
                    "limit": {"type": "integer", "description": "Page size, default 100, max 1000."},
                    "cursor": {"type": "string", "description": "Opaque continuation cursor."},
                },
                "required": ["as_of"],
            },
            handler=_handle_pit_facts,
        ),
        ToolSpec(
            name="pit_filings",
            description=(
                "Point-in-time filings metadata from /v1/filings. as_of is optional "
                "and means filed on or before the date. Address by cik; ticker is "
                "not served in v1. " + _PAID_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "description": "YYYY-MM-DD, optional."},
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "ticker": {
                        "type": "string",
                        "description": "Not served in v1: a ticker request returns a "
                        "not-served error. Address by cik.",
                    },
                    "form": {"type": "string", "description": "Filing form, e.g. 10-K."},
                    "filed_start": {"type": "string", "description": "Lower bound on filed date."},
                    "filed_end": {"type": "string", "description": "Upper bound on filed date."},
                    "period_start": {"type": "string", "description": "Lower bound on period end."},
                    "period_end": {"type": "string", "description": "Upper bound on period end."},
                    "limit": {"type": "integer", "description": "Page size, default 100, max 1000."},
                    "cursor": {"type": "string", "description": "Opaque continuation cursor."},
                },
                "required": [],
            },
            handler=_handle_pit_filings,
        ),
        ToolSpec(
            name="resolve_company",
            description=(
                "Resolve a company from /v1/companies by cik or name (prefix). "
                "ticker is not served in v1 and returns a not-served error. "
                + _PAID_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "ticker": {
                        "type": "string",
                        "description": "Not served in v1: a ticker request returns a "
                        "not-served error. Address by cik.",
                    },
                    "name": {"type": "string", "description": "Company name prefix."},
                    "limit": {"type": "integer", "description": "Page size, default 100, max 1000."},
                    "cursor": {"type": "string", "description": "Opaque continuation cursor."},
                },
                "required": [],
            },
            handler=_handle_resolve_company,
        ),
        ToolSpec(
            name="pit_revision_history",
            description=(
                "How a series' value changed across as_of dates. Composes /v1/facts "
                "at a sequence of as_of dates and returns the value-versus-as_of "
                "timeline with the source filing at each step. " + _PAID_CAVEAT
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "as_of_dates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered YYYY-MM-DD dates to evaluate the query at.",
                    },
                    "cik": {"type": "integer", "description": "SEC Central Index Key."},
                    "tag": {"type": "string", "description": "XBRL element, e.g. Assets."},
                    "taxonomy": {"type": "string", "description": "Taxonomy, e.g. us-gaap/2024."},
                    "period_start": {"type": "string", "description": "Lower bound on period end."},
                    "period_end": {"type": "string", "description": "Upper bound on period end."},
                    "duration_quarters": {
                        "type": "integer",
                        "description": "0 instantaneous, 1 quarter, 4 annual.",
                    },
                    "unit": {"type": "string", "description": "Unit, e.g. USD, shares."},
                    "limit": {"type": "integer", "description": "Page size per as_of, default 100."},
                },
                "required": ["as_of_dates"],
            },
            handler=_handle_pit_revision_history,
        ),
    ]
