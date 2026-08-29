from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from .models import Company, Fact, Filing

AS_OF_WARNING = (
    "WARNING: as_of is best-effort, live-EDGAR point-in-time. It reflects only "
    "what SEC currently serves, is not certified, is not exhaustively "
    "join-verified, and has no permanent-reproducibility guarantee. SEC may "
    "change what its endpoints return at any time."
)


def _value_type(value: object) -> float | int:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    raise TypeError(f"Fact values must be numeric, got {type(value).__name__}")


def _fact_from_record(
    cik: int,
    taxonomy: str,
    tag: str,
    unit: str,
    record: dict[str, Any],
) -> Fact:
    start = record.get("start")
    end = record.get("end")
    if not isinstance(end, str):
        raise TypeError("fact end date must be a string")
    return Fact(
        cik=cik,
        tag=tag,
        taxonomy=taxonomy,
        value=_value_type(record.get("val")),
        unit=unit,
        period_start=start if isinstance(start, str) else None,
        period_end=end,
        instantaneous=start is None,
        form=str(record.get("form", "")),
        filed=str(record.get("filed", "")),
        accession=str(record.get("accn", "")),
    )


def parse_company_facts(payload: dict[str, Any]) -> FactSet:
    if not isinstance(payload, dict):
        raise TypeError("company facts payload must be a JSON object")
    facts: list[Fact] = []
    for taxonomy, tags in payload.get("facts", {}).items():
        if not isinstance(tags, dict):
            continue
        for tag, tag_data in tags.items():
            if not isinstance(tag_data, dict):
                continue
            for unit, records in tag_data.get("units", {}).items():
                if not isinstance(records, list):
                    continue
                facts.extend(
                    _fact_from_record(int(payload["cik"]), taxonomy, tag, unit, record)
                    for record in records
                    if isinstance(record, dict)
                )
    return FactSet(facts)


def parse_company_concept(payload: dict[str, Any]) -> FactSet:
    taxonomy = payload.get("taxonomy")
    tag = payload.get("tag")
    if not isinstance(taxonomy, str) or not isinstance(tag, str):
        raise TypeError("company concept payload must include taxonomy and tag")
    facts: list[Fact] = []
    for unit, records in payload.get("units", {}).items():
        if not isinstance(records, list):
            continue
        facts.extend(
            _fact_from_record(int(payload["cik"]), taxonomy, tag, unit, record)
            for record in records
            if isinstance(record, dict)
        )
    return FactSet(facts)


def parse_submissions(payload: dict[str, Any]) -> tuple[Company, list[Filing]]:
    required = ("cik", "name", "sic", "fiscalYearEnd")
    values = {key: payload.get(key) for key in required}
    if any(not isinstance(value, str) for value in values.values()):
        raise TypeError("submissions payload is missing company metadata")
    company = Company(
        cik=int(payload["cik"]),
        name=str(values["name"]),
        sic=str(values["sic"]),
        fiscal_year_end=str(values["fiscalYearEnd"]),
    )
    keys = (
        "accessionNumber",
        "form",
        "filingDate",
        "reportDate",
        "primaryDocument",
    )
    arrays = {key: payload.get("filings", {}).get("recent", {}).get(key, []) for key in keys}
    lengths = {len(value) for value in arrays.values() if isinstance(value, list)}
    if any(not isinstance(value, list) for value in arrays.values()) or len(lengths) > 1:
        raise TypeError("recent filing arrays must be parallel lists")
    filings = [
        Filing(
            cik=int(payload["cik"]),
            accession=str(accession),
            form=str(form),
            filed=str(filed),
            period=period or None,
            primary_document=str(document),
        )
        for accession, form, filed, period, document in zip(*arrays.values())
    ]
    return company, filings


class FactSet(Iterable[Fact]):
    def __init__(self, facts: Iterable[Fact] = ()) -> None:
        self._facts: tuple[Fact, ...] = tuple(facts)

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def __getitem__(self, index: int | slice) -> Fact | tuple[Fact, ...]:
        return self._facts[index]

    def to_list(self) -> list[Fact]:
        return list(self._facts)

    def as_of(self, date: str) -> "FactSet":
        """Return facts filed on or before ``date``.

WARNING: as_of is best-effort, live-EDGAR point-in-time. It reflects only what SEC currently serves, is not certified, is not exhaustively join-verified, and has no permanent-reproducibility guarantee. SEC may change what its endpoints return at any time.
        """
        return FactSet(fact for fact in self._facts if fact.filed <= date)

    def filter(self, **criteria: object) -> "FactSet":
        return FactSet(
            fact
            for fact in self._facts
            if all(getattr(fact, key) == value for key, value in criteria.items())
        )


def as_of(facts: Iterable[Fact], date: str) -> list[Fact]:
    """Filter facts whose filed date is on or before ``date``.

WARNING: as_of is best-effort, live-EDGAR point-in-time. It reflects only what SEC currently serves, is not certified, is not exhaustively join-verified, and has no permanent-reproducibility guarantee. SEC may change what its endpoints return at any time.
    """
    return [fact for fact in facts if fact.filed <= date]
