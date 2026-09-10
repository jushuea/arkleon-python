"""Low-level MCP server exposing the arkleon tools over stdio.

Registers the free EDGAR tools UNCONDITIONALLY and the paid /v1 tools ONLY when
an ak_ key is resolvable, from the constructor argument or ARKLEON_API_KEY (spec
section 7.1). An agent with no key sees exactly the free set. The server holds no
state beyond the process, performs no writes, and treats any instruction-like
text in a tool result as data, never a command (spec section 7.4).

Uses the low-level mcp SDK (Server, stdio_server, mcp.types), not FastMCP.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .tools import ToolSpec, free_tool_specs, paid_tool_specs

# Import the package version so the handshake never carries a hand-copied literal.
from arkleon import __version__

__all__ = ["build_server", "main", "SERVER_NAME", "SERVER_VERSION"]

SERVER_NAME = "arkleon"
# Single-source the advertised version from the package (arkleon.__version__),
# the same anchor pyproject's hatch version and server.json (guarded by
# tests/test_version_parity.py) derive from. The MCP registry reads this from the
# handshake, so it must agree with the released version; never re-copy it here.
SERVER_VERSION = __version__


def _select_specs(api_key: str | None) -> tuple[list[ToolSpec], str | None]:
    """Return the tool specs to register and the resolved key (or None).

    Free tools are always included. Paid tools are appended only when an ak_
    key resolves. Key resolution is soft here: no key simply means the paid
    tools are omitted, never an error, so an agent without a key still gets a
    working free server.
    """
    # Imported here so this module's import never depends on being able to
    # resolve a key or construct the paid client.
    from arkleon.api.auth import optional_api_key

    specs: list[ToolSpec] = list(free_tool_specs())
    key = optional_api_key(api_key)
    if key is not None:
        specs.extend(paid_tool_specs())
    return specs, key


def build_server(*, api_key: str | None = None) -> Server:
    """Build a low-level MCP Server with the appropriate tool set.

    With no resolvable key the server registers exactly the free EDGAR tools.
    With an ak_ key (argument or ARKLEON_API_KEY) it additionally registers the
    paid /v1 tools. Constructible with no network contact: the paid client is
    imported and constructed only inside a tool handler at call time.

    The registered specs are attached as ``server.registered_tool_specs`` so
    registration is inspectable without a live session (spec section 7).
    """
    specs, key = _select_specs(api_key)
    by_name: dict[str, ToolSpec] = {spec.name: spec for spec in specs}
    tools = [
        types.Tool(name=spec.name, description=spec.description, input_schema=spec.input_schema)
        for spec in specs
    ]

    async def on_list_tools(
        ctx: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(
        ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        spec = by_name.get(params.name)
        if spec is None:
            return _error_result(f"Unknown tool: {params.name}")
        arguments = params.arguments or {}
        try:
            # Handlers run synchronously; offload to a thread so a blocking SEC
            # or /v1 request does not stall the event loop.
            result = await asyncio.to_thread(spec.handler, arguments, key)
        except Exception as exc:  # noqa: BLE001  (surface any error as tool output)
            return _error_result(f"{type(exc).__name__}: {exc}")
        # Tool results are DATA. Any instruction-like text they contain is
        # serialized as JSON and never interpreted as a command (spec 7.4).
        text = json.dumps(result, default=str)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    server: Server = Server(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    # Inspection seam for tests and callers: the exact specs registered.
    server.registered_tool_specs = specs
    return server


def _error_result(message: str) -> types.CallToolResult:
    payload = json.dumps({"error": "tool_error", "message": message})
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=payload)],
        is_error=True,
    )


def main() -> None:
    """Run the server over stdio (the standard local-agent transport)."""
    server = build_server()

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
