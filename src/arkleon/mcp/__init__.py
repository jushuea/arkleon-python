"""Built-in MCP server for arkleon.

Component (c) of the arkleon package (spec section 7). This subpackage is
import-gated on the optional ``mcp`` SDK: it is the only truly extra-gated
dependency of the package. If the SDK is absent, importing this subpackage
raises a clear ImportError naming the extra to install, never a partial or
broken import (spec section 9.1, invariant 4).

The server registers the free EDGAR tools unconditionally and the paid /v1
tools only when an ak_ key is available (spec section 7.1).
"""

from __future__ import annotations

try:
    import mcp as _mcp  # noqa: F401  (import-gate probe only)
except ImportError:
    raise ImportError(
        "arkleon.mcp requires the 'mcp' extra: pip install 'arkleon[mcp]'"
    ) from None

from .server import build_server, main
from .tools import ToolSpec, free_tool_specs, paid_tool_specs

__all__ = [
    "build_server",
    "main",
    "ToolSpec",
    "free_tool_specs",
    "paid_tool_specs",
]
