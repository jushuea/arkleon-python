"""MCP tool registration and description honesty, offline.

build_server is inspected via server.registered_tool_specs; no live server is
run and no network is touched. Descriptions are asserted on substrings so the
provenance caveat each tool must carry is verified mechanically.
"""

from __future__ import annotations

import arkleon.mcp as mcp

FREE_NAMES = {
    "edgar_list_filings",
    "edgar_company_facts",
    "edgar_concept",
    "edgar_facts_as_of",
    "edgar_resolve_cik",
}
PAID_NAMES = {
    "pit_facts",
    "pit_filings",
    "resolve_company",
    "pit_revision_history",
}
# The four data edgar tools carry the best-effort / not-certified caveat.
# edgar_resolve_cik is the identifier resolver and carries the
# non-point-in-time caveat instead (asserted separately below).
FREE_DATA_NAMES = FREE_NAMES - {"edgar_resolve_cik"}


def _names(specs) -> set[str]:
    return {spec.name for spec in specs}


def test_no_key_registers_only_free_tools() -> None:
    server = mcp.build_server()
    assert _names(server.registered_tool_specs) == FREE_NAMES
    assert len(server.registered_tool_specs) == 5


def test_ak_key_registers_free_and_paid_tools() -> None:
    server = mcp.build_server(api_key="ak_test")
    names = _names(server.registered_tool_specs)
    assert names == FREE_NAMES | PAID_NAMES
    assert len(server.registered_tool_specs) == 9


def test_non_ak_key_stays_free_only() -> None:
    server = mcp.build_server(api_key="not_an_ak_key")
    assert _names(server.registered_tool_specs) == FREE_NAMES
    assert len(server.registered_tool_specs) == 5


def test_tool_spec_helpers_match_names() -> None:
    assert _names(mcp.free_tool_specs()) == FREE_NAMES
    assert _names(mcp.paid_tool_specs()) == PAID_NAMES


def test_free_data_tool_descriptions_are_honest() -> None:
    by_name = {spec.name: spec for spec in mcp.free_tool_specs()}
    for name in FREE_DATA_NAMES:
        description = by_name[name].description.lower()
        assert "best-effort" in description, f"{name} lacks a best-effort caveat"
        assert "not certified" in description, f"{name} lacks a not-certified caveat"


def test_resolve_cik_flags_non_point_in_time() -> None:
    by_name = {spec.name: spec for spec in mcp.free_tool_specs()}
    description = by_name["edgar_resolve_cik"].description.lower()
    assert "non-point-in-time" in description


def test_paid_tool_descriptions_claim_certified_reproducible() -> None:
    for spec in mcp.paid_tool_specs():
        description = spec.description.lower()
        assert "certified" in description, f"{spec.name} lacks a certified caveat"
        assert "permanently reproducible" in description, (
            f"{spec.name} lacks a permanently-reproducible caveat"
        )
