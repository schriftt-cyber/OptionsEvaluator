# schwab_vol_scan_prep.py
import argparse
import datetime as dt
from pathlib import Path

import pandas as pd
import httpx  # comes indirectly via schwab-py, but we use it for status codes

from schwab_client import get_schwab_client
from vol_scan_integration import build_vol_table_df, render_vol_table_html


def _ticker_list_from_file(path: Path) -> list[str]:
    """Read tickers from a text file (one per line, '#' begins a comment)."""
    tickers: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    return tickers


def _price_history_to_df(symbol: str, history: dict) -> pd.DataFrame:
    """
    Convert Schwab price-history JSON into a DataFrame with the columns
    expected by vol_scan_integration's CSV loader.

    We assume a 'candles' array with fields:
      - open, high, low, close, volume, datetime (epoch ms)
    If Schwab changes the schema, print(history) once and adjust this mapping.
    """
    # --- DEBUG: show top-level keys and first candle ---
    #print(f"\n[DEBUG] Raw history for {symbol}: keys = {list(history.keys())}")
    candles = history.get("candles", [])
    #if candles:
    #    print(f"[DEBUG] First candle for {symbol}: {candles[0]}")
    #else:
    #    print(f"[DEBUG] No candles in history for {symbol}")

    rows = []
    for c in candles:
        # Schwab uses epoch milliseconds for datetime (mirrors the old TDA API).
        ts_ms = c.get("datetime")
        if ts_ms is None:
            continue

        date = dt.datetime.fromtimestamp(ts_ms / 1000).date()

        rows.append(
            {
                "Date": date,
                "Ticker": symbol,
                "Open": float(c.get("open", 0.0)),
                "High": float(c.get("high", 0.0)),
                "Low": float(c.get("low", 0.0)),
                "Close": float(c.get("close", 0.0)),
                "Volume": int(c.get("volume", 0)),
            }
        )

    df = pd.DataFrame(rows)

    # --- DEBUG: show last few rows and volume stats for this symbol ---
    #if not df.empty:
    #    print(f"[DEBUG] DataFrame for {symbol} (tail):")
    #    print(df.tail())
    #    print(f"[DEBUG] Volume stats for {symbol}:")
    #    print(df["Volume"].describe())
    #else:
    #    print(f"[DEBUG] DataFrame for {symbol} is EMPTY")

    return df



def fetch_ohlcv_for_tickers(
    tickers: list[str],
    lookback_days: int = 260,
) -> pd.DataFrame:
    """
    Fetch daily OHLCV for each symbol from Schwab and return a single DataFrame
    with columns [Date, Ticker, Open, High, Low, Close, Volume].
    """
    client = get_schwab_client()

    end_dt = dt.datetime.now()
    start_dt = end_dt - dt.timedelta(days=lookback_days)

    frames: list[pd.DataFrame] = []

    for symbol in tickers:
        resp = client.get_price_history_every_day(
            symbol,
            start_datetime=start_dt,
            end_datetime=end_dt,
            need_extended_hours_data=False,
            need_previous_close=False,
        )

        # Basic error handling
        if resp.status_code != httpx.codes.OK:
            print(f"[WARN] Failed to fetch data for {symbol}: {resp.status_code}")
            continue

        # --- DEBUG: show HTTP status and top-level JSON keys ---
        data = resp.json()
        print(f"\n[DEBUG] HTTP {resp.status_code} for {symbol}, top-level keys: {list(data.keys())}")

        df_symbol = _price_history_to_df(symbol, data)
        if df_symbol.empty:
            print(f"[WARN] No candles returned for {symbol}")
            continue

        frames.append(df_symbol)

    if not frames:
        return pd.DataFrame(
            columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]
        )

    df_all = pd.concat(frames, ignore_index=True)
    df_all.sort_values(["Ticker", "Date"], inplace=True)

    # --- DEBUG: global sanity check on Volume column ---
    #print("\n[DEBUG] Combined df_all head():")
    #print(df_all.head())
    #print("\n[DEBUG] Combined Volume stats by ticker:")
    #print(df_all.groupby("Ticker")["Volume"].describe())

    return df_all



def main():
    parser = argparse.ArgumentParser(
        description="Fetch OHLCV from Schwab for a list of tickers and "
        "produce a CSV compatible with vol_scan_integration."
    )
    parser.add_argument(
        "--tickers-file",
        type=Path,
        required=True,
        help="Path to text file with one ticker per line.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=260,
        help="Number of calendar days of history to request (default: 260).",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Optional explicit output CSV path. "
             "Default: <repo_root>/csv_html/schwab_ohlcv.csv",
    )
    parser.add_argument(
        "--build-html",
        action="store_true",
        help="If set, also run vol_scan_integration and build an HTML summary.",
    )
    parser.add_argument(
        "--preset",
        default="15%",
        help="Preset to pass into build_vol_table_df (e.g. '15%%' or '30%%').",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    csv_dir = repo_root / "csv_html"
    csv_dir.mkdir(parents=True, exist_ok=True)

    csv_path = args.csv_out or (csv_dir / "schwab_ohlcv.csv")

    tickers = _ticker_list_from_file(args.tickers_file)
    if not tickers:
        raise SystemExit(f"No tickers found in {args.tickers_file}")

    print(f"Fetching OHLCV for {len(tickers)} tickers from Schwab...")
    df = fetch_ohlcv_for_tickers(tickers, lookback_days=args.lookback_days)

    if df.empty:
        raise SystemExit("No data fetched from Schwab. Aborting.")

    # Write CSV in the exact shape vol_scan_integration expects
    df.to_csv(csv_path, index=False)
    print(f"Wrote Schwab OHLCV CSV to: {csv_path}")

    if args.build-html:
        print("Building volatility scan HTML using vol_scan_integration...")
        vol_df = build_vol_table_df(tickers, preset=args.preset, csv_file=str(csv_path))
        out_html = render_vol_table_html(
            vol_df,
            outfile="vol_scanner_from_schwab.html",
            title="Vol Scanner (Schwab Data)",
        )
        print(f"Vol scanner HTML written to: {out_html}")


if __name__ == "__main__":
    main()
