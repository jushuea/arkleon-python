from __future__ import annotations


class InvalidCIKError(ValueError):
    pass


def normalize_cik(value: int | str) -> str:
    if isinstance(value, bool):
        raise InvalidCIKError("CIK must be an integer or string")
    if isinstance(value, int):
        digits = str(value)
    else:
        stripped = value.strip().upper()
        if stripped.startswith("CIK"):
            stripped = stripped[3:]
        if not stripped.isdigit():
            raise InvalidCIKError(f"Invalid CIK: {value!r}")
        digits = stripped.lstrip("0") or "0"
    if not digits.isdigit() or len(digits) > 10:
        raise InvalidCIKError(f"CIK must be at most 10 digits: {value!r}")
    return digits.zfill(10)


def cik_to_int(value: int | str) -> int:
    return int(normalize_cik(value))


def build_ticker_map(payload: object) -> dict[str, str]:
    """Build uppercase ticker to zero-padded CIK from company_tickers.json.

    This mapping is a current snapshot, not point-in-time. It has no ticker
    history; ticker symbols can be reassigned, and one CIK can carry several
    symbols. Duplicate tickers are resolved lossily to the last record.
    """
    if not isinstance(payload, dict):
        raise TypeError("company_tickers payload must be a JSON object")
    result: dict[str, str] = {}
    for record in payload.values():
        if not isinstance(record, dict):
            continue
        ticker = record.get("ticker")
        cik = record.get("cik_str")
        if not isinstance(ticker, str) or not isinstance(cik, int):
            continue
        result[ticker.upper()] = str(cik).zfill(10)
    return result
