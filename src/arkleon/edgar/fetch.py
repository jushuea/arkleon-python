from __future__ import annotations

import time
from typing import Any

import httpx

from .identifiers import build_ticker_map, cik_to_int, normalize_cik
from .parse import FactSet, parse_company_concept, parse_company_facts, parse_submissions
from .useragent import resolve_user_agent

DATA_HOST = "https://data.sec.gov"
WWW_HOST = "https://www.sec.gov"


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.requests_per_second = requests_per_second
        self._last_request = 0.0

    def acquire(self) -> None:
        now = time.monotonic()
        wait = 1.0 / self.requests_per_second - (now - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        requests_per_second: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._user_agent_argument = user_agent
        self._user_agent: str | None = None
        self._timeout = timeout
        self._max_retries = max_retries
        self._limiter = RateLimiter(requests_per_second)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _request(self, url: str, return_bytes: bool) -> httpx.Response:
        if self._user_agent is None:
            self._user_agent = resolve_user_agent(self._user_agent_argument)
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                response = self._client.request(
                    "GET",
                    url,
                    headers={"User-Agent": self._user_agent},
                )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                if attempt == self._max_retries:
                    raise error
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status_code in retryable_statuses and attempt != self._max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
            response.raise_for_status()
            if return_bytes:
                response.read()
            return response
        raise RuntimeError("unreachable retry loop")

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._request(url, return_bytes=False)
        value: object = response.json()
        if not isinstance(value, dict):
            raise TypeError(f"Expected JSON object from {url}")
        return value

    def get_bytes(self, url: str) -> bytes:
        return self._request(url, return_bytes=True).content

    def company(self, cik: int | str) -> Any:
        return parse_submissions(self.get_json(self.submissions_url(cik)))[0]

    def filings(self, cik: int | str, form: str | None = None) -> list[Any]:
        _, filings = parse_submissions(self.get_json(self.submissions_url(cik)))
        return [filing for filing in filings if form is None or filing.form == form]

    def facts(self, cik: int | str) -> FactSet:
        return parse_company_facts(self.get_json(self.company_facts_url(cik)))

    def concept(self, cik: int | str, tag: str, taxonomy: str = "us-gaap") -> FactSet:
        url = self.company_concept_url(cik, taxonomy, tag)
        return parse_company_concept(self.get_json(url))

    def resolve_cik(self, ticker: str) -> int:
        """Resolve a ticker using SEC's current ticker snapshot.

        WARNING: this resolver is explicitly non-point-in-time and lossy. It has
        no ticker history, symbols can be reassigned, one CIK can carry several
        symbols, and duplicate symbols resolve lossily. Use CIK for reproducible
        identity.
        """
        payload = self.get_json(self.company_tickers_url())
        cik = build_ticker_map(payload).get(ticker.strip().upper())
        if cik is None:
            raise ValueError(f"Unknown ticker in current SEC snapshot: {ticker}")
        return cik_to_int(cik)

    @staticmethod
    def submissions_url(cik: int | str) -> str:
        return f"{DATA_HOST}/submissions/CIK{normalize_cik(cik)}.json"

    @staticmethod
    def company_facts_url(cik: int | str) -> str:
        return f"{DATA_HOST}/api/xbrl/companyfacts/CIK{normalize_cik(cik)}.json"

    @staticmethod
    def company_concept_url(cik: int | str, taxonomy: str, tag: str) -> str:
        return f"{DATA_HOST}/api/xbrl/companyconcept/CIK{normalize_cik(cik)}/{taxonomy}/{tag}.json"

    @staticmethod
    def company_tickers_url() -> str:
        return f"{WWW_HOST}/files/company_tickers.json"

    @staticmethod
    def fsds_url(year: int, quarter: int) -> str:
        if quarter not in (1, 2, 3, 4):
            raise ValueError("quarter must be 1, 2, 3, or 4")
        return f"{WWW_HOST}/files/dera/data/financial-statement-data-sets/{year}q{quarter}.zip"

    def fsds(self, year: int, quarter: int) -> bytes:
        return self.get_bytes(self.fsds_url(year, quarter))
