"""Read a prepared local fundamental snapshot in a Lean backtest."""

from pathlib import Path

from AlgorithmImports import Globals, QCAlgorithm, Resolution, TimeZones
from arkleon.quantconnect import ArkleonFundamental


class VertivNetIncome(ArkleonFundamental):
    # Prepare this snapshot offline with prepare_snapshot and an API key outside
    # Lean. Place it under the Lean data directory before starting the backtest.
    snapshot_path = Path(Globals.DataFolder) / "alternative" / "arkleon" / "vertiv-net-income.jsonl"


class ArkleonSnapshotExample(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2021, 4, 30)
        self.SetEndDate(2021, 5, 1)
        self.SetTimeZone(TimeZones.NewYork)
        # This is a caller-chosen series label, not a ticker-to-CIK lookup.
        self.fundamental_symbol = self.AddData(
            VertivNetIncome, "VRT-NET-INCOME-2020", Resolution.Minute,
            TimeZones.Utc, False,  # Data timezone UTC; fill-forward disabled.
        ).Symbol

    def OnData(self, data):
        if data.ContainsKey(self.fundamental_symbol):
            fact = data[self.fundamental_symbol]
            if fact is not None:
                self.Debug(f"{fact.EndTime} UTC: {fact.Value}; accession {fact['accession_id']}")
