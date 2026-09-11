# arkleon
<!-- mcp-name: io.github.jushuea/arkleon -->

arkleon is the free client for Arkleon's point-in-time SEC fundamentals: filing-dated facts straight from EDGAR with no key, and an optional API client for the certified corpus (16,811 companies, 426,003 filings, 181,350,662 facts) with replayable as_of queries.

The free EDGAR core requires no account and no API key. The optional paid `/v1`
client and the corpus-backed point-in-time features are the only parts that need
a key.

## Install

```bash
pip install arkleon
```

## Quickstart: free, no API key

The EDGAR helpers work on the first line of code with no Arkleon account and no
key. The only string they require is an SEC fair-access `User-Agent`, which you
write yourself.

```python
from arkleon.edgar import EdgarClient

# SEC fair-access User-Agent: a self-declared contact string, NOT an Arkleon key.
edgar = EdgarClient(user_agent="Acme Research contact@acme.com")

# Fetch a company's 10-K filings by CIK (Apple = 320193):
for filing in edgar.filings(cik=320193, form="10-K"):
    print(filing.filed, filing.accession, filing.form)

# Parse as-reported numeric facts, filtered best-effort to a date:
assets = edgar.concept(cik=320193, tag="Assets", taxonomy="us-gaap")
for fact in assets.as_of("2020-01-01"):        # keep only filed <= 2020-01-01
    print(fact.period_end, fact.value, fact.unit, fact.filed)
```

*No account, no key, no Arkleon network. Live-EDGAR, best-effort point-in-time.*

## Quickstart: optional paid `/v1` client (certified point-in-time)

```python
# pip install "arkleon[api]"
from arkleon.api import DataClient

client = DataClient(api_key="ak_...")          # or ARKLEON_API_KEY env
page = client.facts(cik=320193, tag="Assets", as_of="2020-01-01")
for fact in page.data:
    print(fact["period_end"], fact["value"], fact.get("source_url"))
```

*Certified corpus. `as_of` required, filters on filing date, identical query +
`as_of` returns identical data permanently.*

## The free/paid boundary

The `arkleon.edgar` helpers never require a key and never contact Arkleon: their
only remote hosts are `data.sec.gov` and `www.sec.gov`. Only the `arkleon[api]`
client and the corpus-backed point-in-time features call Arkleon, and they refuse
to operate without an `ak_`-prefixed key. Installing `arkleon[api]` does not by
itself activate the paid path; a key must still be supplied at runtime.

## MCP server

Install the server extra and launch the stdio server with the console script:

```bash
pip install "arkleon[mcp]"
arkleon-mcp
```

An agent host launches it the same way. Set `ARKLEON_API_KEY` in the launch
environment to unlock the paid tools:

```json
{
  "mcpServers": {
    "arkleon": {
      "command": "arkleon-mcp",
      "env": { "ARKLEON_API_KEY": "ak_..." }
    }
  }
}
```

The free EDGAR tools register **unconditionally**; the paid tools register **only
when an `ak_` key is present**. An agent with no key sees exactly the free set.

| Tool | Backed by | Key required? |
|---|---|---|
| `edgar_list_filings` | free EDGAR core | No |
| `edgar_company_facts` | free EDGAR core | No |
| `edgar_concept` | free EDGAR core | No |
| `edgar_facts_as_of` (best-effort, live EDGAR) | free EDGAR core | No |
| `edgar_resolve_cik` (current-snapshot, non-point-in-time) | free EDGAR core | No |
| `pit_facts` (certified point-in-time) | paid `/v1` client | Yes |
| `pit_filings` | paid `/v1` client | Yes |
| `resolve_company` | paid `/v1` client | Yes |
| `pit_revision_history` | paid `/v1` client | Yes |

**Registry:** The server is described by `server.json` at the repository root for
the official MCP registry under the name `io.github.jushuea/arkleon`. It launches
over stdio as `arkleon-mcp`; the free EDGAR tools register unconditionally and the
paid tools only when an `ak_` key is present. Install with `pip install "arkleon[mcp]"`.

## What it returns, and what it does not

**Returns:** as-reported numeric XBRL facts, filing and company metadata, and the
lineage linking each figure to its source filing.

**Does not return:** market prices, analyst estimates, narrative disclosure
(MD&A, risk factors, footnotes), or derived analytics, ratios, scores, or
signals. Neither layer serves these. It is a research corpus, not a real-time
filing feed: the paid corpus refreshes on the SEC's quarterly cadence.

## Point-in-time, in two sentences

`as_of` filters on the **filing date** (`filed <= as_of`), never on the period a
fact describes, so a query sees only values that were already public on that
date. Because a fact from a later filing never appears, a historical query cannot
observe information that did not yet exist, which is what keeps a study free of
look-ahead bias.

## The certified corpus (paid)

The paid `/v1` client serves the certified corpus. Per the `/v1` API contract at
https://arkleon.com/docs, which is the sole authority for what any surface may
state, the claimable figures are:

| Quantity | Figure | Kind |
|---|---|---|
| Filings | 426,003 | EXACT |
| Facts | 181,350,662 | EXACT |
| Distinct companies (CIK) | 16,811 | EXACT |
| Quarters spanned | 69 (2009q1–2026q1) | exact |
| Quarters populated | 68 | exact |

The EXACT/exact label travels with each number and is not presentational. These
figures are keyed to the date each filing became public, include values that
later filings revised, and trace to their source filing. The earliest filed date
in the corpus is 2009-04-15, so a query with an `as_of` earlier than that date
correctly returns empty. Treat the contract's Appendix A, not this table, as the
authority: a later corpus revision updates the contract, and any figure that
disagrees with it is stale.

## Identifiers

**CIK is the addressable identifier** across both layers. In the free layer,
`resolve_cik(ticker)` maps a symbol to a CIK from SEC's current ticker snapshot;
it is a convenience, not a reproducible identity resolver, because it has no
ticker history, a symbol is reassigned over time, and one CIK carries several
symbols at once (`GOOG` and `GOOGL`, `BRK.A` and `BRK.B`). The `/v1` API does not
serve the `ticker` filter today: a `ticker` request returns a distinct
"not served in this release" error rather than silently resolving through the
free snapshot. Address facts by CIK.

## Install matrix

| Install | Adds |
|---|---|
| `arkleon` | The free EDGAR fetch/parse core. No key, no Arkleon network. |
| `arkleon[api]` | The optional paid `/v1` `DataClient`. Requires an `ak_` key at runtime. |
| `arkleon[mcp]` | The built-in MCP server and the `arkleon-mcp` console script. |
| `arkleon[pandas]` | Optional pandas DataFrame adapters for the free core. Never required. |
| `arkleon[all]` | Convenience union of `api`, `mcp`, and `pandas`. |

Base plus `[pandas]` stays fully free and credential-free. `[api]` and the paid
tools in `[mcp]` are the only parts that consume an `ak_` key.

## License

MIT. See [LICENSE](LICENSE).

## Links

- **`/v1` API contract:** https://arkleon.com/docs (the authority for the corpus
  figures above).
- **Issues and contributing:** https://github.com/jushuea/arkleon-python
- **SEC fair-access policy:** https://www.sec.gov/os/accessing-edgar-data
