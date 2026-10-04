"""Prepare a local snapshot before Lean runs; this step contacts the data API."""

import argparse
import os
from pathlib import Path

from arkleon.api import DataClient
from arkleon.quantconnect import prepare_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file; parent directory must exist")
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--duration-quarters", type=int, required=True)
    parser.add_argument("--period-end", required=True, help="Single accounting period end, YYYY-MM-DD")
    parser.add_argument("--observation-time", action="append", required=True,
                        help="Offset-aware ISO datetime; repeat in strictly increasing instant order")
    args = parser.parse_args()
    api_key = os.environ.get("ARKLEON_API_KEY")
    if not api_key:
        parser.error("Set ARKLEON_API_KEY in the preparation environment")
    # The key stays outside Lean and is never written into the snapshot.
    with DataClient(api_key=api_key) as client:
        prepare_snapshot(
            client, cik=args.cik, tag=args.tag, unit=args.unit,
            duration_quarters=args.duration_quarters,
            period_start=args.period_end, period_end=args.period_end,
            observation_times=args.observation_time, output_path=args.output,
        )


if __name__ == "__main__":
    main()
