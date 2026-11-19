"""LangChain tool for facts from the paid Arkleon /v1 Data API."""

from __future__ import annotations

from typing import Any

try:
    from langchain_core.tools import BaseTool
except ImportError as error:
    raise ImportError('Install the LangChain integration with: pip install "arkleon[langchain]"') from error

from pydantic import BaseModel, Field, PrivateAttr

from arkleon.api import DataClient


class _DataFactsArgs(BaseModel):
    cik: int = Field(description="The SEC CIK of the company.")
    as_of: str = Field(
        description="Required filing date cutoff: only facts from filings filed on or before as_of."
    )
    tag: str | None = Field(
        default=None,
        description="As-filed XBRL element name, such as Assets. Mutually exclusive with concept_alias.",
    )
    concept_alias: str | None = Field(
        default=None,
        description="Plain-language concept mapped to ordered as-filed tags. Mutually exclusive with tag.",
    )
    taxonomy: str | None = Field(
        default=None, description="Taxonomy version qualifying tag, for example us-gaap/2024."
    )
    period_start: str | None = Field(
        default=None, description="Inclusive lower bound on the fact period end date."
    )
    period_end: str | None = Field(
        default=None, description="Inclusive upper bound on the fact period end date."
    )
    duration_quarters: int | None = Field(
        default=None, description="Period length: 0 instantaneous, 1 quarterly, 4 annual."
    )
    unit: str | None = Field(
        default=None, description="Unit of measure, for example USD or shares."
    )
    form: str | None = Field(default=None, description="Filing form type.")
    limit: int = Field(default=100, description="Maximum page size, 1 to 1000.")
    cursor: str | None = Field(
        default=None, description="Opaque next_cursor from the previous result."
    )


class ArkleonDataFactsTool(BaseTool):
    """Fetch facts filed on or before a required cutoff from the paid /v1 DataClient."""

    name: str = "arkleon_data_facts"
    description: str = (
        "Returns XBRL facts for one company from the paid Arkleon /v1 Data API, "
        "the certified corpus, keeping only facts from filings filed on or before "
        "as_of (filing date). Requires an Arkleon ak_ API key."
    )
    args_schema: type[BaseModel] = _DataFactsArgs
    _client: DataClient = PrivateAttr()

    def __init__(
        self, client: DataClient | None = None, api_key: str | None = None
    ) -> None:
        super().__init__()
        self._client = client if client is not None else DataClient(api_key=api_key)

    def _run(
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
        cursor: str | None = None,
    ) -> dict[str, Any]:
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
        result = {"as_of": as_of, "data": page.data, "next_cursor": page.next_cursor}
        if page.concept is not None:
            result["concept"] = page.concept
        return result
