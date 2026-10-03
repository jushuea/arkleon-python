"""Offline preparation of as-filed fundamentals for Lean.

Snapshots are UTF-8 JSON lines, one selected fact per observation/period. Each
line has ``snapshot_version: 1``, an offset-aware ``observation_time``, and the
public fact fields in ``FACT_FIELDS``. Unknown response fields and client state
are never serialized. The file is ordered by observation instant, then period.
No credentials, source URLs, or request headers are stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from arkleon.api import DataClient

__all__ = ["SnapshotError", "AmbiguousFactError", "prepare_snapshot", "visible_as_filed"]

FACT_FIELDS = (
    "cik", "tag", "taxonomy", "unit", "duration_quarters", "value",
    "accession_id", "form", "filed", "accepted_at", "period_end", "segments", "coreg",
)
_IDENTITY = (
    "accession_id", "tag", "taxonomy", "period_end", "duration_quarters",
    "unit", "segments", "coreg",
)
_EASTERN = ZoneInfo("America/New_York")
_INSTANT = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12][0-9]|3[01])"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9])"
    r"(?::(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?)?"
    r"(?:Z|(?P<sign>[+-])(?P<offset_hour>[01][0-9]|2[0-3]):(?P<offset_minute>[0-5][0-9]))"
)


class SnapshotError(ValueError):
    """A snapshot cannot be produced or consumed safely."""


class AmbiguousFactError(SnapshotError):
    """The latest eligible filing does not determine a unique period value."""


def _instant(value: datetime | str) -> datetime:
    if isinstance(value, str):
        match = _INSTANT.fullmatch(value)
        if match is None:
            raise SnapshotError("Expected an ISO 8601 datetime with an explicit offset")
        fields = tuple(int(match[name] or 0) for name in (
            "year", "month", "day", "hour", "minute", "second",
        )) + (int((match["fraction"] or "").ljust(6, "0")),)
        offset_minutes = (
            int(match["offset_hour"] or 0) * 60 + int(match["offset_minute"] or 0)
        ) * (-1 if match["sign"] == "-" else 1)
        try:
            # Check calendar validity (including leap days) before ISO parsing.
            date(*fields[:3])
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SnapshotError("Invalid observation/acceptance datetime") from exc
        # Reject any parser normalization of calendar fields or UTC offset.
        if (
            (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute,
             parsed.second, parsed.microsecond) != fields
            or parsed.utcoffset().total_seconds() != offset_minutes * 60
        ):
            raise SnapshotError("Datetime components changed during parsing")
        value = parsed
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotError("Observation/acceptance times must be timezone-aware")
    # The API accepts offsets only at whole-minute precision.
    if value.utcoffset().total_seconds() % 60:
        raise SnapshotError("Datetime offsets must use whole minutes")
    return value


def _date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected YYYY-MM-DD")
    return date.fromisoformat(value)


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise SnapshotError("Selected fact must have a finite numeric value")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise SnapshotError("Selected fact must have a finite numeric value") from exc
    if not result.is_finite():
        raise SnapshotError("Selected fact must have a finite numeric value")
    return result


def visible_as_filed(
    rows: Iterable[Mapping[str, Any]], instant: datetime | str,
) -> list[dict[str, Any]]:
    """Return a unique consolidated as-filed fact for each period, without I/O.

    Input must describe one CIK/tag/unit/duration series. Taxonomy may vary
    between filings. Missing/malformed acceptance or filing dates are dropped;
    both ``accepted_at <= instant`` and ``filed <= Eastern date(instant)`` apply.
    Only explicitly empty/null segments and coreg are consolidated. Missing
    context is an error. Latest acceptance wins per period, independent of row
    order. Multiple rows at that latest instant (including same-minute filing
    ties or duplicate consolidated contexts) raise ``AmbiguousFactError``.
    Invalid/null selected numbers raise, rather than reviving an older value.
    Returned dictionaries preserve public provenance and do not mutate input.
    """
    cutoff = _instant(instant).astimezone(timezone.utc)
    filing_day = cutoff.astimezone(_EASTERN).date()
    periods: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    series = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise SnapshotError("Fact rows must be mappings")
        try:
            accepted = _instant(row.get("accepted_at")).astimezone(timezone.utc)
            filed = _date(row.get("filed"))
        except (ValueError, TypeError, OverflowError):
            continue
        if accepted > cutoff or filed > filing_day:
            continue
        if "segments" not in row or "coreg" not in row:
            raise SnapshotError("Fact is missing segments/coreg context")
        if row["segments"] not in (None, "", {}, []) or row["coreg"] not in (None, ""):
            continue
        if any(field not in row for field in FACT_FIELDS):
            raise SnapshotError("Eligible consolidated fact is missing public fields")
        if not isinstance(row["accession_id"], str) or not row["accession_id"]:
            raise SnapshotError("Eligible fact is missing accession_id")
        try:
            _date(row["period_end"])
        except (ValueError, TypeError) as exc:
            raise SnapshotError("Eligible fact has an invalid period_end") from exc
        for field in ("cik", "duration_quarters"):
            if type(row[field]) is not int:
                raise SnapshotError(f"Eligible fact {field} must be an integer")
        series.add(json.dumps([row[k] for k in ("cik", "tag", "unit", "duration_quarters")]))
        if len(series) > 1:
            raise SnapshotError("Select one CIK/tag/unit/duration series at a time")
        fact = {field: row[field] for field in FACT_FIELDS}
        periods.setdefault(row["period_end"], []).append((accepted, fact))

    selected = []
    for period, candidates in sorted(periods.items()):
        latest = max(accepted for accepted, _ in candidates)
        winners = [fact for accepted, fact in candidates if accepted == latest]
        if len(winners) != 1:
            raise AmbiguousFactError(
                f"Ambiguous consolidated value for period {period}: "
                "multiple rows from the latest eligible filing/acceptance instant"
            )
        fact = winners[0]
        _number(fact["value"])
        if isinstance(fact["value"], Decimal):
            fact["value"] = str(fact["value"])
        selected.append(fact)
    return selected


def prepare_snapshot(
    client: DataClient, *, cik: int, tag: str, unit: str,
    duration_quarters: int, observation_times: Iterable[datetime | str],
    output_path: str | Path, taxonomy: str | None = None,
    period_start: str | None = None, period_end: str | None = None,
    form: str | None = None, limit: int = 1000, max_pages: int = 10000,
) -> Path:
    """Query every explicit instant and write a new local JSONL snapshot.

    ``period_start``/``period_end`` are inclusive bounds on *period end*, just
    as in DataClient.facts. Set both equal to isolate one period for a Lean
    subscription. Instants must be strictly increasing in UTC; naïve datetimes
    and date-only strings are rejected. Every page repeats every filter and the
    original offset-bearing ``as_of``. Empty pages with advancing cursors are
    followed. Cycles, repeated fact identities, malformed pages, exhausted
    ``max_pages``, and transport errors abort before the output is opened.
    An explicit terminal cursor is the API's completeness signal, not a proof
    of server-side corpus completeness. Existing files are never overwritten.
    Returns the absolute output path. The destination directory must exist.
    """
    if type(cik) is not int or cik <= 0 or not isinstance(tag, str) or not tag:
        raise SnapshotError("A positive integer CIK and nonempty tag are required")
    if not isinstance(unit, str) or not unit:
        raise SnapshotError("A nonempty unit is required")
    if type(duration_quarters) is not int or duration_quarters < 0:
        raise SnapshotError("duration_quarters must be a nonnegative integer")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise SnapshotError("limit must be between 1 and 1000")
    if type(max_pages) is not int or max_pages < 1:
        raise SnapshotError("max_pages must be a positive integer")
    for bound in (period_start, period_end):
        if bound is not None:
            _date(bound)
    if period_start and period_end and period_start > period_end:
        raise SnapshotError("period_start must not exceed period_end")
    times = [_instant(value) for value in observation_times]
    if not times:
        raise SnapshotError("At least one observation instant is required")
    utc_times = [value.astimezone(timezone.utc) for value in times]
    if any(left >= right for left, right in zip(utc_times, utc_times[1:])):
        raise SnapshotError("Observation instants must be strictly increasing")
    path = Path(output_path).expanduser().absolute()
    if path.exists():
        raise FileExistsError(path)
    lines = []
    filters = dict(cik=cik, tag=tag, unit=unit, duration_quarters=duration_quarters,
                   taxonomy=taxonomy, period_start=period_start, period_end=period_end,
                   form=form, limit=limit)
    for instant in times:
        as_of = instant.isoformat()
        cursor = None
        seen_cursors: set[str] = set()
        seen_facts: set[str] = set()
        rows = []
        for _ in range(max_pages):
            page = client.facts(as_of=as_of, cursor=cursor, **filters)
            if not getattr(page, "pagination_valid", True) or not isinstance(page.data, list):
                raise SnapshotError("Malformed facts page; pagination completeness is unknown")
            if page.as_of != as_of:
                raise SnapshotError("Facts page changed the observation cutoff")
            for row in page.data:
                if not isinstance(row, Mapping):
                    raise SnapshotError("Malformed fact in paginated response")
                identity = json.dumps([row.get(k) for k in _IDENTITY], sort_keys=True)
                if identity in seen_facts:
                    raise SnapshotError("Repeated fact identity; pagination is incomplete or overlapping")
                seen_facts.add(identity)
                rows.append(row)
            next_cursor = page.next_cursor
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise SnapshotError("Invalid or cyclic cursor; pagination is incomplete")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise SnapshotError("max_pages reached before pagination completed")
        for fact in visible_as_filed(rows, instant):
            # Defend against a non-conforming client/server ignoring a filter.
            for key in ("cik", "tag", "unit", "duration_quarters", "taxonomy", "form"):
                if filters[key] is not None and fact[key] != filters[key]:
                    raise SnapshotError("Returned fact does not match the requested filters")
            if (period_start and fact["period_end"] < period_start) or (
                period_end and fact["period_end"] > period_end
            ):
                raise SnapshotError("Returned fact is outside the requested period bounds")
            lines.append(json.dumps(
                {"snapshot_version": 1, "observation_time": as_of, **fact},
                sort_keys=True, allow_nan=False, separators=(",", ":"),
            ) + "\n")
    # All queries and serialization finish before creating even an empty file.
    with path.open("x", encoding="utf-8") as output:
        try:
            output.writelines(lines)
            output.flush()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return path
