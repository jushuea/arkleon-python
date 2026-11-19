"""Paid framework integrations exercised with synthetic facts and stub clients."""

import pytest

from arkleon.api import AuthError, Page


FACT = {
    "accession_id": "0000320193-23-000001",
    "tag": "Assets",
    "taxonomy": "us-gaap/2023",
    "period_end": "2023-09-30",
    "duration_quarters": 0,
    "unit": "USD",
    "segments": None,
    "coreg": None,
    "value": 123,
    "form": "10-K",
    "filed": "2023-11-01",
    "cik": 320193,
    "source_url": "https://example.invalid/filing",
    "matched_tag": "Assets",
}


class StubClient:
    def __init__(self):
        self.facts_kwargs = None
        self.facts_iter_kwargs = None

    def facts(self, **kwargs):
        self.facts_kwargs = kwargs
        return Page(data=[FACT], next_cursor="c1", as_of=kwargs["as_of"])

    def facts_iter(self, **kwargs):
        self.facts_iter_kwargs = kwargs
        return iter([FACT])


@pytest.fixture
def tool_class():
    pytest.importorskip("langchain_core")
    from arkleon.integrations.langchain_data import ArkleonDataFactsTool

    return ArkleonDataFactsTool


@pytest.fixture
def reader_class():
    pytest.importorskip("llama_index.core")
    from arkleon.integrations.llamaindex_data import ArkleonDataFactsReader

    return ArkleonDataFactsReader


def test_tool_concept_alias(tool_class):
    stub = StubClient()
    tool = tool_class(client=stub)
    result = tool.invoke(
        {"cik": 320193, "as_of": "2024-01-01", "concept_alias": "revenue"}
    )
    assert stub.facts_kwargs["concept_alias"] == "revenue"
    assert stub.facts_kwargs["tag"] is None
    assert stub.facts_kwargs["cik"] == 320193
    assert stub.facts_kwargs["as_of"] == "2024-01-01"
    assert set(result) == {"as_of", "data", "next_cursor"}
    assert result == {"as_of": "2024-01-01", "data": [FACT], "next_cursor": "c1"}
    assert "warning" not in result
    assert tool.name == "arkleon_data_facts"


def test_reader_tag(reader_class):
    from llama_index.core import Document

    stub = StubClient()
    docs = reader_class(client=stub).load_data(
        cik=320193, as_of="2024-01-01", tag="Assets"
    )
    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].metadata["as_of"] == "2024-01-01"
    assert docs[0].metadata == {**FACT, "as_of": "2024-01-01"}
    assert "warning" not in docs[0].metadata
    assert docs[0].text == (
        "Assets 123 USD for the period ending 2023-09-30, "
        "filed 2023-11-01 in 10-K 0000320193-23-000001"
    )
    assert stub.facts_iter_kwargs["tag"] == "Assets"
    assert stub.facts_iter_kwargs["concept_alias"] is None
    assert stub.facts_iter_kwargs["cik"] == 320193
    assert stub.facts_iter_kwargs["as_of"] == "2024-01-01"


def test_tool_requires_key(tool_class, monkeypatch):
    monkeypatch.delenv("ARKLEON_API_KEY", raising=False)
    with pytest.raises(AuthError):
        tool_class()


def test_reader_requires_key(reader_class, monkeypatch):
    monkeypatch.delenv("ARKLEON_API_KEY", raising=False)
    with pytest.raises(AuthError):
        reader_class()


def test_free_tool_name(tool_class):
    from arkleon.integrations.langchain import ArkleonEdgarFactsTool

    assert ArkleonEdgarFactsTool(client=StubClient()).name == "arkleon_edgar_facts"


def test_tool_forwards_filters(tool_class):
    stub = StubClient()
    params = {
        "cik": 320193,
        "as_of": "2024-01-01",
        "tag": "Assets",
        "concept_alias": None,
        "taxonomy": "us-gaap/2023",
        "period_start": "2023-01-01",
        "period_end": "2023-12-31",
        "duration_quarters": 0,
        "unit": "USD",
        "form": "10-K",
        "limit": 25,
        "cursor": "c0",
    }
    tool_class(client=stub).invoke(params)
    assert stub.facts_kwargs == params


def test_reader_forwards_filters(reader_class):
    stub = StubClient()
    params = {
        "cik": 320193,
        "as_of": "2024-01-01",
        "tag": None,
        "concept_alias": "revenue",
        "taxonomy": "us-gaap/2023",
        "period_start": "2023-01-01",
        "period_end": "2023-12-31",
        "duration_quarters": 4,
        "unit": "USD",
        "form": "10-K",
        "limit": 25,
    }
    reader_class(client=stub).load_data(**params)
    assert stub.facts_iter_kwargs == params
