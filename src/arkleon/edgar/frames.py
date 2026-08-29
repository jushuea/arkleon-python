"""Free-core pandas adapter for EDGAR facts.

This module is gated behind the optional ``pandas`` extra
(``pip install "arkleon[pandas]"``) and is never required by the base
install. Importing this module (or ``arkleon`` / ``arkleon.edgar``) works
fine without pandas installed; pandas is only imported lazily inside
``facts_to_dataframe`` at call time.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Iterable

from .models import Fact

if TYPE_CHECKING:
    import pandas as pd

_FACT_COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(Fact))


def facts_to_dataframe(facts: Iterable[Fact]) -> "pd.DataFrame":
    """Convert a FactSet (or any iterable of Fact) into a pandas DataFrame.

    The DataFrame has one row per fact, with columns matching the Fact
    dataclass fields in declaration order: cik, tag, taxonomy, value, unit,
    period_start, period_end, instantaneous, form, filed, accession.

    Raises:
        ImportError: if the optional ``pandas`` extra is not installed.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "facts_to_dataframe requires the 'pandas' extra: pip install 'arkleon[pandas]'"
        ) from exc

    rows = [asdict(fact) for fact in facts]
    if not rows:
        return pd.DataFrame(columns=list(_FACT_COLUMNS))
    return pd.DataFrame(rows)
