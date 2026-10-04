"""Offline snapshot tests using the public /v1 fact shape and recorded pages."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from arkleon.api.pagination import Page
from arkleon.quantconnect import (
    AmbiguousFactError, SnapshotError, prepare_snapshot, visible_as_filed,
)

FIXTURES = Path(__file__).parent / "fixtures" / "quantconnect"
MORNING = "2021-04-30T08:00:00-04:00"
AFTERNOON = "2021-04-30T16:00:00-04:00"
SERIES = dict(cik=1674101, tag="NetIncomeLoss", unit="USD", duration_quarters=4)
PUBLIC_FIELDS = {
    "cik", "tag", "taxonomy", "unit", "duration_quarters", "value",
    "accession_id", "form", "filed", "accepted_at", "period_end", "segments", "coreg",
}


# Python's ISO parser can normalize invalid offset minutes instead of rejecting them.
MALFORMED_DATETIMES = [
    pytest.param(f"2021-04-30T14:30:00{sign}00:{minute}",
                 id=f"offset-{sign}-minute-{minute}")
    for sign in ("+", "-") for minute in range(60, 100)
] + [
    pytest.param("2021-04-30T14:30:00+24:00", id="offset-plus-hour-24"),
    pytest.param("2021-04-30T14:30:00-24:00", id="offset-minus-hour-24"),
    pytest.param("2021-04-30T24:30:00Z", id="hour-24"),
    pytest.param("2021-04-30T14:60:00Z", id="minute-60"),
    pytest.param("2021-04-30T14:30:60Z", id="second-60"),
    pytest.param("2021-04-31T14:30:00Z", id="impossible-date"),
]


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeDataClient:
    """Return scripted pages; record the entire call without any transport."""

    def __init__(self, pages):
        self.pages = iter(deepcopy(pages))
        self.calls = []

    def facts(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.pages)
        if isinstance(response, Exception):
            raise response
        return Page(
            data=response["data"], next_cursor=response["next_cursor"],
            as_of=response.get("as_of", kwargs["as_of"]),
            pagination_valid=response.get("pagination_valid", True),
        )


def export(tmp_path, pages, times=None, **kwargs):
    client = FakeDataClient(pages)
    path = tmp_path / "snapshot.jsonl"
    prepare_snapshot(client, **SERIES, observation_times=times or [AFTERNOON],
                     output_path=path, **kwargs)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return client, path, records


def test_vertiv_morning_and_afternoon_snapshot(tmp_path):
    client, _, records = export(
        tmp_path, [fixture("morning.json"), fixture("afternoon.json")],
        [MORNING, AFTERNOON],
    )
    assert [r["value"] for r in records] == [-183600000, -327300000]
    assert [r["accession_id"] for r in records] == [
        "0001628280-21-003604", "0001628280-21-008318",
    ]
    assert [r["observation_time"] for r in records] == [MORNING, AFTERNOON]
    assert [call["as_of"] for call in client.calls] == [MORNING, AFTERNOON]


@pytest.mark.parametrize("instant,expected", [
    (MORNING, -183600000),
    ("2021-04-30T13:56:59Z", -183600000),
    ("2021-04-30T13:57:00Z", -327300000),
    (AFTERNOON, -327300000),
])
def test_local_cutoff_including_acceptance_equality(instant, expected):
    # Even a client returning future filings must not move visibility earlier.
    rows = fixture("afternoon.json")["data"]
    assert [row["value"] for row in visible_as_filed(rows, instant)] == [expected]


@pytest.mark.parametrize("instant", [
    "2021-04-30T23:30:00-04:00", "2021-05-01T03:30:00Z", "2021-05-01T12:30:00+09:00",
])
def test_filed_guard_uses_eastern_day_not_request_day(instant):
    rows = fixture("afternoon.json")["data"][:2]
    rows[1].update(filed="2021-05-01", accepted_at="2021-05-01T03:00:00Z")
    assert [row["value"] for row in visible_as_filed(rows, instant)] == [-183600000]


@pytest.mark.parametrize("instant,expected", [
    ("2021-04-30T12:00:00Z", -183600000),
    ("2021-04-30T21:00:00+09:00", -183600000),
    ("2021-04-30T20:00:00Z", -327300000),
    ("2021-05-01T05:00:00+09:00", -327300000),
])
def test_equivalent_offset_instants(tmp_path, instant, expected):
    client, _, records = export(tmp_path, [fixture("afternoon.json")], [instant])
    assert records[0]["value"] == expected
    assert client.calls[0]["as_of"] == datetime.fromisoformat(instant.replace("Z", "+00:00")).isoformat()


@pytest.mark.parametrize("instant,expected", [
    ("2021-11-07T01:30:00-04:00", -183600000),
    ("2021-11-07T01:30:00-05:00", -327300000),
])
def test_dst_fall_back_distinguishes_repeated_wall_clock(instant, expected):
    rows = fixture("afternoon.json")["data"][:2]
    rows[1].update(filed="2021-11-07", accepted_at="2021-11-07T06:30:00Z")
    assert [row["value"] for row in visible_as_filed(rows, instant)] == [expected]


@pytest.mark.parametrize("field,bad", [
    ("accepted_at", None), ("accepted_at", ""), ("accepted_at", "2021-04-30"),
    ("accepted_at", "2021-04-30T13:57:00"), ("accepted_at", "2021-02-30T13:57:00Z"),
    ("accepted_at", 42), ("filed", None), ("filed", ""), ("filed", "2021-02-30"),
    ("filed", "2021-4-30"), ("filed", "2021-04-30T00:00:00Z"), ("filed", 20210430),
])
def test_invalid_acceptance_or_filed_dropped(field, bad):
    rows = fixture("afternoon.json")["data"][:2]
    rows[1][field] = bad
    assert [row["value"] for row in visible_as_filed(rows, AFTERNOON)] == [-183600000]
    assert visible_as_filed([rows[1]], AFTERNOON) == []


@pytest.mark.parametrize("bad_time", MALFORMED_DATETIMES)
def test_malformed_acceptance_datetime_dropped(bad_time):
    rows = fixture("afternoon.json")["data"][:2]
    # A later cutoff keeps rejection independent of the acceptance/filing guards.
    cutoff = "2021-05-02T20:00:00Z"
    assert visible_as_filed([rows[1]], cutoff)
    rows[1]["accepted_at"] = bad_time
    assert visible_as_filed([rows[1]], cutoff) == []
    assert [row["value"] for row in visible_as_filed(rows, cutoff)] == [-183600000]


@pytest.mark.parametrize("field", ["accepted_at", "filed"])
def test_missing_acceptance_or_filed_dropped(field):
    row = fixture("morning.json")["data"][0]
    del row[field]
    assert visible_as_filed([row], AFTERNOON) == []


def test_nonconsolidated_rows_excluded_and_inputs_unchanged():
    rows = fixture("afternoon.json")["data"]
    rows.append(dict(rows[1], coreg="Subsidiary"))
    before = deepcopy(rows)
    selected = visible_as_filed(reversed(rows), AFTERNOON)
    assert len(selected) == 1
    assert selected[0]["value"] == -327300000
    assert selected[0]["segments"] == selected[0]["coreg"] == ""
    assert rows == before


@pytest.mark.parametrize("change", [{}, {"accession_id": "synthetic-same-minute"}, {"taxonomy": "us-gaap/2020"}])
def test_latest_consolidated_tie_raises(change):
    rows = fixture("afternoon.json")["data"][:2]
    rows.append(dict(rows[1], **change))
    with pytest.raises(AmbiguousFactError, match="multiple rows"):
        visible_as_filed(rows, AFTERNOON)


def test_zero_values_kept(tmp_path):
    page = fixture("morning.json")
    page["data"][0]["value"] = 0
    _, _, records = export(tmp_path, [page])
    assert len(records) == 1
    assert records[0]["value"] == 0


@pytest.mark.parametrize("empty_middle", [False, True])
def test_paginated_fixture_and_identical_filters(tmp_path, empty_middle):
    pages = [fixture("page-1.json")]
    if empty_middle:
        pages.append(fixture("empty-middle.json"))
    pages.append(fixture("page-2.json"))
    filters = dict(taxonomy="us-gaap/2019", period_start="2020-12-31",
                   period_end="2020-12-31", limit=10)
    client, _, records = export(tmp_path, pages, **filters)
    cursors = [None, "qc-page-2", "qc-page-3"] if empty_middle else [None, "qc-page-2"]
    assert client.calls == [
        {**SERIES, **filters, "form": None, "as_of": AFTERNOON, "cursor": cursor}
        for cursor in cursors
    ]
    assert [r["value"] for r in records] == [-327300000]


def test_nonempty_form_filter_repeated_on_empty_page(tmp_path):
    first = fixture("page-2.json")
    first["next_cursor"] = "terminal-page"
    filters = dict(taxonomy="us-gaap/2019", period_start="2020-12-31",
                   period_end="2020-12-31", form="10-K/A", limit=10)
    client, _, records = export(tmp_path, [first, {"data": [], "next_cursor": None}], **filters)
    assert client.calls == [
        {**SERIES, **filters, "as_of": AFTERNOON, "cursor": cursor}
        for cursor in [None, "terminal-page"]
    ]
    assert len(records) == 1


@pytest.mark.parametrize("failure", [
    "cycle", "long_cycle", "repeat", "invalid_envelope", "changed_as_of",
    "max_pages", "bad_data", "bad_cursor", "transport", "ambiguity",
])
def test_failed_export_never_creates_output(tmp_path, failure):
    first, second = fixture("page-1.json"), fixture("page-2.json")
    pages, options, error, message = [first, second], {}, SnapshotError, None
    if failure == "cycle":
        pages[1] = {"data": [], "next_cursor": first["next_cursor"]}
        message = "cyclic cursor"
    elif failure == "long_cycle":
        pages = [first, fixture("empty-middle.json"), {"data": [], "next_cursor": first["next_cursor"]}]
        message = "cyclic cursor"
    elif failure == "repeat":
        pages[1]["data"].append(dict(first["data"][0], value=123))
        message = "Repeated fact identity"
    elif failure == "invalid_envelope":
        pages[1]["pagination_valid"] = False
        message = "Malformed facts page"
    elif failure == "changed_as_of":
        pages[1]["as_of"] = MORNING
        message = "changed the observation cutoff"
    elif failure == "max_pages":
        options["max_pages"] = 1
        message = "max_pages"
    elif failure == "bad_data":
        pages[1]["data"] = {}
        message = "Malformed facts page"
    elif failure == "bad_cursor":
        pages[1]["next_cursor"] = 12
        message = "Invalid or cyclic cursor"
    elif failure == "transport":
        pages[1] = RuntimeError("offline transport failure")
        error = RuntimeError
    elif failure == "ambiguity":
        pages[1]["data"].append(dict(second["data"][0], accession_id="synthetic-tie"))
        error = AmbiguousFactError
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(error, match=message):
        prepare_snapshot(FakeDataClient(pages), **SERIES, observation_times=[AFTERNOON],
                         output_path=path, **options)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_later_observation_failure_does_not_leave_partial_snapshot(tmp_path):
    client = FakeDataClient([fixture("morning.json"), RuntimeError("second observation failed")])
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(RuntimeError, match="second observation"):
        prepare_snapshot(client, **SERIES, observation_times=[MORNING, AFTERNOON], output_path=path)
    assert len(client.calls) == 2
    assert not path.exists()


def test_existing_output_never_overwritten(tmp_path):
    path = tmp_path / "snapshot.jsonl"
    original = b"existing snapshot\n"
    path.write_bytes(original)
    client = FakeDataClient([])
    with pytest.raises(FileExistsError):
        prepare_snapshot(client, **SERIES, observation_times=[AFTERNOON], output_path=path)
    assert path.read_bytes() == original
    assert client.calls == []


def test_jsonl_round_trip_preserves_decimal_and_public_provenance(tmp_path):
    page = fixture("morning.json")
    row = page["data"][0]
    row["value"] = Decimal("12345678901234567890.12345678")
    row["unexpected_metadata"] = "not part of the snapshot"
    _, path, records = export(tmp_path, [page])
    expected = {key: row[key] for key in PUBLIC_FIELDS}
    expected.update(value=str(row["value"]), snapshot_version=1, observation_time=AFTERNOON)
    assert records == [expected]
    assert path.is_absolute()
    assert path.read_bytes().endswith(b"\n")
    assert "source_url" not in records[0]
    assert Decimal(records[0]["value"]) == row["value"]
    assert visible_as_filed(records, AFTERNOON) == [{key: expected[key] for key in PUBLIC_FIELDS}]


@pytest.mark.parametrize("bad_time", [
    "2021-04-30", "2021-04-30T16:00:00", date(2021, 4, 30), datetime(2021, 4, 30, 16),
])
def test_naive_and_date_only_observations_rejected_before_fetch(tmp_path, bad_time):
    client = FakeDataClient([])
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(SnapshotError):
        prepare_snapshot(client, **SERIES, observation_times=[bad_time], output_path=path)
    assert client.calls == []
    assert not path.exists()


@pytest.mark.parametrize("bad_time", MALFORMED_DATETIMES)
def test_malformed_observation_datetime_rejected_before_fetch(tmp_path, bad_time):
    client = FakeDataClient([fixture("afternoon.json")])
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(SnapshotError):
        prepare_snapshot(client, **SERIES, observation_times=[bad_time], output_path=path)
    assert client.calls == []
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("times", [
    [AFTERNOON, MORNING], [MORNING, MORNING],
    [AFTERNOON, "2021-05-01T05:00:00+09:00"],
    ["2021-05-01T05:00:00+09:00", "2021-04-30T19:59:00Z"],
])
def test_nonincreasing_instants_rejected_before_fetch(tmp_path, times):
    client = FakeDataClient([])
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(SnapshotError, match="strictly increasing"):
        prepare_snapshot(client, **SERIES, observation_times=times, output_path=path)
    assert client.calls == []
    assert not path.exists()


@pytest.mark.parametrize("value", [None, True, "not-a-number", "NaN", "Infinity"])
def test_invalid_latest_value_fails_instead_of_reviving_old_fact(tmp_path, value):
    page = fixture("afternoon.json")
    page["data"][1]["value"] = value
    path = tmp_path / "snapshot.jsonl"
    with pytest.raises(SnapshotError, match="finite numeric"):
        prepare_snapshot(FakeDataClient([page]), **SERIES, observation_times=[AFTERNOON], output_path=path)
    assert not path.exists()
