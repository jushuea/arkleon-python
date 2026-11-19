"""Mocked request and response coverage for the additional /v1 client surface."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import arkleon.api as api


def _client(handler, captured: list[httpx.Request] | None = None) -> api.DataClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return handler(request)

    return api.DataClient(
        api_key="ak_test",
        client=httpx.Client(transport=httpx.MockTransport(wrapped)),
    )


def _fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "v1" / name).read_text())


def test_facts_concept_alias_query_and_matched_tag() -> None:
    captured: list[httpx.Request] = []
    fixture = _fixture("facts-concept-alias.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    client = _client(handler, captured)
    page = client.facts(as_of="2024-06-28", cik=1, concept_alias="revenue")

    assert captured[0].url.params["concept_alias"] == "revenue"
    assert "tag" not in captured[0].url.params
    assert page.data[0] == fixture["data"][0]
    assert page.data[0]["matched_tag"] == "us-gaap:Revenues"


def test_facts_rejects_concept_alias_with_tag() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent")

    client = _client(handler, captured)
    with pytest.raises(api.RequestError) as excinfo:
        client.facts(as_of="2024-06-28", tag="Revenues", concept_alias="revenue")
    assert excinfo.value.error == "invalid_request"
    assert captured == []


def test_facts_omits_unset_concept_alias() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    client = _client(handler, captured)
    client.facts(as_of="2024-06-28", cik=1, tag="Revenues")
    assert "concept_alias" not in captured[0].url.params
    assert captured[0].url.params["tag"] == "Revenues"


@pytest.mark.parametrize("selectors", [{}, {"segments": ""}, {"unit": "USD", "segments": "", "coreg": ""}])
def test_ttm_query_and_single_object_response(selectors: dict) -> None:
    captured: list[httpx.Request] = []
    fixture = _fixture("ttm.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    client = _client(handler, captured)
    result = client.ttm(
        cik=1,
        tag="Revenues",
        taxonomy="us-gaap/2024",
        fiscal_year=2024,
        fiscal_quarter=4,
        as_of="2025-02-28",
        **selectors,
    )
    assert captured[0].url.path.endswith("/ttm")
    assert dict(captured[0].url.params) == {
        "cik": "1",
        "tag": "Revenues",
        "taxonomy": "us-gaap/2024",
        "fiscal_year": "2024",
        "fiscal_quarter": "4",
        "as_of": "2025-02-28",
        **selectors,
    }
    assert result == fixture
    assert "data" not in result
    assert "_pagination_valid" not in result


def test_ttm_requires_as_of() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent")

    client = _client(handler, captured)
    with pytest.raises(api.RequestError) as excinfo:
        client.ttm(
            cik=1,
            tag="Revenues",
            taxonomy="us-gaap/2024",
            fiscal_year=2024,
            fiscal_quarter=4,
            as_of=None,  # type: ignore[arg-type]
        )
    assert excinfo.value.error == "invalid_request"
    assert captured == []


@pytest.mark.parametrize("selectors", [{}, {"ticker": "TEST", "cik": 1}])
def test_identifiers_requires_exactly_one_selector(selectors: dict) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent")

    client = _client(handler, captured)
    with pytest.raises(api.RequestError) as excinfo:
        client.identifiers(**selectors)
    assert excinfo.value.error == "invalid_request"
    assert captured == []


def test_identifiers_echoes_effective_as_of_for_next_page() -> None:
    captured: list[httpx.Request] = []
    first = _fixture("identifiers-page-1.json")
    second = _fixture("identifiers-page-2.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=second if "cursor" in request.url.params else first)

    client = _client(handler, captured)
    page = client.identifiers(ticker="TEST")
    assert captured[0].url.path.endswith("/identifiers")
    assert dict(captured[0].url.params) == {"ticker": "TEST", "limit": "100"}
    assert "as_of" not in captured[0].url.params
    assert page.as_of == "2024-06-28"
    assert page.data == first["data"]
    assert page.next_cursor == "c1"
    assert page.request == {"ticker": "TEST", "limit": 100}
    assert page.pagination_valid is True

    next_page = client.identifiers(ticker="TEST", cursor="c1", as_of=page.as_of)
    assert dict(captured[1].url.params) == {
        "ticker": "TEST",
        "as_of": "2024-06-28",
        "limit": "100",
        "cursor": "c1",
    }
    assert next_page.data == second["data"]
    assert next_page.as_of == page.as_of
    assert next_page.next_cursor is None
    assert next_page.request == {"ticker": "TEST", "as_of": "2024-06-28", "limit": 100}
    assert next_page.pagination_valid is True
