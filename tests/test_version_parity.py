"""Verify that the server manifest versions match the package version."""

from __future__ import annotations

import json
from pathlib import Path

import arkleon


def test_server_versions_match_runtime_constant() -> None:
    """Ensure server.json versions stay in sync with the runtime package version."""
    runtime_version = arkleon.__version__
    server_path = Path(__file__).resolve().parent.parent / "server.json"
    with server_path.open(encoding="utf-8") as server_file:
        server = json.load(server_file)

    server_version = server["version"]
    assert server_version == runtime_version, (
        f"server.json version {server_version!r} does not match "
        f"arkleon.__version__ {runtime_version!r}"
    )
    package_version = server["packages"][0]["version"]
    assert package_version == runtime_version, (
        f"server.json packages[0] version {package_version!r} does not match "
        f"arkleon.__version__ {runtime_version!r}"
    )
