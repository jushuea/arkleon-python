"""Verify that the package version matches the project metadata."""

from __future__ import annotations

from pathlib import Path
import tomllib

import arkleon


def test_pyproject_version_matches_runtime_constant() -> None:
    """Ensure pyproject.toml and the runtime package version stay in sync."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    pyproject_version = pyproject["project"]["version"]
    assert pyproject_version == arkleon.__version__, (
        f"pyproject.toml version {pyproject_version!r} does not match "
        f"arkleon.__version__ {arkleon.__version__!r}"
    )
