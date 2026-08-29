"""Thin, faithful client for the Arkleon /v1 Data API.

This client adds no semantics the contract at
``docs/data-layer/api-v1-contract.md`` does not define. It is a transport
wrapper: it presents an ak_ key on every request (the paid gate, section 6.2),
enforces the caller-preventable validations the contract specifies locally,
maps the closed error alphabet to typed exceptions (section 4.2), paginates by
opaque cursor while keeping as_of stable (section 2.1.3), and exposes only the
public /v1 vocabulary on returned facts, never the internal FSDS or ingest
telemetry columns (section 3.1.1).

The value this client has over the free EDGAR core's best-effort as_of filter
is the corpus's permanent-reproducibility guarantee (contract section 3.2):
identical query plus identical as_of returns identical data, permanently. The
client does nothing to undermine that: it never caches then serves a stale
value as if it were authoritative, and it never substitutes "today" for a
missing as_of.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from .auth import resolve_api_key
from .errors import RateLimitError, RequestError, error_from_envelope
from .pagination import Page, paginate

__all__ = ["DataClient"]

DEFAULT_BASE_URL = "https://api.arkleon.com/v1"

# Internal ingest telemetry the contract forbids on /v1 (section 3.1.1). The
# server MUST NOT emit these; the client strips them as defense in depth so a
# non-conforming server can never leak them to a caller.
_INTERNAL_FIELDS = frozenset({"created_via", "ingested_at", "run_id", "accepted"})

# Ceiling on a single honored Retry-After sleep, so a pathological or hostile
# Retry-After value cannot block a caller unboundedly.
_MAX_RETRY_AFTER_SLEEP_SECONDS = 120.0


def _strip_internal(record: Any) -> Any:
    """Remove forbidden internal telemetry fields from one record."""
    if isinstance(record, dict):
        return {key: value for key, value in record.items() if key not in _INTERNAL_FIELDS}
    return record


class DataClient:
    """Client for the three /v1 endpoints: facts, filings, companies."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        max_rate_limit_retries: int = 2,
    ) -> None:
        """Construct the client and resolve the paid gate immediately.

        ``api_key`` (or ARKLEON_API_KEY) must be an ak_-prefixed key or
        construction raises AuthError locally, before any network contact
        (contract section 6.2). ``base_url`` must be https. Pass ``client`` to
        inject a preconfigured httpx.Client (for tests or custom transports);
        otherwise one is created and owned by this instance.
        ``max_rate_limit_retries`` bounds how many times a 429 is retried while
        honoring the server's Retry-After (contract section 1.3).
        """
        # Fail closed at construction: no client exists without a valid key.
        self._api_key = resolve_api_key(api_key)
        if not base_url.lower().startswith("https://"):
            raise ValueError("base_url must be https; /v1 is HTTPS only (contract section 6.1).")
        self._base_url = base_url.rstrip("/")
        self._max_rate_limit_retries = max(0, int(max_rate_limit_retries))
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the underlying httpx client if this instance owns it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        # The key is presented on every request and never logged (section 6.2).
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        # Drop unset filters so the server sees only supplied values. The cursor
        # is passed through untouched and never parsed (section 2.1.3).
        return {key: value for key, value in params.items() if value is not None}

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        cleaned = self._clean_params(params)
        attempts = self._max_rate_limit_retries + 1
        for attempt in range(attempts):
            response = self._client.get(url, params=cleaned, headers=self._headers())
            if response.status_code < 400:
                return self._parse_success(response)
            exception = self._exception_for(response)
            if (
                isinstance(exception, RateLimitError)
                and attempt < attempts - 1
                and exception.retry_after is not None
            ):
                # Honor the server's Retry-After rather than a fixed schedule
                # (contract section 1.3), capped to avoid unbounded blocking.
                time.sleep(min(float(exception.retry_after), _MAX_RETRY_AFTER_SLEEP_SECONDS))
                continue
            raise exception
        # Unreachable: the loop either returns or raises on the final attempt.
        raise RuntimeError("unreachable pagination retry loop")

    def _exception_for(self, response: httpx.Response) -> Exception:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        exception = error_from_envelope(response.status_code, body)
        # If the 429 envelope did not carry retry_after, take it from the
        # mandatory Retry-After header (contract section 1.3).
        if isinstance(exception, RateLimitError) and exception.retry_after is None:
            header = response.headers.get("Retry-After")
            if header is not None:
                try:
                    exception.retry_after = float(header)
                except ValueError:
                    exception.retry_after = None
        return exception

    def _parse_success(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise error_from_envelope(
                502, {"error": "internal_error", "message": "Malformed response body"}
            ) from error
        if not isinstance(payload, dict):
            raise error_from_envelope(
                502, {"error": "internal_error", "message": "Malformed response body"}
            )
        data = payload.get("data", [])
        if not isinstance(data, list):
            data = []
        payload["data"] = [_strip_internal(record) for record in data]
        return payload

    def _page(self, path: str, params: dict[str, Any], *, as_of: str | None) -> Page:
        payload = self._request(path, params)
        next_cursor = payload.get("next_cursor")
        next_cursor = next_cursor if isinstance(next_cursor, str) else None
        request_context = {
            key: value for key, value in self._clean_params(params).items() if key != "cursor"
        }
        return Page(
            data=list(payload["data"]),
            next_cursor=next_cursor,
            as_of=as_of,
            request=request_context,
        )

    # -- /v1/facts ---------------------------------------------------------

    def facts(
        self,
        *,
        as_of: str,
        cik: int | None = None,
        tag: str | None = None,
        taxonomy: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        duration_quarters: int | None = None,
        unit: str | None = None,
        form: str | None = None,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        """GET /v1/facts: certified point-in-time numeric facts.

        ``as_of`` is REQUIRED and has NO default. It filters on the FILING date
        (``filed <= as_of``), never on the period a fact describes: a fact from
        a filing submitted after as_of never appears, regardless of the period
        it reports (contract section 2.1.1). Omitting as_of raises RequestError
        locally, before any request: the client MUST NOT substitute "today,"
        because the caller who forgot as_of is the caller who most needs to be
        stopped. Use period_start / period_end to bound the fact's period.

        ``cik`` and ``ticker`` MUST NOT both be supplied (contract section
        2.1.2); doing so raises RequestError locally. ``ticker`` is not served
        in v1: the request is forwarded and the server's 501 surfaces as
        NotServedError, never a silent free-core resolution (contract section
        2.3.1, spec section 6.4). Address facts by ``cik``.
        """
        if as_of is None:
            raise RequestError(
                "as_of is required on facts() and has no default; the client will "
                "not substitute today (contract section 2.1.1).",
                error="invalid_request",
            )
        if cik is not None and ticker is not None:
            raise RequestError(
                "cik and ticker must not both be supplied (contract section 2.1.2).",
                error="invalid_request",
            )
        params: dict[str, Any] = {
            "as_of": as_of,
            "cik": cik,
            "tag": tag,
            "taxonomy": taxonomy,
            "period_start": period_start,
            "period_end": period_end,
            "duration_quarters": duration_quarters,
            "unit": unit,
            "form": form,
            "ticker": ticker,
            "limit": limit,
            "cursor": cursor,
        }
        return self._page("/facts", params, as_of=as_of)

    def facts_iter(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Iterate every fact across pages, resending the same as_of.

        Accepts the same keyword arguments as facts(). The same as_of is
        resent on every page so the result set stays as_of-stable; a mismatched
        as_of on a cursor request is a 400 the iterator prevents by
        construction (contract section 2.1.3). Any incoming ``cursor`` is
        ignored: iteration always starts from the beginning.
        """
        kwargs.pop("cursor", None)

        def fetch(cursor: str | None) -> Page:
            return self.facts(cursor=cursor, **kwargs)

        return paginate(fetch)

    # -- /v1/filings -------------------------------------------------------

    def filings(
        self,
        *,
        as_of: str | None = None,
        cik: int | None = None,
        ticker: str | None = None,
        form: str | None = None,
        filed_start: str | None = None,
        filed_end: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        """GET /v1/filings: submissions metadata.

        ``as_of`` is optional here and means the same thing: return only filings
        filed on or before the date (contract section 2.2). ``ticker`` is not
        served in v1; the server's 501 surfaces as NotServedError. ``cik`` and
        ``ticker`` MUST NOT both be supplied.
        """
        if cik is not None and ticker is not None:
            raise RequestError(
                "cik and ticker must not both be supplied (contract section 2.1.2).",
                error="invalid_request",
            )
        params: dict[str, Any] = {
            "as_of": as_of,
            "cik": cik,
            "ticker": ticker,
            "form": form,
            "filed_start": filed_start,
            "filed_end": filed_end,
            "period_start": period_start,
            "period_end": period_end,
            "limit": limit,
            "cursor": cursor,
        }
        return self._page("/filings", params, as_of=as_of)

    def filings_iter(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Iterate every filing across pages, resending the same as_of."""
        kwargs.pop("cursor", None)

        def fetch(cursor: str | None) -> Page:
            return self.filings(cursor=cursor, **kwargs)

        return paginate(fetch)

    # -- /v1/companies -----------------------------------------------------

    def companies(
        self,
        *,
        cik: int | None = None,
        name: str | None = None,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        """GET /v1/companies: identifier resolution, cik- and name-addressable.

        In v1 the endpoint is cik- and name-addressable only. ``ticker`` is not
        served and the server's 501 surfaces as NotServedError; resolution rules
        1 to 4 of the contract describe the endpoint's completed form and are
        dormant until a persisted point-in-time ticker to CIK mapping exists
        (contract section 2.3.1). ``cik`` and ``ticker`` MUST NOT both be
        supplied.
        """
        if cik is not None and ticker is not None:
            raise RequestError(
                "cik and ticker must not both be supplied (contract section 2.1.2).",
                error="invalid_request",
            )
        params: dict[str, Any] = {
            "cik": cik,
            "name": name,
            "ticker": ticker,
            "limit": limit,
            "cursor": cursor,
        }
        return self._page("/companies", params, as_of=None)

    # -- opt-in, non-point-in-time convenience -----------------------------

    def facts_by_ticker_via_edgar_snapshot(
        self,
        *,
        ticker: str,
        as_of: str,
        user_agent: str | None = None,
        **facts_kwargs: Any,
    ) -> Page:
        """Resolve a ticker to a CIK via the free EDGAR snapshot, then query facts.

        WARNING: OPT-IN, CURRENT-SNAPSHOT, NON-POINT-IN-TIME. This convenience
        resolves ``ticker`` through SEC's current company_tickers.json snapshot,
        which has no history: a ticker string is reassigned over time and one
        CIK carries several symbols at once. The resolved CIK reflects TODAY's
        assignment, not the assignment in effect on ``as_of``. Using it in a
        backtest can silently hold the wrong company, which is exactly the
        failure the contract's 501-on-ticker rule exists to prevent (contract
        section 2.3.1, spec section 6.4).

        The default facts() path NEVER does this. This method exists only for a
        caller who asks for it by name and accepts the non-point-in-time
        resolution. Prefer addressing facts by ``cik`` directly.
        """
        # arkleon.api MAY depend on arkleon.edgar; the boundary is one
        # directional (edgar never imports api). Imported lazily so the paid
        # client does not pull the free core unless this method is called.
        from arkleon.edgar import EdgarClient

        edgar = EdgarClient(user_agent=user_agent)
        cik = edgar.resolve_cik(ticker)
        return self.facts(as_of=as_of, cik=cik, **facts_kwargs)
