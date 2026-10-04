"""Lean callback contract tests with isolated Python stubs, not a Lean runtime."""

from datetime import datetime
from decimal import Decimal
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from arkleon.quantconnect import SnapshotError, prepare_snapshot

FIXTURES = Path(__file__).parent / "fixtures" / "quantconnect"


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


@pytest.fixture
def lean(monkeypatch):
    """Restore every injected module and the package import attribute per test."""
    import arkleon.quantconnect as package

    class PythonData(dict):
        pass

    class LeanDecimal:
        def __init__(self, text):
            self.exact = Decimal(text)

        @staticmethod
        def Parse(text, culture):
            assert culture is invariant
            return LeanDecimal(text)

        def ToString(self, culture):
            assert culture is invariant
            return format(self.exact, "f")

    class SubscriptionDataSource:
        def __init__(self, source, medium):
            self.Source = source
            self.TransportMedium = medium

    invariant = object()
    local_file = object()
    modules = {name: ModuleType(name) for name in (
        "QuantConnect", "QuantConnect.Python", "QuantConnect.Data",
        "System", "System.Globalization",
    )}
    modules["QuantConnect"].__path__ = []
    modules["System"].__path__ = []
    modules["QuantConnect"].Python = modules["QuantConnect.Python"]
    modules["QuantConnect"].Data = modules["QuantConnect.Data"]
    modules["System"].Globalization = modules["System.Globalization"]
    modules["QuantConnect.Python"].PythonData = PythonData
    modules["QuantConnect"].SubscriptionTransportMedium = SimpleNamespace(LocalFile=local_file)
    modules["QuantConnect.Data"].SubscriptionDataSource = SubscriptionDataSource
    modules["System"].Decimal = LeanDecimal
    modules["System.Globalization"].CultureInfo = SimpleNamespace(InvariantCulture=invariant)
    with monkeypatch.context() as patch:
        for name, module in modules.items():
            patch.setitem(sys.modules, name, module)
        patch.delitem(sys.modules, "arkleon.quantconnect.data", raising=False)
        patch.delattr(package, "data", raising=False)
        try:
            adapter = importlib.import_module("arkleon.quantconnect.data")
            yield SimpleNamespace(
                cls=adapter.ArkleonFundamental, decimal=LeanDecimal,
                local_file=local_file, invariant=invariant,
            )
        finally:
            sys.modules.pop("arkleon.quantconnect.data", None)
            package.__dict__.pop("data", None)


@pytest.fixture
def config():
    return SimpleNamespace(Symbol="VRT-NET-INCOME-2020", DataTimeZone=SimpleNamespace(Id="UTC"))


@pytest.fixture
def record():
    row = json.loads((FIXTURES / "page-2.json").read_text(encoding="utf-8"))["data"][0]
    row.pop("source_url")
    return dict(row, snapshot_version=1, observation_time="2021-04-30T16:00:00-04:00")


def test_get_source_local_file(lean, config, tmp_path):
    path = tmp_path / "snapshot.jsonl"
    path.write_text("", encoding="utf-8")
    reader = lean.cls()
    reader.snapshot_path = path
    source = reader.GetSource(config, datetime(2021, 4, 30), False)
    assert source.Source == str(path.resolve())
    assert source.TransportMedium is lean.local_file


@pytest.mark.parametrize("path", [
    "https://example.invalid/snapshot.jsonl", "http://example.invalid/snapshot.jsonl",
    "file:///tmp/snapshot.jsonl", "s3://bucket/snapshot.jsonl",
])
def test_get_source_rejects_urls(lean, config, path):
    reader = lean.cls()
    reader.snapshot_path = path
    with pytest.raises(SnapshotError, match="local file"):
        reader.GetSource(config, datetime(2021, 4, 30), False)


def test_get_source_requires_path(lean, config):
    with pytest.raises(SnapshotError, match="Set snapshot_path"):
        lean.cls().GetSource(config, datetime(2021, 4, 30), False)


def test_get_source_rejects_directory(lean, config, tmp_path):
    reader = lean.cls()
    reader.snapshot_path = tmp_path
    with pytest.raises(SnapshotError, match="local file"):
        reader.GetSource(config, datetime(2021, 4, 30), False)


def test_get_source_missing_file(lean, config, tmp_path):
    reader = lean.cls()
    reader.snapshot_path = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        reader.GetSource(config, datetime(2021, 4, 30), False)


@pytest.mark.parametrize("zone", ["America/New_York", "Asia/Tokyo", None])
@pytest.mark.parametrize("callback", ["GetSource", "Reader"])
def test_non_utc_data_timezone_rejected(lean, config, record, zone, callback):
    config.DataTimeZone = SimpleNamespace(Id=zone)
    args = [config]
    if callback == "Reader":
        args.append(json.dumps(record))
    with pytest.raises(SnapshotError, match="TimeZones.Utc"):
        getattr(lean.cls(), callback)(*args, datetime(2021, 4, 30), False)


@pytest.mark.parametrize("zone", ["UTC", "Etc/UTC"])
@pytest.mark.parametrize("instant,expected", [
    ("2021-04-30T16:00:00-04:00", datetime(2021, 4, 30, 20)),
    ("2021-05-01T05:00:00+09:00", datetime(2021, 4, 30, 20)),
    ("2021-11-07T01:30:00-04:00", datetime(2021, 11, 7, 5, 30)),
    ("2021-11-07T01:30:00-05:00", datetime(2021, 11, 7, 6, 30)),
])
def test_reader_observation_time_is_naive_utc(lean, config, record, zone, instant, expected):
    config.DataTimeZone.Id = zone
    record["observation_time"] = instant
    # Callback date and accounting period must not become the delivery time.
    result = lean.cls().Reader(config, json.dumps(record), datetime(2020, 12, 31), False)
    assert result.Time == result.EndTime == expected
    assert result.Time.tzinfo is result.EndTime.tzinfo is None
    assert result.Symbol == config.Symbol


@pytest.mark.parametrize("value", [-327300000, 0, "12345678901234567890.12345678", "0.0000000000000000000000000001"])
def test_reader_value_exact_and_provenance_copied(lean, config, record, value):
    record["value"] = value
    result = lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False)
    assert result.Value.exact == Decimal(str(value))
    assert result.Value.ToString(lean.invariant) == format(Decimal(str(value)), "f")
    expected = {key: val for key, val in record.items() if key not in {"value", "snapshot_version"}}
    expected["as_filed_value"] = str(value)
    assert dict(result) == expected
    assert "value" not in result


def test_reader_rejects_decimal_rounding(lean, config, record, monkeypatch):
    record["value"] = "1.00000000000000000000000000001"
    monkeypatch.setattr(lean.decimal, "Parse", staticmethod(lambda text, culture: lean.decimal("1")))
    with pytest.raises(SnapshotError, match="represented exactly"):
        lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False)


@pytest.mark.parametrize("line", ["", "\n", " \t\r\n"])
def test_reader_ignores_blank_lines(lean, config, line):
    assert lean.cls().Reader(config, line, datetime(2021, 4, 30), False) is None


@pytest.mark.parametrize("version", [None, 0, 2, "1"])
def test_reader_rejects_wrong_snapshot_version(lean, config, record, version):
    record["snapshot_version"] = version
    with pytest.raises(SnapshotError, match="Unsupported snapshot"):
        lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False)


def test_reader_rejects_boolean_snapshot_version(lean, config, record):
    record["snapshot_version"] = True
    with pytest.raises(SnapshotError, match="Unsupported snapshot"):
        lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False)


@pytest.mark.parametrize("line", ["not-json", "[]", "null"])
def test_reader_rejects_malformed_record(lean, config, line):
    with pytest.raises(SnapshotError):
        lean.cls().Reader(config, line, datetime(2021, 4, 30), False)


def test_reader_reapplies_visibility(lean, config, record):
    record["observation_time"] = "2021-04-30T08:00:00-04:00"
    assert lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False) is None


@pytest.mark.parametrize("bad_time", MALFORMED_DATETIMES)
def test_reader_drops_malformed_acceptance_datetime(lean, config, record, bad_time):
    record["observation_time"] = "2021-05-02T20:00:00Z"
    reader = lean.cls()
    callback_date = datetime(2021, 5, 2)
    assert reader.Reader(config, json.dumps(record), callback_date, False) is not None
    record["accepted_at"] = bad_time
    assert reader.Reader(config, json.dumps(record), callback_date, False) is None


@pytest.mark.parametrize("bad_time", MALFORMED_DATETIMES)
def test_reader_rejects_malformed_observation_datetime(lean, config, record, bad_time):
    record["observation_time"] = bad_time
    with pytest.raises(SnapshotError):
        lean.cls().Reader(config, json.dumps(record), datetime(2021, 4, 30), False)


def test_prepared_jsonl_round_trip_through_reader(lean, config, tmp_path):
    from arkleon.api.pagination import Page

    rows = json.loads((FIXTURES / "afternoon.json").read_text(encoding="utf-8"))["data"]

    class Client:
        def facts(self, **kwargs):
            return Page(data=rows, next_cursor=None, as_of=kwargs["as_of"])

    times = ["2021-04-30T08:00:00-04:00", "2021-04-30T16:00:00-04:00"]
    path = prepare_snapshot(
        Client(), cik=1674101, tag="NetIncomeLoss", unit="USD", duration_quarters=4,
        observation_times=times, output_path=tmp_path / "snapshot.jsonl",
    )
    reader = lean.cls()
    results = [reader.Reader(config, line, datetime(2021, 4, 30), False)
               for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row.Time for row in results] == [datetime(2021, 4, 30, 12), datetime(2021, 4, 30, 20)]
    assert [row.Value.exact for row in results] == [Decimal(-183600000), Decimal(-327300000)]
    assert [row["observation_time"] for row in results] == times


def test_snake_case_callbacks_are_available(lean):
    assert lean.cls.get_source is lean.cls.GetSource
    assert lean.cls.reader is lean.cls.Reader
