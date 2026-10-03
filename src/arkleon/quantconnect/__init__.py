"""As-filed snapshot preparation; Lean is needed only to access the data class."""

from .loader import AmbiguousFactError, SnapshotError, prepare_snapshot, visible_as_filed

__all__ = [
    "AmbiguousFactError", "SnapshotError", "prepare_snapshot", "visible_as_filed",
    "ArkleonFundamental",
]


def __getattr__(name: str):
    if name == "ArkleonFundamental":
        from .data import ArkleonFundamental

        return ArkleonFundamental
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
