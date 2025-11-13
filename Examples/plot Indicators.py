#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
import pandas as pd

from bokeh.plotting import output_file, show
from indicators import (
    SMACrossover, RSIIndicator, MACDIndicator, BollingerBands,
    VolumeSpike, ATRBreakout, GapMove, IndicatorRunner
)
from indicators.plotting_bokeh import build_dashboard


def load_df(path: Path | None) -> pd.DataFrame:
    if path is None:
        # Reuse the synthetic generator from examples/run_indicators.py by copy-pasting minimal logic
        import numpy as np
        rng = pd.date_range("2024-01-01", periods=250, freq="B")
        np.random.seed(42)
        close = pd.Series(np.cumsum(np.random.normal(0, 1, len(rng))) + 100, index=rng)
        high = close + np.random.uniform(0.1, 1.2, len(rng))
        low = close - np.random.uniform(0.1, 1.2, len(rng))
        open_ = close.shift(1).fillna(close) + np.random.uniform(-0.5, 0.5, len(rng))
        volume = pd.Series(np.random.lognormal(mean=12, sigma=0.5, size=len(rng)).astype(int), index=rng)
        return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})

    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    return df

def main():
    p = argparse.ArgumentParser(description="Plot OHLCV indicators with Bokeh")
    p.add_argument("--input", type=Path, default=None,
                   help="CSV with columns: date, open, high, low, close, volume")
    # Default now points inside csv_html/
    p.add_argument("--html", type=Path, default=Path("../csv_html/indicators_dashboard.html"),
                   help="Output HTML file")
    args = p.parse_args()

    # Resolve output path relative to this script’s directory and ensure folder exists
    base_dir = Path(__file__).resolve().parent
    out_path = args.html if args.html.is_absolute() else (base_dir / args.html)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = load_df(args.input)
    runner = IndicatorRunner([
        SMACrossover(short=10, long=50),
        RSIIndicator(length=14),
        MACDIndicator(),
        BollingerBands(length=20, stdev=2.0),
        VolumeSpike(lookback=20, threshold=2.0),
        ATRBreakout(length=14, multiple=1.5),
        GapMove(percent=2.0),
    ])
    wide = runner.run(df)

    layout_obj = build_dashboard(df, wide, atr_multiple=1.5, gap_threshold=2.0)
    output_file(out_path.as_posix(), title="Indicators Dashboard")
    show(layout_obj)  # opens in system default browser

if __name__ == "__main__":
    main()
