"""Throttling and HTTP request shaping for the free EDGAR core, fully mocked.

The RateLimiter is tested against an injected fake clock so spacing is asserted
deterministically with no real sleeping. The EdgarClient is tested against an
injected httpx.MockTransport so no request ever leaves the process.
"""

from __future__ import annotations

import httpx
import pytest

import arkleon.edgar as edgar
import arkleon.edgar.fetch as fetch_mod


class _FakeClock:
    """A controllable stand-in for the time module used inside fetch.

    monotonic() returns the current virtual time; sleep(s) records the request
    and advances the virtual clock by s, so a subsequent monotonic() reflects
    the sleep exactly as the real pair would.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_enforces_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    # Patch only the fetch module's time reference, not the global module.
    monkeypatch.setattr(fetch_mod, "time", clock)

    limiter = edgar.RateLimiter(10.0)  # 10 req/s -> 0.1s minimum spacing
    limiter.acquire()  # first acquire: far past the window, no sleep
    limiter.acquire()  # immediate second acquire: must wait ~1/rate

    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(0.1, abs=1e-9)


def test_rate_limiter_rejects_nonpositive_rate() -> None:
    with pytest.raises(ValueError):
        edgar.RateLimiter(0)


def _submissions_payload() -> dict:
    return {
        "cik": "320193",
        "name": "APPLE INC",
        "sic": "3571",
        "fiscalYearEnd": "0930",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106"],
                "form": ["10-K"],
                "filingDate": ["2023-11-03"],
                "reportDate": ["2023-09-30"],
                "primaryDocument": ["aapl-10k.htm"],
            }
        },
    }


def _concept_payload() -> dict:
    return {
        "cik": 320193,
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "units": {
            "USD": [
                {
                    "end": "2023-09-30",
                    "val": 352755000000,
                    "form": "10-K",
                    "filed": "2023-11-03",
                    "accn": "0000320193-23-000106",
                }
            ]
        },
    }


def _facts_payload() -> dict:
    return {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-09-30",
                                "val": 352755000000,
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            }
                        ]
                    }
                }
            }
        },
    }


def _routing_client(recorder: list[tuple[str, str | None]]) -> edgar.EdgarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        recorder.append((url, request.headers.get("User-Agent")))
        if "/submissions/" in url:
            return httpx.Response(200, json=_submissions_payload())
        if "/api/xbrl/companyconcept/" in url:
            return httpx.Response(200, json=_concept_payload())
        if "/api/xbrl/companyfacts/" in url:
            return httpx.Response(200, json=_facts_payload())
        return httpx.Response(404, json={})

    # A very high rate keeps the single-request paths from sleeping.
    return edgar.EdgarClient(
        user_agent="Tester test@example.com",
        requests_per_second=1e9,
        transport=httpx.MockTransport(handler),
    )


def test_edgar_client_sends_user_agent_and_correct_urls() -> None:
    recorder: list[tuple[str, str | None]] = []
    client = _routing_client(recorder)

    filings = client.filings(320193)
    assert [f.form for f in filings] == ["10-K"]
    assert filings[0].cik == 320193

    factset = client.concept(320193, "Assets")
    assert factset.to_list()[0].value == 352755000000

    facts = client.facts(320193)
    assert facts.to_list()[0].tag == "Assets"

    urls = [url for url, _ in recorder]
    assert "https://data.sec.gov/submissions/CIK0000320193.json" in urls
    assert (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json"
        in urls
    )
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json" in urls
    # The SEC fair-access User-Agent is sent on every request.
    assert all(ua == "Tester test@example.com" for _, ua in recorder)


def test_edgar_client_requires_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent without a User-Agent")

    client = edgar.EdgarClient(transport=httpx.MockTransport(handler))
    # The UA is resolved lazily, so the error surfaces when a live method runs.
    with pytest.raises(edgar.MissingUserAgentError):
        client.filings(320193)
