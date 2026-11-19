"""LlamaIndex reader for facts from the paid Arkleon /v1 Data API."""

from __future__ import annotations

try:
    from llama_index.core import Document
    from llama_index.core.readers.base import BaseReader
except ImportError as error:
    raise ImportError('Install the LlamaIndex integration with: pip install "arkleon[llamaindex]"') from error

from arkleon.api import DataClient


class ArkleonDataFactsReader(BaseReader):
    """Read facts filed on or before a required cutoff from the paid /v1 DataClient."""

    def __init__(
        self, client: DataClient | None = None, api_key: str | None = None
    ) -> None:
        super().__init__()
        self._client = client if client is not None else DataClient(api_key=api_key)

    def load_data(
        self,
        cik: int,
        as_of: str,
        tag: str | None = None,
        concept_alias: str | None = None,
        taxonomy: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        duration_quarters: int | None = None,
        unit: str | None = None,
        form: str | None = None,
        limit: int = 100,
    ) -> list[Document]:
        documents: list[Document] = []
        cursor: str | None = None
        while True:
            page = self._client.facts(
                as_of=as_of,
                cik=cik,
                tag=tag,
                concept_alias=concept_alias,
                taxonomy=taxonomy,
                period_start=period_start,
                period_end=period_end,
                duration_quarters=duration_quarters,
                unit=unit,
                form=form,
                limit=limit,
                cursor=cursor,
            )
            concept = page.concept
            extra = (
                {
                    "concept_alias": concept.get("alias"),
                    "concept_provisional": concept.get("provisional"),
                    "concept_note": concept.get("note"),
                }
                if concept is not None
                else {}
            )
            for fact in page.data:
                documents.append(
                    Document(
                        text=(
                            f"{fact.get('tag')} {fact.get('value')} {fact.get('unit')} "
                            f"for the period ending {fact.get('period_end')}, "
                            f"filed {fact.get('filed')} in {fact.get('form')} {fact.get('accession_id')}"
                        ),
                        metadata={**fact, "as_of": as_of, **extra},
                    )
                )
            cursor = page.next_cursor
            if not cursor:
                return documents
