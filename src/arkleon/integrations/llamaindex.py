"""LlamaIndex reader for filing-date-filtered facts from live SEC EDGAR."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

try:
    from llama_index.core import Document
    from llama_index.core.readers.base import BaseReader
except ImportError as error:
    raise ImportError('Install the LlamaIndex integration with: pip install "arkleon[llamaindex]"') from error

from arkleon.edgar import AS_OF_WARNING, EdgarClient


class ArkleonEdgarFactsReader(BaseReader):
    """Read SEC EDGAR facts by filing date, best-effort and not certified."""

    def __init__(
        self, client: EdgarClient | None = None, user_agent: str | None = None
    ) -> None:
        super().__init__()
        self._client = client if client is not None else EdgarClient(user_agent=user_agent)

    def load_data(
        self, cik: int | str, tag: str, as_of: str, taxonomy: str = "us-gaap"
    ) -> list[Document]:
        try:
            if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError
        except ValueError as error:
            raise ValueError("as_of must be a valid date in YYYY-MM-DD format") from error

        facts = self._client.concept(cik, tag, taxonomy).as_of(as_of)
        return [
            Document(
                text=(
                    f"{tag} {fact.value} {fact.unit} for the period ending "
                    f"{fact.period_end}, filed {fact.filed} in {fact.form} {fact.accession}"
                ),
                metadata={
                    **asdict(fact),
                    "cik": cik,
                    "tag": tag,
                    "taxonomy": taxonomy,
                    "as_of": as_of,
                    "warning": AS_OF_WARNING,
                },
            )
            for fact in facts
        ]
