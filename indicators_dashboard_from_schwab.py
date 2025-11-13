"""
Self-contained indicators dashboard for a single ticker using
the Schwab OHLCV CSV produced by schwab_vol_scan_prep.py or the GUI.

Usage (from repo root):

  .\.venv\Scripts\python.exe indicators_dashboard_from_schwab.py ^
      --ticker AAPL ^
      --schwab-csv csv_html\schwab_ohlcv_gui.csv

This script does NOT rely on your 'indicators' package. It implements basic
indicators itself (SMA, Bollinger Bands, RSI, MACD, ATR) and renders a
multi-panel Bokeh dashboard.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from bokeh.io import output_file, show
from bokeh.layouts import column
from bokeh.plotting import figure
from bokeh.models import Span, ColumnDataSource

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_df_from_schwab(schwab_csv: Path, ticker: str) -> pd.DataFrame:
    """
    Load OHLCV for a single ticker from the Schwab OHLCV CSV.

    Expected columns: Date, Ticker, Open, High, Low, Close, Volume

    Returns a DataFrame indexed by Date with lowercase columns:
    [open, high, low, close, volume]
    """
    if not schwab_csv.exists():
        raise SystemExit(f"Schwab CSV not found: {schwab_csv}")

    df_all = pd.read_csv(schwab_csv, parse_dates=["Date"])

    if "Ticker" not in df_all.columns:
        raise SystemExit(
            f"{schwab_csv} does not have a 'Ticker' column. "
            "Did schwab_vol_scan_prep.py generate this file?"
        )

    mask = df_all["Ticker"].str.upper() == ticker.upper()
    df = df_all[mask].copy()
    if df.empty:
        raise SystemExit(f"No rows for ticker {ticker} in {schwab_csv}")

    df = df.sort_values("Date").set_index("Date")

    # Normalize column names
    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df.rename(columns={c: rename_map.get(c, c) for c in df.columns}, inplace=True)

    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise SystemExit(f"Missing columns for {ticker}: {missing}")

    return df


# ---------------------------------------------------------------------------
# Indicator calculations
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(length).mean()
    rs = gain / loss
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger_bands(series: pd.Series, window: int = 20, stdev: float = 2.0):
    mid = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    upper = mid + stdev * std
    lower = mid - stdev * std
    width = upper - lower
    return upper, mid, lower, width


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


# ---------------------------------------------------------------------------
# Dashboard construction
# ---------------------------------------------------------------------------

def build_dashboard(df: pd.DataFrame, ticker: str):
    """
    Build a Bokeh layout with:
    - Price + SMAs + Bollinger Bands
    - Volume
    - RSI(14)
    - MACD (line, signal, histogram)
    """
    df = df.copy()

    # Basic indicators
    df["sma20"] = sma(df["close"], 20)
    df["sma50"] = sma(df["close"], 50)
    df["sma200"] = sma(df["close"], 200)

    bb_upper, bb_mid, bb_lower, bb_width = bollinger_bands(df["close"], 20, 2.0)
    df["bb_upper"] = bb_upper
    df["bb_mid"] = bb_mid
    df["bb_lower"] = bb_lower

    df["rsi14"] = rsi(df["close"], 14)

    macd_line, signal_line, hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist

    df["atr14"] = atr(df, 14)

    # Reset index for plotting; create a 'date' column
    df_reset = df.reset_index()
    df_reset.rename(columns={"Date": "date"}, inplace=True)
    # In case the index name isn't exactly 'Date'
    if "date" not in df_reset.columns:
        df_reset.rename(columns={df_reset.columns[0]: "date"}, inplace=True)

    # --- Price + BB + SMAs ---
    p_price = figure(
        x_axis_type="datetime",
        title=f"{ticker} Price with SMAs & Bollinger Bands",
        height=300,
        sizing_mode="stretch_width",
    )
    p_price.line(df_reset["date"], df_reset["close"], legend_label="Close", line_width=2)
    p_price.line(df_reset["date"], df_reset["sma20"], legend_label="SMA20", line_width=1)
    p_price.line(df_reset["date"], df_reset["sma50"], legend_label="SMA50", line_width=1)
    p_price.line(df_reset["date"], df_reset["sma200"], legend_label="SMA200", line_width=1)
    p_price.line(df_reset["date"], df_reset["bb_upper"], legend_label="BB Upper", line_width=1)
    p_price.line(df_reset["date"], df_reset["bb_lower"], legend_label="BB Lower", line_width=1)
    p_price.legend.location = "top_left"

    # --- Volume ---
    p_vol = figure(
        x_axis_type="datetime",
        title="Volume",
        height=150,
        sizing_mode="stretch_width",
        x_range=p_price.x_range,
    )
    # width ~ 0.8 trading day in ms
    day_ms = 24 * 60 * 60 * 1000
    p_vol.vbar(
        x=df_reset["date"],
        top=df_reset["volume"],
        bottom=0,
        width=0.8 * day_ms,
    )

    # --- RSI ---
    p_rsi = figure(
        x_axis_type="datetime",
        title="RSI(14)",
        height=150,
        sizing_mode="stretch_width",
        x_range=p_price.x_range,
        y_range=(0, 100),
    )
    p_rsi.line(df_reset["date"], df_reset["rsi14"], line_width=2)
    p_rsi.add_layout(Span(location=70, dimension="width", line_dash="dashed"))
    p_rsi.add_layout(Span(location=30, dimension="width", line_dash="dashed"))

    # --- MACD ---
    p_macd = figure(
        x_axis_type="datetime",
        title="MACD",
        height=200,
        sizing_mode="stretch_width",
        x_range=p_price.x_range,
    )
    p_macd.line(df_reset["date"], df_reset["macd"], line_width=2, legend_label="MACD")
    p_macd.line(
        df_reset["date"],
        df_reset["macd_signal"],
        line_width=1,
        legend_label="Signal",
    )

    cds_hist = ColumnDataSource(
        dict(
            date=df_reset["date"],
            hist=df_reset["macd_hist"],
        )
    )
    p_macd.vbar(
        x="date",
        top="hist",
        bottom=0,
        width=0.8 * day_ms,
        source=cds_hist,
        alpha=0.5,
    )
    p_macd.legend.location = "top_left"

    return column(p_price, p_vol, p_rsi, p_macd)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Indicators dashboard for a ticker using Schwab OHLCV CSV."
    )
    parser.add_argument(
        "--ticker",
        required=True,
        help="Ticker symbol to chart (e.g. AAPL, NVDA).",
    )
    parser.add_argument(
        "--schwab-csv",
        type=Path,
        required=True,
        help="Path to Schwab OHLCV CSV (e.g. csv_html/schwab_ohlcv_gui.csv)",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help=(
            "Optional output HTML filename; default: "
            "csv_html/indicators_dashboard_<TICKER>.html"
        ),
    )
    args = parser.parse_args()

    df = load_df_from_schwab(args.schwab_csv, args.ticker)
    ticker = args.ticker.upper()

    html_dir = BASE_DIR / "csv_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    if args.html is not None:
        html_path = args.html
        if not html_path.is_absolute():
            html_path = html_dir / html_path
    else:
        html_path = html_dir / f"indicators_dashboard_{ticker}.html"

    title = f"Indicators Dashboard - {ticker}"

    layout = build_dashboard(df, ticker)
    output_file(html_path.as_posix(), title=title)
    show(layout)

    print(f"Indicators dashboard written to: {html_path}")


if __name__ == "__main__":
    main()
