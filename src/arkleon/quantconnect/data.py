"""Lean adapter for prepared JSONL snapshots, with no network or credentials.

Set ``snapshot_path`` on a subclass before registering that subclass with Lean.
Use ``AddData(MyData, symbol, Resolution.Minute, TimeZones.Utc, False)``: the
subscription's *data* timezone must be UTC, regardless of algorithm timezone.
Time and EndTime are the observation instant in naive UTC, as required by
Lean's DateTime/data-timezone convention. Using UTC avoids ambiguous DST wall
times. Lean schedules delivery using EndTime, not the accounting period.

A file may contain several periods; use equal period_start/period_end filters
and a distinct subscription symbol for each period if all period values must
be independently addressable in a Lean Slice at the same observation time.
"""

from __future__ import annotations

from datetime import timezone
import json
from pathlib import Path

from .loader import SnapshotError, _instant, _number, visible_as_filed

try:
    from QuantConnect.Python import PythonData
    from QuantConnect import SubscriptionTransportMedium
    from QuantConnect.Data import SubscriptionDataSource
    from System import Decimal as LeanDecimal
    from System.Globalization import CultureInfo
except ImportError as exc:
    raise ImportError(
        "ArkleonFundamental requires the QuantConnect Lean runtime; "
        "snapshot preparation works without Lean"
    ) from exc


class ArkleonFundamental(PythonData):
    """One observation's as-filed value, with public fact provenance fields."""

    snapshot_path: str | Path | None = None

    @staticmethod
    def _check_timezone(config):
        zone = getattr(config, "DataTimeZone", None)
        if getattr(zone, "Id", None) not in ("UTC", "Etc/UTC"):
            raise SnapshotError("Register the subscription with TimeZones.Utc")

    def GetSource(self, config, date, isLiveMode):
        """Return the prepared local file (Lean PythonData callback)."""
        self._check_timezone(config)
        if self.snapshot_path is None:
            raise SnapshotError("Set snapshot_path on the custom data subclass")
        source = str(self.snapshot_path)
        if "://" in source:
            raise SnapshotError("snapshot_path must be a local file")
        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file():
            raise SnapshotError("snapshot_path must name a local file")
        return SubscriptionDataSource(str(path), SubscriptionTransportMedium.LocalFile)

    def Reader(self, config, line, date, isLiveMode):
        """Decode one JSON line and reapply the shared visibility policy."""
        self._check_timezone(config)
        if not line.strip():
            return None
        try:
            record = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise SnapshotError("Invalid snapshot JSON line") from exc
        if (
            not isinstance(record, dict)
            or type(record.get("snapshot_version")) is not int
            or record["snapshot_version"] != 1
        ):
            raise SnapshotError("Unsupported snapshot record")
        cutoff = _instant(record.get("observation_time"))
        facts = visible_as_filed([record], cutoff)
        if not facts:
            return None
        fact = facts[0]
        result = type(self)()
        result.Symbol = config.Symbol
        stamp = cutoff.astimezone(timezone.utc).replace(tzinfo=None)
        result.Time = stamp
        result.EndTime = stamp
        number = _number(fact["value"])
        lean_value = LeanDecimal.Parse(format(number, "f"), CultureInfo.InvariantCulture)
        if _number(lean_value.ToString(CultureInfo.InvariantCulture)) != number:
            raise SnapshotError("Selected value cannot be represented exactly by Lean Decimal")
        result.Value = lean_value
        for key, value in fact.items():
            if key != "value":  # Lean reserves this case-insensitive property.
                result[key] = value
        result["as_filed_value"] = str(fact["value"])
        result["observation_time"] = cutoff.isoformat()
        return result

    # Current Lean Python examples use snake_case; PascalCase is the underlying
    # C# PythonData dispatch contract. Expose both spellings explicitly.
    get_source = GetSource
    reader = Reader
