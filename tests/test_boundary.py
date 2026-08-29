"""Spec section 9.1 boundary invariants, checked mechanically.

The free EDGAR core must stay free: it must not import the paid or MCP
subpackages, must name no Arkleon host, must reference no Arkleon credential,
and must run credential-free end to end. The paid gate is a runtime key gate,
not an import gate; the MCP subpackage is the only import-gated component.

Every check here is offline. The one HTTP path (invariant 6) uses an injected
httpx.MockTransport, never a real host.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
from pathlib import Path

import httpx
import pytest


def _package_dir() -> Path:
    """Locate the installed-or-src arkleon package directory."""
    spec = importlib.util.find_spec("arkleon")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).parent


def _edgar_py_files() -> list[Path]:
    edgar_dir = _package_dir() / "edgar"
    assert edgar_dir.is_dir(), f"edgar package dir not found at {edgar_dir}"
    files = sorted(p for p in edgar_dir.glob("*.py"))
    assert files, "no .py files found under src/arkleon/edgar"
    return files


def _imports_forbidden_subpackage(tree: ast.AST) -> bool:
    """True if the module imports arkleon.api or arkleon.mcp in any form."""
    forbidden_prefixes = ("arkleon.api", "arkleon.mcp")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(forbidden_prefixes):
                    return True
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) stay inside the edgar package.
            if node.level != 0:
                continue
            base = node.module or ""
            if base.startswith(forbidden_prefixes):
                return True
            # Catch `from arkleon import api` / `from arkleon import mcp`.
            if base == "arkleon" and any(a.name in {"api", "mcp"} for a in node.names):
                return True
    return False


def test_free_core_does_not_import_paid_or_mcp() -> None:
    """Invariant 1: no edgar module imports arkleon.api or arkleon.mcp."""
    offenders = []
    for path in _edgar_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _imports_forbidden_subpackage(tree):
            offenders.append(path.name)
    assert offenders == [], f"edgar modules import a paid/mcp subpackage: {offenders}"


def test_free_core_names_only_sec_hosts() -> None:
    """Invariant 2: the only https hosts named are data.sec.gov / www.sec.gov."""
    allowed = {"data.sec.gov", "www.sec.gov"}
    host_re = re.compile(r"https://([A-Za-z0-9.\-]+)")
    for path in _edgar_py_files():
        text = path.read_text(encoding="utf-8")
        assert "arkleon.com" not in text, f"{path.name} names arkleon.com"
        assert "api.arkleon" not in text, f"{path.name} names api.arkleon"
        for host in host_re.findall(text):
            assert host in allowed, f"{path.name} names unexpected host {host!r}"


def test_free_core_references_no_arkleon_credential() -> None:
    """Invariant 3: no edgar module references ARKLEON_API_KEY."""
    for path in _edgar_py_files():
        text = path.read_text(encoding="utf-8")
        assert "ARKLEON_API_KEY" not in text, f"{path.name} references ARKLEON_API_KEY"


def test_mcp_import_gate_present_and_importable() -> None:
    """Invariant 4: arkleon.mcp imports here (SDK installed) and exposes build_server.

    With the mcp SDK absent, importing arkleon.mcp raises ImportError naming the
    'arkleon[mcp]' extra. The SDK cannot be uninstalled in-test, so instead we
    assert the gate CODE exists: the subpackage __init__ carries a try/except
    ImportError that re-raises a message naming 'arkleon[mcp]'.
    """
    import arkleon.mcp as mcp_pkg

    assert hasattr(mcp_pkg, "build_server")

    spec = importlib.util.find_spec("arkleon.mcp")
    assert spec is not None and spec.origin is not None
    src = Path(spec.origin).read_text(encoding="utf-8")
    assert "try:" in src
    assert "except ImportError" in src
    assert "arkleon[mcp]" in src


def test_paid_gate_is_runtime_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant 5: arkleon.api imports fine (httpx is base); no key raises AuthError."""
    monkeypatch.delenv("ARKLEON_API_KEY", raising=False)

    import arkleon.api as api  # imports with no key and no network

    with pytest.raises(api.AuthError):
        api.DataClient()


def test_free_install_runs_credential_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant 6: with a SEC UA set and no Arkleon key, an EdgarClient parse runs offline."""
    monkeypatch.delenv("ARKLEON_API_KEY", raising=False)
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Tester test@example.com")

    import arkleon.edgar as edgar

    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-09-30",
                                "val": 352755000000,
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            }
                        ]
                    }
                }
            }
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    # No Arkleon credential is present in the environment for this call.
    assert "ARKLEON_API_KEY" not in os.environ
    client = edgar.EdgarClient(transport=httpx.MockTransport(handler))
    facts = client.facts(320193)
    values = [fact.value for fact in facts]
    assert values == [352755000000]
