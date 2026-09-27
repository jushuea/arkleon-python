"""LangChain tool for filing-date-filtered facts from live SEC EDGAR."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

try:
    from langchain_core.tools import BaseTool
except ImportError as error:
    raise ImportError('Install the LangChain integration with: pip install "arkleon[langchain]"') from error

from pydantic import BaseModel, Field, PrivateAttr

from arkleon.edgar import AS_OF_WARNING, EdgarClient


class _EdgarFactsArgs(BaseModel):
    cik: int | str = Field(description="The SEC CIK of the company.")
    tag: str = Field(description="XBRL element name, such as Assets.")
    as_of: str = Field(description="Required filing date cutoff in YYYY-MM-DD format.")
    taxonomy: str = Field(default="us-gaap", description="XBRL taxonomy.")


class ArkleonEdgarFactsTool(BaseTool):
    """Fetch facts filed on or before a required cutoff using EdgarClient."""

    name: str = "arkleon_edgar_facts"
    description: str = (
        "Returns SEC EDGAR XBRL facts for one company and one tag, keeping only "
        "facts filed on or before as_of (filing date), best-effort over live "
        "EDGAR; not certified."
    )
    args_schema: type[BaseModel] = _EdgarFactsArgs
    _client: EdgarClient = PrivateAttr()

    def __init__(
        self, client: EdgarClient | None = None, user_agent: str | None = None
    ) -> None:
        super().__init__()
        self._client = client if client is not None else EdgarClient(user_agent=user_agent)

    def _run(
        self, cik: int | str, tag: str, as_of: str, taxonomy: str = "us-gaap"
    ) -> dict[str, Any]:
        try:
            if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError
        except ValueError as error:
            raise ValueError("as_of must be a valid date in YYYY-MM-DD format") from error

        facts = self._client.concept(cik, tag, taxonomy).as_of(as_of)
        return {
            "cik": cik,
            "tag": tag,
            "taxonomy": taxonomy,
            "as_of": as_of,
            "warning": AS_OF_WARNING,
            "facts": [asdict(fact) for fact in facts],
        }
