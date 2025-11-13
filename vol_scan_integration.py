import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import os

from bokeh.resources import INLINE

from bokeh.io import output_file, save
from bokeh.layouts import layout
from bokeh.models import (
    ColumnDataSource,
    DataTable,
    TableColumn,
    HTMLTemplateFormatter,
    NumberFormatter,
    Tabs,
    TabPanel,
)

# -----------------------
# Defaults (15% profile)
# -----------------------
DEFAULTS = dict(
    LOOKBACK_DAYS=260,
    ATR_PERIOD=14,
    BOLL_PERIOD=20,
    BOLL_STD=2.0,
    RVOL_LOOKBACK=30,
    HV_SHORT=20,
    HV_LONG=60,
    CATEGORY_WEIGHTS={"technical": 1.0, "participation": 1.0, "sentiment": 1.0, "volatility": 1.0},
    CATEGORY_CAP={"technical": 1, "participation": 1, "sentiment": 1, "volatility": 1},
    RVOL_MIN=2.0,
    RANGE_MULT_MIN=1.5,
    BASE_SQUEEZE_PCTL=20,
    MIN_OPT_ABS_VOL=10000,
    ATR_RISING_MIN_DAYS=3,
    GREEN_RULE={"WeightedScore_min": 3.5, "CategoryActiveCount_min": 4, "RVOL_min": 3.0},
    YELLOW_RULE={"WeightedScore_min": 2.5, "CategoryActiveCount_min": 3},
)


def _true_range(df):  # pandas DF with ['High','Low','Close']
    prev_close = df['Close'].shift(1)
    tr = pd.concat(
        [
            (df['High'] - df['Low']).abs(),
            (df['High'] - prev_close).abs(),
            (df['Low'] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def _atr(df, period: int):
    return _true_range(df).rolling(period).mean()


def _boll_bandwidth(close, period: int, std: float):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = ma + std * sd
    lower = ma - std * sd
    return (upper - lower) / ma


def _hist_vol(close, window: int):
    lr = np.log(close / close.shift(1))
    return lr.rolling(window).std(ddof=0) * np.sqrt(252)


def _percent_rank(series, value: float):
    arr = series.dropna().values
    if len(arr) == 0:
        return np.nan
    return (np.sum(arr <= value) / len(arr)) * 100.0


def _cross_200dma(df):
    ma200 = df['Close'].rolling(200).mean()
    if ma200.isna().iloc[-1]:
        return None
    prev = df['Close'].iloc[-2] - ma200.iloc[-2]
    curr = df['Close'].iloc[-1] - ma200.iloc[-1]
    if prev <= 0 < curr:
        return "UpCross"
    if prev >= 0 > curr:
        return "DownCross"
    return None


def _options_snapshot(ticker: str):
    try:
        tk = yf.Ticker(ticker)
        expiries = tk.options
        if not expiries:
            return {"opt_total_vol": None, "put_call": None}
        today = dt.date.today()
        exp = None
        for e in expiries:
            try:
                ed = dt.datetime.strptime(e, "%Y-%m-%d").date()
                if ed >= today:
                    exp = e
                    break
            except Exception:
                continue
        if exp is None:
            return {"opt_total_vol": None, "put_call": None}

        chain = tk.option_chain(exp)
        calls = chain.calls if hasattr(chain, "calls") else pd.DataFrame()
        puts = chain.puts if hasattr(chain, "puts") else pd.DataFrame()
        call_vol = int(calls['volume'].fillna(0).sum()) if not calls.empty else 0
        put_vol = int(puts['volume'].fillna(0).sum()) if not puts.empty else 0
        total = call_vol + put_vol
        pcr = (put_vol / call_vol) if call_vol > 0 else (np.inf if put_vol > 0 else None)
        pcr_val = float(pcr) if pcr not in (None, np.inf) else (999.0 if pcr == np.inf else None)
        return {"opt_total_vol": total, "put_call": pcr_val}
    except Exception:
        return {"opt_total_vol": None, "put_call": None}


def _analyze_ticker(ticker: str, cfg: dict):
    try:
        import os
        import pandas as pd
        import yfinance as yf

        # ------------- CSV source (if provided) -------------
        csv_path = cfg.get("LOCAL_CSV_PATH")
        if csv_path:
            # If user selected an absolute path, use it as-is. Otherwise, resolve relative to this file.
            if not os.path.isabs(csv_path):
                csv_path = os.path.join(os.path.dirname(__file__), csv_path)

            if os.path.exists(csv_path):
                try:
                    df_all = pd.read_csv(csv_path, parse_dates=["Date"])
                    # Filter by ticker if column exists; otherwise treat file as single-ticker
                    if "Ticker" in df_all.columns:
                        df = df_all[df_all["Ticker"].str.upper() == ticker.upper()].copy()
                    else:
                        df = df_all.copy()

                    if df.empty:
                        return None  # no rows for this ticker in the CSV

                    df = df.sort_values("Date").set_index("Date")
                except Exception:
                    return None  # parsing error -> treat as no data
            else:
                return None  # path provided but file missing -> no data
        else:
            # ------------- fallback: live Yahoo -------------
            df = yf.download(
                ticker,
                period=f"{cfg['LOOKBACK_DAYS']}d",
                interval="1d",
                auto_adjust=False,
                progress=False,
            )

        if df is None or df.empty:
            return None

        # Clean
        df = df.dropna().copy()

        df['ATR'] = _atr(df, cfg['ATR_PERIOD'])
        atr_diff = df['ATR'] - df['ATR'].shift(1)
        atr_rising_days = int((atr_diff.iloc[-cfg['ATR_RISING_MIN_DAYS']:] > 0).sum())

        bb = _boll_bandwidth(df['Close'], cfg['BOLL_PERIOD'], cfg['BOLL_STD'])
        df['BBWidth'] = bb
        bb_rank = _percent_rank(df['BBWidth'].tail(180), df['BBWidth'].iloc[-1])
        bb_expanding = df['BBWidth'].iloc[-1] > df['BBWidth'].iloc[-2]

        vol30 = df['Volume'].rolling(cfg['RVOL_LOOKBACK']).mean()
        rvol = float(df['Volume'].iloc[-1] / vol30.iloc[-1]) if vol30.iloc[-1] > 0 else np.nan

        df['TR'] = _true_range(df)
        avg_range20 = df['TR'].rolling(20).mean().iloc[-1]
        range_mult = float(df['TR'].iloc[-1] / avg_range20) if avg_range20 > 0 else np.nan

        df['HV20'] = _hist_vol(df['Close'], cfg['HV_SHORT'])
        df['HV60'] = _hist_vol(df['Close'], cfg['HV_LONG'])
        hv_turning_up = df['HV20'].iloc[-1] > df['HV20'].iloc[-2]
        hv20, hv60 = float(df['HV20'].iloc[-1]), float(df['HV60'].iloc[-1])

        cross200 = _cross_200dma(df)
        price = float(df['Close'].iloc[-1])

        opt = _options_snapshot(ticker)
        opt_total_vol = opt.get("opt_total_vol")
        pcr = opt.get("put_call")

        flags = {
            "rvol": (rvol >= cfg['RVOL_MIN']) if not np.isnan(rvol) else False,
            "atr_up": atr_rising_days >= cfg['ATR_RISING_MIN_DAYS'],
            "bb_squeeze_then_expand": (bb_rank <= cfg['BASE_SQUEEZE_PCTL']) and bb_expanding,
            "range_pop": (range_mult >= cfg['RANGE_MULT_MIN']) if not np.isnan(range_mult) else False,
            "hv_turn": (hv20 < hv60) and hv_turning_up if not (np.isnan(hv20) or np.isnan(hv60)) else False,
            "cross200": cross200 is not None,
            "opt_vol_surge": (opt_total_vol is not None) and (opt_total_vol >= cfg['MIN_OPT_ABS_VOL']),
            "pcr_extreme": (isinstance(pcr, (int, float))) and (pcr <= 0.5 or pcr >= 1.5),
        }

        cat_map = {
            "technical": ["atr_up", "bb_squeeze_then_expand", "cross200"],
            "participation": ["rvol", "range_pop"],
            "sentiment": ["opt_vol_surge", "pcr_extreme"],
            "volatility": ["hv_turn"],
        }
        cat_hits = {k: 0 for k in cat_map}
        total_flags = 0
        for f, on in flags.items():
            if on:
                total_flags += 1
                for cat, members in cat_map.items():
                    if f in members:
                        cat_hits[cat] += 1

        weighted = 0.0
        for cat, hits in cat_hits.items():
            weighted += min(hits, cfg['CATEGORY_CAP'].get(cat, 1)) * cfg['CATEGORY_WEIGHTS'].get(cat, 1.0)

        # Recommendation
        active_cats = sum(1 for v in cat_hits.values() if v > 0)
        if (
            weighted >= cfg['GREEN_RULE']["WeightedScore_min"]
            and active_cats >= cfg['GREEN_RULE']["CategoryActiveCount_min"]
            and (rvol >= cfg['GREEN_RULE']["RVOL_min"] if not np.isnan(rvol) else False)
        ):
            rec, color = "GO", "#18A558"
        elif (
            weighted >= cfg['YELLOW_RULE']["WeightedScore_min"]
            and active_cats >= cfg['YELLOW_RULE']["CategoryActiveCount_min"]
        ):
            rec, color = "WATCH", "#F4C430"
        else:
            rec, color = "PASS", "#D7263D"

        return {
            "Ticker": ticker,
            "Price": round(price, 2),
            "WeightedScore": round(float(weighted), 3),
            "CategoryActiveCount": int(active_cats),
            "CategoryHits_Technical": cat_hits["technical"],
            "CategoryHits_Participation": cat_hits["participation"],
            "CategoryHits_Sentiment": cat_hits["sentiment"],
            "CategoryHits_Volatility": cat_hits["volatility"],
            "Flags": total_flags,
            "RVOL": round(float(rvol), 2) if not np.isnan(rvol) else np.nan,
            "Range_mult_20d": round(float(range_mult), 2) if not np.isnan(range_mult) else np.nan,
            "BBWidth_pct_rank": round(float(bb_rank), 1) if not np.isnan(bb_rank) else np.nan,
            "ATR_rising_days": int(atr_rising_days),
            "HV20": round(hv20, 3) if not np.isnan(hv20) else np.nan,
            "HV60": round(hv60, 3) if not np.isnan(hv60) else np.nan,
            "Cross_200DMA": cross200 if cross200 else "",
            "Opt_total_vol": opt_total_vol if opt_total_vol is not None else "",
            "Put_Call": (">>∞" if pcr == 999.0 else (round(pcr, 2) if isinstance(pcr, (int, float)) else "")),
            "Recommendation": rec,
            "RecColor": color,
        }
    except Exception:
        return None


def _badge_column():
    return """
    <div style="background-color:<%= RecColor %>; color:white; border-radius:12px;
                padding:2px 8px; text-align:center; font-weight:600;">
      <%= Recommendation %>
    </div>
    """


def _make_table(df):
    source = ColumnDataSource(df)

    cols = [
        TableColumn(field="Ticker", title="Ticker", width=90),
        TableColumn(field="Price", title="Price", formatter=NumberFormatter(format="$0,0.00"), width=90),
        # New: actual share volume from Schwab CSV (if present)
        TableColumn(field="Vol", title="Vol", formatter=NumberFormatter(format="0,0"), width=110),

        # Badge is prebuilt HTML
        TableColumn(field="RecBadge", title="Rec", formatter=HTMLTemplateFormatter(template="<%= value %>"), width=120),

        TableColumn(field="WeightedScore", title="Weighted", formatter=NumberFormatter(format="0.00"), width=100),
        TableColumn(field="CategoryActiveCount", title="#Cats", width=70),
        TableColumn(field="CategoryHits_Technical", title="Tech", width=70),
        TableColumn(field="CategoryHits_Participation", title="Part.", width=70),
        TableColumn(field="CategoryHits_Sentiment", title="Sent.", width=70),
        # Renamed to avoid confusion with true volume
        TableColumn(field="CategoryHits_Volatility", title="Vol Cat", width=70),

        TableColumn(field="RVOL", title="RVOL", formatter=NumberFormatter(format="0.00"), width=80),
        TableColumn(field="Range_mult_20d", title="Range×20d", formatter=NumberFormatter(format="0.00"), width=110),
        TableColumn(field="BBWidth_pct_rank", title="BB %Rank", formatter=NumberFormatter(format="0.0"), width=95),
        TableColumn(field="ATR_rising_days", title="ATR Up", width=75),
        TableColumn(field="HV20", title="HV20", formatter=NumberFormatter(format="0.000"), width=90),
        TableColumn(field="HV60", title="HV60", formatter=NumberFormatter(format="0.000"), width=90),
        TableColumn(field="Cross_200DMA", title="200DMA Cross", width=120),
        TableColumn(field="Opt_total_vol", title="Opt Vol", width=90),
        TableColumn(field="Put_Call", title="Put/Call", width=80),
    ]

    return DataTable(
        source=source,
        columns=cols,
        index_position=None,
        width=1700,
        height=600,
        row_height=28,
        sortable=True,
        selectable=True,
        reorderable=False,
        autosize_mode="none",
        sizing_mode=None,
    )


# ---------- Public API ----------

def build_vol_table_df(tickers, preset="15%", csv_file=None):
    """
    Build the volatility scan table for the given tickers.

    - If csv_file is provided, it's passed via cfg["LOCAL_CSV_PATH"] so _analyze_ticker()
      loads OHLCV from that CSV instead of yfinance.
    - Also, if csv_file is provided and has Ticker/Date/Volume, we attach
      the latest Volume per ticker as 'Vol' for display.
    - Adds a pre-rendered 'RecBadge' HTML column.
    """
    cfg = DEFAULTS.copy()

    # Optional stricter preset
    if "30" in str(preset):
        cfg.update(
            dict(
                RVOL_MIN=3.0,
                RANGE_MULT_MIN=2.0,
                BASE_SQUEEZE_PCTL=10,
                MIN_OPT_ABS_VOL=20000,
                ATR_RISING_MIN_DAYS=5,
                GREEN_RULE={"WeightedScore_min": 3.8, "CategoryActiveCount_min": 4, "RVOL_min": 3.0},
                YELLOW_RULE={"WeightedScore_min": 2.8, "CategoryActiveCount_min": 3},
            )
        )

    # If a CSV was chosen in the GUI, use it
    if csv_file:
        cfg["LOCAL_CSV_PATH"] = csv_file

    rows = []
    for t in tickers:
        r = _analyze_ticker(t.strip().upper(), cfg)
        if r:
            rows.append(r)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Attach latest daily Volume per ticker as 'Vol' if we have a Schwab CSV
    if csv_file:
        try:
            hist = pd.read_csv(csv_file, parse_dates=["Date"])
            if {"Ticker", "Date", "Volume"}.issubset(hist.columns):
                hist_sorted = hist.sort_values(["Ticker", "Date"])
                last_by_ticker = (
                    hist_sorted.groupby("Ticker")["Volume"]
                    .last()
                    .rename("Vol")
                    .reset_index()
                )
                df = df.merge(last_by_ticker, on="Ticker", how="left")
            else:
                print("[WARN] CSV missing Ticker/Date/Volume; cannot attach Vol column")
                df["Vol"] = pd.NA
        except Exception as e:
            print(f"[WARN] Failed to attach Vol from {csv_file}: {e}")
            df["Vol"] = pd.NA
    else:
        df["Vol"] = pd.NA

    # Prebuild badge HTML so the DataTable template can safely use <%= value %>
    def _badge_html(row):
        color = row.get("RecColor", "#444")
        text = row.get("Recommendation", "")
        return (
            f"<div style='background-color:{color}; color:white; border-radius:12px;"
            f" padding:2px 8px; text-align:center; font-weight:600;'>{text}</div>"
        )

    df["RecBadge"] = df.apply(_badge_html, axis=1)

    # Order rows: strongest first
    df = df.sort_values(
        ["Recommendation", "WeightedScore", "CategoryActiveCount", "RVOL"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)

    # Debug: confirm Vol exists and looks sane
    print("\n[DEBUG] vol_df columns:", list(df.columns))
    if "Vol" in df.columns:
        print("[DEBUG] Vol stats:")
        print(df["Vol"].describe())
        print("[DEBUG] Sample Vol rows:")
        print(df[["Ticker", "Vol"]].head(20))
    else:
        print("[DEBUG] No 'Vol' column in vol_df!")

    return df


def render_vol_table_html(df, outfile="vol_scanner_summary.html", title="Indicator Summary"):
    """
    Save the volatility scan DataTable to an HTML file in the 'csv_html' folder.
    Automatically creates the folder if it doesn't exist.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_dir = os.path.join(base_dir, "csv_html")
    os.makedirs(html_dir, exist_ok=True)

    out_path = os.path.join(html_dir, outfile)

    table = _make_table(df)
    output_file(out_path, title=title)
    save(layout([[table]]), resources=INLINE)

    return out_path


def tab_for_vol_table(df, title="Vol Scanner"):
    """Return a TabPanel to append into your existing Bokeh Tabs."""
    table = _make_table(df)
    return TabPanel(child=layout([[table]]), title=title)
