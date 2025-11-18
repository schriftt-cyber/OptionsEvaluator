import datetime as dt
import os

import numpy as np
import pandas as pd
import yfinance as yf

from bokeh.resources import INLINE
from bokeh.io import output_file, save
from bokeh.layouts import layout
from bokeh.models import (
    ColumnDataSource,
    DataTable,
    TableColumn,
    HTMLTemplateFormatter,
    NumberFormatter,
    TabPanel,
    Tabs,
)

# --------------------
# CONFIG
# --------------------

DEFAULTS = dict(
    LOOKBACK_DAYS=260,
    ATR_PERIOD=14,
    BOLL_PERIOD=20,
    BOLL_STD=2.0,
    RVOL_LOOKBACK=30,
    HV_SHORT=20,
    HV_LONG=60,
    CATEGORY_WEIGHTS={
        "technical": 1.0,
        "participation": 1.0,
        "sentiment": 1.0,
        "volatility": 1.0,
    },
    CATEGORY_CAP={"technical": 1, "participation": 1, "sentiment": 1, "volatility": 1},
    RVOL_MIN=2.0,
    RANGE_MULT_MIN=1.5,
    BASE_SQUEEZE_PCTL=20,
    MIN_OPT_ABS_VOL=10000,
    ATR_RISING_MIN_DAYS=3,
    GREEN_RULE={"WeightedScore_min": 3.5, "CategoryActiveCount_min": 4, "RVOL_min": 3.0},
    YELLOW_RULE={"WeightedScore_min": 2.5, "CategoryActiveCount_min": 3},
)

EXPLOSIVE_OVERRIDES = dict(
    RVOL_MIN=3.0,
    RANGE_MULT_MIN=2.0,
    BASE_SQUEEZE_PCTL=10,
    MIN_OPT_ABS_VOL=20000,
    ATR_RISING_MIN_DAYS=5,
    GREEN_RULE={"WeightedScore_min": 3.8, "CategoryActiveCount_min": 4, "RVOL_min": 3.0},
    YELLOW_RULE={"WeightedScore_min": 2.8, "CategoryActiveCount_min": 3},
)


# --------------------
# CORE PRICE/VOL HELPERS
# --------------------


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            (df["High"] - df["Low"]).abs(),
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    return _true_range(df).rolling(period).mean()


def _boll_bandwidth(close: pd.Series, period: int, std: float) -> pd.Series:
    ma = close.rolling(period).mean()
    sd = close.rolling(window=period).std(ddof=0)
    upper = ma + std * sd
    lower = ma - std * sd
    return (upper - lower) / ma


def _hist_vol(close: pd.Series, window: int) -> pd.Series:
    lr = np.log(close / close.shift(1))
    return lr.rolling(window).std(ddof=0) * np.sqrt(252)


def _percent_rank(series: pd.Series, value: float) -> float:
    arr = series.dropna().values
    if len(arr) == 0:
        return np.nan
    return (np.sum(arr <= value) / len(arr)) * 100.0


def _cross_200dma(df: pd.DataFrame):
    ma200 = df["Close"].rolling(200).mean()
    if ma200.isna().iloc[-1]:
        return None
    prev = df["Close"].iloc[-2] - ma200.iloc[-2]
    curr = df["Close"].iloc[-1] - ma200.iloc[-1]
    if prev <= 0 < curr:
        return "UpCross"
    if prev >= 0 > curr:
        return "DownCross"
    return None


# --------------------
# DIRECTIONAL INDICATORS
# --------------------


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / avg_loss
    rsi_val = 100 - 100 / (1 + rs)
    return rsi_val


def _macd_histogram(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return hist


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]

    plus_dm = high.diff()
    minus_dm = low.shift(1) - low

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

    tr = _true_range(df)
    atr_val = tr.rolling(period).mean()

    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr_val)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr_val)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = dx.rolling(period).mean()
    return adx_val


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """
    Simple SuperTrend implementation.
    Returns:
        st_line: pd.Series
        direction: pd.Series (1 = bullish, -1 = bearish)
    """
    hl2 = (df["High"] + df["Low"]) / 2.0
    atr_val = _atr(df, period)

    upperband = hl2 + multiplier * atr_val
    lowerband = hl2 - multiplier * atr_val

    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)

    st.iloc[0] = hl2.iloc[0]
    direction.iloc[0] = 1  # start bullish arbitrarily

    for i in range(1, len(df)):
        prev_st = st.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]

        curr_upper = upperband.iloc[i]
        curr_lower = lowerband.iloc[i]

        if prev_dir == 1:
            curr_lower = max(curr_lower, prev_st)
        else:
            curr_upper = min(curr_upper, prev_st)

        price = df["Close"].iloc[i]

        if price > curr_upper:
            direction.iloc[i] = 1
            st.iloc[i] = curr_lower
        elif price < curr_lower:
            direction.iloc[i] = -1
            st.iloc[i] = curr_upper
        else:
            direction.iloc[i] = prev_dir
            st.iloc[i] = curr_lower if prev_dir == 1 else curr_upper

    return st, direction


# --------------------
# OPTIONS SNAPSHOT + STRADDLE METRICS
# --------------------


def _options_snapshot(ticker: str, underlying_price: float, hv20: float, log_fn=print):
    """
    Returns:
        {
          "opt_total_vol": int|None,
          "put_call": float|None,
          "straddle_cost": float|None,
          "expected_move": float|None,
          "ev_ratio": float|None,
        }
    """
    try:
        tk = yf.Ticker(ticker)
        expiries = tk.options
        if not expiries:
            return {
                "opt_total_vol": None,
                "put_call": None,
                "straddle_cost": None,
                "expected_move": None,
                "ev_ratio": None,
            }

        today = dt.date.today()
        exp = None
        exp_date = None
        for e in expiries:
            try:
                ed = dt.datetime.strptime(e, "%Y-%m-%d").date()
                if ed >= today:
                    exp = e
                    exp_date = ed
                    break
            except Exception:
                continue

        if exp is None:
            return {
                "opt_total_vol": None,
                "put_call": None,
                "straddle_cost": None,
                "expected_move": None,
                "ev_ratio": None,
            }

        chain = tk.option_chain(exp)
        calls = chain.calls if hasattr(chain, "calls") else pd.DataFrame()
        puts = chain.puts if hasattr(chain, "puts") else pd.DataFrame()

        call_vol = int(calls["volume"].fillna(0).sum()) if not calls.empty else 0
        put_vol = int(puts["volume"].fillna(0).sum()) if not puts.empty else 0
        total = call_vol + put_vol
        pcr = (put_vol / call_vol) if call_vol > 0 else (np.inf if put_vol > 0 else None)
        pcr_val = float(pcr) if pcr not in (None, np.inf) else (999.0 if pcr == np.inf else None)

        # ATM call/put selection
        atm_call_price = atm_put_price = None
        if not calls.empty:
            calls = calls.copy()
            calls["dist"] = (calls["strike"] - underlying_price).abs()
            call_row = calls.sort_values("dist").iloc[0]
            atm_call_price = float(call_row.get("lastPrice", np.nan))
        if not puts.empty:
            puts = puts.copy()
            puts["dist"] = (puts["strike"] - underlying_price).abs()
            put_row = puts.sort_values("dist").iloc[0]
            atm_put_price = float(put_row.get("lastPrice", np.nan))

        if atm_call_price is None or atm_put_price is None:
            straddle_cost = None
        else:
            straddle_cost = atm_call_price + atm_put_price

        # Expected move from HV20 over time to expiry (rough 1-sigma)
        if exp_date and hv20 and not np.isnan(hv20):
            days_to_exp = max((exp_date - today).days, 1)
            daily_vol = hv20 / np.sqrt(252)
            expected_move = underlying_price * daily_vol * np.sqrt(days_to_exp)
        else:
            expected_move = None

        if straddle_cost and expected_move and straddle_cost > 0:
            ev_ratio = expected_move / straddle_cost
        else:
            ev_ratio = None

        return {
            "opt_total_vol": total,
            "put_call": pcr_val,
            "straddle_cost": float(straddle_cost) if straddle_cost else None,
            "expected_move": float(expected_move) if expected_move else None,
            "ev_ratio": float(ev_ratio) if ev_ratio else None,
        }
    except Exception as e:
        log_fn(f"[VolScan] ERROR in options snapshot for {ticker}: {e}")
        return {
            "opt_total_vol": None,
            "put_call": None,
            "straddle_cost": None,
            "expected_move": None,
            "ev_ratio": None,
        }


# --------------------
# PER-TICKER ANALYSIS
# --------------------


def _analyze_ticker(ticker: str, cfg: dict, log_fn=print):
    try:
        # ------------- CSV source (if provided) -------------
        csv_path = cfg.get("LOCAL_CSV_PATH")
        if csv_path:
            if not os.path.isabs(csv_path):
                csv_path = os.path.join(os.path.dirname(__file__), csv_path)

            if os.path.exists(csv_path):
                try:
                    df_all = pd.read_csv(csv_path, parse_dates=["Date"])
                    if "Ticker" in df_all.columns:
                        df = df_all[df_all["Ticker"].str.upper() == ticker.upper()].copy()
                    else:
                        df = df_all.copy()

                    if df.empty:
                        log_fn(f"[VolScan] WARNING: no rows found for {ticker} in CSV.")
                        return None

                    df = df.sort_values("Date").set_index("Date")
                except Exception as e:
                    log_fn(f"[VolScan] ERROR reading CSV for {ticker}: {e}")
                    return None
            else:
                log_fn(f"[VolScan] WARNING: CSV path does not exist: {csv_path}")
                return None
        else:
            # ------------- fallback: live Yahoo -------------
            try:
                df = yf.download(
                    ticker,
                    period=f"{cfg['LOOKBACK_DAYS']}d",
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                )
            except Exception as e:
                log_fn(f"[VolScan] ERROR downloading data for {ticker}: {e}")
                return None

        if df is None or df.empty:
            log_fn(f"[VolScan] WARNING: no price data for {ticker}.")
            return None

        df = df.dropna().copy()

        # --- core vol indicators ---
        df["ATR"] = _atr(df, cfg["ATR_PERIOD"])
        atr_diff = df["ATR"] - df["ATR"].shift(1)
        atr_rising_days = int((atr_diff.iloc[-cfg["ATR_RISING_MIN_DAYS"]:] > 0).sum())

        bb = _boll_bandwidth(df["Close"], cfg["BOLL_PERIOD"], cfg["BOLL_STD"])
        df["BBWidth"] = bb
        bb_rank = _percent_rank(df["BBWidth"].tail(180), df["BBWidth"].iloc[-1])
        bb_expanding = df["BBWidth"].iloc[-1] > df["BBWidth"].iloc[-2]

        vol30 = df["Volume"].rolling(cfg["RVOL_LOOKBACK"]).mean()
        rvol = float(df["Volume"].iloc[-1] / vol30.iloc[-1]) if vol30.iloc[-1] > 0 else np.nan

        df["TR"] = _true_range(df)
        avg_range20 = df["TR"].rolling(20).mean().iloc[-1]
        range_mult = float(df["TR"].iloc[-1] / avg_range20) if avg_range20 > 0 else np.nan

        df["HV20"] = _hist_vol(df["Close"], cfg["HV_SHORT"])
        df["HV60"] = _hist_vol(df["Close"], cfg["HV_LONG"])
        hv_turning_up = df["HV20"].iloc[-1] > df["HV20"].iloc[-2]
        hv20 = float(df["HV20"].iloc[-1])
        hv60 = float(df["HV60"].iloc[-1])

        cross200 = _cross_200dma(df)
        price = float(df["Close"].iloc[-1])

        opt = _options_snapshot(ticker, price, hv20, log_fn=log_fn)
        opt_total_vol = opt.get("opt_total_vol")
        pcr = opt.get("put_call")
        straddle_cost = opt.get("straddle_cost")
        expected_move = opt.get("expected_move")
        ev_ratio = opt.get("ev_ratio")

        # --- vol flags / category scoring ---
        flags = {
            "rvol": (rvol >= cfg["RVOL_MIN"]) if not np.isnan(rvol) else False,
            "atr_up": atr_rising_days >= cfg["ATR_RISING_MIN_DAYS"],
            "bb_squeeze_then_expand": (bb_rank <= cfg["BASE_SQUEEZE_PCTL"]) and bb_expanding,
            "range_pop": (range_mult >= cfg["RANGE_MULT_MIN"]) if not np.isnan(range_mult) else False,
            "hv_turn": (hv20 < hv60) and hv_turning_up if not (np.isnan(hv20) or np.isnan(hv60)) else False,
            "cross200": cross200 is not None,
            "opt_vol_surge": (opt_total_vol is not None) and (opt_total_vol >= cfg["MIN_OPT_ABS_VOL"]),
            "pcr_extreme": isinstance(pcr, (int, float)) and (pcr <= 0.5 or pcr >= 1.5),
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
            weighted += min(hits, cfg["CATEGORY_CAP"].get(cat, 1)) * cfg["CATEGORY_WEIGHTS"].get(cat, 1.0)

        active_cats = sum(1 for v in cat_hits.values() if v > 0)

        # --- volatility recommendation (GO/WATCH/PASS) ---
        if (
            weighted >= cfg["GREEN_RULE"]["WeightedScore_min"]
            and active_cats >= cfg["GREEN_RULE"]["CategoryActiveCount_min"]
            and (rvol >= cfg["GREEN_RULE"]["RVOL_min"] if not np.isnan(rvol) else False)
        ):
            rec, color = "GO", "#18A558"
        elif (
            weighted >= cfg["YELLOW_RULE"]["WeightedScore_min"]
            and active_cats >= cfg["YELLOW_RULE"]["CategoryActiveCount_min"]
        ):
            rec, color = "WATCH", "#F4C430"
        else:
            rec, color = "PASS", "#D7263D"

        # ---------------- Directional metrics ----------------
        rsi14_series = _rsi(df["Close"], 14)
        rsi2_series = _rsi(df["Close"], 2)
        macd_hist_series = _macd_histogram(df["Close"])
        adx_series = _adx(df)
        _, st_dir_series = _supertrend(df, period=10, multiplier=3.0)
        ma50 = df["Close"].rolling(50).mean()

        rsi14_last = float(rsi14_series.iloc[-1])
        rsi2_last = float(rsi2_series.iloc[-1])
        macd_hist_last = float(macd_hist_series.iloc[-1])
        adx_last = float(adx_series.iloc[-1]) if not np.isnan(adx_series.iloc[-1]) else np.nan
        st_dir_last = int(st_dir_series.iloc[-1]) if not np.isnan(st_dir_series.iloc[-1]) else 0

        # simple MA50 slope
        if ma50.iloc[-1] > ma50.iloc[-5]:
            trend_dir = 1
        elif ma50.iloc[-1] < ma50.iloc[-5]:
            trend_dir = -1
        else:
            trend_dir = 0

        bull_score = 0
        bear_score = 0

        # RSI14
        if rsi14_last > 55:
            bull_score += 1
        if rsi14_last < 45:
            bear_score += 1

        # RSI2 extremes
        if rsi2_last < 20:
            bull_score += 1
        if rsi2_last > 80:
            bear_score += 1

        # MACD hist
        if macd_hist_last > 0:
            bull_score += 1
        elif macd_hist_last < 0:
            bear_score += 1

        # SuperTrend direction
        if st_dir_last == 1:
            bull_score += 1
        elif st_dir_last == -1:
            bear_score += 1

        # Trend / ADX bonus
        if not np.isnan(adx_last) and adx_last > 20:
            if trend_dir == 1 and macd_hist_last > 0:
                bull_score += 1
            elif trend_dir == -1 and macd_hist_last < 0:
                bear_score += 1

        # slope bonus
        if trend_dir == 1:
            bull_score += 1
        elif trend_dir == -1:
            bear_score += 1

        def _decide_call_put(bull, bear, vol_score):
            call_rec = "PASS"
            put_rec = "PASS"
            diff = bull - bear

            if vol_score >= 3.0:
                if diff >= 2 and bull >= 3:
                    call_rec = "GO"
                elif diff <= -2 and bear >= 3:
                    put_rec = "GO"
                elif diff >= 1 and bull >= 2:
                    call_rec = "WATCH"
                elif diff <= -1 and bear >= 2:
                    put_rec = "WATCH"
            elif vol_score >= 2.0:
                if diff >= 2 and bull >= 3:
                    call_rec = "WATCH"
                elif diff <= -2 and bear >= 3:
                    put_rec = "WATCH"

            return call_rec, put_rec

        call_rec, put_rec = _decide_call_put(bull_score, bear_score, weighted)

        def _decide_straddle(vol_score, bull, bear, ev):
            if vol_score >= 3.0 and ev and ev >= 1.2 and abs(bull - bear) <= 1:
                return "GO"
            if vol_score >= 2.5 and ev and ev >= 1.0 and abs(bull - bear) <= 2:
                return "WATCH"
            return "PASS"

        def _decide_strangle(vol_score, bull, bear, ev):
            if vol_score >= 3.3 and ev and ev >= 1.1 and abs(bull - bear) <= 2:
                return "GO"
            if vol_score >= 2.5 and ev and ev >= 0.9:
                return "WATCH"
            return "PASS"

        straddle_rec = _decide_straddle(weighted, bull_score, bear_score, ev_ratio)
        strangle_rec = _decide_strangle(weighted, bull_score, bear_score, ev_ratio)

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
            "Put_Call": (
                ">>∞"
                if pcr == 999.0
                else (round(pcr, 2) if isinstance(pcr, (int, float)) else "")
            ),
            "Recommendation": rec,
            "RecColor": color,
            "RSI14": round(rsi14_last, 1),
            "RSI2": round(rsi2_last, 1),
            "MACD_hist": round(macd_hist_last, 4),
            "ADX": round(adx_last, 1) if not np.isnan(adx_last) else np.nan,
            "ST_dir": st_dir_last,
            "TrendDir": trend_dir,
            "BullScore": bull_score,
            "BearScore": bear_score,
            "StraddleCost": round(straddle_cost, 2) if straddle_cost else "",
            "ExpectedMove": round(expected_move, 2) if expected_move else "",
            "EV_ratio": round(ev_ratio, 2) if ev_ratio else "",
            "Call_Rec": call_rec,
            "Put_Rec": put_rec,
            "Straddle_Rec": straddle_rec,
            "Strangle_Rec": strangle_rec,
        }
    except Exception as e:
        print(f"[VolScan] ERROR analyzing {ticker}: {e}")
        return None


# --------------------
# HISTORY + REC DAYS
# --------------------


def _attach_rec_days(df: pd.DataFrame, history_path: str, log_fn=print) -> pd.DataFrame:
    """
    Keeps a running history of (Date, Ticker, Recommendation) in history_path
    and adds a 'RecDays' column to df representing how many consecutive scan
    days the ticker has had its current Recommendation.
    """
    if df.empty or "Ticker" not in df.columns or "Recommendation" not in df.columns:
        df["RecDays"] = 0
        return df

    today = dt.date.today()

    # Ensure uppercase tickers in current DF
    df["Ticker"] = df["Ticker"].astype(str).str.upper()

    # Load existing history if any
    if os.path.exists(history_path):
        try:
            hist = pd.read_csv(history_path, parse_dates=["Date"])
        except Exception as e:
            log_fn(f"[VolScan] WARNING: failed to read history file {history_path}: {e}")
            hist = pd.DataFrame(columns=["Date", "Ticker", "Recommendation"])
    else:
        hist = pd.DataFrame(columns=["Date", "Ticker", "Recommendation"])

    if not hist.empty:
        hist["Ticker"] = hist["Ticker"].astype(str).str.upper()

    # Remove any existing rows for today's date + these tickers (we'll replace them)
    if not hist.empty:
        mask = ~(
            (hist["Date"].dt.date == today)
            & (hist["Ticker"].isin(df["Ticker"]))
        )
        hist = hist[mask]

    # Append today's rows
    new_rows = df[["Ticker", "Recommendation"]].copy()
    new_rows["Date"] = pd.Timestamp(today)
    new_rows = new_rows[["Date", "Ticker", "Recommendation"]]

    hist = pd.concat([hist, new_rows], ignore_index=True)

    # Save updated history
    try:
        hist.to_csv(history_path, index=False)
        log_fn(f"[VolScan] Updated recommendation history at {history_path}")
    except Exception as e:
        log_fn(f"[VolScan] WARNING: failed to write history file {history_path}: {e}")

    # Compute RecDays for current df
    rec_days = []
    for _, row in df.iterrows():
        t = str(row["Ticker"]).upper()
        rec = row["Recommendation"]

        h_t = hist[hist["Ticker"] == t].copy()
        if h_t.empty:
            rec_days.append(0)
            continue

        # Only consider rows up to today, sorted newest → oldest
        h_t = h_t[h_t["Date"] <= pd.Timestamp(today)]
        if h_t.empty:
            rec_days.append(0)
            continue

        h_t = h_t.sort_values("Date", ascending=False)

        count = 0
        for _, hrow in h_t.iterrows():
            if hrow["Recommendation"] == rec:
                count += 1
            else:
                break

        rec_days.append(count)

    df["RecDays"] = rec_days
    return df


# --------------------
# TABLE + PUBLIC API
# --------------------


def _make_table(df: pd.DataFrame) -> DataTable:
    """
    Build a Bokeh DataTable for the vol scanner.

    Key change: give the table explicit width/height and avoid tricky autosize
    so it renders reliably inside Tabs.
    """
    source = ColumnDataSource(df)

    cols = [
        TableColumn(field="Ticker", title="Ticker", width=90),
        TableColumn(field="Price", title="Price",
                    formatter=NumberFormatter(format="$0,0.00"), width=90),
        TableColumn(field="Vol", title="Vol",
                    formatter=NumberFormatter(format="0,0"), width=110),
        TableColumn(
            field="RecBadge",
            title="Vol Rec",
            formatter=HTMLTemplateFormatter(template="<%= value %>"),
            width=120,
        ),
        TableColumn(field="WeightedScore", title="Weighted",
                    formatter=NumberFormatter(format="0.00"), width=100),
        TableColumn(field="CategoryActiveCount", title="#Cats", width=70),
        TableColumn(field="CategoryHits_Technical", title="Tech", width=70),
        TableColumn(field="CategoryHits_Participation", title="Part.", width=70),
        TableColumn(field="CategoryHits_Sentiment", title="Sent.", width=70),
        TableColumn(field="CategoryHits_Volatility", title="Vol Cat", width=70),
        TableColumn(field="RVOL", title="RVOL",
                    formatter=NumberFormatter(format="0.00"), width=80),
        TableColumn(field="Range_mult_20d", title="Range×20d",
                    formatter=NumberFormatter(format="0.00"), width=110),
        TableColumn(field="BBWidth_pct_rank", title="BB %Rank",
                    formatter=NumberFormatter(format="0.0"), width=95),
        TableColumn(field="ATR_rising_days", title="ATR Up", width=75),
        TableColumn(field="HV20", title="HV20",
                    formatter=NumberFormatter(format="0.000"), width=90),
        TableColumn(field="HV60", title="HV60",
                    formatter=NumberFormatter(format="0.000"), width=90),
        TableColumn(field="Cross_200DMA", title="200DMA Cross", width=120),
        TableColumn(field="Opt_total_vol", title="Opt Vol", width=90),
        TableColumn(field="Put_Call", title="Put/Call", width=80),
        TableColumn(field="RSI14", title="RSI14",
                    formatter=NumberFormatter(format="0.0"), width=70),
        TableColumn(field="RSI2", title="RSI2",
                    formatter=NumberFormatter(format="0.0"), width=70),
        TableColumn(field="MACD_hist", title="MACD Hist",
                    formatter=NumberFormatter(format="0.0000"), width=95),
        TableColumn(field="ADX", title="ADX",
                    formatter=NumberFormatter(format="0.0"), width=70),
        TableColumn(field="BullScore", title="Bull", width=60),
        TableColumn(field="BearScore", title="Bear", width=60),
        TableColumn(field="StraddleCost", title="Straddle $",
                    formatter=NumberFormatter(format="0.00"), width=95),
        TableColumn(field="ExpectedMove", title="ExpMove $",
                    formatter=NumberFormatter(format="0.00"), width=95),
        TableColumn(field="EV_ratio", title="EV ratio",
                    formatter=NumberFormatter(format="0.00"), width=80),
        TableColumn(field="Call_Rec", title="Call", width=70),
        TableColumn(field="Put_Rec", title="Put", width=70),
        TableColumn(field="Straddle_Rec", title="Straddle", width=80),
        TableColumn(field="Strangle_Rec", title="Strangle", width=80),
        # If you added RecDays earlier, it will show up automatically
        # once you add a TableColumn here, e.g.:
        # TableColumn(field="RecDays", title="Days on Rec", width=90),
    ]

    return DataTable(
        source=source,
        columns=cols,
        index_position=None,
        width=1500,     # explicit width so it actually shows
        height=650,     # explicit height
        row_height=28,
        sortable=True,
        selectable=True,
        reorderable=False,
        # avoid autosize_mode here; it can cause zero-width behavior in some setups
    )



def build_vol_table_df(
    tickers,
    preset: str = "15%",
    csv_file: str | None = None,
    log_fn=print,
    total_count: int | None = None,
    completed_so_far: int = 0,
    progress_cb=None,
) -> pd.DataFrame:
    """
    Build the volatility scan table for the given tickers.

    - If csv_file is provided, it's passed via cfg["LOCAL_CSV_PATH"] so _analyze_ticker()
      loads OHLCV from that CSV instead of yfinance.
    - Also, if csv_file is provided and has Ticker/Date/Volume, we attach
      the latest Volume per ticker as 'Vol' for display.

    Progress logging:
      total_count      = total number of tickers in the overall run (file)
      completed_so_far = how many tickers have been processed BEFORE this batch

      For each ticker in this batch, we log:
        [VolScan] TICKER ... Complete (global_index/total_count, XX.X%)

    If progress_cb is provided, it will be called as:
        progress_cb(global_index, total_count, ticker)
    """
    cfg = DEFAULTS.copy()
    if "30" in str(preset):
        cfg.update(EXPLOSIVE_OVERRIDES)

    if csv_file:
        cfg["LOCAL_CSV_PATH"] = csv_file

    # Normalize and filter tickers
    norm_tickers = []
    for t in tickers:
        if t is None:
            continue
        t_sym = str(t).strip().upper()
        if not t_sym:
            continue
        norm_tickers.append(t_sym)

    batch_size = len(norm_tickers)
    if batch_size == 0:
        log_fn("[VolScan] No valid tickers provided.")
        return pd.DataFrame()

    # If caller didn't pass a total_count, assume this batch IS the total.
    if total_count is None or total_count <= 0:
        total_count = batch_size

    rows = []
    for batch_index, t_sym in enumerate(norm_tickers, start=1):
        global_index = completed_so_far + batch_index
        pct = (global_index / total_count) * 100.0 if total_count > 0 else 0.0

        result = _analyze_ticker(t_sym, cfg, log_fn=log_fn)
        if result:
            rows.append(result)
            log_fn(
                f"[VolScan] {t_sym} ... Complete "
                f"({global_index}/{total_count}, {pct:.1f}%)"
            )
        else:
            log_fn(
                f"[VolScan] {t_sym} ... Skipped (no data or error) "
                f"({global_index}/{total_count}, {pct:.1f}%)"
            )

        if progress_cb is not None:
            try:
                progress_cb(global_index, total_count, t_sym)
            except Exception:
                # don't let a progress callback crash the scan
                pass

    if not rows:
        log_fn("[VolScan] No tickers produced results.")
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
                log_fn(
                    "[VolScan] WARNING: CSV missing Ticker/Date/Volume; "
                    "cannot attach Vol column"
                )
                df["Vol"] = pd.NA
        except Exception as e:
            log_fn(f"[VolScan] WARNING: Failed to attach Vol from {csv_file}: {e}")
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

    df = df.sort_values(
        ["Recommendation", "WeightedScore", "CategoryActiveCount", "RVOL", "BullScore"],
        ascending=[True, False, False, False, False],
    ).reset_index(drop=True)

    return df


def render_vol_table_html(
    df,
    outfile: str = "vol_scanner_summary.html",
    title: str = "Indicator Summary",
    log_fn=print,
) -> str:
    """
    Save the volatility scan DataTables into an HTML file in the 'csv_html' folder,
    separated into Tabs by Vol Rec (PASS / WATCH / GO).

    Each tab contains a DataTable wrapped in a simple layout so it renders
    at full width/height.
    """
    from bokeh.io import output_file, save
    from bokeh.models import Tabs, TabPanel
    from bokeh.layouts import layout
    from bokeh.resources import INLINE

    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_dir = os.path.join(base_dir, "csv_html")
    os.makedirs(html_dir, exist_ok=True)

    out_path = os.path.join(html_dir, outfile)
    history_path = os.path.join(html_dir, "vol_rec_history.csv")

    # If you previously implemented RecDays tracking, keep this.
    # If you don't have _attach_rec_days defined, comment this line out.
    if "_attach_rec_days" in globals():
        df = _attach_rec_days(df.copy(), history_path, log_fn=log_fn)

    tabs_list = []
    for rec in ["GO", "WATCH", "PASS"]:
        sub = df[df["Recommendation"] == rec]
        if sub.empty:
            continue

        table = _make_table(sub)
        # Wrap table in a layout so Bokeh can size it correctly
        tab_layout = layout([[table]], sizing_mode="stretch_width")
        tabs_list.append(TabPanel(child=tab_layout, title=f"{rec} ({len(sub)})"))

    if not tabs_list:
        # No rec buckets? show a single table
        table = _make_table(df)
        root_obj = layout([[table]], sizing_mode="stretch_width")
    else:
        root_obj = Tabs(tabs=tabs_list)
        root_obj.width = 1600
        root_obj.height = 750

    output_file(out_path, title=title)
    save(root_obj, resources=INLINE)

    log_fn(f"[VolScan] HTML saved to {out_path}")
    return out_path


def tab_for_vol_table(df, title: str = "Vol Scanner") -> TabPanel:

    """
    Helper to embed the vol scanner table(s) as a single TabPanel.

    Used if you want to plug this table into a larger Bokeh Tabs structure.
    """
    from bokeh.models import Tabs, TabPanel
    from bokeh.layouts import layout

    base_dir = os.path.dirname(os.path.abspath(__file__))
    html_dir = os.path.join(base_dir, "csv_html")
    os.makedirs(html_dir, exist_ok=True)
    history_path = os.path.join(html_dir, "vol_rec_history.csv")

    if "_attach_rec_days" in globals():
        df = _attach_rec_days(df.copy(), history_path)

    inner_tabs = []
    for rec in ["GO", "WATCH", "PASS"]:
        sub = df[df["Recommendation"] == rec]
        if sub.empty:
            continue
        table = _make_table(sub)
        tab_layout = layout([[table]], sizing_mode="stretch_width")
        inner_tabs.append(TabPanel(child=tab_layout, title=f"{rec} ({len(sub)})"))

    if not inner_tabs:
        child = layout([[_make_table(df)]], sizing_mode="stretch_width")
    else:
        child = Tabs(tabs=inner_tabs)
        child.width = 1600
        child.height = 750

    return TabPanel(child=child, title=title)
