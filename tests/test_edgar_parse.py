"""Pure parsing of the free EDGAR core: submissions, company facts / concept,
the FSDS zip, and the best-effort as_of filter. No network anywhere; every
input is a tiny inline fixture.
"""

from __future__ import annotations

import io
import zipfile

import arkleon.edgar as edgar
from arkleon.edgar import Fact, FactSet


def test_parse_submissions_threads_cik_into_filings() -> None:
    payload = {
        "cik": "320193",
        "name": "APPLE INC",
        "sic": "3571",
        "fiscalYearEnd": "0930",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077"],
                "form": ["10-K", "10-Q"],
                "filingDate": ["2023-11-03", "2023-08-04"],
                "reportDate": ["2023-09-30", "2023-07-01"],
                "primaryDocument": ["aapl-10k.htm", "aapl-10q.htm"],
            }
        },
    }
    company, filings = edgar.parse_submissions(payload)

    assert isinstance(company.cik, int)
    assert company.cik == 320193
    assert company.name == "APPLE INC"
    assert len(filings) == 2
    # cik is threaded onto every filing.
    assert [f.cik for f in filings] == [320193, 320193]
    assert filings[0].form == "10-K"
    assert filings[0].accession == "0000320193-23-000106"
    assert filings[0].period == "2023-09-30"


def test_parse_company_facts_derives_fields() -> None:
    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2023-09-30",
                                "val": 352755000000,
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            }
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2022-10-01",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            }
                        ]
                    }
                },
            }
        },
    }
    factset = edgar.parse_company_facts(payload)
    assert isinstance(factset, FactSet)
    by_tag = {fact.tag: fact for fact in factset}

    assets = by_tag["Assets"]
    assert assets.cik == 320193
    assert assets.taxonomy == "us-gaap"
    assert assets.unit == "USD"
    assert assets.period_end == "2023-09-30"
    assert assets.period_start is None
    # No start present, so the fact is instantaneous.
    assert assets.instantaneous is True
    assert assets.form == "10-K"
    assert assets.filed == "2023-11-03"

    revenues = by_tag["Revenues"]
    assert revenues.period_start == "2022-10-01"
    # A start is present, so the fact is a duration, not instantaneous.
    assert revenues.instantaneous is False


def test_parse_company_concept_returns_factset() -> None:
    payload = {
        "cik": 320193,
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "units": {
            "USD": [
                {
                    "end": "2023-09-30",
                    "val": 352755000000,
                    "form": "10-K",
                    "filed": "2023-11-03",
                    "accn": "0000320193-23-000106",
                },
                {
                    "end": "2022-09-24",
                    "val": 352583000000,
                    "form": "10-K",
                    "filed": "2022-10-28",
                    "accn": "0000320193-22-000108",
                },
            ]
        },
    }
    factset = edgar.parse_company_concept(payload)
    assert isinstance(factset, FactSet)
    facts = factset.to_list()
    assert len(facts) == 2
    assert all(fact.tag == "Assets" for fact in facts)
    assert all(fact.taxonomy == "us-gaap" for fact in facts)
    assert all(fact.instantaneous is True for fact in facts)
    assert {fact.period_end for fact in facts} == {"2023-09-30", "2022-09-24"}


def _build_fsds_zip(sub_text: str, num_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("2023q4/sub.txt", sub_text)
        archive.writestr("2023q4/num.txt", num_text)
    return buffer.getvalue()


def test_parse_fsds_zip_joins_num_to_sub() -> None:
    sub_text = (
        "adsh\tcik\tform\tperiod\tfiledate\tfilename\n"
        "0000320193-23-000106\t320193\t10-K\t20230930\t2023-11-03\taapl-10k.htm\n"
    )
    num_text = (
        "adsh\tcik\ttag\tversion\tddate\tqtrs\tuom\tvalue\n"
        "0000320193-23-000106\t320193\tAssets\tus-gaap/2023\t20230930\t0\tUSD\t352755000000\n"
        "0000320193-23-000106\t320193\tRevenues\tus-gaap/2023\t20230930\t4\tUSD\t383285000000\n"
    )
    result = edgar.parse_fsds_zip(_build_fsds_zip(sub_text, num_text))

    # Tuple return: (list[Filing], list[Fact]).
    assert isinstance(result, tuple) and len(result) == 2
    filings, facts = result
    assert isinstance(filings, list) and isinstance(facts, list)

    assert len(filings) == 1
    assert filings[0].cik == 320193
    assert filings[0].accession == "0000320193-23-000106"

    by_tag = {fact.tag: fact for fact in facts}
    assets = by_tag["Assets"]
    revenues = by_tag["Revenues"]
    # cik is threaded onto every fact.
    assert assets.cik == 320193 and revenues.cik == 320193
    # The num -> sub join fills form and filed from the sub row.
    assert assets.form == "10-K" and assets.filed == "2023-11-03"
    assert revenues.form == "10-K" and revenues.filed == "2023-11-03"
    # qtrs == 0 is instantaneous; qtrs != 0 is a duration.
    assert assets.instantaneous is True
    assert revenues.instantaneous is False
    assert assets.value == 352755000000


def _fact_filed(filed: str) -> Fact:
    return Fact(
        cik=320193,
        tag="Assets",
        taxonomy="us-gaap",
        value=1,
        unit="USD",
        period_start=None,
        period_end="2023-09-30",
        instantaneous=True,
        form="10-K",
        filed=filed,
        accession="a",
    )


def test_factset_as_of_boundary_inclusive() -> None:
    factset = FactSet(
        [
            _fact_filed("2023-01-01"),
            _fact_filed("2023-06-15"),
            _fact_filed("2023-12-31"),
        ]
    )
    kept = factset.as_of("2023-06-15")
    kept_dates = [fact.filed for fact in kept]
    # filed <= as_of, inclusive on the boundary date itself.
    assert kept_dates == ["2023-01-01", "2023-06-15"]
    # The later filing is excluded.
    assert "2023-12-31" not in kept_dates


def test_factset_as_of_carries_reproducibility_warning() -> None:
    doc = FactSet.as_of.__doc__
    assert doc is not None
    # The honesty caveat is documented in place on the method.
    assert "permanent-reproducibility" in doc
    # And the shared warning constant carries the same phrase.
    assert "permanent-reproducibility" in edgar.AS_OF_WARNING
