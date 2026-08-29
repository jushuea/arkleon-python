"""Request shaping and error mapping for the paid /v1 DataClient, fully mocked.

Every request is served by an injected httpx.MockTransport, so no request leaves
the process. The paid gate itself (resolve_api_key) is exercised directly.
"""

from __future__ import annotations

import httpx
import pytest

import arkleon.api as api
from arkleon.api.auth import resolve_api_key


def _client(handler, captured: list[httpx.Request] | None = None) -> api.DataClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return handler(request)

    return api.DataClient(
        api_key="ak_test",
        client=httpx.Client(transport=httpx.MockTransport(wrapped)),
    )


def test_authorization_header_present() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    client = _client(handler, captured)
    client.facts(as_of="2024-01-01", cik=320193)

    assert captured[0].headers.get("Authorization") == "Bearer ak_test"


def test_facts_requires_as_of() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent when as_of is invalid")

    client = _client(handler)
    # as_of is keyword-only with no default: omitting it is a TypeError.
    with pytest.raises(TypeError):
        client.facts(cik=320193)  # type: ignore[call-arg]
    # Passing None explicitly is caught locally as a RequestError.
    with pytest.raises(api.RequestError):
        client.facts(as_of=None, cik=320193)  # type: ignore[arg-type]


def test_facts_rejects_cik_and_ticker_together() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent on a local validation error")

    client = _client(handler)
    with pytest.raises(api.RequestError):
        client.facts(as_of="2024-01-01", cik=320193, ticker="AAPL")


def test_facts_query_params_shaped() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "next_cursor": None})

    client = _client(handler, captured)
    client.facts(as_of="2024-01-01", cik=320193, tag="Assets")

    params = captured[0].url.params
    assert params.get("as_of") == "2024-01-01"
    assert params.get("cik") == "320193"
    assert params.get("tag") == "Assets"
    assert params.get("limit") == "100"
    # Unset filters are dropped, not sent as empty or "None".
    assert "ticker" not in params
    assert "taxonomy" not in params
    assert "cursor" not in params


def test_ticker_501_raises_not_served() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            501,
            json={
                "error": "not_implemented",
                "message": "ticker is not served in v1",
                "error_id": "eid-501",
            },
        )

    client = _client(handler)
    with pytest.raises(api.NotServedError) as excinfo:
        client.facts(as_of="2024-01-01", ticker="AAPL")

    exc = excinfo.value
    # NotServedError is catchable as the builtin NotImplementedError too.
    assert isinstance(exc, NotImplementedError)
    assert api.NotImplementedError is api.NotServedError
    assert exc.error == "not_implemented"
    assert exc.error_id == "eid-501"


def test_facts_iter_paginates_with_stable_as_of() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        if cursor is None:
            record = {
                "tag": "Assets",
                "value": 1,
                "created_via": "fsds_ingest",
                "ingested_at": "2024-01-01T00:00:00Z",
                "run_id": "run-1",
                "accepted": True,
            }
            return httpx.Response(200, json={"data": [record], "next_cursor": "opaque-2"})
        record = {
            "tag": "Assets",
            "value": 2,
            "created_via": "fsds_ingest",
            "ingested_at": "2024-01-02T00:00:00Z",
            "run_id": "run-2",
            "accepted": True,
        }
        return httpx.Response(200, json={"data": [record], "next_cursor": None})

    client = _client(handler, captured)
    records = list(client.facts_iter(as_of="2024-01-01", cik=320193))

    # Both pages are yielded, in order.
    assert [r["value"] for r in records] == [1, 2]
    # Internal telemetry is stripped from every returned record.
    for record in records:
        assert set(record) == {"tag", "value"}
        assert "created_via" not in record
        assert "ingested_at" not in record
        assert "run_id" not in record
        assert "accepted" not in record

    # The same as_of is resent on every page; the cursor is opaque.
    assert len(captured) == 2
    as_ofs = [req.url.params.get("as_of") for req in captured]
    assert as_ofs == ["2024-01-01", "2024-01-01"]
    assert captured[0].url.params.get("cursor") is None
    assert captured[1].url.params.get("cursor") == "opaque-2"


def test_single_page_data_strips_internal_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        record = {
            "tag": "Revenues",
            "value": 42,
            "created_via": "fsds_ingest",
            "ingested_at": "2024-01-01T00:00:00Z",
            "run_id": "run-9",
            "accepted": True,
        }
        return httpx.Response(200, json={"data": [record], "next_cursor": None})

    client = _client(handler)
    page = client.facts(as_of="2024-01-01", cik=320193)
    assert page.data == [{"tag": "Revenues", "value": 42}]
    assert page.as_of == "2024-01-01"


def test_error_from_envelope_mapping() -> None:
    rate = api.error_from_envelope(
        429,
        {
            "error": "rate_limited",
            "message": "slow down",
            "retry_after": 5,
            "error_id": "eid-429",
        },
    )
    assert isinstance(rate, api.RateLimitError)
    assert rate.retry_after == 5
    assert rate.error_id == "eid-429"

    server = api.error_from_envelope(503, {"error": "dependency_unavailable", "message": "down"})
    assert isinstance(server, api.ServerError)

    # An unknown 5xx code collapses to the status-mapped ServerError default.
    unknown = api.error_from_envelope(503, {"error": "totally_unknown_code", "message": "boom"})
    assert isinstance(unknown, api.ServerError)

    not_found = api.error_from_envelope(
        404, {"error": "not_found", "message": "no such route", "error_id": "eid-404"}
    )
    assert isinstance(not_found, api.NotFoundError)
    assert not_found.error_id == "eid-404"


def test_resolve_api_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARKLEON_API_KEY", raising=False)
    # No key at all.
    with pytest.raises(api.AuthError):
        resolve_api_key(None)
    # A non-ak key is rejected.
    with pytest.raises(api.AuthError):
        resolve_api_key("sk_not_an_arkleon_key")
    # A well-formed ak_ key resolves.
    assert resolve_api_key("ak_live_123") == "ak_live_123"
