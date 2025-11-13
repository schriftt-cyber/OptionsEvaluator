#!/usr/bin/env python3
"""
Quick example runner for the indicators package.

Usage:
  python examples/run_indicators.py --input data.csv --output signals.csv

The input CSV (optional) should have columns: open, high, low, close, volume
and either a DatetimeIndex or a column named 'date' or 'timestamp'. If --input
is omitted, a synthetic price series is generated for demonstration.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

from indicators import (SMACrossover, RSIIndicator, MACDIndicator, BollingerBands, VolumeSpike, ATRBreakout, GapMove, IndicatorRunner)



def _load_df(path: Path | None) -> pd.DataFrame:
    if path is None:
        # Generate a simple synthetic dataset (business days)
        rng = pd.date_range("2024-01-01", periods=250, freq="B")
        np.random.seed(42)
        close = pd.Series(np.cumsum(np.random.normal(0, 1, len(rng))) + 100, index=rng)
        high = close + np.random.uniform(0.1, 1.2, len(rng))
        low = close - np.random.uniform(0.1, 1.2, len(rng))
        open_ = close.shift(1).fillna(close) + np.random.uniform(-0.5, 0.5, len(rng))
        volume = pd.Series(np.random.lognormal(mean=12, sigma=0.5, size=len(rng)).astype(int), index=rng)
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
        return df

    df = pd.read_csv(path)
    # Try to set a datetime index if present
    for col in ("date", "timestamp", "Datetime", "datetime"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
            df = df.set_index(col).sort_index()
            break
    # Ensure required columns exist
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input file missing required columns: {sorted(missing)}")
    return df


essentials = [
    SMACrossover(short=10, long=50),
    RSIIndicator(length=14, oversold=30, overbought=70),
    MACDIndicator(fast=12, slow=26, signal_len=9),
    BollingerBands(length=20, stdev=2.0),
    VolumeSpike(lookback=20, threshold=2.0),
    ATRBreakout(length=14, multiple=1.5),
    GapMove(percent=2.0),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=None, help="Path to OHLCV CSV (optional)")
    p.add_argument("--output", type=Path, default=None, help="Where to save signals CSV (optional)")
    args = p.parse_args()

    df = _load_df(args.input)
    runner = IndicatorRunner(essentials)
    wide = runner.run(df)

    # Show a peek
    print("Signals (tail):")
    print(wide.tail(10))

    if args.output is not None:
        wide.to_csv(args.output)
        print(f"\nSaved signals to: {args.output}")


if __name__ == "__main__":
    main()
