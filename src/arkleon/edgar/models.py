from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    cik: int
    name: str
    sic: str | None = None
    fiscal_year_end: str | None = None
    tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Filing:
    cik: int
    accession: str
    form: str
    filed: str
    period: str | None = None
    primary_document: str | None = None


@dataclass(frozen=True)
class Fact:
    cik: int
    tag: str
    taxonomy: str
    value: float | int
    unit: str
    period_start: str | None
    period_end: str | None
    instantaneous: bool
    form: str
    filed: str
    accession: str
    segments: str | None = None
    coreg: str | None = None
