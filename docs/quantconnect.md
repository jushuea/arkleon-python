# QuantConnect local fundamental snapshots
<!-- INTRO -->

`arkleon.quantconnect` prepares local fundamental snapshots for QuantConnect Lean backtests. A preparation step runs outside Lean, queries the Arkleon `/v1/facts` endpoint at explicit observation instants, applies acceptance and filing-date guards, selects consolidated as-filed facts, and writes a JSONL file. An Arkleon API key is required only for this preparation step. Inside Lean, the `ArkleonFundamental` custom data class reads the prepared file, makes no API calls, needs no credentials, and keeps filing provenance such as accession, form, filing date, and acceptance instant. Preparation also validates pagination metadata and rejects malformed response envelopes. The test suite uses offline fixtures and Lean interface stubs. It does not run inside a Lean runtime.

## What the module does

`arkleon.quantconnect.prepare_snapshot` queries `DataClient.facts` for explicit
observation instants, selects consolidated as-filed facts for each accounting
period, and writes a new local UTF-8 JSONL file. Preparation runs outside Lean
with an API key supplied through `ARKLEON_API_KEY`. It needs API connectivity;
“offline” refers to preparing the file before the backtest.

`ArkleonFundamental` reads that file as Lean custom data. Importing the
preparation functions does not require Lean. Importing the data class requires
the Lean runtime. The reader performs no API calls and needs no credentials.

## Cutoff and selection

Every request uses a datetime `as_of` with an explicit offset. A fact is eligible
only when both conditions hold:

- `accepted_at <= observation_time`, comparing instants in UTC. The API serves
  `accepted_at` at minute precision, as `YYYY-MM-DDTHH:MM:SSZ`; equality at the
  acceptance minute is eligible. This carries no sub-minute timing guarantee.
- `filed <= observation_time.astimezone(ZoneInfo("America/New_York")).date()`.
  The filing date can be later than the acceptance date. Acceptance alone does
  not override this filing-date guard.

The New York calendar date applies even if the caller supplies UTC or another
offset. Missing or malformed `accepted_at` or `filed` causes the row to be
dropped. Observation times must be offset-aware datetimes or ISO strings and
strictly increasing by instant. Naive and date-only inputs are rejected. Use
explicit offsets across DST transitions. ISO strings support up to six
fractional-second digits, matching Python datetime precision.

The selector excludes non-consolidated segment and co-registrant rows. The
public API uses empty strings for consolidated `segments` and `coreg`; the
loader also accepts null contexts (and empty objects/lists for `segments`).
Missing context fields raise `SnapshotError`.

For each period, the latest eligible acceptance instant wins. Multiple
consolidated rows tied at that instant raise `AmbiguousFactError`, including
same-minute filing ties and competing taxonomies. Zero is a valid value.
An invalid latest value raises instead of falling back to an older filing.

## Preparation and pagination

```python
import os
from arkleon.api import DataClient
from arkleon.quantconnect import prepare_snapshot

with DataClient(api_key=os.environ["ARKLEON_API_KEY"]) as client:
    path = prepare_snapshot(
        client,
        cik=1674101,
        tag="NetIncomeLoss",
        unit="USD",
        duration_quarters=4,
        period_start="2020-12-31",
        period_end="2020-12-31",
        observation_times=[
            "2021-04-30T08:00:00-04:00",
            "2021-04-30T16:00:00-04:00",
        ],
        output_path="vertiv-net-income.jsonl",
    )
```

`period_start` and `period_end` are inclusive bounds on the fact's period end.
Use equal bounds to prepare a single period for a subscription. Optional
`taxonomy` and `form` restrict the requested series; leaving `form` unset allows
both original and amended filings to participate.

Every page repeats all filters and the original observation offset in `as_of`.
ISO spelling is normalized by `datetime.isoformat()` (for example, `Z` becomes
`+00:00`). Empty pages with advancing cursors are followed. Cyclic cursors,
repeated fact identities, malformed envelopes, changed page cutoffs, and
`max_pages` exhaustion abort preparation. `limit` defaults to 1000 and
`max_pages` to 10000 per observation. A terminal cursor is the API's completion
signal; the loader cannot establish that the server omitted no facts.

All observations are fetched and serialized before the output is opened. The
destination directory must exist and the file must be new. Query or selection
failure creates no output; an existing destination is never overwritten. The
complete export is buffered in memory.

## Snapshot format

Each JSON line contains one selected fact for one observation and period.
Records are ordered by observation instant, then period. Observations with no
eligible facts produce no records.

| Fields | Meaning |
|---|---|
| `snapshot_version` | Format version, currently integer `1`. |
| `observation_time` | Offset-aware ISO datetime used for the query. |
| `cik`, `tag`, `unit`, `duration_quarters` | Selected series identity. |
| `taxonomy`, `period_end` | Taxonomy version and accounting period end. |
| `value` | Fact value; Decimal inputs are serialized as decimal strings. |
| `accession_id`, `form` | Source filing identity and form. |
| `filed`, `accepted_at` | Filing date and UTC acceptance instant. |
| `segments`, `coreg` | Consolidated context metadata. |

Arbitrary API response fields and `source_url` are not serialized. Neither
credentials nor request headers appear in the snapshot. JSONL can be read with
`json.loads` line by line; preserve decimal strings when consuming exact values.

## Lean registration and delivery

Set the local path on a data subclass before registering it:

```python
from AlgorithmImports import Resolution, TimeZones
from arkleon.quantconnect import ArkleonFundamental

class NetIncome(ArkleonFundamental):
    snapshot_path = "/path/inside/lean/data/vertiv-net-income.jsonl"

# Inside QCAlgorithm.Initialize:
# self.symbol = self.AddData(
#     NetIncome, "VRT-NET-INCOME-2020", Resolution.Minute, TimeZones.Utc, False
# ).Symbol
```

The subscription's data timezone must be UTC, and fill-forward is disabled in
the sample. The algorithm's timezone can differ. `GetSource` accepts a local
file and rejects URLs. `Reader` ignores blank lines, checks the snapshot
version, and reapplies the visibility rules. Both `Time` and `EndTime` are the
observation instant represented as naive UTC, not the accounting period or
callback date. Lean uses `EndTime` for delivery.

`Value` is parsed as a .NET Decimal using invariant culture. A decimal that
cannot be represented exactly fails rather than being silently rounded. Other
public fact fields are copied through the data indexer. `as_filed_value`
preserves the value's textual representation, and `observation_time` preserves
the offset-bearing observation. `value` is not separately written through the
indexer because Lean reserves that property.

See the [preparation script and Lean algorithm](../examples/quantconnect/README.md)
for local setup and run commands.

## Limits

- One CIK/tag/unit/duration series is supported per snapshot. Taxonomy may vary
  across filings unless filtered.
- Multiple periods can produce records at the same instant. Use one period per
  snapshot and a distinct subscription symbol per period when each value must
  be independently addressable in a Lean Slice.
- The caller supplies CIK mappings, observation times, and subscription labels.
  The module does not reconstruct historical ticker mappings or a universe.
- This is a prepared research snapshot, with no live trading feed or automatic
  refresh inside Lean.
- Tests exercise fake API pages and minimal Lean interface stubs. The Lean
  runtime, .NET implementation and engine scheduling are not exercised by the
  test suite. A real Lean replay remains a separate integration check.
