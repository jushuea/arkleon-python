"""Concept metadata survives the client and framework adapters, entirely offline."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from arkleon.api import DataClient


AS_OF = "2024-06-28"
PROVISIONAL_FIXTURE = "facts-concept-alias-provisional.json"


def _fixture(name: str = PROVISIONAL_FIXTURE) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "v1" / name).read_text())


@contextmanager
def _client(handler, captured: list[httpx.Request] | None = None):
    def wrapped(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return handler(request)

    with httpx.Client(transport=httpx.MockTransport(wrapped)) as transport_client:
        yield DataClient(api_key="ak_test", client=transport_client)


@pytest.mark.parametrize(
    "name", ["facts-concept-alias.json", PROVISIONAL_FIXTURE]
)
def test_facts_preserves_concept_metadata(name: str) -> None:
    fixture = _fixture(name)
    with _client(lambda request: httpx.Response(200, json=fixture)) as client:
        page = client.facts(
            as_of=AS_OF,
            cik=fixture["data"][0]["cik"],
            concept_alias=fixture["concept"]["alias"],
        )

    assert page.concept == fixture["concept"]


def test_facts_without_concept_has_no_metadata() -> None:
    body = _fixture()
    del body["concept"]
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        page = client.facts(as_of=AS_OF, cik=2, tag="NetIncomeLoss")

    assert page.concept is None


def test_facts_non_object_concept_has_no_metadata() -> None:
    body = {**_fixture(), "concept": "net_income"}
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        page = client.facts(as_of=AS_OF, cik=2, concept_alias="net_income")

    assert page.concept is None


@pytest.mark.parametrize("include_concept", [False, True])
def test_identifiers_has_no_concept_metadata(include_concept: bool) -> None:
    body = {"data": [], "next_cursor": None, "as_of": "2024-01-01"}
    if include_concept:
        body["concept"] = _fixture()["concept"]
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        page = client.identifiers(cik=2, as_of="2024-01-01")

    assert page.concept is None


def test_facts_concept_metadata_does_not_change_request() -> None:
    fixture = _fixture()
    captured: list[httpx.Request] = []
    with _client(lambda request: httpx.Response(200, json=fixture), captured) as client:
        client.facts(as_of="2024-06-28", cik=2, concept_alias="net_income")

    assert len(captured) == 1
    assert dict(captured[0].url.params) == {
        "as_of": "2024-06-28",
        "cik": "2",
        "concept_alias": "net_income",
        "limit": "100",
    }


@pytest.mark.parametrize("include_concept", [True, False])
def test_langchain_tool_concept_metadata(include_concept: bool) -> None:
    pytest.importorskip("langchain_core")
    from arkleon.integrations.langchain_data import ArkleonDataFactsTool

    fixture = _fixture()
    body = dict(fixture)
    if not include_concept:
        del body["concept"]
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        result = ArkleonDataFactsTool(client=client).invoke(
            {"as_of": AS_OF, "cik": 2, "concept_alias": "net_income"}
            if include_concept
            else {"as_of": AS_OF, "cik": 2, "tag": "NetIncomeLoss"}
        )

    if include_concept:
        assert result["concept"] == fixture["concept"]
        assert result["concept"]["provisional"] is True
    else:
        assert "concept" not in result
        assert set(result) == {"as_of", "data", "next_cursor"}


@pytest.mark.parametrize("include_concept", [True, False])
def test_pit_facts_concept_metadata(monkeypatch, include_concept: bool) -> None:
    import arkleon.mcp.tools as tools

    fixture = _fixture()
    body = dict(fixture)
    if not include_concept:
        del body["concept"]
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        monkeypatch.setattr(tools, "_paid_client", lambda api_key: client)
        spec = next(spec for spec in tools.paid_tool_specs() if spec.name == "pit_facts")
        result = spec.handler(
            {"as_of": AS_OF, "cik": 2, "concept_alias": "net_income"}
            if include_concept
            else {"as_of": AS_OF, "cik": 2, "tag": "NetIncomeLoss"},
            api_key="ak_test",
        )

    if include_concept:
        assert result["concept"] == fixture["concept"]
    else:
        assert "concept" not in result
        assert set(result) == {"data", "next_cursor", "as_of"}


@pytest.mark.parametrize("include_concept", [True, False])
def test_reader_concept_metadata(include_concept: bool) -> None:
    pytest.importorskip("llama_index.core")
    from llama_index.core import Document
    from arkleon.integrations.llamaindex_data import ArkleonDataFactsReader

    fixture = _fixture()
    body = dict(fixture)
    if not include_concept:
        del body["concept"]
    with _client(lambda request: httpx.Response(200, json=body)) as client:
        if include_concept:
            docs = ArkleonDataFactsReader(client=client).load_data(
                as_of=AS_OF, cik=2, concept_alias="net_income"
            )
        else:
            docs = ArkleonDataFactsReader(client=client).load_data(
                as_of=AS_OF, cik=2, tag="NetIncomeLoss"
            )

    assert len(docs) == len(fixture["data"]) == 1
    for doc, fact in zip(docs, fixture["data"]):
        assert isinstance(doc, Document)
        if include_concept:
            assert doc.metadata["concept_alias"] == "net_income"
            assert doc.metadata["concept_provisional"] is True
            assert doc.metadata["concept_note"] == fixture["concept"]["note"]
            assert doc.metadata == {
                **fact,
                "as_of": AS_OF,
                "concept_alias": "net_income",
                "concept_provisional": True,
                "concept_note": fixture["concept"]["note"],
            }
        else:
            assert doc.metadata == {**fact, "as_of": AS_OF}
            assert not {
                "concept_alias", "concept_provisional", "concept_note"
            }.intersection(doc.metadata)


def test_reader_paginates_with_stable_as_of_and_concept() -> None:
    pytest.importorskip("llama_index.core")
    from llama_index.core import Document
    from arkleon.integrations.llamaindex_data import ArkleonDataFactsReader

    fixture = _fixture()
    second_fact = {**fixture["data"][0], "value": 45, "period_end": "2023-12-31"}
    first_page = {**fixture, "next_cursor": "c2"}
    second_page = {**fixture, "data": [second_fact], "next_cursor": None}
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert len(captured) <= 2, "reader requested an unexpected third page"
        if "cursor" not in request.url.params:
            return httpx.Response(200, json=first_page)
        assert request.url.params["cursor"] == "c2"
        return httpx.Response(200, json=second_page)

    with _client(handler, captured) as client:
        docs = ArkleonDataFactsReader(client=client).load_data(
            as_of=AS_OF, cik=2, concept_alias="net_income"
        )

    assert len(docs) == 2
    assert len(captured) == 2
    assert "cursor" not in captured[0].url.params
    assert captured[1].url.params["cursor"] == "c2"
    assert [request.url.params["as_of"] for request in captured] == [AS_OF, AS_OF]
    for doc, fact in zip(docs, [fixture["data"][0], second_fact]):
        assert isinstance(doc, Document)
        assert doc.metadata == {
            **fact,
            "as_of": AS_OF,
            "concept_alias": "net_income",
            "concept_provisional": True,
            "concept_note": fixture["concept"]["note"],
        }
