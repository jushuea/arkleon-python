# Changelog

## [0.1.7] - 2026-11-19

- Added `concept_alias` to `DataClient.facts()`. It cannot be combined with `tag`, and each returned fact keeps the server's `matched_tag`.
- Added `DataClient.ttm()` for `/v1/ttm` and `DataClient.identifiers()` for `/v1/identifiers`.
- Added the certified pair `arkleon.integrations.langchain_data.ArkleonDataFactsTool` and `arkleon.integrations.llamaindex_data.ArkleonDataFactsReader` over the paid `DataClient.facts` (extras: `langchain`, `llamaindex`; an `ak_` key is required).
- The `pit_facts` MCP tool accepts `concept_alias`.
- The README states that `concept_alias` is accepted, in place of the sentence that reserved it.
- The `pit_facts` MCP tool passes `concept` on, `Page.concept` holds the server's `concept` object, and with `concept_alias` the tool's dict also carries `concept` while each `Document`'s metadata also carries `concept_alias`, `concept_provisional` and `concept_note`.

## [0.1.6] - 2026-10-03

- Added `arkleon.quantconnect` snapshot preparation using datetime `/v1/facts` queries, acceptance and filing-date guards, and consolidated as-filed selection.
- Added a Lean `PythonData` adapter that reads prepared local snapshots and retains filing provenance.
- Added pagination validity metadata so snapshot preparation can reject malformed response envelopes.

## [0.1.5] - 2026-09-27

### Added

- `arkleon.integrations.langchain.ArkleonEdgarFactsTool`, a LangChain tool over `EdgarClient.concept(...).as_of(...)` (extra: `langchain`).
- `arkleon.integrations.llamaindex.ArkleonEdgarFactsReader`, a LlamaIndex reader over the same call (extra: `llamaindex`).

## [0.1.4] - 2026-09-27

### Added

- Documented the free `/v1` tier cap of 500 requests / day in the README.
- Reserved a `concept_alias` parameter in the README, to be activated after /v1 ships it.
- Added the `com.arkleon/arkleon` mcp-name marker to the package description for the official MCP registry.
