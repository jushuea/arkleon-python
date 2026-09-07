"""Free EDGAR core imported by default; api and mcp are optional extras."""

from __future__ import annotations

__version__ = "0.1.2"

from .edgar import (
    AS_OF_WARNING,
    Company,
    EdgarClient,
    Fact,
    FactSet,
    Filing,
    MissingUserAgentError,
    RateLimiter,
    as_of,
    build_ticker_map,
    cik_to_int,
    facts_to_dataframe,
    normalize_cik,
    parse_company_concept,
    parse_company_facts,
    parse_fsds_zip,
    parse_submissions,
    resolve_user_agent,
)

__all__ = [
    "AS_OF_WARNING",
    "Company",
    "EdgarClient",
    "Fact",
    "FactSet",
    "Filing",
    "MissingUserAgentError",
    "RateLimiter",
    "as_of",
    "build_ticker_map",
    "cik_to_int",
    "facts_to_dataframe",
    "normalize_cik",
    "parse_company_concept",
    "parse_company_facts",
    "parse_fsds_zip",
    "parse_submissions",
    "resolve_user_agent",
    "__version__",
]
