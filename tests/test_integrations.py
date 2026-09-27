"""Exercise optional integrations against recorded SEC companyconcept responses."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
import runpy

import httpx
import pytest

from arkleon.edgar import AS_OF_WARNING, EdgarClient

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
USER_AGENT = "Arkleon tests tests@example.com"
AS_OF = "2015-01-01"


def _fixture_path(tag):
    return FIXTURES / f"companyconcept-CIK0000320193-us-gaap-{tag}.json"


def _expected_facts(tag):
    payload = json.loads(_fixture_path(tag).read_bytes())
    return [
        {
            "cik": payload["cik"],
            "tag": tag,
            "taxonomy": "us-gaap",
            "period_start": record.get("start"),
            "period_end": record["end"],
            "value": record["val"],
            "unit": unit,
            "form": record["form"],
            "filed": record["filed"],
            "accession": record["accn"],
            "instantaneous": record.get("start") is None,
            "segments": None,
            "coreg": None,
        }
        for unit, records in payload["units"].items()
        for record in records
        if record["filed"] <= AS_OF
    ]


@pytest.fixture
def edgar_client():
    requests = []

    def handle(request):
        requests.append(request)
        tag = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        assert tag in {"Assets", "NetIncomeLoss"}
        return httpx.Response(200, content=_fixture_path(tag).read_bytes())

    client = EdgarClient(user_agent=USER_AGENT, transport=httpx.MockTransport(handle))
    try:
        yield client, requests
    finally:
        client._client.close()


@pytest.fixture
def tool_class():
    pytest.importorskip("langchain_core")
    from arkleon.integrations.langchain import ArkleonEdgarFactsTool

    return ArkleonEdgarFactsTool


@pytest.fixture
def reader_class():
    pytest.importorskip("llama_index.core")
    from arkleon.integrations.llamaindex import ArkleonEdgarFactsReader

    return ArkleonEdgarFactsReader


def _assert_request(requests, tag):
    assert len(requests) == 1
    assert str(requests[0].url) == (
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/{tag}.json"
    )
    assert requests[0].headers["User-Agent"] == USER_AGENT


def test_tool_contract(tool_class, edgar_client):
    tool = tool_class(client=edgar_client[0])
    assert tool.name == "arkleon_edgar_facts"
    assert "filing date" in tool.description.lower()
    assert "best-effort" in tool.description.lower()
    assert "not certified" in tool.description.lower()
    schema = tool.args_schema.model_json_schema()
    assert "as_of" in schema["required"]
    assert schema["properties"]["taxonomy"]["default"] == "us-gaap"
    with pytest.raises(ValueError):
        tool.invoke({"cik": 320193, "tag": "Assets"})
    assert not edgar_client[1]


@pytest.mark.parametrize("tag", ["Assets", "NetIncomeLoss"])
@pytest.mark.parametrize("cik", [320193, "0000320193"])
def test_tool_facts(tool_class, edgar_client, tag, cik):
    client, requests = edgar_client
    result = tool_class(client=client).invoke({"cik": cik, "tag": tag, "as_of": AS_OF})
    expected = _expected_facts(tag)
    assert expected
    assert len(result["facts"]) == len(expected)
    assert all(fact["filed"] <= AS_OF for fact in result["facts"])
    assert result == {
        "cik": cik,
        "tag": tag,
        "taxonomy": "us-gaap",
        "as_of": AS_OF,
        "warning": AS_OF_WARNING,
        "facts": expected,
    }
    _assert_request(requests, tag)


@pytest.mark.parametrize("tag", ["Assets", "NetIncomeLoss"])
@pytest.mark.parametrize("cik", [320193, "0000320193"])
def test_reader_facts(reader_class, edgar_client, tag, cik):
    from llama_index.core import Document

    client, requests = edgar_client
    documents = reader_class(client=client).load_data(cik, tag, AS_OF)
    expected = _expected_facts(tag)
    assert expected
    assert len(documents) == len(expected)
    for document, fact in zip(documents, expected):
        assert isinstance(document, Document)
        assert document.metadata["filed"] <= AS_OF
        assert document.metadata == {
            **fact,
            "cik": cik,
            "as_of": AS_OF,
            "warning": AS_OF_WARNING,
        }
        assert document.text == (
            f"{tag} {fact['value']} {fact['unit']} for the period ending "
            f"{fact['period_end']}, filed {fact['filed']} in {fact['form']} {fact['accession']}"
        )
    _assert_request(requests, tag)


@pytest.mark.parametrize("as_of", ["invalid", "2015-1-01", "20150101", "2015-02-30", "2015-01-01T00:00:00"])
def test_tool_invalid_as_of(tool_class, edgar_client, as_of):
    client, requests = edgar_client
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        tool_class(client=client).invoke({"cik": 320193, "tag": "Assets", "as_of": as_of})
    assert not requests


@pytest.mark.parametrize("as_of", ["invalid", "2015-1-01", "20150101", "2015-02-30", "2015-01-01T00:00:00"])
def test_reader_invalid_as_of(reader_class, edgar_client, as_of):
    client, requests = edgar_client
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        reader_class(client=client).load_data(320193, "Assets", as_of)
    assert not requests


@pytest.mark.parametrize(
    ("module", "dependency", "extra"),
    [("langchain", "langchain_core", "langchain"), ("llamaindex", "llama_index", "llamaindex")],
)
def test_missing_optional_dependency(monkeypatch, module, dependency, extra):
    original_import = builtins.__import__

    def import_without_dependency(name, *args, **kwargs):
        if name == dependency or name.startswith(dependency + "."):
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_dependency)
    path = Path(__file__).parents[1] / "src" / "arkleon" / "integrations" / f"{module}.py"
    with pytest.raises(ImportError) as error:
        runpy.run_path(str(path))
    assert f'pip install "arkleon[{extra}]"' in str(error.value)
