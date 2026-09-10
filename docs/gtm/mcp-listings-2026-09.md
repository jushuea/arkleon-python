# MCP listing checklist, September 2026

## Purpose

This document is the operator runbook for listing the Arkleon MCP server in the official MCP registry and the reviewed public directories. It freezes the launch copy, records the exact submission URLs and required fields, and separates automated preparation from operator actions.

## Listing copy

```text
Name: Arkleon
Description: Point-in-time SEC EDGAR fundamentals: free fetch/parse helpers, an optional certified /v1 client, and a built-in MCP server.
Summary: Arkleon provides point-in-time SEC EDGAR fundamentals through free EDGAR fetch and parse helpers that require zero credentials. The built-in MCP server registers the free EDGAR tools unconditionally, while paid /v1 tools register only when an ak_ key is present. The paid corpus-backed client is optional and refuses to operate without an ak_-prefixed key.
Tools:

| Tool | Backed by | Key required? |
|---|---|---|
| `edgar_list_filings` | free EDGAR core | No |
| `edgar_company_facts` | free EDGAR core | No |
| `edgar_concept` | free EDGAR core | No |
| `edgar_facts_as_of` (best-effort, live EDGAR) | free EDGAR core | No |
| `edgar_resolve_cik` (current-snapshot, non-point-in-time) | free EDGAR core | No |
| `pit_facts` (certified point-in-time) | paid `/v1` client | Yes |
| `pit_filings` | paid `/v1` client | Yes |
| `resolve_company` | paid `/v1` client | Yes |
| `pit_revision_history` | paid `/v1` client | Yes |
Launch config:

```json
{
  "mcpServers": {
    "arkleon": {
      "command": "arkleon-mcp",
      "env": { "ARKLEON_API_KEY": "ak_..." }
    }
  }
}
```

## 1. Official MCP registry

URL: https://registry.modelcontextprotocol.io

1. Prerequisite: publish arkleon 0.1.3 to PyPI with README.md containing the ownership line `<!-- mcp-name: io.github.jushuea/arkleon -->`; the registry verifies PyPI ownership by that string in the package README.
2. Install `mcp-publisher`:
   ```bash
   curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" | tar xz mcp-publisher
   ```
   Alternative: `brew install mcp-publisher`.
3. Run `mcp-publisher login github`; complete device-code login as the GitHub user `jushuea`.
4. Confirm server.json has `name` set to `io.github.jushuea/arkleon`.
5. Run `mcp-publisher validate`.
6. Run `mcp-publisher publish`.
7. Verify the listing at https://registry.modelcontextprotocol.io/v0/servers?search=arkleon.

Required server.json fields:

- `name`
- `description`
- description at most 100 characters (the registry validator enforces this; the manifest uses the 89-character form).
- `version`
- `packages` with `registryType` set to `pypi`, plus `identifier`, `version`, and `transport` set to `stdio`.

## 2. Smithery

URL: https://smithery.ai/new

1. Use the "Local (MCPB Bundle)" tab, or run `smithery mcp publish ./server.mcpb -n jushuea/arkleon`.
2. Build the MCPB bundle first if it is used. An MCPB bundle contains manifest.json plus the packaged server, as documented at https://github.com/modelcontextprotocol/mcpb. The bundle is not part of this PR.
3. Submit the listing fields below.

Required fields:

- Name
- Description
- Repository URL: https://github.com/jushuea/arkleon-python
- Launch command: `arkleon-mcp`
- Optional environment variable: `ARKLEON_API_KEY`

## 3. Glama

URL: https://glama.ai/mcp/servers

1. Select "Add Server".
2. Submit https://github.com/jushuea/arkleon-python.
3. Claim the listing with the same GitHub account.

Required fields:

- Repository
- Description
- Install command

## 4. mcp.so

URL: https://mcp.so/submit

The operator completes this web form by hand because automated fetches are refused.

Required fields:

- Name
- GitHub URL
- One-line description
- Category
- Launch config

## Screenshots the operator needs

1. Official MCP registry entry.
2. Smithery listing.
3. Glama listing.
4. mcp.so listing.

## AWAITING OPERATOR

1. Release arkleon 0.1.3 to PyPI with the README ownership line.
2. Complete GitHub device login.
3. Approve the listing copy.
4. Decide whether to build an MCPB bundle for Smithery.
