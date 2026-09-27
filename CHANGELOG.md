# Changelog

## [0.1.5] - 2026-09-27

### Added

- `arkleon.integrations.langchain.ArkleonEdgarFactsTool`, a LangChain tool over `EdgarClient.concept(...).as_of(...)` (extra: `langchain`).
- `arkleon.integrations.llamaindex.ArkleonEdgarFactsReader`, a LlamaIndex reader over the same call (extra: `llamaindex`).

## [0.1.4] - 2026-09-27

### Added

- Documented the free `/v1` tier cap of 500 requests / day in the README.
- Reserved a `concept_alias` parameter in the README, to be activated after /v1 ships it.
- Added the `com.arkleon/arkleon` mcp-name marker to the package description for the official MCP registry.
