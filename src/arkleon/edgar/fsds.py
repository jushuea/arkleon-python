from __future__ import annotations

import csv
import io
import zipfile
from typing import Any

from .models import Fact, Filing


def _tab_reader(text: str) -> csv.DictReader[str]:
    return csv.DictReader(io.StringIO(text), delimiter="\t")


def parse_fsds_zip(data: bytes) -> tuple[list[Filing], list[Fact]]:
    """Parse ``sub.txt`` and ``num.txt`` from an in-memory FSDS zip."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sub_name = next(name for name in archive.namelist() if name.endswith("/sub.txt") or name == "sub.txt")
        num_name = next(name for name in archive.namelist() if name.endswith("/num.txt") or name == "num.txt")
        sub_text = archive.read(sub_name).decode("utf-8-sig")
        num_text = archive.read(num_name).decode("utf-8-sig")

    filings_by_accession: dict[str, dict[str, str]] = {}
    filings: list[Filing] = []
    for row in _tab_reader(sub_text):
        filings_by_accession[row["adsh"]] = row
        filings.append(
            Filing(
                cik=int(row["cik"]),
                accession=row["adsh"],
                form=row.get("form", ""),
                filed=row.get("filedate", ""),
                period=row.get("period", ""),
                primary_document=row.get("filename", ""),
            )
        )

    facts: list[Fact] = []
    for row in _tab_reader(num_text):
        value_text = row.get("value", "")
        value = float(value_text) if value_text and ("." in value_text or "e" in value_text.lower()) else int(value_text)
        qtrs = int(row.get("qtrs", "0"))
        sub_row = filings_by_accession.get(row["adsh"], {})
        facts.append(
            Fact(
                cik=int(row["cik"]),
                tag=row.get("tag", ""),
                taxonomy=row.get("version", ""),
                value=value,
                unit=row.get("uom", ""),
                period_start=None,
                period_end=row["ddate"],
                instantaneous=qtrs == 0,
                form=str(sub_row.get("form", "")),
                filed=str(sub_row.get("filedate", "")),
                accession=row["adsh"],
                segments=row.get("segments") or None,
                coreg=row.get("coreg") or None,
            )
        )
    return filings, facts
