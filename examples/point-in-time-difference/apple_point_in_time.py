"""A data-integrity demonstration, not a strategy result, making no performance or signal claims."""

import os
import sys

os.environ.setdefault(
    "SEC_EDGAR_USER_AGENT", "arkleon point-in-time example (founder@arkleon.com)"
)

from arkleon import EdgarClient


def main():
    client = EdgarClient()
    facts = client.concept(320193, "Assets", taxonomy="us-gaap")
    selected = sorted(
        (
            fact
            for fact in facts
            if fact.period_end == "2008-09-27"
            and fact.segments is None
            and fact.coreg is None
        ),
        key=lambda fact: fact.filed,
    )
    expected = [
        (39572000000, "2009-07-22"),
        (39572000000, "2009-10-27"),
        (36171000000, "2010-01-25"),
        (36171000000, "2010-10-27"),
    ]
    pairs = [(fact.value, fact.filed) for fact in selected]
    if len(selected) != 4 or pairs != expected:
        print(f"Mismatch: expected 4 facts with pairs {expected}; got {len(selected)}: {pairs}")
        sys.exit(1)
    assert len(selected) == 4 and pairs == expected

    for fact in selected:
        print(f"{fact.period_end}  {fact.value}  {fact.filed}")
    print(
        "The as-filed value for the same period changed between filings. "
        "For the same reporting period, fiscal year end 2008-09-27, Apple's Assets "
        "were 39,572,000,000 in 2009 filings vs 36,171,000,000 in 2010 filings, "
        "figures as filed with SEC via public EDGAR."
    )
    print("OK")


if __name__ == "__main__":
    main()
