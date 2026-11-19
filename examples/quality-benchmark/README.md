# Quality benchmark

The benchmark draws facts from the SEC's own quarterly archives using the fixed seed in PLAN.md. For each selected fact, it asks the facts endpoint at the filing date and at the day before, then compares the returned fields with the archive fields. Numeric comparisons use exact decimals. Each populated quarter contributes the same filing allocation, with one selected fact per filing.

The check cannot establish that the SEC archive is itself correct, that the corpus is complete, or anything about facts that were not drawn. Agreement is a comparison with the archived fields under the stated sampling and query rules. Neither a passing draw nor the aggregate comparison establishes claims beyond that scope.

## Prerequisites

Use the supported Python version, and install the repository's optional dependencies from its root. The run needs an Arkleon API key with an admitted minute limit. Reserve enough disk space for every quarterly zip in the whitelist and for the separate results directory. The combined size of the archive downloads determines the archive storage requirement. Preparation streams the zipped tables without extracting copies. The API key's daily budget also covers other activity that uses that key.

| Requirement | Value |
| --- | --- |
| Python | `3.11+` |
| Installation directory | Repository root |
| API key environment variable | `ARKLEON_API_KEY` |
| Comparison endpoint | `/v1/facts` |
| Admission endpoint | `/v1/companies?limit=1` |
| Admitted `RateLimit-Limit` header | `60` or `300` |
| Archive storage | Space for all quarterly zip files listed in `PLAN.md` |
| Results storage | A separate directory outside the repository |

```sh
pip install -e ".[all]"
```

The client reads the API key from ARKLEON_API_KEY. The shell prompt accepts it without echoing it or placing its value in shell command history. The variable must be kept in the shell that starts the run. Credentials stay out of benchmark records.

```sh
read -r -s -p 'Arkleon API key: ' ARKLEON_API_KEY
export ARKLEON_API_KEY
printf '\n'
```

## Get the quarterly archives

Download the SEC Financial Statement Data Sets quarterly zips for exactly the quarters in PLAN.md into one directory. Name each zip for its quarter. Keep the submission and numeric tables inside each zip. Follow the SEC's fair-access rules when downloading. Preparation requires every whitelisted archive. If an archive is missing or cannot supply the required filing allocation, preparation stops and leaves no preparation artifacts.

| Resource | Location or naming rule |
| --- | --- |
| SEC Financial Statement Data Sets | https://www.sec.gov/dera/data/financial-statement-data-sets |
| SEC fair-access rules | https://www.sec.gov/os/accessing-edgar-data |
| Quarters | The whitelist in `PLAN.md` |
| Local zip names | `<quarter>.zip`, for example `2009q2.zip` |
| Archive members | `sub.txt` and `num.txt` |

## Verify the plan pin

Run the plan digest check from the benchmark directory. Preparation and every later command refuse a missing pin or changed plan bytes. The plan maintainer pins and commits the final method before any draw or request.

```sh
cd examples/quality-benchmark
sha256sum -c PLAN.sha256
```

## Prepare the draw

Preparation creates a deterministic manifest in the chosen results directory. An existing manifest blocks preparation in that directory. The manifest fixes the selected filings and facts, their archive evidence, and both queries. Source issues and later query outcomes never cause a replacement draw. Replace the angle-bracket arguments in the commands with local directory paths.

```sh
python benchmark.py prepare --archives <dir> --out <results-dir>
```

## Compare the manifest with the freeze record

Compare the manifest digest with the manifest entry in FREEZE.md. The plan maintainer creates and commits the freeze record after preparation and before any API request. The freeze record also pins the plan and archive digest file. The run refuses any disagreement and requires a clean repository. Keep the repository unchanged from the freeze commit through the last request, including continuations.

```sh
cat <results-dir>/manifest.sha256
cat FREEZE.md
```

| Digest | Required comparison |
| --- | --- |
| `PLAN.sha256` | `PLAN.md sha256` in `FREEZE.md` |
| `<results-dir>/manifest.sha256` | `manifest.jsonl sha256` in `FREEZE.md` |
| SHA-256 of `<results-dir>/archives.sha256` | `archives.sha256 sha256` in `FREEZE.md` |

## Run

The run first reads the companies endpoint to admit the key's minute limit, and fact requests then follow the frozen filing-date and day-before rules. Every outbound attempt consumes its persisted allowance, including retries. Authorization, quota, admission, and daily-budget stops preserve the work already recorded. A UTC day change also stops further requests until an explicit continuation.

```sh
python benchmark.py run --handoff <results-dir>
```

## Report

The report prints attempt totals, outcome classes, and quarter completion. Both headline and resolved-only figures appear only after every draw has an outcome. Pending draws suppress bounds. The frozen predicates distinguish filing-date matches from checks that also require a clean day-before query. The statistical interpretation and its limits follow PLAN.md.

```sh
python benchmark.py report --handoff <results-dir>
```

## Audit

The audit compares the attempt journal with the persisted counters, checks outcome identities, and checks page and attempt allowances. It prints its findings and returns an unsuccessful exit status when reconciliation fails. Interrupted reservations are reconciled by continuation before the audit can pass.

```sh
python benchmark.py audit --handoff <results-dir>
```

## Results and continuation

Preparation and run records remain in the results directory passed on the command line, which lies outside the repository. Report and audit print to the terminal. The manifest, archive digests, journals, and state are preserved together so that continuation uses the same draw and accumulated evidence.

| File in the results directory | Content |
| --- | --- |
| `manifest.jsonl` | Immutable draw, source evidence, query parameters, and embedded archive summary |
| `manifest-summary.json` | Archive population and parsing counts |
| `manifest.sha256` | Manifest digest |
| `archives.sha256` | Quarterly zip digests |
| `results.jsonl` | HTTP attempt evidence |
| `outcomes.jsonl` | Final draw outcomes and comparisons |
| `state.json` | Persistent usage, cursors, admission, waits, and run status |

A stopped run is resumed on a later UTC day with the same run command and results directory. Continuation skips completed draws, keeps pending cursors and accepted evidence, honors outstanding waits, and never redraws. Used pages and attempts remain spent. An accepted limit read is reused, and its original attempt allowance is never renewed. A new UTC day refreshes only the daily counter.

```sh
python benchmark.py run --handoff <results-dir>
```

Follow PLAN.md for every sampling, parsing, query, comparison, outcome, budget, continuation, and reporting rule.
