import os
import sys
import threading
import time
import tempfile
import webbrowser
import importlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import subprocess
import traceback

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText

# --- Optional plotting deps (installed via: pip install bokeh numpy) ---
try:
    import numpy as np
    from bokeh.plotting import figure, output_file, save
    from bokeh.models import (
        Label,
        Span,
        Tabs,
        TabPanel,
        HoverTool,
        CrosshairTool,
        TapTool,
        ColumnDataSource,
        CustomJS,
    )
    from bokeh.resources import INLINE
except Exception:
    np = None

BASE_DIR = Path(__file__).resolve().parent

# ----------------------------
# Browser helper (prefer Chrome)
# ----------------------------
def _open_in_chrome(url: str) -> bool:
    """
    Try to open a URL specifically in Google Chrome on Windows.
    Returns True if successful, False otherwise (so caller can fall back).
    """
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("google-chrome"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                webbrowser.register("chrome", None, webbrowser.BackgroundBrowser(path))
                webbrowser.get("chrome").open(url)
                return True
            except Exception:
                pass
    return False


# ----------------------------
# Vol scanner module loader
# ----------------------------
import importlib.util

def _load_vol_scan_module(log_fn=print):
    """
    Load vol_scan_integration.py by absolute path so cwd / sys.path don't matter.
    Returns the loaded module object.
    """
    base = Path(__file__).resolve().parent
    candidates = [
        base / "vol_scan_integration.py",
        base / "scanners" / "vol_scan_integration.py",  # optional fallback folder
    ]

    for path in candidates:
        if path.exists():
            try:
                mod_name = "vol_scan_integration"  # fixed name
                spec = importlib.util.spec_from_file_location(mod_name, str(path))
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not create spec for {path}")
                mod = importlib.util.module_from_spec(spec)
                # replace any stale cached module
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                log_fn(f"[Vol Scanner] Loaded module from: {path}")
                return mod
            except Exception as e:
                log_fn(f"[Vol Scanner] Import failed from {path}: {e}")
                log_fn(traceback.format_exc())
                raise
    raise FileNotFoundError("vol_scan_integration.py not found in expected locations.")


def _ticker_list_from_file(path):
    """
    Read tickers from a text file (one per line, '#' for comments).
    Returns a list of uppercased tickers.
    """
    p = Path(path)
    if not p.exists():
        return []

    tickers = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    return tickers


# ----------------------------
# Option payoff utilities
# ----------------------------
@dataclass
class OptionInputs:
    ticker: str
    spot: float        # current price S0 (will be set from Schwab if available)
    call_strike: float
    call_premium: float
    put_strike: float
    put_premium: float
    price_min: float
    price_max: float
    step: float


def read_option_inputs_csv(path):
    """
    Reads a CSV file with columns:
      strategy,ticker,call_strike,call_premium,put_strike,put_premium

    The 'spot' column is optional and ONLY used as a fallback if Schwab
    prices cannot be fetched. The plots will normally use live prices
    from Charles Schwab instead.

    price_min, price_max, and step are derived automatically:
      - step = 0.01
      - For a straddle  (Kc == Kp):
            price_min = Kc - 3 * (call_premium + put_premium)
            price_max = Kc + 3 * (call_premium + put_premium)
      - For a strangle (Kp < Kc):
            price_min = Kp - 3 * (call_premium + put_premium)
            price_max = Kc + 3 * (call_premium + put_premium)
    """
    import csv

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)

        # Spot is no longer required
        required = [
            "strategy",
            "ticker",
            "call_strike",
            "call_premium",
            "put_strike",
            "put_premium",
        ]
        missing = [c for c in required if c not in rdr.fieldnames]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        has_spot_col = "spot" in (rdr.fieldnames or [])

        for i, r in enumerate(rdr, start=2):  # header is row 1
            try:
                strategy = (r["strategy"] or "").strip().lower()
                if strategy not in ("strangle", "straddle"):
                    raise ValueError(f"Row {i}: strategy must be 'strangle' or 'straddle'.")

                def fget(k): return float(str(r[k]).strip())

                # Optional: CSV may still include spot; we keep it ONLY as fallback.
                spot = None
                if has_spot_col:
                    val = (r.get("spot") or "").strip()
                    if val:
                        spot = float(val)

                kc = fget("call_strike")
                c  = fget("call_premium")
                kp = fget("put_strike")
                p  = fget("put_premium")

                total_premium = c + p
                step = 0.01  # your updated step

                # For a straddle, put strike is same as call strike
                if strategy == "straddle":
                    kp = kc

                # Set plotting range based on strikes and total premium
                if strategy == "straddle":
                    price_min = kc - 3.0 * total_premium
                    price_max = kc + 3.0 * total_premium
                else:  # strangle
                    price_min = kp - 3.0 * total_premium
                    price_max = kc + 3.0 * total_premium

                rows.append(OptionInputs(
                    ticker=r["ticker"].strip().upper() or "TICKER",
                    spot=spot if spot is not None else 0.0,  # will be replaced by Schwab
                    call_strike=kc,
                    call_premium=c,
                    put_strike=kp,
                    put_premium=p,
                    price_min=price_min,
                    price_max=price_max,
                    step=step,
                ))
            except Exception as e:
                raise ValueError(f"Error parsing row {i}: {e}") from e

    return rows


def _make_payoff_figure(inp: OptionInputs):
    """
    Return a single Bokeh Figure for one straddle/strangle input.
    Shows:
      - Total payoff
      - Individual call/put legs
      - Per-leg ITM start (strike) and per-leg break-evens
      - Current price point in green with current payoff
      - Last up to 9 prior closes as smaller, fading green dots (no labels)
      - Total premium annotation
      - Interactive hover and click to show Price & P/L
    """
    if np is None:
        raise RuntimeError("Missing dependencies. Install with: pip install bokeh numpy")

    # Price grid
    S = np.arange(inp.price_min, inp.price_max + inp.step, inp.step)

    # Legs and combined payoff (at expiration)
    call_leg = np.maximum(0.0, S - inp.call_strike) - inp.call_premium
    put_leg  = np.maximum(0.0, inp.put_strike - S) - inp.put_premium
    payoff   = call_leg + put_leg

    # Combined-strategy break-evens
    total_premium = inp.call_premium + inp.put_premium
    be_lower = inp.put_strike - total_premium
    be_upper = inp.call_strike + total_premium

    # Per-leg break-evens (where each individual option crosses 0 P/L)
    call_be = inp.call_strike + inp.call_premium
    put_be  = inp.put_strike - inp.put_premium

    p = figure(
        title=f"{inp.ticker} Payoff (Strangle/Straddle)",
        x_axis_label="Stock Price at Expiration",
        y_axis_label="Profit / Loss (per 1x)",
        toolbar_location="right",
        sizing_mode="stretch_both",
        min_width=1000,
        min_height=500,
        tools="pan,wheel_zoom,box_zoom,reset",
        active_drag="pan",
        active_scroll="wheel_zoom",
    )

    # Force x-axis to exactly match price_min/price_max
    p.x_range.start = inp.price_min
    p.x_range.end   = inp.price_max

    from bokeh.models import (
        Label,
        Span,
        HoverTool,
        CrosshairTool,
        TapTool,
        ColumnDataSource,
        CustomJS,
    )

    # Data source for the main payoff curve (for hover/tap)
    source = ColumnDataSource(data=dict(S=S, payoff=payoff))

    # --- Main lines ---
    # Total payoff (using source so hover/tap work)
    line_renderer = p.line(
        'S', 'payoff',
        source=source,
        line_width=3,
        legend_label="Total payoff",
    )

    # Invisible points solely for better hit-testing on tap (click)
    hit_renderer = p.scatter(
        'S', 'payoff',
        source=source,
        size=5,
        alpha=0.0,
    )

    # Individual legs (helps explain the shape)
    p.line(S, call_leg, line_width=1, line_dash="dashed", alpha=0.7,
           legend_label="Call leg")
    p.line(S, put_leg, line_width=1, line_dash="dotted", alpha=0.7,
           legend_label="Put leg")

    # Zero P/L line
    p.add_layout(Span(location=0, dimension='width', line_color='gray',
                      line_dash='dashed', line_width=1))

    # Combined-strategy break-even verticals
    p.add_layout(Span(location=be_lower, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height',
                      line_dash='dotted', line_width=2))

    y_top = float(np.nanmax(payoff)) if payoff.size else 0.0
    y_bottom = float(np.nanmin(payoff)) if payoff.size else 0.0

    p.add_layout(Label(x=be_lower, y=y_top, x_offset=5, y_offset=-20,
                       text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=y_top, x_offset=5, y_offset=-20,
                       text=f"BE Upper ≈ {be_upper:.2f}"))

    # Total premium annotation
    premium_text = f"Total premium (debit): {total_premium:.2f}"
    p.add_layout(Label(
        x=inp.price_min,
        y=y_top,
        x_offset=5,
        y_offset=5,
        text=premium_text,
    ))

    # Helper to grab the nearest y from a given x on a particular leg
    def _nearest_xy(x_target: float, y_array: np.ndarray):
        if x_target < inp.price_min or x_target > inp.price_max:
            return None
        idx = int(np.clip(round((x_target - inp.price_min) / inp.step),
                          0, len(S) - 1))
        return S[idx], float(y_array[idx])

    # --- Per-leg ITM start (strike) markers ---
    # Call ITM start: stock price crosses call_strike
    call_itm = _nearest_xy(inp.call_strike, call_leg)
    if call_itm is not None:
        x, y = call_itm
        p.scatter([x], [y], size=8, color="orange")
        p.add_layout(Label(x=x, y=y, x_offset=5, y_offset=5,
                           text=f"Call ITM @ {x:.2f}",
                           text_color="orange"))

    # Put ITM start: stock price crosses put_strike (below)
    put_itm = _nearest_xy(inp.put_strike, put_leg)
    if put_itm is not None:
        x, y = put_itm
        p.scatter([x], [y], size=8, color="purple")
        p.add_layout(Label(x=x, y=y, x_offset=5, y_offset=5,
                           text=f"Put ITM @ {x:.2f}",
                           text_color="purple"))

    # --- Per-leg break-even markers ---
    call_be_xy = _nearest_xy(call_be, call_leg)
    if call_be_xy is not None:
        x, y = call_be_xy
        p.scatter([x], [y], size=8, color="orange")
        p.add_layout(Label(x=x, y=y, x_offset=5, y_offset=-15,
                           text=f"Call BE @ {x:.2f}",
                           text_color="orange"))

    put_be_xy = _nearest_xy(put_be, put_leg)
    if put_be_xy is not None:
        x, y = put_be_xy
        p.scatter([x], [y], size=8, color="purple")
        p.add_layout(Label(x=x, y=y, x_offset=5, y_offset=-15,
                           text=f"Put BE @ {x:.2f}",
                           text_color="purple"))

    # --- Recent close markers (small green dots, fading with age) ---
    recent = getattr(inp, "recent_closes", None)
    if recent and len(recent) >= 2:
        # Use all but the most recent as "history" (past days only)
        past_closes = recent[:-1]
        past_closes = past_closes[-9:]  # last 9
        n = len(past_closes)

        # Iterate newest past first so we can fade older ones
        for idx, s_val in enumerate(reversed(past_closes)):
            payoff_val = (
                max(0.0, s_val - inp.call_strike) - inp.call_premium +
                max(0.0, inp.put_strike - s_val) - inp.put_premium
            )

            # Weight for size/alpha (newer = bigger & less transparent)
            frac = 1.0 - (idx + 1) / (n + 1)  # decreases with idx
            size = 6 + 6 * frac               # between ~6 and 12
            alpha = 0.3 + 0.4 * frac          # between ~0.3 and 0.7

            p.scatter(
                [s_val],
                [payoff_val],
                size=size,
                color="green",
                alpha=alpha,
            )

    # --- Current price marker (largest green dot with label) ---
    spot = inp.spot
    spot_payoff = (
        max(0.0, spot - inp.call_strike) - inp.call_premium +
        max(0.0, inp.put_strike - spot) - inp.put_premium
    )

    p.scatter([spot], [spot_payoff], size=12, color="green")
    p.add_layout(Label(
        x=spot, y=spot_payoff,
        x_offset=8, y_offset=8,
        text=f"Current S={spot:.2f}, P/L={spot_payoff:.2f}",
        text_color="green",
    ))

    # --- Hover and click tools for Price & P/L ---
    # Hover: attach to the line renderer so we only get ONE Price/P&L per x
    hover = HoverTool(
        tooltips=[
            ("Price", "@S{0.00}"),
            ("P/L", "@payoff{0.00}"),
        ],
        mode="vline",
        renderers=[line_renderer],
    )

    crosshair = CrosshairTool(dimensions="both")

    # Label that will be updated on click
    click_label = Label(
        x=inp.price_min,
        y=y_bottom,
        x_offset=10,
        y_offset=10,
        text="",
        text_font_style="bold",
        text_color="black",
    )
    p.add_layout(click_label)

    tap_callback = CustomJS(
        args=dict(source=source, label=click_label),
        code="""
        const inds = source.selected.indices;
        if (inds.length === 0) {
            return;
        }
        const i = inds[0];
        const x = source.data['S'][i];
        const y = source.data['payoff'][i];
        label.x = x;
        label.y = y;
        label.text = `Price=${x.toFixed(2)}, P/L=${y.toFixed(2)}`;
        label.visible = true;
        label.change.emit();
        """
    )

    # Tap: still use the invisible scatter (hit_renderer) for selection
    taptool = TapTool(callback=tap_callback, renderers=[hit_renderer])

    p.add_tools(hover, crosshair, taptool)

    # Legend tweaks
    p.legend.location = "top_left"
    p.legend.click_policy = "hide"

    return p



def _fallback_compute_strangle(inp: OptionInputs):
    S = np.arange(inp.price_min, inp.price_max + inp.step, inp.step)
    call_leg = np.maximum(0.0, S - inp.call_strike) - inp.call_premium
    put_leg = np.maximum(0.0, inp.put_strike - S) - inp.put_premium
    total = call_leg + put_leg
    return S, total


def _fallback_plot(inp: OptionInputs, log_fn):
    if np is None:
        raise RuntimeError("Missing dependencies. Install with: pip install bokeh numpy")

    S, payoff = _fallback_compute_strangle(inp)
    total_premium = inp.call_premium + inp.put_premium
    be_lower = inp.put_strike - total_premium
    be_upper = inp.call_strike + total_premium

    title = f"{inp.ticker} Long Strangle Payoff (Fallback)"
    fname = f"{inp.ticker.replace('/', '-')}_payoff.html"
    out_path = os.path.join(tempfile.gettempdir(), fname)

    p = figure(
        title=title,
        x_axis_label="Stock Price at Expiration",
        y_axis_label="Profit / Loss (per 1x)",
        width=900,
        height=520,
        toolbar_location="right",
    )

    p.line(S, payoff, line_width=3)
    p.add_layout(Span(location=0, dimension='width', line_color='gray',
                      line_dash='dashed', line_width=1))

    # Break-evens
    p.add_layout(Span(location=be_lower, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Span(location=be_upper, dimension='height',
                      line_dash='dotted', line_width=2))
    p.add_layout(Label(x=be_lower, y=max(payoff), x_offset=5, y_offset=-20,
                       text=f"BE Lower ≈ {be_lower:.2f}"))
    p.add_layout(Label(x=be_upper, y=max(payoff), x_offset=5, y_offset=-20,
                       text=f"BE Upper ≈ {be_upper:.2f}"))

    # Current price marker
    idx = int(np.clip(round((inp.spot - inp.price_min) / inp.step), 0, len(S) - 1))
    spot_payoff = payoff[idx]
    p.scatter([inp.spot], [spot_payoff], size=10)
    p.add_layout(Label(x=inp.spot, y=spot_payoff, x_offset=8, y_offset=8,
                       text=f"S0={inp.spot:.2f}, P/L={spot_payoff:.2f}"))

    output_file(out_path)
    save(p, resources=INLINE)

    log_fn("[Options] Using built-in payoff diagram.")
    return out_path


def plot_option_payoff_using_your_code(inp: OptionInputs, log_fn=print):
    """
    Currently we only use the built-in fallback plot.
    This is kept as a hook if you later wire your own payoff backend.
    """
    return _fallback_plot(inp, log_fn)


# ----------------------------
# Tkinter App
# ----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Trading Tools Launcher")
        self.geometry("700x420")

        # Top header
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=10)
        ttk.Label(top, text="Quick Launch", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

        # Button row
        btns = ttk.Frame(self)
        btns.pack(side=tk.TOP, fill=tk.X, padx=12, pady=8)

        self.btn_ind = ttk.Button(btns, text="Run Indicators",
                                  command=self.run_indicators)
        self.btn_ind.pack(side=tk.LEFT, padx=6)

        # Button for CSV-based payoff plotting
        self.btn_csv = ttk.Button(btns, text="Strat/Strang Plot (CSV)",
                                  command=self._on_plot_from_csv)
        self.btn_csv.pack(side=tk.LEFT, padx=6)

        # Existing CSV-based vol scanner
        self.btn_vol = ttk.Button(btns, text="Run Vol Scanner",
                                  command=self._on_run_vol_scanner)
        self.btn_vol.pack(side=tk.LEFT, padx=6)

        # NEW: Schwab-based vol scanner
        self.btn_vol_schwab = ttk.Button(
            btns,
            text="Schwab Vol Scanner",
            command=self._on_run_vol_scanner_schwab,
        )
        self.btn_vol_schwab.pack(side=tk.LEFT, padx=6)

        # Status + log
        self.status = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(
            fill=tk.X, padx=12, pady=(0, 10)
        )

        self.log = ScrolledText(self, height=10, state="normal")
        self.log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self._style = ttk.Style()
        try:
            self._style.theme_use("vista")
        except Exception:
            pass

        self._log("Ready.")

    # --- helpers ---
    def _log(self, msg: str):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.status.set(msg)

    def _run_bg(self, target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    # --- Run Indicators (popup + Schwab CSV) ---
    def run_indicators(self):
        """
        Ask the user for a ticker, then run the indicators dashboard using the
        already-downloaded Schwab OHLCV data.

        Prefers the GUI-generated Schwab CSV (schwab_ohlcv_gui.csv), but will
        fall back to schwab_ohlcv.csv if that one exists instead.
        """
        ticker = simpledialog.askstring(
            "Run Indicators",
            "Enter ticker symbol (e.g. AAPL, NVDA, SPY):",
            parent=self,
        )
        if not ticker:
            # user cancelled or left blank
            self._log("Indicators cancelled.")
            return

        ticker = ticker.strip().upper()
        if not ticker:
            messagebox.showerror("Error", "Ticker cannot be empty.")
            return

        # Prefer the GUI Schwab file, fall back to CLI one
        schwab_csv_gui = BASE_DIR / "csv_html" / "schwab_ohlcv_gui.csv"
        schwab_csv_cli = BASE_DIR / "csv_html" / "schwab_ohlcv.csv"

        if schwab_csv_gui.exists():
            schwab_csv = schwab_csv_gui
        elif schwab_csv_cli.exists():
            schwab_csv = schwab_csv_cli
        else:
            messagebox.showerror(
                "Error",
                "No Schwab OHLCV CSV found.\n\n"
                f"Tried:\n  {schwab_csv_gui}\n  {schwab_csv_cli}\n\n"
                "Run either the Schwab Vol Scanner from the GUI\n"
                "or schwab_vol_scan_prep.py first.",
            )
            return

        script = BASE_DIR / "indicators_dashboard_from_schwab.py"
        if not script.exists():
            messagebox.showerror(
                "Error",
                f"Indicator script not found:\n{script}\n\n"
                f"Make sure you saved indicators_dashboard_from_schwab.py in the repo root.",
            )
            return

        self._log(f"Running indicators for {ticker} using {schwab_csv.name}...")

        def job():
            # capture stdout/stderr so we can show the real error
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--ticker",
                    ticker,
                    "--schwab-csv",
                    str(schwab_csv),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self._log(f"Indicators dashboard generated for {ticker}.")
                if result.stdout.strip():
                    self._log("[Indicators stdout]")
                    self._log(result.stdout.strip())
            else:
                self._log(f"[Indicators] script exited with code {result.returncode}")
                if result.stdout.strip():
                    self._log("[Indicators stdout]")
                    self._log(result.stdout.strip())
                if result.stderr.strip():
                    self._log("[Indicators stderr]")
                    self._log(result.stderr.strip())

                messagebox.showerror(
                    "Indicators Error",
                    "Indicators script failed.\n\n"
                    f"Exit code: {result.returncode}\n\n"
                    f"STDOUT:\n{result.stdout[-1000:]}\n\n"
                    f"STDERR:\n{result.stderr[-1000:]}"
                )

        # Run in background so GUI doesn't freeze
        self._run_bg(job)

    # --- button handlers ---
    def _on_plot_from_csv(self):
        path = filedialog.askopenfilename(
            title="Select options_input.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            inputs_list = read_option_inputs_csv(path)
        except Exception as e:
            messagebox.showerror("CSV Error", str(e))
            return

        if not inputs_list:
            messagebox.showinfo("No rows", "CSV has no data rows.")
            return

        # ---------------------------------------------------------
        # Fetch current spot prices + recent history from Schwab
        # ---------------------------------------------------------
        tickers = sorted({inp.ticker for inp in inputs_list})
        self._log(f"[Schwab] Fetching current prices for {len(tickers)} ticker(s): {tickers}")

        price_map = {}
        history_map = {}  # ticker -> list of recent closes (oldest -> newest)

        try:
            from schwab_vol_scan_prep import fetch_ohlcv_for_tickers
            # Use a slightly longer lookback so we can get at least 9 recent closes
            df = fetch_ohlcv_for_tickers(tickers, lookback_days=15)

            if df is not None and not df.empty:
                # Try to find a "close" column (case-insensitive)
                cols_lower = {c.lower(): c for c in df.columns}
                close_col = None
                for cand in ("close", "adjclose", "adj_close", "last"):
                    if cand in cols_lower:
                        close_col = cols_lower[cand]
                        break

                if close_col is None:
                    self._log("[Schwab] No close/last price column found in OHLCV data.")
                elif "Ticker" not in df.columns:
                    self._log("[Schwab] No 'Ticker' column in OHLCV data.")
                else:
                    # Try to find a date-like column for ordering
                    date_col_key = None
                    for cand in ("date", "timestamp", "datetime"):
                        if cand in cols_lower:
                            date_col_key = cand
                            break
                    date_col = cols_lower[date_col_key] if date_col_key else None

                    for t in tickers:
                        df_t = df[df["Ticker"] == t]
                        if df_t.empty:
                            continue
                        if date_col:
                            df_t = df_t.sort_values(date_col)

                        closes = df_t[close_col].tolist()
                        # Keep only the last 10 closes (oldest -> newest)
                        closes = closes[-10:]
                        if not closes:
                            continue

                        history_map[t] = closes
                        # Most recent close is the "current" spot
                        price_map[t] = float(closes[-1])

            self._log(f"[Schwab] Got prices for {len(price_map)} ticker(s).")
        except ImportError as e:
            self._log(f"[Schwab] Could not import schwab_vol_scan_prep: {e}")
            self._log("[Schwab] Using CSV spot values (if provided).")
        except Exception as e:
            self._log(f"[Schwab] ERROR fetching prices: {e}")
            self._log(traceback.format_exc())
            self._log("[Schwab] Using CSV spot values (if provided).")

        # Overwrite inp.spot with Schwab price when available, and attach history
        for inp in inputs_list:
            if inp.ticker in price_map:
                inp.spot = price_map[inp.ticker]
                setattr(inp, "recent_closes", history_map.get(inp.ticker, []))
            else:
                # Fallback if we couldn't get a price and CSV had no spot:
                if not inp.spot:
                    inp.spot = (inp.call_strike + inp.put_strike) / 2.0
                self._log(f"[Schwab] No live price for {inp.ticker}; using fallback spot={inp.spot:.2f}")
                setattr(inp, "recent_closes", [])

        self._log(f"Loaded {len(inputs_list)} row(s) from CSV. Building combined HTML with tabs…")
        self.btn_csv.config(state=tk.DISABLED)

        def job():
            try:
                panels = []
                for idx, inp in enumerate(inputs_list, 1):
                    try:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: rendering figure…")
                        fig = _make_payoff_figure(inp)
                        label = (
                            f"{inp.ticker} | "
                            f"Kc={inp.call_strike:g}, C={inp.call_premium:g} | "
                            f"Kp={inp.put_strike:g}, P={inp.put_premium:g}"
                        )
                        panels.append(TabPanel(child=fig, title=label))
                    except Exception as e:
                        self._log(f"[{idx}/{len(inputs_list)}] {inp.ticker}: ERROR {e}")

                if not panels:
                    self._log("No valid rows to plot.")
                    return

                tabs = Tabs(tabs=panels, sizing_mode="stretch_both")
                tabs.width_policy = "max"

                ts = time.strftime("%Y%m%d_%H%M%S")
                fname = f"options_payoffs_{ts}.html"
                out_path = os.path.join(tempfile.gettempdir(), fname)

                output_file(out_path, title="Option Payoffs (Tabs)")
                save(tabs, resources=INLINE)

                self._log(f"Saved combined HTML: {out_path}")
                try:
                    webbrowser.open(f"file:///{out_path}")
                except Exception:
                    pass
            finally:
                self.btn_csv.config(state=tk.NORMAL)
                self._log("CSV plotting finished.")

        self._run_bg(job)

    def _on_run_vol_scanner(self):
        """
        Prompt user for a CSV file and run vol_scan_integration using that data.
        """
        self._log("Starting Vol Scanner…")
        self.btn_vol.config(state=tk.DISABLED)

        def job():
            try:
                vol_mod = _load_vol_scan_module(self._log)

                csv_path = filedialog.askopenfilename(
                    title="Select OHLCV CSV File",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                )
                if not csv_path:
                    self._log("Vol Scanner cancelled — no file selected.")
                    return
                self._log(f"Selected CSV file: {csv_path}")

                try:
                    import pandas as pd
                    df_all = pd.read_csv(csv_path)
                    if "Ticker" in df_all.columns:
                        tickers = sorted(df_all["Ticker"].dropna().unique().tolist())
                        self._log(f"Found {len(tickers)} ticker(s) in CSV: {tickers}")
                    else:
                        self._log("No 'Ticker' column in CSV — using default tickers list.")
                        tickers = ["NVDA", "AAPL", "MSFT"]
                except Exception as e:
                    self._log(f"Could not parse CSV to detect tickers: {e}")
                    tickers = ["NVDA", "AAPL", "MSFT"]

                self._log(f"Scanning {len(tickers)} tickers for volatility patterns…")
                df = vol_mod.build_vol_table_df(tickers, preset="15%", csv_file=csv_path)

                if df.empty:
                    self._log("No data found for volatility scan.")
                    return

                self._log("Rendering volatility table to HTML…")
                outfile = vol_mod.render_vol_table_html(df, outfile="vol_scanner_summary.html")
                self._log(f"Vol scanner output: {outfile}")

                url = f"file:///{os.path.abspath(outfile)}"
                if not _open_in_chrome(url):
                    webbrowser.open(url)
                self._log("Opened volatility summary in browser.")

            except FileNotFoundError as e:
                self._log(str(e))
                messagebox.showerror("Missing File", str(e))
            except Exception as e:
                self._log(f"[Vol Scanner] ERROR: {e}")
                self._log(traceback.format_exc())
                messagebox.showerror("Vol Scanner Error", str(e))
            finally:
                self.btn_vol.config(state=tk.NORMAL)
                self._log("Vol Scanner task finished.")

        self._run_bg(job)

    def _on_run_vol_scanner_schwab(self):
        """
        Fetch OHLCV from Schwab based on a tickers text file and
        run the vol scanner using that data.
        """
        self._log("Starting Schwab Vol Scanner…")
        self.btn_vol_schwab.config(state=tk.DISABLED)

        def job():
            try:
                try:
                    from schwab_vol_scan_prep import fetch_ohlcv_for_tickers
                except ImportError as e:
                    self._log(f"[Schwab] Could not import schwab_vol_scan_prep: {e}")
                    messagebox.showerror(
                        "Missing module",
                        "schwab_vol_scan_prep.py not found or import failed.\n"
                        "Make sure you've added it to the project.",
                    )
                    return

                ticker_file = filedialog.askopenfilename(
                    title="Select text file with tickers (one per line)",
                    filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                )
                if not ticker_file:
                    self._log("Schwab Vol Scanner cancelled — no tickers file selected.")
                    return

                tickers = _ticker_list_from_file(ticker_file)
                if not tickers:
                    self._log("Ticker file was empty or only comments.")
                    messagebox.showwarning(
                        "No tickers",
                        "No valid tickers found in the selected file.",
                    )
                    return

                self._log(f"[Schwab] Fetching OHLCV for {len(tickers)} ticker(s)…")
                df = fetch_ohlcv_for_tickers(tickers, lookback_days=260)
                if df.empty:
                    self._log("[Schwab] No data returned from Schwab.")
                    messagebox.showwarning(
                        "No data",
                        "No data was returned from Schwab for these tickers.",
                    )
                    return

                base_dir = os.path.dirname(os.path.abspath(__file__))
                csv_dir = os.path.join(base_dir, "csv_html")
                os.makedirs(csv_dir, exist_ok=True)

                csv_path = os.path.join(csv_dir, "schwab_ohlcv_gui.csv")
                df.to_csv(csv_path, index=False)
                self._log(f"[Schwab] Wrote OHLCV CSV to: {csv_path}")

                vol_mod = _load_vol_scan_module(self._log)

                self._log("Building volatility table from Schwab data…")
                vol_df = vol_mod.build_vol_table_df(
                    tickers,
                    preset="15%",
                    csv_file=csv_path,
                )
                if vol_df.empty:
                    self._log("Vol scanner returned no rows.")
                    messagebox.showwarning(
                        "Empty result",
                        "Vol scanner returned no rows.",
                    )
                    return

                self._log("Rendering volatility table to HTML…")
                outfile = vol_mod.render_vol_table_html(
                    vol_df,
                    outfile="vol_scanner_from_schwab.html",
                    title="Vol Scanner (Schwab Data)",
                )

                self._log(f"Schwab Vol scanner output: {outfile}")
                url = f"file:///{os.path.abspath(outfile)}"
                if not _open_in_chrome(url):
                    webbrowser.open(url)
                self._log("Opened Schwab volatility summary in browser.")

            except Exception as e:
                self._log(f"[Schwab Vol Scanner] ERROR: {e}")
                self._log(traceback.format_exc())
                messagebox.showerror("Schwab Vol Scanner Error", str(e))
            finally:
                self.btn_vol_schwab.config(state=tk.NORMAL)
                self._log("Schwab Vol Scanner task finished.")

        self._run_bg(job)


def main():
    sys.stdout.reconfigure(line_buffering=True)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
