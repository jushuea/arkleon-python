# Local QuantConnect snapshot example

This example prepares one fundamental series outside Lean, then reads its local
JSONL file during a backtest. Preparation calls the Arkleon data API and requires
`ARKLEON_API_KEY`; the Lean algorithm only reads the prepared file. It places no
orders. See the [technical documentation](../../docs/quantconnect.md).

## Prepare outside Lean

From this repository, create a Python environment with `uv`:

```bash
uv venv /tmp/arkleon-qc-example
uv pip install --python /tmp/arkleon-qc-example/bin/python3 '.[api]'
```

Supply `ARKLEON_API_KEY` through your preparation environment's secret manager.
Do not put it in the algorithm, snapshot, source code, or command line. Choose
an existing destination directory and a new filename. For the sample algorithm,
use `alternative/arkleon/vertiv-net-income.jsonl` under your local Lean data
directory. Create that directory if necessary, then run:

```bash
/tmp/arkleon-qc-example/bin/python3 examples/quantconnect/prepare_snapshot.py \
  --output /path/to/lean/data/alternative/arkleon/vertiv-net-income.jsonl \
  --cik 1674101 \
  --tag NetIncomeLoss \
  --unit USD \
  --duration-quarters 4 \
  --period-end 2020-12-31 \
  --observation-time 2021-04-30T08:00:00-04:00 \
  --observation-time 2021-04-30T16:00:00-04:00
```

Replace `/path/to/lean/data` with your Lean data directory. The CIK, series,
period and observation times are explicit caller choices. The script requests
equal period bounds so each observation has at most one record for this
subscription. Existing snapshots are never overwritten. Use a new destination
for another preparation run. No row is emitted when no eligible fact exists.

“Offline preparation” means outside the Lean run; the preparation command
requires API connectivity. Reading the resulting snapshot requires no API key.

## Run the Lean example

Use an existing local Lean Python project and copy `main.py` from this directory
into that project's algorithm file. Make `arkleon` available in the Python
environment used by the Lean engine. A host virtual environment is separate
from a containerized Lean engine, so installing above alone may not install the
package inside your engine. Follow your Lean installation's package setup.

Mount or copy the snapshot into the engine's data directory at the relative
path shown above. Keep the preparation credential out of the Lean environment.
With the Lean CLI configured for your local project, run:

```bash
lean backtest /path/to/your/lean-project
```

The algorithm registers the data with `TimeZones.Utc` and fill-forward disabled,
then logs each delivered record's observation time, value and accession. Its
algorithm timezone may remain New York. This repository's tests use minimal
Lean interface stubs; they do not exercise the Lean engine or its scheduling.
The example has not been run under Lean by this test suite.
